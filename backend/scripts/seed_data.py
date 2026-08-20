"""种子数据：VIP 套餐 + 测试用户"""

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.vip_plan import VipPlan
from app.models.quota_pack import QuotaPack

settings = get_settings()


# ---------- VIP 套餐种子数据 ----------
# 注意：features 里的"X次/天"会被前端 tp-vip-card 组件按 daily_limit 实时拼写并过滤，
# 写在这里仅作 fallback。前端展示以 daily_limit 为准。
VIP_PLAN_SEEDS = [
    {
        "level": "vip1",
        "name": "基础会员",
        "description": "入门级 VIP，适合轻度旅行拍照用户",
        "price_monthly": 1990,           # 19.9 元
        "price_yearly": 19900,           # 199 元
        "original_price_monthly": 2990,  # 29.9 元
        "original_price_yearly": 29900,
        "photos_per_task": 50,
        "daily_limit": 3,
        "features": '["50张/次", "去水印", "在线客服"]',
        "highlight": False,
        "sort_order": 1,
    },
    {
        "level": "vip2",
        "name": "高级会员",
        "description": "进阶版 VIP，单次处理更多，客服优先",
        "price_monthly": 3990,           # 39.9 元
        "price_yearly": 39900,           # 399 元
        "original_price_monthly": 5990,
        "original_price_yearly": 59900,
        "photos_per_task": 80,
        "daily_limit": 5,
        "features": '["80张/次", "去水印", "优先客服", "加速50%"]',
        "badge": "推荐",
        "highlight": True,
        "sort_order": 2,
    },
    {
        "level": "vip3",
        "name": "旗舰会员",
        "description": "顶级 VIP，畅享所有权益",
        "price_monthly": 6990,           # 69.9 元
        "price_yearly": 69900,           # 699 元
        "original_price_monthly": 9990,
        "original_price_yearly": 99900,
        "photos_per_task": 150,
        "daily_limit": 7,
        "features": '["150张/次", "去水印", "专属客服", "加速100%", "永久历史"]',
        "highlight": False,
        "sort_order": 3,
    },
]


# ---------- 次数套餐包种子数据 ----------
QUOTA_PACK_SEEDS = [
    {
        "code": "daily",
        "name": "日常包",
        "description": "针对日常出游，1 次批量处理",
        "price": 990,                # 9.9 元
        "original_price": 1490,      # 14.9 元（划线价）
        "task_quota": 1,             # 1 次处理
        "photos_per_task": 30,       # 每次最多 30 张
        "max_refine_per_task": 6,    # 单次最多精修 6 张
        "valid_days": 30,            # 30 天有效
        "features": '["1次批量处理", "30张/次", "6张精修", "30天有效"]',
        "sort_order": 1,
    },
    {
        "code": "enjoy",
        "name": "尽兴包",
        "description": "针对周边短途游，3 次批量处理",
        "price": 1990,               # 19.9 元
        "original_price": 2990,      # 29.9 元
        "task_quota": 3,
        "photos_per_task": 50,
        "max_refine_per_task": 9,
        "valid_days": 60,
        "features": '["3次批量处理", "50张/次", "9张精修", "60天有效"]',
        "badge": "推荐",
        "highlight": True,
        "sort_order": 2,
    },
    {
        "code": "unlimited",
        "name": "畅游包",
        "description": "针对长途游，7 次批量处理",
        "price": 3990,               # 39.9 元
        "original_price": 5990,      # 59.9 元
        "task_quota": 7,
        "photos_per_task": 100,
        "max_refine_per_task": 18,
        "valid_days": 90,
        "features": '["7次批量处理", "100张/次", "18张精修", "90天有效"]',
        "badge": "热销",
        "sort_order": 3,
    },
]


# ---------- 测试用户种子数据 ----------
TEST_USER_SEEDS = [
    {
        "openid": "test_openid_free_001",
        "unionid": "test_unionid_001",
        "nickname": "测试免费用户",
        "avatar_url": "https://api.dicebear.com/9.x/avataaars/svg?seed=free",
        "member_type": "free",
        "trial_remaining": 1,
        "trial_first_used_date": None,
        "ad_unlock_remaining_today": 2,
        "ad_unlock_watched_today": 0,
        "ad_unlock_date": date.today(),
        "vip_daily_used": 0,
        "vip_daily_date": date.today(),
        "vip_expire_date": None,
        "is_test": True,
    },
    {
        "openid": "test_openid_vip1_001",
        "unionid": "test_unionid_002",
        "nickname": "测试基础会员",
        "avatar_url": "https://api.dicebear.com/9.x/avataaars/svg?seed=vip1",
        "member_type": "vip1",
        "trial_remaining": 0,
        "trial_first_used_date": date.today() - timedelta(days=15),
        "ad_unlock_remaining_today": 0,
        "ad_unlock_watched_today": 2,
        "ad_unlock_date": date.today(),
        "vip_daily_used": 2,
        "vip_daily_date": date.today(),
        "vip_expire_date": date.today() + timedelta(days=15),
        "is_test": True,
    },
    {
        "openid": "test_openid_vip3_001",
        "unionid": "test_unionid_003",
        "nickname": "测试旗舰会员",
        "avatar_url": "https://api.dicebear.com/9.x/avataaars/svg?seed=vip3",
        "member_type": "vip3",
        "trial_remaining": 0,
        "trial_first_used_date": date.today() - timedelta(days=60),
        "ad_unlock_remaining_today": 0,
        "ad_unlock_watched_today": 2,
        "ad_unlock_date": date.today(),
        "vip_daily_used": 5,
        "vip_daily_date": date.today(),
        "vip_expire_date": date.today() + timedelta(days=305),
        "is_test": True,
    },
]


async def seed_vip_plans(session) -> int:
    """写入 VIP 套餐，幂等：已存在则更新价格/权益"""
    print("  -- VIP 套餐 --")
    count = 0
    for data in VIP_PLAN_SEEDS:
        stmt = select(VipPlan).where(VipPlan.level == data["level"])
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            # 更新价格/权益（保持 id）
            for k, v in data.items():
                setattr(existing, k, v)
            print(f"     更新: {data['level']} - {data['name']} ({data['price_monthly']/100:.2f}元/月)")
        else:
            session.add(VipPlan(**data))
            print(f"     新增: {data['level']} - {data['name']} ({data['price_monthly']/100:.2f}元/月)")
            count += 1
    return count


async def seed_quota_packs(session) -> int:
    """写入次数套餐包，幂等：已存在则更新价格/权益"""
    print("  -- 次数套餐包 --")
    count = 0
    for data in QUOTA_PACK_SEEDS:
        stmt = select(QuotaPack).where(QuotaPack.code == data["code"])
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            print(f"     更新: {data['code']} - {data['name']} ({data['price']/100:.2f}元, {data['task_quota']}次)")
        else:
            session.add(QuotaPack(**data))
            print(f"     新增: {data['code']} - {data['name']} ({data['price']/100:.2f}元, {data['task_quota']}次)")
            count += 1
    return count


async def seed_test_users(session) -> int:
    """写入测试用户（仅在 ENABLE_MOCK_MODE=true 时）"""
    if not settings.ENABLE_MOCK_MODE:
        print("  -- 跳过测试用户（ENABLE_MOCK_MODE=false）--")
        return 0
    print("  -- 测试用户 --")
    count = 0
    for data in TEST_USER_SEEDS:
        stmt = select(User).where(User.openid == data["openid"])
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            print(f"     更新: {data['openid']} ({data['member_type']})")
        else:
            session.add(User(**data))
            print(f"     新增: {data['openid']} ({data['member_type']})")
            count += 1
    return count


async def seed_all() -> None:
    """写入所有种子数据"""
    async with AsyncSessionLocal() as session:
        try:
            vip_count = await seed_vip_plans(session)
            pack_count = await seed_quota_packs(session)
            user_count = await seed_test_users(session)
            await session.commit()
            print(f"  -> 新增 {vip_count} 个 VIP 套餐，{pack_count} 个次数包，{user_count} 个测试用户")
        except Exception as e:
            await session.rollback()
            print(f"  [ERROR] 种子数据失败: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(seed_all())
