"""次数包订单表

与 orders（VIP 月卡订单）物理隔离：业务流不同、支付金额区间不同、未来可能上不同的
优惠规则（次数包常做限时折扣、VIP 月卡做连续包月）。
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class PackOrderStatus(str, Enum):
    PENDING = "pending"          # 待支付
    PAID = "paid"                # 已支付
    REFUNDING = "refunding"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PayChannel(str, Enum):
    WECHAT = "wechat"
    ALIPAY = "alipay"


class PackOrder(Base, TimestampMixin):
    """次数包订单"""

    __tablename__ = "pack_orders"
    __table_args__ = (
        Index("ix_pack_orders_order_no", "order_no", unique=True),
        Index("ix_pack_orders_user_id", "user_id"),
        Index("ix_pack_orders_user_status", "user_id", "status"),
        Index("ix_pack_orders_paid_at", "paid_at"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="商户订单号")
    user_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 商品快照（防止 quota_packs 改价后影响历史订单）
    pack_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("quota_packs.id", ondelete="RESTRICT"), nullable=False
    )
    pack_code: Mapped[str] = mapped_column(String(32), nullable=False)
    pack_name: Mapped[str] = mapped_column(String(64), nullable=False)
    task_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    photos_per_task: Mapped[int] = mapped_column(Integer, nullable=False)
    max_refine_per_task: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # 金额（分）
    amount: Mapped[int] = mapped_column(Integer, nullable=False, comment="实付金额（分）")
    original_amount: Mapped[int] = mapped_column(Integer, nullable=False, comment="原价（分）")

    # 支付
    pay_channel: Mapped[PayChannel] = mapped_column(
        SAEnum(PayChannel, name="pack_pay_channel", native_enum=False, length=32), nullable=False, default=PayChannel.WECHAT
    )
    status: Mapped[PackOrderStatus] = mapped_column(
        SAEnum(PackOrderStatus, name="pack_order_status", native_enum=False, length=32), nullable=False, default=PackOrderStatus.PENDING
    )

    # 微信支付回执
    transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prepay_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 客户端信息
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extra: Mapped[str | None] = mapped_column(Text, nullable=True, comment="扩展 JSON")

    def __repr__(self) -> str:
        return f"<PackOrder order_no={self.order_no} amount={self.amount/100:.2f} status={self.status}>"
