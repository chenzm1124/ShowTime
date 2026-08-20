"""基于多模态大模型 + 知识库（RAG）的朋友圈文案生成 Provider

三阶段（完整 RAG 链路）：
1. 调用 qwen-vl-plus 多模态大模型"看图"，抽取结构化关键词：
   - subjects: 主体（"我"/"我们"/"她"/"情侣"/"一家三口" ...）
   - scene:    场景（"海边"/"古镇"/"街拍" ...，尽量归一到 SCENE_MOOD 已收录词）
   - mood:     情绪（"治愈"/"兴奋"/"宁静" ...，尽量归一到 MOOD_RESONANCE 已收录词）
   - keywords: 其他视觉关键词（"日落"/"樱花"/"咖啡馆" ...）
2. 本地 RAG 检索：caption_retrieval.retrieve_similar_captions 按 (scene, style) 召回 top 5
3. LLM 写作：把 top 5 参考样本 + 关键词 + 风格 + location 喂给 qwen，
   让它写出 3 条新文案（明确要求"不要逐字抄袭参考样本，要有自己的变化"）

降级链（任意环节失败都优雅降级，不让用户看到错误）：
- LLM 写作失败 → 返回检索样本
- 检索样本不足 → 走样本库 + 模板渲染
- LLM 完全不可用 → 仅返回样本库 + 模板

业务约束：
- 一次请求可指定 1~2 种风格，每种风格生成 3 条文案
- 不消耗套餐次数（由调用方保证）
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
from typing import Any

import httpx

from app.ai.base import CaptionProvider, CaptionResult, CaptionStyle
from app.ai.caption_knowledge import (
    MOOD_RESONANCE,
    SCENE_MOOD,
    STYLE_EMOJI,
    list_templates,
    render_template,
    sample_match,
)
# 重要：导入 caption_samples 以触发其模块顶层的 register_samples() 调用，
# 把 200 条真实样本注入到 caption_knowledge 的 (scene, style) 反查索引中
from app.ai import caption_samples  # noqa: F401
# 本地 RAG 检索层
from app.ai.caption_retrieval import retrieve_for_multi_styles
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# 风格中文名（用于 LLM prompt）
STYLE_LABEL: dict[str, str] = {
    "professional": "专业干练",
    "energetic": "积极正能量",
    "warm": "温暖有温度",
    "minimal": "简约高级",
    "reflective": "深度思考",
}

# 关键词抽取 prompt：要求 LLM 返回严格 JSON，便于解析
_EXTRACT_PROMPT = """请分析这一组线下沙龙/活动照片，提取关键信息用于生成品牌朋友圈文案。

只返回严格 JSON 格式（不要任何解释、不要 markdown 标记）：

{
  "subjects": ["我" | "我们" | "讲师" | "嘉宾" | "团队" | "听众" | "主理人" | ...],
  "scene": "演讲台|分享现场|圆桌会议|沙龙现场|讲座|工作坊|私董会|发布会|论坛|合影|交流互动|茶歇|签到|颁奖|讨论|会场全景|场地布置|品牌墙|大屏展示|灯光氛围|花艺茶席|讲师特写|嘉宾特写|团队合影|专注聆听|其他",
  "mood": "赋能|成长|共鸣|温暖|专注|启发|仪式感|感恩|坚定|收获|链接|轻松|专业|突破|期待|充实",
  "keywords": ["PPT", "白板", "名牌", "话筒", "鲜花", "奖杯", "名牌", "茶具", ...]
}

要求：
- subjects: 照片中的人物主体，1~2 个
- scene: 选一个最贴切的场景词（优先从给定列表中选，没有合适的可写"其他"并补充到 keywords）
- mood: 整组照片传达的情绪，选一个
- keywords: 其他视觉关键词（会场元素、物料、道具、氛围细节等），2~4 个

只输出 JSON，不要其他任何字符。"""


# ---------- 写作 prompt：基于参考样本 + 关键词生成新文案 ----------
_WRITING_PROMPT = """你是个人品牌朋友圈文案专家。请根据用户的线下沙龙/活动照片，写出风格为「{style_label}」的品牌朋友圈文案。

【用户照片的视觉关键词】（来自多模态 AI 看图分析）
- 场景：{scene}
- 情绪：{mood}
- 关键元素：{keywords}
- 活动地点：{location}

【参考样本】（仅供学习风格和句式，不要逐字抄袭或仅做同义词替换）
{refs}

【要求】
1. 写出 3 条文案（与参考样本有差异，要有自己的创意）
2. 风格严格符合「{style_label}」调性
3. 每条 8~30 字
4. 可以用 emoji（每条最多 2 个，emoji 不是必需的）
5. 体现专业度和正能量，不浮夸、不鸡汤、不油腻
6. 要有"画面感"——让读者一眼能联想到活动场景
7. 避免与参考样本重复度 >50%
8. 不要使用"旅行"、"风景"、"远方"等旅行向词汇
9. 【活动地点】里若包含「·」分隔，说明是「活动主题 + 地点」，请在 1~2 条文案里自然带出活动主题

只返回严格 JSON（不要 markdown 标记、不要任何解释）：
{{"captions": ["文案1", "文案2", "文案3"]}}"""


# ---------- 图片下载与 base64 ----------
async def _fetch_image_b64(client: httpx.AsyncClient, image_url: str) -> str | None:
    """下载图片转 base64 data URL（前端已经压缩过，这里再下载一次到后端送 LLM）

    注意：httpx 默认 follow_redirects=False，对 CDN/短链类图片（302/301）会下载失败，
    这里显式开启 follow_redirects=True 兼容常见图片托管
    """
    try:
        r = await client.get(image_url, follow_redirects=True)
        if r.status_code != 200:
            logger.warning(f"[caption] 图片下载失败 status={r.status_code} url={image_url[:80]}")
            return None
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not ct.startswith("image/"):
            ct = "image/jpeg"
        b64 = base64.b64encode(r.content).decode("ascii")
        return f"data:{ct};base64,{b64}"
    except Exception as e:
        logger.warning(f"[caption] 图片下载异常: {e} url={image_url[:80]}")
        return None


async def _extract_keywords(photo_urls: list[str]) -> dict[str, Any]:
    """调用多模态 LLM 抽取关键词

    返回结构：{"subjects": [...], "scene": "...", "mood": "...", "keywords": [...]}
    失败时返回空 dict，调用方走降级路径
    """
    if not settings.LLM_API_KEY:
        logger.debug("[caption] 未配置 LLM_API_KEY，跳过关键词抽取")
        return {}

    if not photo_urls:
        return {}

    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT + 10) as client:
        # 最多 6 张图，避免 token 爆炸（前端已压缩）
        urls_for_llm = photo_urls[:6]
        # 并行下载转 base64
        b64_tasks = [_fetch_image_b64(client, u) for u in urls_for_llm]
        b64_results = await asyncio.gather(*b64_tasks, return_exceptions=True)
        image_inputs: list[str] = []
        for r in b64_results:
            if isinstance(r, str) and r:
                image_inputs.append(r)
        if not image_inputs:
            logger.warning("[caption] 所有图片下载失败，无法调 LLM")
            return {}

        # 构造多模态消息：图片 + 文本指令
        content: list[dict[str, Any]] = []
        for img in image_inputs:
            content.append({"type": "image_url", "image_url": {"url": img}})
        content.append({"type": "text", "text": _EXTRACT_PROMPT})

        payload = {
            "model": settings.LLM_MODEL,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": settings.LLM_MAX_TOKENS,
            "temperature": 0.3,  # 关键词抽取偏稳定
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
                logger.warning(
                    f"[caption] LLM 返回非 200: {resp.status_code} body={resp.text[:200]}"
                )
                return {}

            data = resp.json()
            content_str = (
                data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            )
            if not content_str:
                return {}

            # 容忍 ```json 包裹
            clean = content_str.replace("```json", "").replace("```", "").strip()
            obj = json.loads(clean)

            # 归一 scene/mood 到知识库已有词，命中才能取到意境修饰
            scene = (obj.get("scene") or "").strip()
            if scene and scene not in SCENE_MOOD:
                # 找最接近的已收录词
                scene = _nearest_key(scene, list(SCENE_MOOD.keys())) or scene
            mood = (obj.get("mood") or "").strip()
            if mood and mood not in MOOD_RESONANCE:
                mood = _nearest_key(mood, list(MOOD_RESONANCE.keys())) or mood

            return {
                "subjects": obj.get("subjects") or [],
                "scene": scene,
                "mood": mood,
                "keywords": obj.get("keywords") or [],
            }
        except Exception as e:
            logger.warning(f"[caption] LLM 关键词抽取异常: {e}")
            return {}


def _nearest_key(word: str, candidates: list[str]) -> str | None:
    """简单字面相近匹配：返回包含关系或最长公共子串的候选词"""
    if not word:
        return None
    w = word.strip()
    # 完全包含
    for c in candidates:
        if c in w or w in c:
            return c
    return None


def _pick_subject(subjects: list[str]) -> str:
    """从 LLM 返回的 subjects 里挑一个用于模板填充"""
    if not subjects:
        return "我"
    # 优先选 "我"/"我们"，否则取第一个
    for s in subjects:
        if s in ("我", "我们"):
            return s
    return subjects[0]


def _pick_keyword(keywords: list[str]) -> str:
    """挑一个关键词用于模板填充"""
    if not keywords:
        return "分享"
    return keywords[0]


# ---------- LLM 写作：把参考样本 + 关键词喂给 LLM 生成新文案 ----------
async def _llm_write_captions(
    style: str,
    kw: dict[str, Any],
    refs: list[str],
    location: str | None,
    count: int = 3,
) -> list[str] | None:
    """调 LLM 基于参考样本 + 关键词生成 count 条文案。

    Returns:
        成功：list[str]，长度 >= count 时取前 count 条
        成功但不足 count：list[str]，调用方需补足
        失败：None（调用方走降级）
    """
    if not settings.LLM_API_KEY:
        return None

    style_label = STYLE_LABEL.get(style, style)
    refs_text = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(refs)) if refs else "（暂无参考样本，请自由发挥）"

    prompt = _WRITING_PROMPT.format(
        style_label=style_label,
        scene=kw.get("scene") or "未知场景",
        mood=kw.get("mood") or "未知情绪",
        keywords=", ".join(kw.get("keywords") or []) or "（无）",
        location=location or "（未填写）",
        refs=refs_text,
    )

    payload = {
        "model": settings.LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "你是个人品牌朋友圈文案专家，擅长为创业者/主理人的线下活动照片写调性匹配的品牌短文案。",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 600,
        "temperature": 0.85,  # 写作偏创意，避免重复
    }

    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
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
                    f"[caption] LLM 写作返回非 200: {resp.status_code} body={resp.text[:200]}"
                )
                return None

            data = resp.json()
            content_str = (
                data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            )
            if not content_str:
                return None

            # 容忍 ```json 包裹
            clean = content_str.replace("```json", "").replace("```", "").strip()
            obj = json.loads(clean)
            captions = obj.get("captions") or []
            captions = [str(c).strip() for c in captions if c and str(c).strip()]
            if not captions:
                return None
            logger.info(
                f"[caption] LLM 写作成功 [{style}]: "
                f"{captions[0][:40]}... (共 {len(captions)} 条)"
            )
            return captions
    except Exception as e:
        logger.warning(f"[caption] LLM 写作异常: {e}")
        return None


def _render_n_for_style(
    style: str,
    kw: dict[str, Any],
    count: int,
    location: str | None,
) -> list[str]:
    """按风格渲染 count 条文案。

    优先级：
    1. 真实样本库（caption_samples）按 (scene, style) 反查
    2. 模板渲染（caption_knowledge.TEMPLATES）
    3. 重复 + 简化模板兜底

    去重 + 打乱顺序。
    """
    templates = list_templates(style)
    subject = _pick_subject(kw.get("subjects", []))
    scene = kw.get("scene", "")
    mood = kw.get("mood", "")
    keyword = _pick_keyword(kw.get("keywords", []))

    rendered: list[str] = []
    seen: set[str] = set()

    def _push(text: str) -> bool:
        """去重入栈，返回是否新增"""
        text = (text or "").strip()
        if not text or text in seen:
            return False
        seen.add(text)
        rendered.append(text)
        return True

    # === 阶段 1：真实样本库检索（注入"有人味"的内容）===
    # 样本库已在模块加载时（caption_samples.py）自动注册到 caption_knowledge
    if scene:
        samples = sample_match(scene, style, n=count)
        for s in samples:
            _push(s)

    # === 阶段 2：模板渲染补足 ===
    if len(rendered) < count:
        for t in templates:
            text = render_template(
                t,
                subject=subject,
                scene=scene,
                mood=mood,
                location=location or "",
                keyword=keyword,
            )
            if _push(text) and len(rendered) >= count:
                break

    # === 阶段 3：模板不够 count 条时，shuffle 重复渲染（极少见：模板数 < count）===
    safety = 0
    while len(rendered) < count and templates and safety < 20:
        safety += 1
        t = random.choice(templates)
        text = render_template(
            t,
            subject=subject,
            scene=scene,
            mood=mood,
            location=location or "",
            keyword=keyword,
        )
        if not _push(text):
            # 退化为不加 scene 的简化版，保证不卡死
            simplified = render_template(t, subject=subject, location=location or "")
            _push(simplified)

    random.shuffle(rendered)
    return rendered[:count]


class QwenCaptionProvider(CaptionProvider):
    """多模态大模型 + 知识库文案生成

    - generate(photo_urls, location, style, count): 兼容旧接口（单风格）
    - generate_multi(photo_urls, location, styles, count_per_style): 新接口（多风格）
    """

    async def generate(
        self,
        photo_urls: list[str],
        location: str | None,
        style: CaptionStyle,  # type: ignore
        count: int = 3,
    ) -> CaptionResult:
        """旧接口：单风格生成（保持向后兼容）"""
        captions = await self.generate_multi(
            photo_urls, location, [style], count
        )
        return CaptionResult(
            captions=captions.get(style, []),
            style=style,
            location=location,
        )

    async def generate_multi(
        self,
        photo_urls: list[str],
        location: str | None,
        styles: list[str],
        count_per_style: int = 3,
        event_name: str | None = None,
    ) -> dict[str, list[str]]:
        """新接口：多风格批量生成，返回 {style: [text, ...]}

        完整 RAG 链路：
        1. LLM 看图抽关键词
        2. 本地 RAG 检索 top 5 参考样本
        3. LLM 基于参考样本 + 关键词写作
        4. 失败时降级（写作失败→检索样本→模板）

        业务约定（用户需求 #3）：
        - styles 最多 2 个
        - 每风格生成 count_per_style 条（默认 3）
        - event_name 非必填；存在时与 location 合并为 "活动名称 · 地点"，作为
          LLM 提示词中的【活动地点】字段；模板降级路径中也自动包含活动名称。
        """
        if not styles:
            styles = ["professional"]
        # 业务上限保护
        styles = styles[:2]
        count_per_style = max(1, min(3, count_per_style))

        # 合并 event_name + location：避免改动 LLM prompt 与模板系统的所有分支
        _e = (event_name or "").strip()
        _l = (location or "").strip()
        if _e and _l:
            merged_location: str | None = f"{_e} · {_l}"
        elif _e:
            merged_location = _e
        else:
            merged_location = location  # 保持 None 或原值未变，让「（未填写）」兜底生效
        location = merged_location

        # === 阶段 1：LLM 看图抽关键词 ===
        kw = await _extract_keywords(photo_urls)
        if kw:
            logger.info(
                f"[caption] LLM 抽取关键词: subjects={kw.get('subjects')} "
                f"scene={kw.get('scene')} mood={kw.get('mood')} "
                f"keywords={kw.get('keywords')}"
            )
        else:
            logger.info("[caption] LLM 未返回关键词，RAG 检索降级为通用匹配")

        # === 阶段 2：本地 RAG 检索（每风格 top 5）===
        refs_by_style = retrieve_for_multi_styles(kw, styles, top_k=5)
        for s, refs in refs_by_style.items():
            logger.info(
                f"[caption] RAG 检索 [{s}]: 召回 {len(refs)} 条"
                + (f"，首条={refs[0][:30]}..." if refs else "")
            )

        # === 阶段 3：LLM 写作 + 降级链 ===
        result: dict[str, list[str]] = {}
        for style in styles:
            captions: list[str] = []
            refs = refs_by_style.get(style, [])

            # === 3a. 优先 LLM 写作 ===
            try:
                llm_result = await _llm_write_captions(
                    style=style,
                    kw=kw,
                    refs=refs,
                    location=location,
                    count=count_per_style,
                )
                if llm_result and len(llm_result) >= count_per_style:
                    result[style] = llm_result[:count_per_style]
                    continue
                elif llm_result:
                    # LLM 写了但不足 count 条，先记下
                    captions = llm_result
            except Exception as e:
                logger.warning(f"[caption] LLM 写作异常 [{style}]: {e}")

            # === 3b. 降级 1：用检索样本补足 ===
            seen: set[str] = set(captions)
            for r in refs:
                r = (r or "").strip()
                if r and r not in seen:
                    seen.add(r)
                    captions.append(r)
                if len(captions) >= count_per_style:
                    break

            # === 3c. 降级 2：模板渲染兜底 ===
            if len(captions) < count_per_style:
                try:
                    fallback = _render_n_for_style(style, kw, count_per_style, location)
                    for t in fallback:
                        t = (t or "").strip()
                        if t and t not in seen:
                            seen.add(t)
                            captions.append(t)
                        if len(captions) >= count_per_style:
                            break
                except Exception as e:
                    logger.warning(f"[caption] 模板兜底失败 [{style}]: {e}")

            # 截断到 count 条
            result[style] = captions[:count_per_style]

        return result



