"""文案生成相关 Schema（与前端 caption.ts 对齐）"""

from pydantic import BaseModel, Field, field_validator


class CaptionStyleOut(BaseModel):
    """文案风格（与前端 CaptionStyle 对齐）"""

    code: str = Field(..., description="风格代码")
    name: str = Field(..., description="风格名称")
    description: str = Field("", description="风格描述")
    emoji: str = Field("", description="风格 emoji")


class CaptionGenerateReq(BaseModel):
    """生成文案请求（与前端 GenerateCaptionPayload 对齐）

    业务约定：
    - styles 1~2 个，每风格生成 count 条（默认 3）
    - 不消耗套餐次数（业务侧不扣额度）
    """

    photo_urls: list[str] = Field(..., min_length=1, max_length=9, description="照片 URL 列表")
    location: str | None = Field(None, description="拍摄地点")
    event_name: str | None = Field(
        None,
        max_length=60,
        description="活动名称（可选）。与 location 一起作为提示词传给 LLM，用于在文案中体现活动主题",
    )
    styles: list[str] = Field(
        default_factory=lambda: ["professional"],
        description="文案风格列表（1~2 个）",
    )
    count: int = Field(3, ge=1, le=3, description="每风格生成条数（默认 3，上限 3）")

    @field_validator("styles")
    @classmethod
    def _validate_styles(cls, v: list[str]) -> list[str]:
        if not v:
            return ["professional"]
        if len(v) > 2:
            # 业务上限：最多 2 种风格
            return v[:2]
        return v


class GeneratedCaptionOut(BaseModel):
    """单条生成文案（与前端 GeneratedCaption 对齐）"""

    id: str
    text: str
    style: str
    style_label: str
    emoji: str


class CaptionGroupOut(BaseModel):
    """按风格分组的生成结果"""

    style: str = Field(..., description="风格代码")
    style_label: str = Field(..., description="风格名称")
    emoji: str = Field("", description="风格 emoji")
    captions: list[GeneratedCaptionOut] = Field(
        default_factory=list, description="该风格下的文案列表"
    )
