"""分享记录表（朋友圈分享统计）"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class ShareRecord(Base, TimestampMixin):
    """用户分享记录

    用于：
    1. 运营统计每日分享数 / 转化率
    2. 触发"分享得次数"等运营活动
    3. 防止同一用户同一照片重复刷分享
    """

    __tablename__ = "share_records"
    __table_args__ = (
        Index("ix_share_records_user_id", "user_id"),
        Index("ix_share_records_task_id", "task_id"),
        Index("ix_share_records_share_date", "share_date"),
        Index("ix_share_records_user_date", "user_id", "share_date"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )

    # 分享渠道
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, default="wechat_moments", comment="wechat_moments | wechat_friend | copy_link"
    )
    share_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="分享时间（精确到秒）")

    # 后续回流
    clicked_back: Mapped[bool] = mapped_column(nullable=False, default=False, comment="是否有点击回流")
    registered_user_id: Mapped[int | None] = mapped_column(BigInt, nullable=True, comment="通过此分享注册的新用户 ID")
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ShareRecord user={self.user_id} channel={self.channel}>"
