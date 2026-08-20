"""任务表（一次出图任务 = 一个 Task + N 个 Photo）"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class TaskStatus(str, Enum):
    PENDING = "pending"        # 已创建待派发
    QUEUED = "queued"          # 已入队
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 失败
    CANCELLED = "cancelled"    # 已取消


class Task(Base, TimestampMixin):
    """处理任务表"""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_id", "user_id"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_created_at", "created_at"),
        Index("ix_tasks_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 任务类型
    task_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="photo_process", comment="任务类型"
    )

    # 状态
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status", native_enum=False, length=32),
        nullable=False,
        default=TaskStatus.PENDING,
    )

    # 输入参数（JSON 序列化）
    location: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="拍摄地点")
    retouch_style: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="修图风格"
    )
    extra_params: Mapped[str | None] = mapped_column(Text, nullable=True, comment="额外参数 JSON")

    # 进度
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="总照片数")
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已处理数")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="失败数")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="进度 0-100")

    # 配额消费
    quota_reason: Mapped[str] = mapped_column(
        String(16), nullable=False, default="trial", comment="trial | ad | vip"
    )

    # 时间戳
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Celery 任务 ID
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<Task id={self.id} user={self.user_id} status={self.status}>"
