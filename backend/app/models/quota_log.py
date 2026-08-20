"""额度流水表（所有配额变动可追溯）"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class QuotaChangeType(str, Enum):
    """额度变更类型"""

    TRIAL_CONSUME = "trial_consume"          # 试用扣减
    AD_UNLOCK_REWARD = "ad_unlock_reward"    # 广告解锁奖励
    VIP_GRANT = "vip_grant"                  # VIP 开通奖励
    VIP_RENEW = "vip_renew"                  # VIP 续费
    VIP_EXPIRE = "vip_expire"                # VIP 过期清零
    PACK_PURCHASE = "pack_purchase"          # 次数包购买
    PACK_CONSUME = "pack_consume"            # 次数包扣减
    PACK_EXPIRE = "pack_expire"              # 次数包过期清零
    PACK_EXHAUST = "pack_exhaust"            # 次数包用完
    TASK_FAIL_REFUND = "task_fail_refund"    # 任务失败回滚
    ADMIN_ADJUST = "admin_adjust"            # 管理员调整
    DAILY_RESET = "daily_reset"              # 每日重置（VIP/广告次数）


class QuotaLog(Base, TimestampMixin):
    """额度流水表

    每一次配额变化都写一条记录，便于审计、对账、客服查询。
    """

    __tablename__ = "quota_logs"
    __table_args__ = (
        Index("ix_quota_logs_user_id", "user_id"),
        Index("ix_quota_logs_change_type", "change_type"),
        Index("ix_quota_logs_user_type_time", "user_id", "change_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    change_type: Mapped[QuotaChangeType] = mapped_column(
        SAEnum(QuotaChangeType, name="quota_change_type", native_enum=False, length=32), nullable=False
    )

    # 关联业务单据
    related_task_id: Mapped[int | None] = mapped_column(BigInt, nullable=True, index=True)
    related_order_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_ad_unlock_id: Mapped[int | None] = mapped_column(BigInt, nullable=True)

    # 变更详情（JSON 字符串，含 before / after）
    change_detail: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON：变更前后对比")

    # 备注
    remark: Mapped[str | None] = mapped_column(String(256), nullable=True)

    operator_id: Mapped[int | None] = mapped_column(BigInt, nullable=True, comment="操作人（管理员）ID")

    def __repr__(self) -> str:
        return f"<QuotaLog user={self.user_id} type={self.change_type}>"
