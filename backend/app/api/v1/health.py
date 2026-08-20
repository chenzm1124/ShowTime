"""健康检查端点"""

from fastapi import APIRouter
from sqlalchemy import text

from app import get_runtime_version
from app.core.config import get_settings
from app.db.session import engine

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """基础健康检查（含运行期 git SHA，用于识别在跑进程加载的是哪份代码）"""
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "env": settings.APP_ENV,
        "version": get_runtime_version(),
    }


@router.get("/health/db")
async def health_db() -> dict:
    """数据库连接健康检查"""
    settings = get_settings()
    try:
        async with engine.connect() as conn:
            # PostgreSQL 才有 version()；SQLite 走 SELECT 1
            try:
                result = await conn.execute(text("SELECT version()"))
                version = result.scalar() or "unknown"
            except Exception:
                result = await conn.execute(text("SELECT 1"))
                version = "sqlite"
        return {
            "status": "ok",
            "database": "connected",
            "version": version,
            "env": settings.APP_ENV,
        }
    except Exception as e:
        return {
            "status": "degraded",
            "database": "disconnected",
            "error": f"{type(e).__name__}: {e}",
            "env": settings.APP_ENV,
        }
