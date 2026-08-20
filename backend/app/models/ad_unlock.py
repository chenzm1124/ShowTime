"""广告解锁记录表"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class AdProvider(str, Enum):
    WECHAT = "wechat"            # 微信短视频广告
    TENCENT = "tencent"          # 优量汇
    PANGOLIN = "pangolin"        # 穿山甲


class AdStatus(str, Enum):
    PENDING = "pending"          # 已发放奖励等待确认
    REWARDED = "rewarded"        # 已发放奖励
    INVALID = "invalid"          # 无效（作弊 / 中途退出）
    FAILED = "failed"            # 失败


class AdUnlock(Base, TimestampMixin):
    """广告解锁记录

    每次用户看完整广告后，客户端上报 ad_callback_data，服务端校验合法性后写本表 + 扣减 ad_unlock_remaining_today。
    """

    __tablename__ = "ad_unlocks"
    __table_args__ = (
        Index("ix_ad_unlocks_user_id", "user_id"),
        Index("ix_ad_unlocks_status", "status"),
        Index("ix_ad_unlocks_user_date", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    provider: Mapped[AdProvider] = mapped_column(
        SAEnum(AdProvider, name="ad_provider", native_enum=False, length=32), nullable=False
    )
    ad_unit_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="广告位 ID")
    ad_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="rewarded_video", comment="广告类型"
    )

    status: Mapped[AdStatus] = mapped_column(
        SAEnum(AdStatus, name="ad_status", native_enum=False, length=32), nullable=False, default=AdStatus.PENDING
    )

    # 客户端上报的回调数据（用于反作弊校验）
    callback_data: Mapped[str | None] = mapped_column(Text, nullable=True, comment="ad_callback_data JSON")
    watch_duration_seconds: Mapped[int] = mapped_column(default=0, comment="观看时长（秒）")
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)

    def __repr__(self) -> str:
        return f"<AdUnlock id={self.id} user={self.user_id} status={self.status}>"
