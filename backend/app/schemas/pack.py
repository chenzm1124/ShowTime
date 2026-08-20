"""次数套餐包相关 Schema

包含：QuotaPackOut（详情）、UserPackBrief（用户持有快照）、PurchaseReq/Resp
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


# ==================== QuotaPack（套餐定义）====================

class QuotaPackOut(BaseModel):
    """次数套餐包详情（前端展示用）"""

    id: int
    code: Literal["daily", "enjoy", "unlimited"]
    name: str
    description: str | None = None
    price: float = Field(..., description="售价（元）")
    original_price: float | None = Field(None, description="划线价（元）")
    task_quota: int = Field(..., description="处理次数")
    photos_per_task: int = Field(..., description="单次最多处理张数")
    max_refine_per_task: int = Field(..., description="单次最多精修张数")
    valid_days: int = Field(..., description="有效期（天）")
    features: list[str] = []
    badge: str | None = None
    highlight: bool = False

    @classmethod
    def from_orm_obj(cls, obj) -> "QuotaPackOut":
        import json
        return cls(
            id=obj.id,
            code=obj.code,
            name=obj.name,
            description=obj.description,
            price=obj.price / 100.0,            # 分 → 元
            original_price=(obj.original_price / 100.0) if obj.original_price else None,
            task_quota=obj.task_quota,
            photos_per_task=obj.photos_per_task,
            max_refine_per_task=obj.max_refine_per_task,
            valid_days=obj.valid_days,
            features=json.loads(obj.features) if obj.features else [],
            badge=obj.badge,
            highlight=obj.highlight,
        )


# ==================== UserPack（用户持有）====================

class UserPackBrief(BaseModel):
    """用户持有的次数包（供 QuotaInfo.user_packs 嵌入）"""

    user_pack_id: int
    pack_code: str
    pack_name: str
    remaining_tasks: int
    total_tasks: int
    photos_per_task: int
    max_refine_per_task: int
    expire_at: datetime
    expire_in_seconds: int

    @classmethod
    def from_orm_obj(cls, obj) -> "UserPackBrief":
        # 修复：SQLite 不存储时区信息，DB 读出的 datetime 可能是 naive 也可能是 aware；
        # 这里统一按 UTC 处理，避免 offset-naive/aware 混用的 TypeError
        now = datetime.now(timezone.utc)
        expire_at = obj.expire_at
        if expire_at is not None and expire_at.tzinfo is None:
            expire_at = expire_at.replace(tzinfo=timezone.utc)
        in_seconds = int((expire_at - now).total_seconds()) if expire_at else 0
        return cls(
            user_pack_id=obj.id,
            pack_code=obj.pack_code,
            pack_name=obj.pack_name,
            remaining_tasks=obj.remaining_tasks,
            total_tasks=obj.initial_task_quota,
            photos_per_task=obj.photos_per_task,
            max_refine_per_task=obj.max_refine_per_task,
            expire_at=expire_at or now,
            expire_in_seconds=in_seconds,
        )


class UserPackOut(UserPackBrief):
    """完整的用户持有包记录（后台用）"""

    status: str
    purchased_at: datetime
    activated_at: datetime
    consumed_at: datetime | None
    related_order_no: str | None


# ==================== 购买 ====================

class PurchasePackReq(BaseModel):
    """购买次数包请求"""

    pack_code: Literal["daily", "enjoy", "unlimited"]
    pay_channel: Literal["wechat", "alipay"] = "wechat"


class PurchasePackResp(BaseModel):
    """购买次数包响应

    - mock 模式下：status='success'，已直接到账（同步返回 user_pack）
    - 真实模式：status='pending'，前端拿到 prepay_params 调起微信支付
    """

    order_no: str
    pack: QuotaPackOut
    pay_status: Literal["success", "pending"]
    # 仅在 pending 时有值
    prepay_params: dict | None = None
    # 仅在 success 时有值（mock 模式同步到账）
    user_pack: UserPackBrief | None = None
    message: str | None = None


class PackConsumeReq(BaseModel):
    """任务创建时扣减次数包（原子操作）"""

    user_pack_id: int = Field(..., description="要扣减的 user_pack 主键")


class PackConsumeResp(BaseModel):
    """扣减响应"""

    user_pack_id: int
    remaining_tasks: int
    message: str
