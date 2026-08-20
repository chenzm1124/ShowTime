"""照片表"""

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import SoftDeleteMixin, TimestampMixin
from app.db.session import Base


class Photo(Base, TimestampMixin, SoftDeleteMixin):
    """照片元信息表

    - 对象存储（OSS / COS）保存原图与处理结果
    - url 字段存对象 key，签发后的临时 URL 在 service 层拼接
    """

    __tablename__ = "photos"
    __table_args__ = (
        Index("ix_photos_user_id", "user_id"),
        Index("ix_photos_task_id", "task_id"),
        Index("ix_photos_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )

    # ---------- 原始照片 ----------
    original_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="原图 OSS key")
    original_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="原图字节数")
    original_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="原图 sha256（去重用）")

    # ---------- AI 处理结果 ----------
    processed_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="精修后 OSS key")
    thumb_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="缩略图 OSS key")

    # 智能筛选字段
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="质量评分 0-1")
    aesthetic_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="美学评分")
    face_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="人脸数")
    is_blurry: Mapped[bool] = mapped_column(nullable=False, default=False, comment="是否模糊")
    is_duplicate: Mapped[bool] = mapped_column(nullable=False, default=False, comment="是否重复")
    cluster_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="构图聚类 ID")
    scene_tags: Mapped[str | None] = mapped_column(Text, nullable=True, comment="场景标签 JSON")

    # 精修字段
    retouch_style: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="修图风格 auto/hk/cyber/soft/film/fresh"
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="uploaded", comment="uploaded|processing|done|failed"
    )
    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 原图清理标记：精修完成后原图保留，待用户下载精修图后才删除（用于前后对比）
    original_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="原图是否已删除（下载精修图后清理）"
    )

    # 图片过期时间（用于生命周期管理：免费7天/VIP30天/VIP3永久(null)）
    expire_at: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="图片过期时间 ISO 格式，null=永久")

    # 上传顺序
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<Photo id={self.id} user={self.user_id} status={self.status}>"
