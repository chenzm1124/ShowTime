"""Qwen 多模态 Embedding 客户端。

使用阿里云 DashScope multimodal-embedding-v1 模型，把图片转为 1024 维向量。
用于 Screener 阶段的「语义聚类」（同人物不同背景也能命中）。

API endpoint（非 OpenAI 兼容）：
    POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding
    Authorization: Bearer <API_KEY>
    Body:
        {
          "model": "multimodal-embedding-v1",
          "input": {"contents": [{"image": "https://..."}, ...]},
        }

    Response:
        {
          "output": {
            "embeddings": [{"index": 0, "embedding": [float, ...]}, ...],
          },
          "usage": {"image_tokens": N},
        }

成本：约 0.001 元/张（输入图片，按张计费）。
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
from typing import Any

import httpx
from PIL import Image

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# DashScope multimodal-embedding 限制单图 <= 3072KB（3MB），原图常超此限制 → HTTP 400。
# 超过则下载后用 Pillow 压缩到 <3MB 再传 base64 data URL。
_EMBED_MAX_BYTES = 3 * 1024 * 1024
_EMBED_TARGET_BYTES = 2_800_000  # 留一点余量，避免边界抖动


def _fetch_and_compress_image(url: str, presign_fn=None) -> str | None:
    """下载图片并压缩到 <3MB，返回 base64 data URL；失败返回 None。

    P1-14 修复：DashScope embedding 接口对图片体积限制 [0, 3072KB]，而旅行原图
    常 3~8MB，直接传 URL 会被 API 拒（HTTP 400 image size should be [0, 3072KB]），
    导致 embedding 全部失败、语义聚类维度失效。这里下载后用 Pillow 缩放/降质
    压到目标体积，再用 data URL 直接内联传输，规避体积限制。

    P1-15 修复：原图直传 COS 私有桶，set_object_public 有最终一致性延迟，
    并发场景下匿名 GET 裸 URL 仍会 403（实测 preview 阶段 6 张 embedding 全 403）。
    若传入 presign_fn(object_key) -> signed_url，优先用带 owner 密钥的签名 GET URL
    取图，规避 ACL 延迟，稳定拿到原图。
    """
    fetch_url = url
    if presign_fn:
        try:
            signed = presign_fn(url)
            if signed:
                fetch_url = signed
        except Exception as e:
            logger.debug(f"[qwen_embedding] 生成签名 URL 失败，回退裸 URL: {e}")
    try:
        with httpx.Client(timeout=30) as cli:
            r = cli.get(fetch_url)
            r.raise_for_status()
            raw = r.content
        if len(raw) <= _EMBED_MAX_BYTES:
            # 已满足限制，原样 base64 内联
            b64 = base64.b64encode(raw).decode()
            return f"data:image/jpeg;base64,{b64}"

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        # 先按边长缩放（最长边 1600px 足够 embedding 语义），再逐步降质直到 <3MB
        max_side = 1600
        if max(img.size) > max_side:
            ratio = max_side / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        quality = 85
        while quality >= 20:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            data = buf.getvalue()
            if len(data) <= _EMBED_TARGET_BYTES:
                b64 = base64.b64encode(data).decode()
                return f"data:image/jpeg;base64,{b64}"
            quality -= 10
        # 兜底：仍超限制就直接返回最低质版本（极端情况）
        b64 = base64.b64encode(data).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.warning(f"[qwen_embedding] 下载/压缩图片失败 {url[:80]}: {e}")
        return None

# DashScope multimodal-embedding 原生 endpoint（独立 URL，不走 OpenAI 兼容）
_EMBEDDING_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)
_DEFAULT_MODEL = "multimodal-embedding-v1"
_EMBEDDING_DIM = 1024  # multimodal-embedding-v1 输出维度
_TIMEOUT = 30.0


async def embed_images(
    image_urls: list[str],
    batch_size: int = 1,   # Qwen API 单批只支持 1 张图（"batch size can should be [1, 1]"）
    presign_fn=None,       # 可选：object_url -> 签名 GET URL，规避私有桶 403
) -> list[list[float] | None]:
    """把多张图片编码为向量。

    Args:
        image_urls: 图片 URL 列表（公网可访问的 URL 或 base64 data URL）
        batch_size: 每批请求的图片数（API 限制单批 ≤ 25）

    Returns:
        与输入等长的 list，每个元素是 1024 维向量（或 None 表示该张失败）。
        失败不会中断整批调用——失败的索引对应 None，由调用方 fallback 到多哈希。
    """
    if not settings.LLM_API_KEY:
        logger.warning("[qwen_embedding] LLM_API_KEY 未配置，跳过 embedding 聚类")
        return [None] * len(image_urls)

    result: list[list[float] | None] = [None] * len(image_urls)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for batch_start in range(0, len(image_urls), batch_size):
            batch = image_urls[batch_start:batch_start + batch_size]
            # P1-14：先把每张 URL 压缩到 <3MB 再内联，规避 DashScope 体积限制（400）
            processed: list[str] = []
            for url in batch:
                data_url = await asyncio.to_thread(_fetch_and_compress_image, url, presign_fn)
                if not data_url:
                    logger.warning(
                        f"[qwen_embedding] 图片获取/压缩失败，跳过: {url[:80]}"
                    )
                    continue
                processed.append(data_url)
            if not processed:
                continue
            payload = {
                "model": _DEFAULT_MODEL,
                "input": {"contents": [{"image": u} for u in processed]},
            }
            headers = {
                "Authorization": f"Bearer {settings.LLM_API_KEY}",
                "Content-Type": "application/json",
            }
            try:
                resp = await client.post(_EMBEDDING_URL, json=payload, headers=headers)
                if resp.status_code != 200:
                    logger.warning(
                        f"[qwen_embedding] HTTP {resp.status_code} "
                        f"batch={batch_start // batch_size} body={resp.text[:200]}"
                    )
                    continue  # 这一批留 None
                data: dict[str, Any] = resp.json()
                embeddings = (
                    data.get("output", {}).get("embeddings", [])
                )
                for item in embeddings:
                    idx_global = batch_start + int(item.get("index", -1))
                    if 0 <= idx_global < len(image_urls):
                        result[idx_global] = item.get("embedding")
                # 监控 token 消耗
                usage = data.get("usage", {})
                if usage:
                    logger.info(
                        f"[qwen_embedding] batch={batch_start // batch_size} "
                        f"image_tokens={usage.get('image_tokens')}"
                    )
            except Exception as e:
                logger.warning(f"[qwen_embedding] 异常 batch={batch_start // batch_size}: {e}")
                continue
            # 避免打爆限流（DashScope 默认 60 QPS，简单 sleep 一下）
            await asyncio.sleep(0.05)
    ok = sum(1 for v in result if v is not None)
    logger.info(f"[qwen_embedding] 完成 {ok}/{len(image_urls)} 张")
    return result


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """两向量的余弦相似度（-1~1）。调用方负责先确认两者都非 None。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    # 用 sum 避免 import numpy 在小循环里更轻
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def embedding_dim() -> int:
    return _EMBEDDING_DIM