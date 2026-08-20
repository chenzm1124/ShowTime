"""ORM 模型包

所有模型必须在此导入，确保 Base.metadata 收集到全部表，
Alembic 自动迁移才能正确生成。
"""

from app.db.session import Base

# 必须按依赖顺序导入（无外键依赖的先导入）
from app.models.user import User  # noqa: F401
from app.models.vip_plan import VipPlan  # noqa: F401
from app.models.quota_pack import QuotaPack  # noqa: F401
from app.models.user_pack import UserPack, UserPackStatus  # noqa: F401
from app.models.task import Task, TaskStatus  # noqa: F401
from app.models.photo import Photo  # noqa: F401
from app.models.order import Order, OrderStatus, PayChannel, PayPeriod  # noqa: F401
from app.models.pack_order import PackOrder, PackOrderStatus  # noqa: F401
from app.models.ad_unlock import AdUnlock, AdProvider, AdStatus  # noqa: F401
from app.models.quota_log import QuotaLog, QuotaChangeType  # noqa: F401
from app.models.share_record import ShareRecord  # noqa: F401
from app.models.anti_fraud_log import AntiFraudLog, FraudAction, FraudRiskLevel  # noqa: F401
from app.models.operation_log import OperationLog, OperationModule  # noqa: F401

__all__ = [
    "Base",
    "User",
    "VipPlan",
    "QuotaPack",
    "UserPack",
    "UserPackStatus",
    "Task",
    "TaskStatus",
    "Photo",
    "Order",
    "OrderStatus",
    "PayChannel",
    "PayPeriod",
    "PackOrder",
    "PackOrderStatus",
    "AdUnlock",
    "AdProvider",
    "AdStatus",
    "QuotaLog",
    "QuotaChangeType",
    "ShareRecord",
    "AntiFraudLog",
    "FraudAction",
    "FraudRiskLevel",
    "OperationLog",
    "OperationModule",
]
