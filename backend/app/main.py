"""途吖 · 旅行照片AI处理工具 — FastAPI 应用入口"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

# 强制 stdout/stderr 使用 UTF-8：Windows 默认 GBK 会让 loguru 静默吞掉含 emoji/中文的日志行
# （典型表现：函数继续执行下一行，但上一行 [MEITU-DEBUG] 莫名消失）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.websockets import WebSocketDisconnect

from app.api.v1 import api_router
from app import get_runtime_version
from app.core.config import get_settings
from app.core.response import UnifiedResponseMiddleware

settings = get_settings()

# loguru 接管 logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level=settings.LOG_LEVEL,
)


class InterceptHandler(logging.Handler):
    """把 stdlib logging 转发到 loguru"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 不用 emoji：Windows PowerShell 默认 GBK，loguru 会炸
    logger.info(f"[BOOT] {settings.APP_NAME} 启动 (env={settings.APP_ENV}, port={settings.APP_PORT}, version={get_runtime_version()})")

    # 配置 COS 生命周期规则（自动清理过期文件）
    if not settings.ENABLE_MOCK_MODE:
        try:
            from app.services.photo_service import setup_cos_lifecycle
            setup_cos_lifecycle()
        except Exception as e:
            logger.warning(f"[BOOT] COS 生命周期配置失败（不影响运行）: {e}")

    # 美图精修回调地址校验：配置了美图密钥但回调地址仍是默认占位时，回调无法到达
    if settings.MEITU_API_KEY and settings.MEITU_MEDIA_CODE:
        if not settings.CALLBACK_BASE_URL or settings.CALLBACK_BASE_URL in (
            "https://your-domain.com",
            "",
        ):
            logger.warning(
                "[BOOT] 已配置美图密钥，但 CALLBACK_BASE_URL 仍是默认占位地址。"
                "请用内网穿透（花生壳/ngrok）设置一个可被美图服务器访问的公网回调地址，"
                "否则精修回调无法到达后端，结果将一直显示原图。"
            )

    # 恢复因 reload/重启而中断的后台任务（asyncio.create_task 在进程重启后会丢失）
    try:
        from app.services.task_service import _recover_interrupted_tasks
        await _recover_interrupted_tasks()
    except Exception as e:
        logger.warning(f"[BOOT] 恢复中断任务失败（不影响运行）: {e}")

    # 启动精修图 7 天清理调度器（每天北京 24:00 跑一次，启动时先跑一次兜底）
    cleanup_task = None
    if not settings.ENABLE_MOCK_MODE:
        try:
            from app.services.cleanup_scheduler import run_loop
            cleanup_task = asyncio.create_task(run_loop(), name="retouch-cleanup-scheduler")
            logger.info("[BOOT] 精修图 7 天清理调度器已启动")
        except Exception as e:
            logger.warning(f"[BOOT] 清理调度器启动失败（不影响运行）: {e}")

    yield

    # 关闭时取消调度器
    if cleanup_task and not cleanup_task.done():
        cleanup_task.cancel()
        try:
            await cleanup_task
        except (asyncio.CancelledError, Exception):
            pass
    logger.info(f"[SHUTDOWN] {settings.APP_NAME} 关闭")


app = FastAPI(
    title=settings.APP_NAME,
    description="途吖后端 API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# 统一响应包装：将 2xx JSON 响应自动包装为 { code: 0, message, data }
app.add_middleware(UnifiedResponseMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理：开发详细，生产简化

    P0 修复：WebSocket 客户端断开（前端切页面/断网/任务结束）会抛
    WebSocketDisconnect，如果走到这里会被误判成「未处理异常」并返回 500，
    同时前端 console 出现 CloseSocket 报错。WebSocket 是正常断连，跳过即可。
    """
    if isinstance(exc, WebSocketDisconnect):
        # 正常断连，记录 debug 即可
        logger.debug(f"[ws] 客户端断开: code={exc.code} reason={exc.reason}")
        # 这里返回的响应 WebSocket 不会使用，仅避免 FastAPI 内部栈溢出
        return JSONResponse(status_code=200, content={"code": 0, "message": "ws closed", "data": None})
    detail = f"{type(exc).__name__}: {exc}" if settings.APP_DEBUG else "服务器内部错误"
    logger.exception("未处理异常: %s - %s", type(exc).__name__, exc)
    return JSONResponse(
        status_code=500,
        content={"code": -1, "message": detail, "data": None},
    )


app.include_router(api_router, prefix="/api/v1")

# WebSocket 实时精修进度推送（独立于 REST 前缀，路径 /api/v1/ws/...）
from app.api.ws import router as ws_router  # noqa: E402

app.include_router(ws_router, prefix="/api/v1")
