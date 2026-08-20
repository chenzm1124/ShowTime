"""用户表（含试用/广告/VIP 字段）"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Index, String
from app.models.types import BigInt
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class User(Base, TimestampMixin):
    """用户表

    核心字段：
    - openid / unionid：微信唯一标识
    - member_type：会员等级（free / vip1 / vip2 / vip3）
    - trial_remaining：账号终身免费试用剩余次数（默认 1）
    - trial_first_used_date：首次试用日期
    - ad_unlock_remaining_today：当日看广告解锁剩余次数（默认 2）
    - ad_unlock_watched_today：当日已观看次数
    - ad_unlock_date：当日日期（YYYY-MM-DD，跨天重置）
    - vip_daily_used：VIP 当日已用次数
    - vip_daily_date：VIP 计数日期
    - vip_expire_date：VIP 过期日期
    - status：账户状态（active / banned）
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_openid", "openid"),
        Index("ix_users_unionid", "unionid"),
        Index("ix_users_member_type", "member_type"),
        Index("ix_users_status", "status"),
        Index("ix_users_vip_expire_date", "vip_expire_date"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="微信 openid")
    unionid: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="微信 unionid")
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="昵称")
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="头像 URL")
    gender: Mapped[int | None] = mapped_column(nullable=True, default=0, comment="0未知 1男 2女")
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    city: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ---------- 会员 ----------
    member_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="free", comment="free | vip1 | vip2 | vip3"
    )
    vip_expire_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="VIP 过期日期")
    vip_daily_used: Mapped[int] = mapped_column(nullable=False, default=0, comment="VIP 当日已用次数")
    vip_daily_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="VIP 计数日期（跨天重置）")

    # ---------- 试用（账号终身 1 次）----------
    trial_remaining: Mapped[int] = mapped_column(nullable=False, default=1, comment="账号终身免费试用剩余次数")
    trial_first_used_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="首次试用日期")

    # ---------- 看广告解锁（每天 2 次）----------
    ad_unlock_remaining_today: Mapped[int] = mapped_column(
        nullable=False, default=2, comment="当日看广告解锁剩余次数"
    )
    ad_unlock_watched_today: Mapped[int] = mapped_column(
        nullable=False, default=0, comment="当日已观看次数"
    )
    ad_unlock_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="广告计数日期")

    # ---------- 设备/反作弊 ----------
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True, comment="最近登录时间")
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    register_device_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="注册设备指纹")

    # ---------- 状态 ----------
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", comment="active | banned"
    )
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否测试账号")

    def __repr__(self) -> str:
        return f"<User id={self.id} openid={self.openid} member={self.member_type}>"
