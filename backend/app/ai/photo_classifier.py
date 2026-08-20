"""照片人物分类器

使用多模态大模型（qwen-vl-plus）判断照片中的人物类型，
用于在美图云修 Pro 精修时选择对应的人物预设 ID。

5 种类别：
- man     成年男性（≥18 岁）
- woman   成年女性（≥18 岁）
- child   小孩（< 18 岁）
- elderly 老人（≥ 60 岁）
- group   多人（≥2 人，无法明确单一分类）

异常/超时/未配置 → 返回 None，由 MeituProRetoucher 兜底到 MEITU_MEDIA_CODE
"""

import asyncio
import base64
import logging
from typing import Literal

import httpx

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

PhotoCategory = Literal["man", "woman", "child", "elderly", "group"]
_CATEGORY_SET = {"man", "woman", "child", "elderly", "group"}

# 腾讯云 IAI 性别枚举：1=男 / 0=女 / 2=未知
_IAI_GENDER_MALE = 1
_IAI_GENDER_FEMALE = 0
_CHILD_MAX_AGE = 17     # < 18 记为儿童
_ELDERLY_MIN_AGE = 60   # >= 60 记为长者


def infer_person_type(
    face_count: int,
    gender: int | None = None,
    age: int | None = None,
) -> PhotoCategory | None:
    """基于人脸检测的结构化属性（face_count / gender / age）确定性推导人物类别。

    替代多模态大模型做「男人/女人/儿童/长者/合照」判定：
    - 优先用 face_count 与年龄，性别作为成人段的细分依据
    - 与 PRD 5 分类优先级一致：group > child > elderly > man/woman

    返回 None 表示属性不足以判定（交由 LLM 兜底或默认预设）。
    """
    if not face_count or face_count <= 0:
        return None  # 无人脸，不归为人物类别
    if face_count >= 2:
        return "group"

    # 单脸：先看年龄区间（优先级高于性别细分）
    if age is not None:
        if age <= _CHILD_MAX_AGE:
            return "child"
        if age >= _ELDERLY_MIN_AGE:
            return "elderly"
    # 成年段（或年龄缺失）按性别判定
    if gender == _IAI_GENDER_MALE:
        return "man"
    if gender == _IAI_GENDER_FEMALE:
        return "woman"
    # 性别/年龄都缺失：无法确定性判定
    return None

# 5 分类 prompt：明确指令 + 严格 JSON 输出，便于解析
_CLASSIFY_PROMPT = """请分析这张照片中的人物，并只返回严格 JSON 格式（不要任何解释、markdown 标记）：

{
  "category": "man" | "woman" | "child" | "elderly" | "group",
  "confidence": 0.0-1.0
}

分类规则（按优先级判断）：
1. "group"  - 画面中有 ≥2 个清晰可辨的人脸（合照、合影、群像）
2. "child"  - 画面中是 1 个小孩（年龄 < 18 岁）
3. "elderly"- 画面中是 1 个老人（年龄 ≥ 60 岁，有明显衰老特征）
4. "man"    - 画面中是 1 个成年男性（18-59 岁）
5. "woman"  - 画面中是 1 个成年女性（18-59 岁）

如果画面中无人物，返回：
{"category": null, "confidence": 0, "note": "no_person"}

只输出 JSON，不要其他任何字符。"""


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


async def _fetch_image_b64(image_url: str) -> str | None:
    """如果 image_url 是 COS 公开 URL，下载后转 base64 data URL

    qwen-vl-plus 同时支持 URL 和 base64，但 base64 避免公网图片访问失败
    （如 COS 私有 ACL 或网络抖动）
    """
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(image_url)
            if r.status_code != 200:
                logger.warning(f"[classifier] 图片下载失败 status={r.status_code} url={image_url[:80]}")
                return None
            # 检测 content-type
            ct = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not ct.startswith("image/"):
                ct = "image/jpeg"
            b64 = base64.b64encode(r.content).decode("ascii")
            return f"data:{ct};base64,{b64}"
    except Exception as e:
        logger.warning(f"[classifier] 图片下载异常: {e} url={image_url[:80]}")
        return None


async def _classify_one(client: httpx.AsyncClient, image_url: str) -> str | None:
    """对单张图调一次 qwen-vl-plus，返回分类字符串

    返回 None 表示分类失败（不影响精修主流程）
    """
    if not settings.LLM_API_KEY:
        logger.debug("[classifier] 未配置 LLM_API_KEY，跳过分类")
        return None

    # 优先用 base64（更稳），回退到 URL
    image_input = await _fetch_image_b64(image_url) or image_url

    payload = {
        "model": settings.LLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_input}},
                    {"type": "text", "text": _CLASSIFY_PROMPT},
                ],
            }
        ],
        "max_tokens": settings.LLM_MAX_TOKENS,
        "temperature": 0.0,
    }
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = await client.post(
            f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=settings.LLM_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(f"[classifier] LLM 返回非 200: {resp.status_code} body={resp.text[:200]}")
            return None

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not content:
            return None

        # 解析 JSON（容忍 ```json 包裹）
        import json
        clean = content.replace("```json", "").replace("```", "").strip()
        obj = json.loads(clean)
        category = obj.get("category")  # 可能为 None（no_person 场景）
        if category is None or not isinstance(category, str):
            return None
        category = category.strip().lower()
        if category in _CATEGORY_SET:
            return category
        logger.warning(f"[classifier] 未知 category: {category}, 原始: {content[:100]}")
        return None
    except Exception as e:
        logger.warning(f"[classifier] 分类异常: {e}")
        return None


async def classify_photos(photo_urls: list[str]) -> dict[str, str]:
    """批量分类多张照片

    输入: ["url1", "url2", ...]
    输出: {"url1": "man", "url2": "woman", ...}   # 仅包含分类成功的

    失败的 URL 不会出现在结果中，由调用方决定兜底（None → 默认 media_code）
    """
    if not settings.LLM_API_KEY:
        return {}

    if not photo_urls:
        return {}

    logger.info(f"[classifier] 开始分类 {len(photo_urls)} 张照片")

    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT + 5) as client:
        # 并发调 LLM（单图 2-3s，并发可大幅缩短）
        tasks = [_classify_one(client, url) for url in photo_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    mapping: dict[str, str] = {}
    for url, r in zip(photo_urls, results):
        if isinstance(r, str) and r in _CATEGORY_SET:
            mapping[url] = r
        # 失败/异常的 url 不入 map，pipeline._classify() 会用 None 兜底

    logger.info(f"[classifier] 分类完成: {len(mapping)}/{len(photo_urls)} 张成功, 分布: "
                f"{dict((k, mapping[k]) for k in list(mapping.keys())[:5])}")
    return mapping
