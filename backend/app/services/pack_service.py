"""次数包业务服务

封装：
- 列出当前可购买的次数包
- 创建订单（mock 模式直接到账；真实模式调微信统一下单）
- 支付回调处理（写入 user_packs）
- 用户额度聚合（VIP / Pack / 试用 / 广告）
- 包原子扣减
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.pack_order import PackOrder, PackOrderStatus, PayChannel
from app.models.quota_log import QuotaChangeType, QuotaLog
from app.models.quota_pack import QuotaPack
from app.models.user import User
from app.models.user_pack import UserPack, UserPackStatus

settings = get_settings()
logger = logging.getLogger(__name__)


# ==================== 次数包定义 ====================

async def list_active_packs(db: AsyncSession) -> list[QuotaPack]:
    """列出所有上架的次数包（按 sort_order 升序）"""
    stmt = (
        select(QuotaPack)
        .where(QuotaPack.is_active == True)  # noqa: E712
        .order_by(QuotaPack.sort_order.asc(), QuotaPack.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_pack_by_code(db: AsyncSession, code: str) -> QuotaPack | None:
    return (await db.execute(select(QuotaPack).where(QuotaPack.code == code))).scalar_one_or_none()


# ==================== 订单号生成 ====================

def generate_order_no(prefix: str = "PK") -> str:
    """生成订单号：PK + yyyymmddHHMMss + 6 位随机"""
    import random
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = f"{random.randint(0, 999999):06d}"
    return f"{prefix}{ts}{suffix}"


# ==================== 用户持有的包 ====================

async def list_user_packs(
    db: AsyncSession,
    user_id: int,
    include_status: list[UserPackStatus] | None = None,
) -> list[UserPack]:
    """列出用户持有的所有包（默认仅 ACTIVE）"""
    stmt = select(UserPack).where(UserPack.user_id == user_id)
    if include_status:
        stmt = stmt.where(UserPack.status.in_(include_status))
    else:
        stmt = stmt.where(UserPack.status == UserPackStatus.ACTIVE)
    stmt = stmt.order_by(UserPack.purchased_at.asc(), UserPack.id.asc())
    return list((await db.execute(stmt)).scalars().all())


async def activate_user_pack_from_order(db: AsyncSession, order: PackOrder) -> UserPack:
    """订单支付成功后，写入/激活 user_pack（幂等）"""
    # 幂等保护：若该订单已激活过，返回旧记录
    existing = (
        await db.execute(
            select(UserPack).where(UserPack.related_order_no == order.order_no)
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    now = datetime.now(timezone.utc)
    user_pack = UserPack(
        user_id=order.user_id,
        pack_id=order.pack_id,
        pack_code=order.pack_code,
        pack_name=order.pack_name,
        initial_task_quota=order.task_quota,
        photos_per_task=order.photos_per_task,
        max_refine_per_task=order.max_refine_per_task,
        remaining_tasks=order.task_quota,
        status=UserPackStatus.ACTIVE,
        purchased_at=order.paid_at or now,
        activated_at=now,
        expire_at=(order.paid_at or now) + timedelta(days=order.valid_days),
        related_order_no=order.order_no,
    )
    db.add(user_pack)

    # 写 quota_log
    db.add(
        QuotaLog(
            user_id=order.user_id,
            change_type=QuotaChangeType.PACK_PURCHASE,
            related_order_no=order.order_no,
            change_detail=_pack_purchase_log_detail(order),
            remark=f"购买次数包 {order.pack_name}",
        )
    )

    await db.flush()
    return user_pack


def _pack_purchase_log_detail(order: PackOrder) -> str:
    import json
    return json.dumps(
        {
            "pack_code": order.pack_code,
            "pack_name": order.pack_name,
            "task_quota": order.task_quota,
            "photos_per_task": order.photos_per_task,
            "amount": order.amount,
            "valid_days": order.valid_days,
        },
        ensure_ascii=False,
    )


# ==================== 购买 ====================

async def create_purchase_order(
    db: AsyncSession,
    user: User,
    pack: QuotaPack,
    pay_channel: Literal["wechat", "alipay"] = "wechat",
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[PackOrder, UserPack | None]:
    """创建订单。

    Mock 模式下（ENABLE_MOCK_MODE=true）：
        直接标记为已支付，激活 user_pack，同步到账。
    真实模式：
        创建 PENDING 订单，返回给调用方去调微信统一下单。
    """
    order = PackOrder(
        order_no=generate_order_no(),
        user_id=user.id,
        pack_id=pack.id,
        pack_code=pack.code,
        pack_name=pack.name,
        task_quota=pack.task_quota,
        photos_per_task=pack.photos_per_task,
        max_refine_per_task=pack.max_refine_per_task,
        valid_days=pack.valid_days,
        amount=pack.price,
        original_amount=pack.original_price or pack.price,
        pay_channel=PayChannel(pay_channel),
        client_ip=client_ip,
        user_agent=user_agent,
    )
    db.add(order)
    await db.flush()  # 拿到 order.id

    if settings.ENABLE_MOCK_MODE:
        order.status = PackOrderStatus.PAID
        order.paid_at = datetime.now(timezone.utc)
        order.transaction_id = f"MOCK_{order.order_no}"
        user_pack = await activate_user_pack_from_order(db, order)
        await db.commit()
        await db.refresh(order)
        await db.refresh(user_pack)
        return order, user_pack

    await db.commit()
    await db.refresh(order)
    return order, None


# ==================== 包扣减（原子）====================

async def consume_user_pack(
    db: AsyncSession,
    user: User,
    user_pack_id: int,
) -> UserPack:
    """原子扣减一个 user_pack 的剩余次数

    校验：归属、未过期、状态 ACTIVE、剩余次数 > 0
    """
    from fastapi import HTTPException, status as http_status

    stmt = select(UserPack).where(
        and_(
            UserPack.id == user_pack_id,
            UserPack.user_id == user.id,
        )
    ).with_for_update()  # 行锁，防止并发扣成负数
    user_pack = (await db.execute(stmt)).scalar_one_or_none()

    if not user_pack:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="次数包不存在或不属于当前用户")
    if user_pack.status != UserPackStatus.ACTIVE:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="次数包已不可用")
    # 统一 DB 取出的 expire_at 时区（SQLite 不存 tz，可能 naive）
    expire_at = user_pack.expire_at
    if expire_at is not None and expire_at.tzinfo is None:
        expire_at = expire_at.replace(tzinfo=timezone.utc)
    if expire_at is not None and expire_at <= datetime.now(timezone.utc):
        user_pack.status = UserPackStatus.EXPIRED
        user_pack.remaining_tasks = 0
        await db.commit()
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="次数包已过期")
    if user_pack.remaining_tasks <= 0:
        user_pack.status = UserPackStatus.EXHAUSTED
        await db.commit()
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="次数包已用完")

    user_pack.remaining_tasks -= 1
    user_pack.consumed_at = datetime.now(timezone.utc)
    if user_pack.remaining_tasks == 0:
        user_pack.status = UserPackStatus.EXHAUSTED

    db.add(
        QuotaLog(
            user_id=user.id,
            change_type=QuotaChangeType.PACK_CONSUME,
            related_order_no=user_pack.related_order_no,
            change_detail=_pack_consume_log_detail(user_pack),
            remark=f"消耗次数包 {user_pack.pack_name}",
        )
    )
    await db.commit()
    await db.refresh(user_pack)
    return user_pack


def _pack_consume_log_detail(user_pack: UserPack) -> str:
    import json
    return json.dumps(
        {
            "pack_code": user_pack.pack_code,
            "remaining_tasks": user_pack.remaining_tasks,
            "expire_at": user_pack.expire_at.isoformat(),
        },
        ensure_ascii=False,
    )


# ==================== 额度聚合 ====================

def _apply_daily_reset(user: User) -> None:
    """把 user 表内按日计数的字段拨到今天（跨天重置）

    防御性钳制：任何异常写入（历史脏数据 / 重复回滚）都会在读取配额时
    被自动纠正到合规范围，避免「900多次免费次数」类问题复发。
    """
    today = date.today()
    if user.ad_unlock_date != today:
        user.ad_unlock_date = today
        user.ad_unlock_remaining_today = AD_UNLOCK_DAILY_LIMIT
        user.ad_unlock_watched_today = 0
    else:
        # 同日内也钳制，防脏数据（同日不会重置，但可能有历史异常值）
        if user.ad_unlock_remaining_today > AD_UNLOCK_DAILY_LIMIT:
            user.ad_unlock_remaining_today = AD_UNLOCK_DAILY_LIMIT
    if user.vip_daily_date != today:
        user.vip_daily_date = today
        user.vip_daily_used = 0
    # 终身试用次数钳制到总配额上限
    if user.trial_remaining > TRIAL_TOTAL_QUOTA:
        user.trial_remaining = TRIAL_TOTAL_QUOTA


async def get_user_quota_snapshot(
    db: AsyncSession,
    user: User,
) -> dict:
    """聚合 4 个维度的额度快照 + 用户持有的所有包"""
    _apply_daily_reset(user)
    user_packs = await list_user_packs(
        db,
        user.id,
        include_status=[UserPackStatus.ACTIVE, UserPackStatus.EXHAUSTED, UserPackStatus.EXPIRED],
    )

    # 计算 current_quota 块
    source, photos = _resolve_current_quota(user, user_packs)
    source_label = {
        "vip": f"VIP · {photos}张/次",
        "pack": f"次数包 · {photos}张/次",
        "trial": "免费试用 · 20张/次",
        "ad": "广告解锁 · 20张/次",
        "none": "无可用额度",
    }.get(source, f"{photos}张/次")

    return {
        "member_type": user.member_type,
        "trial_remaining": user.trial_remaining,
        "trial_first_used_date": user.trial_first_used_date,
        "ad_unlock_remaining_today": user.ad_unlock_remaining_today,
        "ad_unlock_watched_today": user.ad_unlock_watched_today,
        "ad_unlock_date": user.ad_unlock_date or date.today(),
        "vip_expire_date": user.vip_expire_date,
        "vip_daily_used": user.vip_daily_used,
        "vip_daily_date": user.vip_daily_date or date.today(),
        "current_quota": {
            "photos_per_task": photos,
            "photos_per_task_label": source_label,
            "source": source,
        },
        "monthly_used": 0,  # 暂未实现
        "user_packs": [_user_pack_to_brief(p) for p in user_packs],
    }


def _resolve_current_quota(user: User, user_packs: list[UserPack]) -> tuple[str, int]:
    """根据优先级解析当前应展示的额度

    优先级：VIP > 有效 Pack > 试用 > 广告 > none
    """
    if user.member_type in ("vip1", "vip2", "vip3"):
        photos = {"vip1": 50, "vip2": 80, "vip3": 150}[user.member_type]
        return "vip", photos

    # 找有效包（status=active + 未过期 + 剩余 > 0）
    now = datetime.now(timezone.utc)
    active = []
    for p in user_packs:
        if p.status != UserPackStatus.ACTIVE:
            continue
        if p.remaining_tasks <= 0:
            continue
        # SQLite 不存 tz，DB 取出的 expire_at 可能 naive → 一律转 UTC aware
        expire_at = p.expire_at
        if expire_at is not None and expire_at.tzinfo is None:
            expire_at = expire_at.replace(tzinfo=timezone.utc)
        if expire_at is not None and expire_at > now:
            active.append(p)
    if active:
        return "pack", max(p.photos_per_task for p in active)

    if user.trial_remaining > 0:
        return "trial", 20
    if user.ad_unlock_remaining_today > 0:
        return "ad", 20

    return "none", 20


def _user_pack_to_brief(user_pack: UserPack) -> dict:
    # 修复：DB 读出的 expire_at 可能 naive（SQLite 不存 tz），统一按 UTC 处理
    now = datetime.now(timezone.utc)
    expire_at = user_pack.expire_at
    if expire_at is not None and expire_at.tzinfo is None:
        expire_at = expire_at.replace(tzinfo=timezone.utc)
    in_seconds = int((expire_at - now).total_seconds()) if expire_at else 0
    return {
        "user_pack_id": user_pack.id,
        "pack_code": user_pack.pack_code,
        "pack_name": user_pack.pack_name,
        "remaining_tasks": user_pack.remaining_tasks,
        "total_tasks": user_pack.initial_task_quota,
        "photos_per_task": user_pack.photos_per_task,
        "max_refine_per_task": user_pack.max_refine_per_task,
        "purchased_at": user_pack.purchased_at,
        "expire_at": expire_at or now,
        "expire_in_seconds": in_seconds,
    }


# ==================== 广告解锁 ====================

AD_UNLOCK_DAILY_LIMIT = 2

# 终身免费试用总配额（一次性，注册时授予）
# release_quota 回滚时不能超过此值，防止任务失败回滚路径反复 +1 导致 trial_remaining 无限累加
TRIAL_TOTAL_QUOTA = 1


async def ad_unlock(
    db: AsyncSession,
    user: User,
    ad_type: str = "rewarded_video",
    ad_platform: str = "wechat",
    watch_duration_seconds: int = 0,
    callback_data: dict | None = None,
) -> dict:
    """广告解锁：观看广告后增加 1 次处理额度

    - 每日最多观看 2 次广告
    - 每次观看 ad_unlock_remaining_today += 1
    """
    import json
    from fastapi import HTTPException, status as http_status
    from app.models.ad_unlock import AdUnlock, AdProvider, AdStatus

    _apply_daily_reset(user)

    if user.ad_unlock_watched_today >= AD_UNLOCK_DAILY_LIMIT:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"今日看广告次数已达上限（{AD_UNLOCK_DAILY_LIMIT}次）",
        )

    # 增加额度
    user.ad_unlock_remaining_today += 1
    user.ad_unlock_watched_today += 1

    # 匹配广告平台
    provider_map = {"wechat": AdProvider.WECHAT, "tencent": AdProvider.TENCENT, "pangolin": AdProvider.PANGOLIN}
    provider = provider_map.get(ad_platform, AdProvider.WECHAT)

    # 创建广告记录
    ad = AdUnlock(
        user_id=user.id,
        provider=provider,
        ad_type=ad_type,
        status=AdStatus.REWARDED,
        watch_duration_seconds=watch_duration_seconds,
        callback_data=json.dumps(callback_data, ensure_ascii=False) if callback_data else None,
        rewarded_at=datetime.now(timezone.utc),
    )
    db.add(ad)
    await db.flush()

    return {
        "unlocked_count": user.ad_unlock_watched_today,
        "ad_unlock_remaining_today": user.ad_unlock_remaining_today,
        "ad_unlock_daily_limit": AD_UNLOCK_DAILY_LIMIT,
    }


# ==================== 额度扣减（任务创建时调用）====================

class QuotaExhaustedError(Exception):
    """额度不足：所有渠道都用完"""
    pass


async def consume_quota_for_task(db: AsyncSession, user: User) -> str:
    """任务创建时扣减额度，返回 quota_reason

    优先级：VIP > Pack > Trial > Ad

    P0-02/03/05 修复：行锁 + 真实拒绝
    - 旧逻辑：无锁 + 静默扣减 → trial_remaining 扣到 -1 / Pack 超扣
    - 新逻辑：
      1) SELECT FOR UPDATE 锁 User 行（防止并发同时改 trial_remaining）
      2) 优先级判定：每路都必须"还有额度"才扣减
      3) 全部用完 → 抛 QuotaExhaustedError（HTTP 402）
      4) commit 由调用方负责
    """
    from fastapi import HTTPException, status as http_status
    from sqlalchemy import select as sa_select

    _apply_daily_reset(user)

    # P0-02 修复：行锁 User 行（防止并发同 user 提交同时扣 trial_remaining）
    locked_user = (
        await db.execute(
            sa_select(User).where(User.id == user.id).with_for_update()
        )
    ).scalar_one_or_none()
    if not locked_user:
        raise QuotaExhaustedError("用户不存在")

    user_packs = await list_user_packs(
        db,
        locked_user.id,
        include_status=[UserPackStatus.ACTIVE],
    )
    source, _ = _resolve_current_quota(locked_user, user_packs)

    if source == "vip":
        # VIP 每天有上限，超出后降级到 Pack/Trial
        vip_daily_limit = _get_vip_daily_limit(locked_user)
        if locked_user.vip_daily_used >= vip_daily_limit:
            # 降级：再尝试 Pack / Trial
            source = _try_pack_or_trial(locked_user, user_packs, db)
            if source is None:
                raise QuotaExhaustedError("今日 VIP 额度已用完")
            return source
        locked_user.vip_daily_used += 1
        # 把改动同步到外层 user 对象（避免后续 .commit 时漏字段）
        user.vip_daily_used = locked_user.vip_daily_used
        return "vip"

    if source == "pack":
        # P0-03 修复：行锁 Pack 行
        # 统一 DB 取出的 expire_at 时区（SQLite 不存 tz，可能 naive），避免
        # "can't compare offset-naive and offset-aware datetimes"
        now = datetime.now(timezone.utc)
        active = []
        for p in user_packs:
            if p.status != UserPackStatus.ACTIVE:
                continue
            if p.remaining_tasks <= 0:
                continue
            expire_at = p.expire_at
            if expire_at is not None and expire_at.tzinfo is None:
                expire_at = expire_at.replace(tzinfo=timezone.utc)
            if expire_at is not None and expire_at > now:
                active.append(p)
        if not active:
            # 降级 Trial
            return await _consume_trial(locked_user, user, db)
        # 锁住所有 active packs（按 ID ASC 避免死锁）
        # P0-修复：原代码写的是 from app.models.pack import UserPack，但项目里没有
        # app/models/pack.py，UserPack 实际定义在 app/models/user_pack.py。这会导致
        # 走「套餐额度」路径时（用户的 trial 已用完、走 pack 扣减）抛 ModuleNotFoundError，
        # 表现为 POST /api/v1/tasks 500。
        from app.models.user_pack import UserPack as UP
        pack_ids = [p.id for p in active]
        locked_packs = (
            await db.execute(
                sa_select(UP).where(UP.id.in_(pack_ids)).with_for_update().order_by(UP.id)
            )
        ).scalars().all()
        target = min(locked_packs, key=lambda p: (p.purchased_at, p.id))
        target.remaining_tasks -= 1
        target.consumed_at = now
        if target.remaining_tasks == 0:
            target.status = UserPackStatus.EXHAUSTED
        return "pack"

    if source == "trial":
        return await _consume_trial(locked_user, user, db)

    if source == "ad":
        return await _consume_ad(locked_user, user, db)

    # 所有渠道都用完
    raise QuotaExhaustedError("额度已用完，请购买套餐或开通 VIP")


async def _consume_trial(locked_user: User, user: User, db: AsyncSession) -> str:
    """试用额度扣减（P0-02 修复：在行锁内做）"""
    if locked_user.trial_remaining <= 0:
        raise QuotaExhaustedError("试用额度已用完")
    locked_user.trial_remaining -= 1
    if not locked_user.trial_first_used_date:
        locked_user.trial_first_used_date = date.today()
    # 同步到外层
    user.trial_remaining = locked_user.trial_remaining
    user.trial_first_used_date = locked_user.trial_first_used_date
    return "trial"


async def _consume_ad(locked_user: User, user: User, db: AsyncSession) -> str:
    """广告额度扣减"""
    if locked_user.ad_unlock_remaining_today <= 0:
        raise QuotaExhaustedError("今日广告额度已用完")
    locked_user.ad_unlock_remaining_today -= 1
    user.ad_unlock_remaining_today = locked_user.ad_unlock_remaining_today
    return "ad"


def _try_pack_or_trial(locked_user: User, user_packs: list, db: AsyncSession):
    """VIP 用完后降级到 Pack / Trial 的内部辅助"""
    # 优先 Pack（统一 expire_at 时区，避免 naive-aware 比较报错）
    now = datetime.now(timezone.utc)
    active = []
    for p in user_packs:
        if p.status != UserPackStatus.ACTIVE or p.remaining_tasks <= 0:
            continue
        expire_at = p.expire_at
        if expire_at is not None and expire_at.tzinfo is None:
            expire_at = expire_at.replace(tzinfo=timezone.utc)
        if expire_at is not None and expire_at > now:
            active.append(p)
    if active:
        return "pack"
    if locked_user.trial_remaining > 0:
        return "trial"
    return None


def _get_vip_daily_limit(user: User) -> int:
    """VIP 每日任务上限，按 member_type 走不同上限"""
    if user.member_type == "vip3":
        return 9999
    if user.member_type == "vip2":
        return 50
    if user.member_type == "vip1":
        return 20
    return 0  # 非 VIP


async def release_quota_for_failed_task(
    db: AsyncSession, user: User, quota_reason: str | None
) -> None:
    """P0-06 修复：AI 处理失败时回滚额度

    之前扣减了额度就算失败也不退 → 用户白扣。
    现在 task 进入 FAILED 时调用此函数按原 channel 退回一次额度。

    注意：调用方需在 commit 失败后单独再 commit 一次。
    """
    if not quota_reason or quota_reason not in ("vip", "pack", "trial", "ad"):
        return

    from sqlalchemy import select as sa_select
    locked = (
        await db.execute(sa_select(User).where(User.id == user.id).with_for_update())
    ).scalar_one_or_none()
    if not locked:
        return

    if quota_reason == "vip":
        if locked.vip_daily_used > 0:
            locked.vip_daily_used -= 1
            user.vip_daily_used = locked.vip_daily_used
    elif quota_reason == "trial":
        # 终身一次试用：回滚时不能超过 TRIAL_TOTAL_QUOTA，
        # 防止 release_quota 被多次触发（任务失败回滚路径）时 trial_remaining 无限累加
        locked.trial_remaining = min(locked.trial_remaining + 1, TRIAL_TOTAL_QUOTA)
        user.trial_remaining = locked.trial_remaining
    elif quota_reason == "ad":
        # 每日广告额度回滚必须钳制：不能超过「当日已看广告次数」，
        # 否则任务反复失败重试会突破每日 2 次上限（重演 trial_remaining 膨胀问题）。
        # ad_unlock_watched_today 是当日实际看广告次数，是硬上限。
        max_ad = max(0, user.ad_unlock_watched_today)
        locked.ad_unlock_remaining_today = min(locked.ad_unlock_remaining_today + 1, max_ad)
        user.ad_unlock_remaining_today = locked.ad_unlock_remaining_today
    elif quota_reason == "pack":
        # Pack 回滚：找最近消费的包 +1
        # 同上，模块路径应为 app.models.user_pack（UserPack 定义在 user_pack.py）
        from sqlalchemy import desc as sa_desc
        from app.models.user_pack import UserPack
        last = (
            await db.execute(
                sa_select(UserPack)
                .where(UserPack.user_id == user.id)
                .order_by(sa_desc(UserPack.consumed_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if last:
            last.remaining_tasks += 1
            if last.status == UserPackStatus.EXHAUSTED:
                last.status = UserPackStatus.ACTIVE
    logger.info(f"[pack_service] 失败回滚额度 user_id={user.id} channel={quota_reason}")
