"""安全与鉴权：JWT、密码哈希"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# bcrypt 密码哈希（passlib 自动处理 salt）
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与哈希是否匹配"""
    return pwd_context.verify(plain, hashed)


def create_access_token(
    subject: str | int,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """创建 JWT access token

    :param subject: 用户标识（通常用 user_id），写入 sub 字段
    :param extra_claims: 额外 payload（如 role / openid）
    :param expires_delta: 过期时长，默认从 settings 读取
    """
    to_encode: dict[str, Any] = {"sub": str(subject), "iat": datetime.now(timezone.utc)}
    if extra_claims:
        to_encode.update(extra_claims)
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码 JWT token，返回 payload；非法或过期返回 None"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
