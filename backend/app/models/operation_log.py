"""操作日志表（管理员 / 关键业务操作可追溯）"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, Index, Integer, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class OperationModule(str, Enum):
    USER = "user"            # 用户管理
    ORDER = "order"          # 订单管理
    VIP = "vip"              # VIP 管理
    QUOTA = "quota"          # 额度管理
    PHOTO = "photo"          # 照片管理
    TASK = "task"            # 任务管理
    AD = "ad"                # 广告
    CONFIG = "config"        # 系统配置


class OperationLog(Base, TimestampMixin):
    """操作日志

    主要用于：
    1. 审计（哪个管理员在什么时间做了什么）
    2. 客户支持（用户行为回溯）
    3. 系统监控（高频异常操作报警）
    """

    __tablename__ = "operation_logs"
    __table_args__ = (
        Index("ix_operation_logs_operator_id", "operator_id"),
        Index("ix_operation_logs_module", "module"),
        Index("ix_operation_logs_user_id", "user_id"),
        Index("ix_operation_logs_created_at", "created_at"),
        Index("ix_operation_logs_module_action", "module", "action"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    operator_id: Mapped[int | None] = mapped_column(
        BigInt, nullable=True, comment="操作人 ID（NULL 表示系统自动）"
    )
    operator_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="操作人名称快照")
    operator_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="admin", comment="admin | system | user"
    )

    # 操作目标
    user_id: Mapped[int | None] = mapped_column(BigInt, nullable=True, comment="被操作用户 ID")

    # 操作内容
    module: Mapped[OperationModule] = mapped_column(
        SAEnum(OperationModule, name="operation_module", native_enum=False, length=64), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, comment="操作：login / ban / refund_quota ...")
    description: Mapped[str] = mapped_column(String(256), nullable=False, comment="操作描述")

    # 请求上下文
    request_method: Mapped[str | None] = mapped_column(String(8), nullable=True)
    request_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 变更前后（JSON）
    before_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[str | None] = mapped_column(Text, nullable=True, comment="扩展信息 JSON")

    cost_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="处理耗时（ms）")
    success: Mapped[bool] = mapped_column(nullable=False, default=True)
    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)

    def __repr__(self) -> str:
        return f"<OperationLog {self.module.value}.{self.action} by {self.operator_name}>"
