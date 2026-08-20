"""VIP 套餐配置表"""

from sqlalchemy import Boolean, Index, Integer, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class VipPlan(Base, TimestampMixin):
    """VIP 套餐配置

    - level: 套餐等级（vip1 / vip2 / vip3）
    - price_monthly / price_yearly: 月价 / 年价（单位：分）
    - photos_per_task: 单次可处理照片数上限
    - daily_limit: 每日次数上限
    - features: 权益列表（JSON 字符串）
    - is_active: 是否可购买
    - sort_order: 排序权重
    """

    __tablename__ = "vip_plans"
    __table_args__ = (
        Index("ix_vip_plans_level", "level", unique=True),
        Index("ix_vip_plans_active_sort", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, comment="vip1 | vip2 | vip3")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="套餐名")
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 价格（单位：分，避免浮点）
    price_monthly: Mapped[int] = mapped_column(Integer, nullable=False, comment="月价（分）")
    price_yearly: Mapped[int] = mapped_column(Integer, nullable=False, comment="年价（分）")
    original_price_monthly: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="月价原价（分）")
    original_price_yearly: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="年价原价（分）")

    # 权益
    photos_per_task: Mapped[int] = mapped_column(Integer, nullable=False, comment="单次处理上限")
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, comment="每日次数上限")
    features: Mapped[str] = mapped_column(Text, nullable=False, default="[]", comment="权益 JSON 数组")
    badge: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="角标：推荐 / 限时")
    highlight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否高亮")

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<VipPlan level={self.level} name={self.name} price={self.price_monthly/100:.2f}/月>"
