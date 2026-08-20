"""认证业务服务

- 微信 code2session（真实模式调微信 API；Mock 模式生成假 openid）
- 用户查找/创建
- JWT 签发
"""

import hashlib
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.user import User

settings = get_settings()

WX_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


async def _code2session_mock(code: str) -> dict:
    """Mock 模式：根据 code 生成稳定的假 openid（同一 code 产生同一 openid）"""
    digest = hashlib.md5(code.encode()).hexdigest()[:16]
    return {
        "openid": f"mock_openid_{digest}",
        "session_key": f"mock_session_{digest}",
        "unionid": None,
    }


async def _code2session_real(code: str) -> dict:
    """真实模式：调用微信 code2session 接口"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            WX_CODE2SESSION_URL,
            params={
                "appid": settings.WECHAT_APPID,
                "secret": settings.WECHAT_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
        )
        data = resp.json()

    if "errcode" in data and data["errcode"] != 0:
        logger.error("微信 code2session 失败: {}", data)
        raise ValueError(f"微信登录失败: {data.get('errmsg', 'unknown error')}")

    return {
        "openid": data["openid"],
        "session_key": data.get("session_key", ""),
        "unionid": data.get("unionid"),
    }


async def code2session(code: str) -> dict:
    """根据 wx.login code 获取 openid + session_key"""
    if settings.ENABLE_MOCK_MODE or not settings.WECHAT_APPID:
        return await _code2session_mock(code)
    return await _code2session_real(code)


async def login_or_register(
    db: AsyncSession, code: str, device_info: dict | None = None
) -> tuple[User, bool]:
    """登录或注册

    :return: (user, is_new_user)
    """
    session_info = await code2session(code)
    openid = session_info["openid"]
    unionid = session_info.get("unionid")

    # 查找已有用户
    user = (
        await db.execute(select(User).where(User.openid == openid))
    ).scalar_one_or_none()

    if user is not None:
        # 更新登录信息
        user.last_login_at = datetime.now(timezone.utc)
        if device_info and device_info.get("model"):
            user.register_device_id = user.register_device_id or device_info["model"]
        await db.flush()
        return user, False

    # 创建新用户
    user = User(
        openid=openid,
        unionid=unionid,
        member_type="free",
        trial_remaining=1,
        ad_unlock_remaining_today=2,
        ad_unlock_watched_today=0,
        status="active",
        is_test=settings.ENABLE_MOCK_MODE,
        last_login_at=datetime.now(timezone.utc),
        register_device_id=device_info.get("model") if device_info else None,
    )
    db.add(user)
    await db.flush()
    logger.info("新用户注册: openid={}", openid)
    return user, True


def build_token(user: User) -> str:
    """为用户签发 JWT"""
    return create_access_token(
        subject=user.id,
        extra_claims={
            "openid": user.openid,
            "member_type": user.member_type,
        },
    )
