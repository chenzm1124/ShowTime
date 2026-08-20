"""FastAPI 依赖注入

WBS 1.8 阶段会拆分成完整 JWT 中间件；目前提供"软认证"：
- 有 Authorization Bearer token → 解析出 user_id
- 没有 / 解析失败 → mock 模式 fallback 到 test_openid_free_001，否则抛 401
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import DbSession
from app.models.user import User

settings = get_settings()


async def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """获取当前登录用户

    1) 解析 Authorization: Bearer <jwt>，取 sub 作为 user_id
    2) 解析失败：mock 模式 fallback 到第一个测试用户；否则 401
    """
    user_id: int | None = None

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        payload = decode_access_token(token)
        if payload and payload.get("sub"):
            try:
                user_id = int(payload["sub"])
            except (ValueError, TypeError):
                user_id = None

    if user_id is not None:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user:
            return user

    # 未拿到有效 token
    if settings.ENABLE_MOCK_MODE:
        # P0-11 修复：只 fallback 到 is_test=True 的固定测试用户
        # - 旧逻辑：拿不到 is_test 用户时再兜底到任意一个 user
        #   → mock 模式串到生产用户 = 跨用户数据访问
        # - 新逻辑：找不到测试用户直接 503，明确告诉开发者「请跑 seed」，
        #   不再"无脑"把生产用户当 mock 兜底。
        user = (
            await db.execute(
                select(User)
                .where(User.is_test == True)  # noqa: E712
                .order_by(User.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if user:
            return user
        # 没有 is_test=True 的测试用户：拒绝兜底到任意用户
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="mock 模式未配置测试用户（is_test=True），请先运行 seed 脚本",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或 token 无效",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentUser = Annotated[User, Depends(get_current_user)]
