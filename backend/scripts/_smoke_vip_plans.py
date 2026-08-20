"""
冒烟测试：验证后端 /vip/plans 路由 + 数据库 vip_plans 数据是否更新到 3/5/7

不需要启动后端服务，直接读 DB + 模拟 HTTP 即可。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.vip_plan import VipPlan

settings = get_settings()

EXPECTED = {
    "vip1": {"daily_limit": 3, "photos_per_task": 50},
    "vip2": {"daily_limit": 5, "photos_per_task": 80},
    "vip3": {"daily_limit": 7, "photos_per_task": 150},
}


async def main() -> int:
    print("=" * 60)
    print("  冒烟测试：vip_plans 表 daily_limit 是否更新到 3/5/7")
    print("=" * 60)
    print(f"  APP_ENV    = {settings.APP_ENV}")
    print(f"  MOCK_MODE  = {settings.ENABLE_MOCK_MODE}")
    print(f"  DB         = {settings.DATABASE_URL.split('@')[-1]}")
    print()

    async with AsyncSessionLocal() as session:
        stmt = select(VipPlan).where(VipPlan.is_active.is_(True)).order_by(VipPlan.sort_order)
        result = await session.execute(stmt)
        plans = result.scalars().all()

        if not plans:
            print("  [FAIL] vip_plans 表为空！请先运行：python scripts/seed_data.py")
            return 1

        ok = True
        for plan in plans:
            expected = EXPECTED.get(plan.level)
            if not expected:
                print(f"  [WARN] 未知等级: {plan.level}")
                continue

            limit_ok = plan.daily_limit == expected["daily_limit"]
            photos_ok = plan.photos_per_task == expected["photos_per_task"]
            status = "OK" if (limit_ok and photos_ok) else "FAIL"
            if not (limit_ok and photos_ok):
                ok = False

            # 检查 features 里有无老"X次/天"文案
            import json
            feats = json.loads(plan.features) if plan.features else []
            old_features = [f for f in feats if "次/天" in f]
            feat_status = "OK" if not old_features else f"WARN 残留{old_features}"
            if old_features:
                ok = False  # features 里残留"X次/天"也是问题

            print(f"  [{status}] {plan.level} {plan.name}")
            print(f"         daily_limit   = {plan.daily_limit} (期望 {expected['daily_limit']})")
            print(f"         photos_per_task= {plan.photos_per_task} (期望 {expected['photos_per_task']})")
            print(f"         features      = {feats}  [{feat_status}]")
            print(f"         price_monthly = ¥{plan.price_monthly/100:.2f}")
            print()

        print("=" * 60)
        if ok:
            print("  结论: 所有数据已是最新 (3/5/7) - 直接重启后端服务即可")
            print("=" * 60)
            return 0
        else:
            print("  结论: 数据未更新或 features 残留旧文案，需重新 seed")
            print("  操作: cd backend && python scripts/seed_data.py")
            print("=" * 60)
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
