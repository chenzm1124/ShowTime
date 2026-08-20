"""反作弊日志表"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Index, String, Text
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class FraudRiskLevel(str, Enum):
    LOW = "low"          # 低风险
    MEDIUM = "medium"    # 中风险
    HIGH = "high"        # 高风险
    BLOCKED = "blocked"  # 已拦截


class FraudAction(str, Enum):
    """风控动作"""

    ALLOW = "allow"                # 放行
    WARN = "warn"                  # 警告（不影响业务）
    CAPTCHA = "captcha"            # 要求验证码
    LIMIT = "limit"                # 限流
    BLOCK = "block"                # 拦截
    BAN = "ban"                    # 封号


class AntiFraudLog(Base, TimestampMixin):
    """反作弊事件日志

    记录所有可疑行为：设备指纹异常、短时间内多次试用、IP 聚集、广告作弊等。
    用于：
    1. 风控策略迭代（统计高频触发规则）
    2. 客服查询
    3. 司法取证
    """

    __tablename__ = "anti_fraud_logs"
    __table_args__ = (
        Index("ix_anti_fraud_logs_user_id", "user_id"),
        Index("ix_anti_fraud_logs_risk_level", "risk_level"),
        Index("ix_anti_fraud_logs_action", "action"),
        Index("ix_anti_fraud_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # 风险评分
    risk_level: Mapped[FraudRiskLevel] = mapped_column(
        SAEnum(FraudRiskLevel, name="fraud_risk_level"), nullable=False
    )
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0, comment="0-100")

    # 命中规则
    rule_code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="命中的规则编码：DEVICE_FINGERPRINT_DUP | IP_CLUSTER | ..."
    )
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="规则中文名")

    # 上下文
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scene: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="触发场景：trial_use | ad_unlock | vip_purchase | ..."
    )

    # 处置
    action: Mapped[FraudAction] = mapped_column(
        SAEnum(FraudAction, name="fraud_action", native_enum=False, length=32), nullable=False
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True, comment="详细信息 JSON")

    def __repr__(self) -> str:
        return f"<AntiFraudLog rule={self.rule_code} level={self.risk_level} action={self.action}>"
