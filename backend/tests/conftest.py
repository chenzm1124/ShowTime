"""pytest 公共 fixtures

策略：
- 每个测试函数使用独立的临时 SQLite 文件，互不干扰
- 用同步引擎建表（简单可靠），用异步引擎查询（与生产一致）
- Override FastAPI 的 get_db 依赖注入，指向测试数据库
- 提供 auth_token / auth_headers fixture，自动登录获取 JWT
"""

import os
import tempfile
import warnings

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 抑制 httpx + starlette TestClient 的 deprecation warning
warnings.filterwarnings("ignore")

# 确保所有模型注册到 Base.metadata（必须在 import app.main 之前）
import app.models  # noqa: F401

from app.db.session import Base, get_db
from app.main import app


@pytest.fixture(scope="function")
def client():
    """每个测试函数一个干净的 TestClient + 临时 SQLite 数据库"""
    # 创建临时 SQLite 文件
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_")
    os.close(fd)

    # 同步引擎建表（可靠，不依赖 async 事件循环）
    sync_engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    # 异步引擎供 app 使用
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    TestSessionLocal = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    async def get_test_db():
        async with TestSessionLocal() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = get_test_db

    with TestClient(app) as c:
        yield c

    # 清理
    app.dependency_overrides.clear()
    import asyncio

    asyncio.run(async_engine.dispose())
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(scope="function")
def auth_token(client):
    """登录获取 JWT token（Mock 模式自动创建用户）"""
    r = client.post(
        "/api/v1/auth/wx-login",
        json={"code": "pytest_login_code", "device_info": {"model": "test-device"}},
    )
    assert r.status_code == 200, f"登录失败: {r.text}"
    body = r.json()
    assert body["code"] == 0, f"登录响应格式错误: {body}"
    return body["data"]["token"]


@pytest.fixture(scope="function")
def auth_headers(auth_token):
    """带 Bearer token 的请求头"""
    return {"Authorization": f"Bearer {auth_token}"}
