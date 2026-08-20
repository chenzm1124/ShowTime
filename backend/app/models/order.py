"""VIP 订单表"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class OrderStatus(str, Enum):
    PENDING = "pending"          # 待支付
    PAID = "paid"                # 已支付
    REFUNDING = "refunding"      # 退款中
    REFUNDED = "refunded"        # 已退款
    CANCELLED = "cancelled"      # 已取消
    FAILED = "failed"            # 支付失败


class PayChannel(str, Enum):
    WECHAT = "wechat"            # 微信支付
    ALIPAY = "alipay"            # 支付宝（预留）


class PayPeriod(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class Order(Base, TimestampMixin):
    """VIP 订单表

    流程：创建订单 → 调微信统一下单 → 用户支付 → 微信回调 → 验签 → 更新为 PAID
    """

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_order_no", "order_no", unique=True),
        Index("ix_orders_user_id", "user_id"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_paid_at", "paid_at"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="商户订单号")
    user_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 商品信息
    plan_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("vip_plans.id", ondelete="RESTRICT"), nullable=False
    )
    plan_level: Mapped[str] = mapped_column(String(16), nullable=False, comment="冗余：vip1/vip2/vip3")
    plan_name: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[PayPeriod] = mapped_column(
        SAEnum(PayPeriod, name="pay_period", native_enum=False, length=32), nullable=False, default=PayPeriod.MONTHLY
    )

    # 金额（分）
    amount: Mapped[int] = mapped_column(Integer, nullable=False, comment="实际支付金额（分）")
    original_amount: Mapped[int] = mapped_column(Integer, nullable=False, comment="原价（分）")

    # 支付信息
    pay_channel: Mapped[PayChannel] = mapped_column(
        SAEnum(PayChannel, name="pay_channel", native_enum=False, length=32), nullable=False, default=PayChannel.WECHAT
    )
    pay_status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status", native_enum=False, length=32), nullable=False, default=OrderStatus.PENDING
    )
    # 别名 status（兼容旧查询）
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status", native_enum=False, length=32, create_type=False),
        nullable=False,
        default=OrderStatus.PENDING,
    )

    # 微信支付回执
    transaction_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="微信支付订单号"
    )
    prepay_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="预支付交易会话标识")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_amount: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="退款金额（分）")

    # VIP 生效区间
    vip_start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vip_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 客户端信息
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extra: Mapped[str | None] = mapped_column(Text, nullable=True, comment="扩展字段 JSON")

    def __repr__(self) -> str:
        return f"<Order order_no={self.order_no} amount={self.amount/100:.2f} status={self.status}>"
