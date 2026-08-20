"""Qwen-VL-Plus 图像结构化标签提取。

设计目标：把每张照片提取为 `{people, background, pose, action}` 结构化标签，
供 Screener 阶段做"三维度 AND 聚类"（人物同一人 + 背景相似 + 动作一致）。

输出 JSON Schema：
{
  "people_count": int,
  "people": [
    {
      "gender": "男|女|未知",
      "hair": "<简述，如'长发'/'短发'>",
      "clothing": "<简述服装颜色+款式，如'白裙'/'红衬衫'>",
      "pose": "站立|坐着|蹲着|走着|躺着|其他",
      "action": "<简述动作，如'微笑看镜头'/'挥手'/'看风景'>"
    }
    // ... 多人时数组更长
  ],
  "background_type": "花海|山脉|海边|城市|古镇|室内|雪景|森林|草原|夜景|其他",
  "background_elements": ["<主要元素1>", "<元素2>"]   // 至多 3 个

成本：Qwen-VL-Plus 每次调用约 0.025 元（输入图片 + 输出 JSON）；
7 张照片一次任务约 0.175 元。
"""
from __future__ import annotations

import asyncio
import base64
import difflib
import json
import logging
import re
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_TIMEOUT = 30.0
_MAX_CONCURRENCY = 4   # 同时跑的最大请求数
_MAX_BASE64_BYTES = 8 * 1024 * 1024   # VL base64 限制 ~10MB，留余量


def _is_private_url(url: str) -> bool:
    """判断是否为内网 URL（Qwen-VL 服务端无法直接访问）。

    私网：127.0.0.1 / localhost / 192.168.* / 10.* / file://
    """
    if not url:
        return True
    u = url.strip().lower()
    if u.startswith("file://"):
        return True
    if u.startswith("http://localhost"):
        return True
    if u.startswith("http://127."):
        return True
    if u.startswith("http://10."):
        return True
    if u.startswith("http://192.168."):
        return True
    if u.startswith("http://172."):
        # 172.16.0.0/12 私网段
        rest = u[len("http://172."):]
        try:
            second = int(rest.split(".")[0])
            if 16 <= second <= 31:
                return True
        except (ValueError, IndexError):
            pass
    return False


async def _to_payload_url(
    client: httpx.AsyncClient,
    url: str,
) -> str | None:
    """把内网 URL 转成 base64 data URL（Qwen-VL 可读）。

    公网 URL 原样返回。
    """
    if not _is_private_url(url):
        return url
    try:
        r = await client.get(url, timeout=_TIMEOUT)
        if r.status_code != 200:
            logger.warning(f"[qwen_vl_labeller] 下载内网图失败 url={url[:60]}: {r.status_code}")
            return None
        if len(r.content) > _MAX_BASE64_BYTES:
            logger.warning(f"[qwen_vl_labeller] 内网图过大 url={url[:60]} size={len(r.content)}")
            return None
        b64 = base64.b64encode(r.content).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.warning(f"[qwen_vl_labeller] 下载内网图异常 url={url[:60]}: {e}")
        return None


# ===== Prompt 设计 =====
_SYSTEM_PROMPT = """你是图像结构化分析助手，专门分析旅行照片。请严格按要求输出 JSON，不要任何额外解释。

要求：
1. 只输出一个 JSON 对象，不要 markdown 标记
2. 字段值必须是规定枚举之一，不要自由发挥
3. 简述字段（hair/clothing/action）请用 2~6 个汉字"""

_USER_PROMPT = """分析这张旅行照片，输出严格 JSON：

{
  "people_count": <照片中清晰可辨的人物数量，整数>,
  "people": [
    {
      "gender": "男" | "女" | "未知",
      "hair": "<发型简述，2~6 字，如'长发'/'短发'/'盘发'>",
      "clothing": "<服装简述，2~8 字，如'白裙'/'红衬衫'/'黑色T恤'>",
      "pose": "站立" | "坐着" | "蹲着" | "走着" | "躺着" | "其他",
      "action": "<动作简述，2~8 字，如'微笑看镜头'/'挥手'/'看风景'/'低头'>"
    }
    // 如有多人，依次列出每个主要人物
  ],
  "background_type": "花海" | "山脉" | "海边" | "城市" | "古镇" | "室内" | "雪景" | "森林" | "草原" | "夜景" | "其他",
  "background_elements": ["<主要环境元素 1>", "<元素 2>"]   // 至多 3 个元素，如 ["樱花", "远山", "蓝天"]
}

注意：
- 看不到脸的人物（如远景背影）也算一个人物
- people_count 必须 = len(people)
- 实在无法判断的字段填"未知"或"其他"
- 整张图没有人（如纯风景）时 people_count=0, people=[]"""


# ===== 默认值（VL 失败时使用） =====
def _empty_label() -> dict[str, Any]:
    return {
        "people_count": 0,
        "people": [],
        "background_type": "其他",
        "background_elements": [],
    }


# ===== JSON 鲁棒解析 =====
def _parse_label_response(content: str) -> dict[str, Any] | None:
    """从 VL 输出里提取 JSON 对象。

    Qwen-VL-Plus 经常输出 ```json ... ``` 包裹，或者前后有解释文字。
    用正则提取最外层 {...}。
    """
    if not content:
        return None
    # 去除 markdown 包裹
    cleaned = re.sub(r"```(?:json)?\s*", "", content).replace("```", "").strip()
    # 提取第一个 {...} 块
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        # 校验必需字段
        if not isinstance(obj, dict):
            return None
        if "people_count" not in obj or "people" not in obj:
            return None
        if "background_type" not in obj or "background_elements" not in obj:
            return None
        # 类型保护
        if not isinstance(obj["people"], list):
            obj["people"] = []
        if not isinstance(obj["people_count"], int):
            obj["people_count"] = len(obj["people"])
        if not isinstance(obj["background_elements"], list):
            obj["background_elements"] = []
        # 元素统一为字符串
        obj["background_elements"] = [str(e) for e in obj["background_elements"][:3]]
        # 每个 person 字段兜底
        for p in obj["people"]:
            if not isinstance(p, dict):
                continue
            for f in ["gender", "hair", "clothing", "pose", "action"]:
                if f not in p or not isinstance(p[f], str):
                    p[f] = "未知" if f != "pose" else "其他"
        return obj
    except json.JSONDecodeError:
        return None


# ===== 单张图调用 =====
async def _label_one(
    client: httpx.AsyncClient,
    image_url: str,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    """单张图片的结构化标签提取。失败时返回 _empty_label()。"""
    async with sem:
        if not settings.LLM_API_KEY:
            logger.warning("[qwen_vl_labeller] LLM_API_KEY 未配置")
            return _empty_label()

        # 内网 URL → 下载转 base64（Qwen-VL 不能直接访问私网）
        payload_url = await _to_payload_url(client, image_url)
        if payload_url is None:
            logger.warning(f"[qwen_vl_labeller] URL 转换失败 url={image_url[:60]}")
            return _empty_label()

        payload = {
            "model": settings.LLM_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": payload_url}},
                        {"type": "text", "text": _USER_PROMPT},
                    ],
                },
            ],
            "max_tokens": 600,
            "temperature": 0.2,   # 低温度保证 JSON 结构稳定
            "response_format": {"type": "json_object"},  # 强制 JSON 输出
        }
        try:
            resp = await client.post(
                f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    f"[qwen_vl_labeller] HTTP {resp.status_code} url={image_url[:60]} "
                    f"body={resp.text[:200]}"
                )
                return _empty_label()
            data = resp.json()
            content = (
                data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            )
            label = _parse_label_response(content)
            if label is None:
                logger.warning(
                    f"[qwen_vl_labeller] JSON 解析失败 url={image_url[:60]} content={content[:200]}"
                )
                return _empty_label()
            logger.info(
                f"[qwen_vl_labeller] url={image_url[:50]} "
                f"people={label['people_count']} bg={label['background_type']} "
                f"elements={label['background_elements']}"
            )
            return label
        except Exception as e:
            logger.warning(f"[qwen_vl_labeller] 异常 url={image_url[:50]}: {e}")
            return _empty_label()


# ===== 批量调用 =====
async def label_images(
    image_urls: list[str],
    concurrency: int = _MAX_CONCURRENCY,
) -> list[dict[str, Any]]:
    """并发调 Qwen-VL-Plus 给多张图片打结构化标签。

    Args:
        image_urls: 图片 URL 列表（公网可访问 URL 或 base64 data URL）
        concurrency: 同时进行的请求数（避免打爆限流）

    Returns:
        与输入等长的 list，每张图一个 label dict。
        失败 / 解析失败的索引对应 _empty_label()。
    """
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        tasks = [_label_one(client, url, sem) for url in image_urls]
        labels = await asyncio.gather(*tasks)
    ok = sum(1 for l in labels if l["people_count"] > 0 or l["background_type"] != "其他")
    logger.info(f"[qwen_vl_labeller] 完成 {ok}/{len(image_urls)} 张（成功标签数）")
    return labels


# ===== 三维度匹配规则（供 screener_real 调用） =====
# P1-12 修复：阈值从 0.6 降到 0.5。Qwen-VL 对同一人物 clothing 经常给出 0.5~0.7
# 的相似度（如 "白裙" vs "白色连衣裙"=0.5，"红色卫衣" vs "红卫衣"=0.67），
# 0.6 经常擦边不命中，0.5 更稳。
_DEFAULT_ATTR_FUZZY_THRESHOLD = 0.5


def _attr_match(va: str, vb: str, fuzzy_threshold: float | None = None) -> bool:
    """单属性匹配：精确相等 / 双方未知 → 命中；否则子串包含或模糊相似。

    用于 clothing / hair 这类 Qwen 会对同一实物给出不同长度/同义描述（如
    '黑白格纹外套' vs '黑白格纹外套+黑色内搭'、'黑白拼色外套' vs '黑白格纹外套'）。

    P1-12：默认模糊阈值 0.6 → 0.5（容忍同义/扩展描述更宽）。
    """
    if fuzzy_threshold is None:
        fuzzy_threshold = _DEFAULT_ATTR_FUZZY_THRESHOLD
    va, vb = _norm_attr(va), _norm_attr(vb)
    if va == vb:
        return True
    # 两边都缺失/未知 → 不强卡
    if va in ("未知", "其他", "") and vb in ("未知", "其他", ""):
        return True
    # 子串包含：容忍"扩展描述"（前者是后者的一部分）
    if va and (va in vb or vb in va):
        return True
    # 模糊相似：容忍同义/简繁写法（difflib 序列相似度）
    if va and vb and difflib.SequenceMatcher(None, va, vb).ratio() >= fuzzy_threshold:
        return True
    return False


# 元素同义归一化：把 Qwen 对同一实物给出的不同措辞统一。
# 比如 ['樱花','樱花树','樱花花瓣'] 都归并为 '樱花'。
_ELEMENT_SYNONYMS = {
    "樱花树": "樱花",
    "樱花花瓣": "樱花",
    "樱花花瓣雨": "樱花",
    "樱花大道": "樱花",
    "樱花林": "樱花",
    "红叶": "枫叶",
    "枫叶林": "枫叶",
    "雪山": "山脉",
    "远山": "山脉",
    "山脉": "山脉",
    "海面": "海",
    "大海": "海",
    "海边": "海",
    "海浪": "海",
    "沙雕": "沙滩",
    "海滩": "沙滩",
    "金门大桥": "桥",
    "吊桥": "桥",
    "古建筑": "建筑",
    "古楼": "建筑",
    "宫殿": "建筑",
    "寺庙": "建筑",
    "教堂": "建筑",
}


def _norm_attr(s: str) -> str:
    """对 clothing/hair/elements 做归一化（同义合并 + 去空格 + 截断）。"""
    s = str(s).strip()
    if not s:
        return ""
    # 去多余空格
    s = s.replace(" ", "")
    # 元素同义词归一化
    s = _ELEMENT_SYNONYMS.get(s, s)
    return s


def people_match(
    a_people: list[dict[str, Any]],
    b_people: list[dict[str, Any]],
) -> bool:
    """人物匹配：人数相同 + 第一个人物特征一致。

    性别(gender)严格相等；发型(hair)/服装(clothing)放宽为子串包含+模糊相似，
    以容忍 Qwen 对同一人同一件衣服给出不同措辞。

    合照（≥2 人）vs 单人照（1 人）必然不匹配。
    """
    if not a_people or not b_people:
        return False
    if len(a_people) != len(b_people):
        return False
    # 取第一个主要人物（合照时取最大脸的那个——这里按顺序即可）
    a0, b0 = a_people[0], b_people[0]
    # gender 硬区分（男/女是明确的）
    g_a, g_b = str(a0.get("gender", "")), str(b0.get("gender", ""))
    if g_a != g_b:
        if not (g_a in ("未知", "其他", "") and g_b in ("未知", "其他", "")):
            return False
    # hair / clothing 放宽匹配
    for f in ["hair", "clothing"]:
        if not _attr_match(a0.get(f, ""), b0.get(f, ""), fuzzy_threshold=0.6):
            return False
    return True


# 背景「大类」映射：把细分 type 归并到更粗的语义类别，
# 用于"相似背景即可同组"的放宽判定（如 山脉/森林/草原 都算自然风光，
# 海边/夜景 都算水景夜色，城市/古镇 都算人文街区）。
_BG_CATEGORY = {
    "花海": "自然风光",
    "山脉": "自然风光",
    "森林": "自然风光",
    "草原": "自然风光",
    "雪景": "自然风光",
    "海边": "水景夜色",
    "夜景": "水景夜色",
    "城市": "人文街区",
    "古镇": "人文街区",
    "室内": "室内",
    "其他": "其他",
}


def _bg_same_category(a_bg_type: str, b_bg_type: str) -> bool:
    """两个背景 type 是否属于同一大类（用于放宽"相似背景"判定）。"""
    if not a_bg_type or not b_bg_type:
        return False
    ca = _BG_CATEGORY.get(a_bg_type, "其他")
    cb = _BG_CATEGORY.get(b_bg_type, "其他")
    # 都是"其他"时仅在 type 同为"其他"才放宽（避免把未知背景强行同组）
    if ca == "其他" and cb == "其他":
        return a_bg_type == b_bg_type
    return ca == cb


def background_match(
    a_bg_type: str,
    a_bg_elements: list[str],
    b_bg_type: str,
    b_bg_elements: list[str],
    overlap_threshold: float = 0.5,
) -> bool:
    """背景匹配：放宽版，满足"相似背景即可同组"。

    判定规则（任一成立即视为相似背景）：
    1. type 完全相同；
    2. 同属一个背景大类（如 山脉/森林/草原 都算自然风光，海边/夜景 都算水景夜色）；
    3. 即便 type 不同，元素 Jaccard 重叠 ≥ overlap_threshold（元素高度重合即视为同场景）。

    比如：
    - a=山脉 b=草原（同大类自然风光）→ 匹配
    - a=['樱花','远山'] b=['樱花','远山','蓝天'] → 重叠 2/3 = 0.67 ≥ 阈值 → 匹配
    - a=海边 b=山脉（不同大类、无重叠元素）→ 不匹配
    """
    if not a_bg_type or not b_bg_type:
        return False

    # P1-13 修复：VL 标签"不可判定"时不强行判同组。
    # 当双方 type 都是"其他"且都没有 elements 时，说明 VL 没识别出有效背景信息，
    # 此时 background_match 应返回 False（不可判定），避免把所有未识别图 union 进同组。
    # 之前：same_type("其他"=="其他") 直接 return True，导致 6 张 VL 全空的图被
    # 错误合并成 1 组，配合 max_per_group=1 只保留 1 张，过度剔除。
    set_a = {_norm_attr(e) for e in (a_bg_elements or []) if _norm_attr(e)}
    set_b = {_norm_attr(e) for e in (b_bg_elements or []) if _norm_attr(e)}
    if a_bg_type == "其他" and b_bg_type == "其他" and not set_a and not set_b:
        return False

    # 规则 1 + 2：type 相同 或 同大类
    same_type = a_bg_type == b_bg_type
    same_cat = _bg_same_category(a_bg_type, b_bg_type)
    if same_type or same_cat:
        # 同大类下进一步要求元素不要明显冲突：若双方都有元素且完全无重叠，
        # 仍要求重叠率达标（避免"山脉+雪山"被强行并入"山脉+城市"）。
        if set_a and set_b:
            union = set_a | set_b
            inter = set_a & set_b
            if len(union) > 0 and len(inter) / len(union) < overlap_threshold:
                # 元素冲突较大：仍属同大类但场景细节差异明显，放宽接受
                # （用户要求"相似背景即可"，同大类已满足，故仍匹配）
                pass
        return True

    # 规则 3：type 不同，但元素高度重叠 → 视为同场景
    if not set_a and not set_b:
        return False
    union = set_a | set_b
    if not union:
        return False
    inter = set_a & set_b
    overlap = len(inter) / len(union)
    return overlap >= overlap_threshold



def action_match(
    a_people: list[dict[str, Any]],
    b_people: list[dict[str, Any]],
) -> bool:
    """动作匹配：第一个人物的 (pose, action) 一致。

    简化：动作标签相等的判一致。"其他"/"未知" 视为宽松匹配。
    """
    if not a_people or not b_people:
        return False
    a0, b0 = a_people[0], b_people[0]
    pa, pb = str(a0.get("pose", "")), str(b0.get("pose", ""))
    aa, ab = str(a0.get("action", "")), str(b0.get("action", ""))
    pose_ok = (pa == pb) or (pa in ("其他", "未知", "") and pb in ("其他", "未知", ""))
    action_ok = (aa == ab) or (aa in ("未知", "其他", "") and ab in ("未知", "其他", ""))
    return pose_ok and action_ok