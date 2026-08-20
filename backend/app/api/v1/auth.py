"""认证路由

- POST /api/v1/auth/wx-login  微信登录（code 换 token）
- POST /api/v1/auth/logout    退出登录
"""

from fastapi import APIRouter
from loguru import logger

from app.db.session import DbSession
from app.schemas.auth import LoginResultOut, WxLoginReq
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/wx-login",
    response_model=LoginResultOut,
    summary="微信登录",
)
async def wx_login(req: WxLoginReq, db: DbSession) -> LoginResultOut:
    """用 wx.login 的 code 换取 JWT token"""
    device_info = req.device_info.model_dump() if req.device_info else None
    user, is_new = await auth_service.login_or_register(db, req.code, device_info)
    await db.commit()

    token = auth_service.build_token(user)
    logger.info("用户登录成功: id={} openid={} new={}", user.id, user.openid, is_new)

    return LoginResultOut(
        token=token,
        user_id=str(user.id),
        openid=user.openid,
        is_new_user=is_new,
        member_type=user.member_type,
        member_expire_date=user.vip_expire_date.isoformat() if user.vip_expire_date else None,
        trial_remaining=user.trial_remaining,
        trial_expire_date=None,
    )


@router.post(
    "/logout",
    summary="退出登录",
)
async def logout() -> dict:
    """退出登录（客户端清除 token 即可，服务端无状态）"""
    return {"ok": True}
