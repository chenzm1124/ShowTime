"""用户持有的次数套餐包

一个用户可能买过多个包（同时有效 / 先后到期），每个包独立扣减。
设计要点：
- remaining_tasks 剩余处理次数，初始等于 pack.task_quota，每次发起任务扣 1，到期/用完置 0
- expire_at 过期时间，到期时把 remaining_tasks 清零并把 status 置为 EXPIRED
- status: ACTIVE / EXHAUSTED(用完) / EXPIRED(过期) / REFUNDED(退款)
- 一个 user 在同一种 pack 上可有多个持有记录（叠加购买），但 active 阶段只能各扣各的
"""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class UserPackStatus(str, Enum):
    ACTIVE = "active"            # 有效期内，剩余次数 > 0
    EXHAUSTED = "exhausted"      # 次数已用完
    EXPIRED = "expired"          # 到期清零
    REFUNDED = "refunded"        # 已退款


class UserPack(Base, TimestampMixin):
    """用户持有的次数套餐包"""

    __tablename__ = "user_packs"
    __table_args__ = (
        Index("ix_user_packs_user_id", "user_id"),
        Index("ix_user_packs_user_status", "user_id", "status"),
        Index("ix_user_packs_user_expire", "user_id", "expire_at"),
        Index("ix_user_packs_order_no", "related_order_no", unique=False),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)

    # 持有关系
    user_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    pack_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("quota_packs.id", ondelete="RESTRICT"), nullable=False
    )
    # 冗余快照（防止 pack 表后续改价/改权益影响历史订单展示）
    pack_code: Mapped[str] = mapped_column(String(32), nullable=False)
    pack_name: Mapped[str] = mapped_column(String(64), nullable=False)
    initial_task_quota: Mapped[int] = mapped_column(Integer, nullable=False, comment="初始次数")
    photos_per_task: Mapped[int] = mapped_column(Integer, nullable=False, comment="单次张数（购买时的快照）")
    max_refine_per_task: Mapped[int] = mapped_column(Integer, nullable=False, comment="单次精修张数（快照）")

    # 剩余 / 状态
    remaining_tasks: Mapped[int] = mapped_column(Integer, nullable=False, comment="剩余处理次数")
    status: Mapped[UserPackStatus] = mapped_column(
        SAEnum(UserPackStatus, name="user_pack_status", native_enum=False, length=32), nullable=False, default=UserPackStatus.ACTIVE
    )

    # 时间
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="购买时间")
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="激活时间（=purchased_at）")
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="过期时间")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="最后一次扣减时间")

    # 关联订单
    related_order_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="关联订单号")

    @property
    def is_usable(self) -> bool:
        """当前是否可用：状态 ACTIVE 且未过期 且 剩余次数 > 0"""
        # 修复：DB 读出的 expire_at 可能 naive，此处统一按 UTC 处理
        expire_at = self.expire_at
        if expire_at is not None and expire_at.tzinfo is None:
            expire_at = expire_at.replace(tzinfo=timezone.utc)
        return (
            self.status == UserPackStatus.ACTIVE
            and self.remaining_tasks > 0
            and expire_at > datetime.now(timezone.utc)
        )

    def __repr__(self) -> str:
        return f"<UserPack user={self.user_id} pack={self.pack_code} remaining={self.remaining_tasks} status={self.status}>"
