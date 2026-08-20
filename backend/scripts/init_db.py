"""数据库初始化脚本

用法：
    python -m scripts.init_db              # 升级到最新版本
    python -m scripts.init_db --seed       # 升级 + 写入种子数据
    python -m scripts.init_db --drop       # 先删除所有表再重建（⚠️ 危险）
    python -m scripts.init_db --drop --seed
"""

import argparse
import asyncio
import sys
from pathlib import Path

# 把项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import command
from alembic.config import Config

from app.core.config import get_settings
from app.db.session import Base, engine
from app import models  # noqa: F401 确保模型被注册


def alembic_upgrade(revision: str = "head") -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, revision)


def alembic_downgrade(revision: str = "base") -> None:
    cfg = Config("alembic.ini")
    command.downgrade(cfg, revision)


async def drop_all() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def create_all() -> None:
    """不走 Alembic，直接用 metadata.create_all 快速建表（开发用）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main() -> None:
    parser = argparse.ArgumentParser(description="数据库初始化")
    parser.add_argument("--drop", action="store_true", help="先 drop_all 再建表（⚠️ 删除全部数据）")
    parser.add_argument("--seed", action="store_true", help="写入种子数据")
    parser.add_argument(
        "--use-metadata",
        action="store_true",
        help="跳过 Alembic，直接用 metadata.create_all 建表（开发快速迭代用）",
    )
    args = parser.parse_args()

    settings = get_settings()
    print(f"==> 数据库: {settings.DATABASE_URL.split('@')[-1]}")
    print(f"==> 环境: {settings.APP_ENV}")

    if args.drop:
        confirm = input("[WARNING]  将删除所有表，确认吗？(yes/no): ")
        if confirm.strip().lower() != "yes":
            print("已取消")
            return
        print("==> drop_all ...")
        await drop_all()
        print("==> drop_all 完成")

    if args.use_metadata:
        print("==> create_all (metadata) ...")
        await create_all()
        print("==> create_all 完成")
    else:
        print("==> alembic upgrade head ...")
        alembic_upgrade("head")
        print("==> alembic 升级完成")

    if args.seed:
        from scripts.seed_data import seed_all

        print("==> 写入种子数据 ...")
        await seed_all()
        print("==> 种子数据完成")

    print("✅ 初始化完成") if False else print("[OK] 初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
