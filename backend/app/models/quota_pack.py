"""次数套餐包配置表

与 vip_plans 物理隔离：vip_plans 是订阅制（包月/包年），quota_packs 是
一次性售卖的次数包（买断制）。两者权益、计费、有效期逻辑完全不同。
"""

from sqlalchemy import Boolean, Index, Integer, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class QuotaPack(Base, TimestampMixin):
    """次数套餐包配置

    - code: 业务编码（daily / enjoy / unlimited）
    - price: 售价（分）
    - task_quota: 处理次数（可发起几次批量任务）
    - photos_per_task: 单次最多处理张数
    - max_refine_per_task: 单次最多精修张数（精修是 GPU 重活，要单独限）
    - valid_days: 有效期（天），从购买日开始算
    - features: 权益文案（JSON 数组）
    """

    __tablename__ = "quota_packs"
    __table_args__ = (
        Index("ix_quota_packs_code", "code", unique=True),
        Index("ix_quota_packs_active_sort", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False,
        comment="业务编码：daily | enjoy | unlimited",
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="套餐名")
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 价格（分）
    price: Mapped[int] = mapped_column(Integer, nullable=False, comment="售价（分）")
    original_price: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="划线价（分）")

    # 权益
    task_quota: Mapped[int] = mapped_column(Integer, nullable=False, comment="处理次数（可发起几次批量任务）")
    photos_per_task: Mapped[int] = mapped_column(Integer, nullable=False, comment="单次最多处理张数")
    max_refine_per_task: Mapped[int] = mapped_column(Integer, nullable=False, comment="单次最多精修张数")
    valid_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="有效期（天）")
    features: Mapped[str] = mapped_column(Text, nullable=False, default="[]", comment="权益 JSON 数组")

    # 展示
    badge: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="角标：推荐 / 限时 / 热销")
    highlight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否高亮")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<QuotaPack code={self.code} name={self.name} price={self.price/100:.2f} task_quota={self.task_quota}>"
