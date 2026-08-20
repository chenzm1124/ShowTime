"""本地 RAG 检索：从 caption_samples 样本库中，按 LLM 看图抽出的关键词
召回最相关的 top_k 条参考文案，用于喂给 LLM 写作时作为风格示例。

设计目标：
- 零外部依赖：不引入 sentence-transformers / chroma / faiss 等重型库
- 召回质量：靠"加权打分"算法，对 200~5000 条样本规模的场景足够
- 可扩展：后续可平滑替换为向量检索（接口保持不变）

打分维度（按重要性排序）：
1. scene 完全命中（scene ∈ sample.scenes）：+10
2. scene 字面包含/被包含：+5
3. mood 命中（mood ∈ sample.moods）：+5
4. keyword 在样本 text 中出现：+3
5. keyword 与样本 keywords 字段重叠：+2
6. subject 在样本 text 中出现：+2
7. 字面 token 重叠率（分字 + 2 字切片）：+0~2

调用顺序：
1. 先调 caption_knowledge.sample_match(scene, style, n) 做精确反查
2. 不够 top_k 时，再按 _score_sample 加权打分补充
"""

from __future__ import annotations

import random
import re
from typing import Any

from app.ai.caption_knowledge import sample_match

# ---------- 字面 token 化（避免引入 jieba） ----------
_TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+")


def _tokenize(text: str) -> set[str]:
    """简单中文分词：单字 + 2 字切片。返回去重后的 token 集合。"""
    if not text:
        return set()
    text = _TOKEN_PATTERN.sub("", text)  # 仅保留中文/英文/数字
    if not text:
        return set()
    tokens: set[str] = set()
    # 单字
    for c in text:
        tokens.add(c)
    # 2 字切片（捕获常见 2 字词）
    for i in range(len(text) - 1):
        tokens.add(text[i:i + 2])
    return tokens


# ---------- 加权打分 ----------
def _score_sample(sample: dict, kw: dict[str, Any]) -> float:
    """对一条样本按与用户关键词的契合度打分。

    Args:
        sample: 单条样本 dict（含 text/style/scenes/moods/keywords 字段）
        kw: LLM 抽出的关键词 dict（scene/mood/keywords/subjects）

    Returns:
        float 打分（0 表示无关，>0 表示越相关分越高）
    """
    scene = (kw.get("scene") or "").strip()
    mood = (kw.get("mood") or "").strip()
    keywords: list[str] = kw.get("keywords") or []
    subjects: list[str] = kw.get("subjects") or []

    text = sample.get("text", "")
    scenes = sample.get("scenes", [])
    moods = sample.get("moods", [])
    sample_keywords = sample.get("keywords", [])

    score = 0.0

    # === 场景匹配 ===
    if scene and scenes:
        if scene in scenes:
            score += 10.0  # 完全命中
        else:
            # 字面包含/被包含（避免误命中用长度差判断）
            for s in scenes:
                if abs(len(s) - len(scene)) <= 1 and (scene in s or s in scene):
                    score += 5.0
                    break

    # === 情绪匹配 ===
    if mood and moods and mood in moods:
        score += 5.0

    # === keyword 在样本 text 中出现 ===
    for k in keywords:
        if k and len(k) >= 1 and k in text:
            score += 3.0

    # === keyword 与 sample.keywords 重叠 ===
    if keywords and sample_keywords:
        for k in keywords:
            for sk in sample_keywords:
                if k and sk and (k in sk or sk in k):
                    score += 2.0
                    break

    # === subject 在 text 中出现 ===
    for subj in subjects:
        if subj and subj in text:
            score += 2.0

    # === 字面 token 重叠率（0~2）===
    if scene or keywords:
        query_tokens = _tokenize(scene) | {k for k in keywords if k}
        text_tokens = _tokenize(text)
        if query_tokens and text_tokens:
            overlap = len(query_tokens & text_tokens)
            ratio = overlap / max(len(query_tokens), 1)
            score += min(ratio * 4.0, 2.0)  # 最高 +2

    return score


def retrieve_similar_captions(
    kw: dict[str, Any],
    style: str,
    top_k: int = 5,
) -> list[str]:
    """根据 LLM 抽出的关键词，从本地知识库检索最相关的 top_k 条参考文案。

    算法：
    1. 先按 (scene, style) 精确反查（caption_knowledge.sample_match）
       - 命中率高时返回的样本与图最贴切，作为首选
    2. 不够 top_k 时，按 _score_sample 加权打分从全样本库补充
       - 排序后去重追加，直到凑够 top_k

    Args:
        kw: LLM 看图抽出的关键词 dict（含 scene/mood/keywords/subjects）
        style: 风格代码（literary/humor/...）
        top_k: 召回条数上限（默认 5）

    Returns:
        list[str] 去重后的 top_k 条文案（可能少于 top_k）
    """
    if not kw:
        # 关键词为空（如 LLM 失败）：退化为该风格的随机 top_k 条（避免每次结果固定）
        from app.ai.caption_samples import SAMPLES
        pool = [
            (s.get("text") or "").strip()
            for s in SAMPLES
            if s.get("style") == style and (s.get("text") or "").strip()
        ]
        if not pool:
            return []
        random.shuffle(pool)
        return pool[:top_k]

    # === 阶段 1：精确反查（高质量、零成本）===
    scene = kw.get("scene") or ""
    exact = sample_match(scene, style, n=top_k)
    if len(exact) >= top_k:
        return exact[:top_k]

    # === 阶段 2：加权打分补充 ===
    from app.ai.caption_samples import SAMPLES

    scored: list[tuple[float, str]] = []
    for s in SAMPLES:
        if s.get("style") != style:
            continue
        text = (s.get("text") or "").strip()
        if not text or text in exact:
            continue
        score = _score_sample(s, kw)
        if score > 0:
            scored.append((score, text))

    # 按分数降序，相同分数时保持稳定（避免每次结果差太多）
    scored.sort(key=lambda x: -x[0])

    # 补充到 top_k（保留精确反查的优先位置）
    seen = set(exact)
    for _, t in scored:
        if t not in seen:
            seen.add(t)
            exact.append(t)
        if len(exact) >= top_k:
            break

    return exact[:top_k]


def retrieve_for_multi_styles(
    kw: dict[str, Any],
    styles: list[str],
    top_k: int = 5,
) -> dict[str, list[str]]:
    """为多种风格批量检索参考样本（一次遍历样本库，按风格分组）。

    Returns:
        {style: [text, ...]}
    """
    if not styles:
        return {}
    return {
        style: retrieve_similar_captions(kw, style, top_k=top_k)
        for style in styles
    }


# ---------- 监控/调试 ----------
def get_retrieval_stats() -> dict:
    """返回检索层统计信息（用于监控/调试）。"""
    from app.ai.caption_samples import SAMPLES, get_sample_stats
    return {
        "sample_count": len(SAMPLES),
        "sample_stats": get_sample_stats(),
    }