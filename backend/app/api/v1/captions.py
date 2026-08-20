"""文案生成路由

对应 PRD FR-401~408：
- GET  /api/v1/captions/styles   获取文案风格列表
- POST /api/v1/captions/generate 生成朋友圈文案（按风格分组返回）

业务约定（2026-08 调整 · 个人创业者沙龙场景）：
- 一次请求最多 2 种风格，每风格 3 条文案
- 不消耗套餐次数（鼓励分享，提升拉新）
- 多模态大模型抽关键词 + 知识库模板渲染
- 风格列表仅返回新版 5 种商务场景风格
"""

import uuid

from fastapi import APIRouter

from app.ai import ai_pipeline
from app.ai.base import CAPTION_STYLE_LABELS, CaptionStyle
from app.ai.caption_knowledge import STYLE_DESC, STYLE_EMOJI
from app.api.deps import CurrentUser
from app.schemas.caption import (
    CaptionGenerateReq,
    CaptionGroupOut,
    CaptionStyleOut,
    GeneratedCaptionOut,
)

router = APIRouter(prefix="/captions", tags=["captions"])

# 新版 5 种商务场景风格（仅这些通过 /styles 返回给前端）
_NEW_STYLES = ["professional", "energetic", "warm", "minimal", "reflective"]


@router.get(
    "/styles",
    response_model=list[CaptionStyleOut],
    summary="获取文案风格列表",
)
async def get_styles() -> list[CaptionStyleOut]:
    """获取可用的文案风格列表（FR-404）· 仅返回新版 5 种商务场景风格"""
    return [
        CaptionStyleOut(
            code=code,
            name=name,
            description=STYLE_DESC.get(code, ""),
            emoji=STYLE_EMOJI.get(code, ""),
        )
        for code, name in CAPTION_STYLE_LABELS.items()
        if code in _NEW_STYLES
    ]


@router.post(
    "/generate",
    response_model=list[CaptionGroupOut],
    summary="生成朋友圈文案",
)
async def generate(
    req: CaptionGenerateReq,
    user: CurrentUser,
) -> list[CaptionGroupOut]:
    """根据照片和风格生成朋友圈文案（FR-401~408）

    - 不消耗套餐次数（业务侧不扣额度，由 pipeline 保证）
    - 返回按风格分组的结果，每风格 count 条
    """
    # 业务保护：未知风格剔除
    valid_styles = [s for s in req.styles if s in CAPTION_STYLE_LABELS]
    if not valid_styles:
        valid_styles = ["professional"]

    # 调 pipeline 生成多风格文案
    grouped: dict[str, list[str]] = await ai_pipeline.generate_captions_only(
        photo_urls=req.photo_urls,
        location=req.location,
        event_name=req.event_name,
        styles=valid_styles,
        count_per_style=req.count,
    )

    # 组装响应
    out: list[CaptionGroupOut] = []
    for style_code in valid_styles:
        style_label = CAPTION_STYLE_LABELS.get(style_code, style_code)
        emoji = STYLE_EMOJI.get(style_code, "")
        captions = [
            GeneratedCaptionOut(
                id=str(uuid.uuid4()),
                text=text,
                style=style_code,
                style_label=style_label,
                emoji=emoji,
            )
            for text in grouped.get(style_code, [])
        ]
        out.append(
            CaptionGroupOut(
                style=style_code,
                style_label=style_label,
                emoji=emoji,
                captions=captions,
            )
        )

    return out
