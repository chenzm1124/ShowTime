"""VIP 套餐相关 Schema"""

import json
from typing import Literal

from pydantic import BaseModel, Field


class VipPlanOut(BaseModel):
    """VIP 套餐详情（前端展示用）

    注意：daily_limit 是权威字段，features 仅作为附加权益文案。
    前端 tp-vip-card 组件会优先用 daily_limit 实时拼"X次/天"，
    避免后端 features 里残留老文案（5/8/12）。
    """

    level: Literal["vip1", "vip2", "vip3"]
    name: str
    price_monthly: float = Field(..., description="月价（元）")
    price_yearly: float = Field(..., description="年价（元）")
    photos_per_task: int = Field(..., description="单次最多处理照片数")
    daily_limit: int = Field(..., description="每日次数上限（vip1=3, vip2=5, vip3=7）")
    features: list[str] = Field(default_factory=list, description="附加权益文案")
    badge: str | None = None
    highlight: bool = False
    description: str | None = None

    @classmethod
    def from_orm_obj(cls, obj) -> "VipPlanOut":
        return cls(
            level=obj.level,
            name=obj.name,
            price_monthly=obj.price_monthly / 100.0,            # 分 → 元
            price_yearly=obj.price_yearly / 100.0,
            photos_per_task=obj.photos_per_task,
            daily_limit=obj.daily_limit,
            features=json.loads(obj.features) if obj.features else [],
            badge=obj.badge,
            highlight=obj.highlight,
            description=obj.description,
        )
