"""额度查询路由

- GET  /api/v1/user/quota       当前用户额度快照（含 user_packs）
- POST /api/v1/quota/ad-unlock  广告解锁处理次数
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.db.session import DbSession
from app.schemas.ad import AdUnlockReq, AdUnlockResultOut
from app.schemas.quota import QuotaInfoOut
from app.services import pack_service

router = APIRouter()


@router.get(
    "/user/quota",
    response_model=QuotaInfoOut,
    summary="查询当前用户额度",
)
async def get_my_quota(user: CurrentUser, db: DbSession) -> QuotaInfoOut:
    snapshot = await pack_service.get_user_quota_snapshot(db, user)
    return QuotaInfoOut(**snapshot)


@router.post(
    "/quota/ad-unlock",
    response_model=AdUnlockResultOut,
    summary="广告解锁处理次数",
)
async def ad_unlock(
    req: AdUnlockReq,
    user: CurrentUser,
    db: DbSession,
) -> AdUnlockResultOut:
    """观看广告后增加 1 次处理额度（每日最多 2 次）"""
    result = await pack_service.ad_unlock(
        db,
        user,
        ad_type=req.ad_type,
        ad_platform=req.ad_platform,
        watch_duration_seconds=req.watch_duration_seconds,
        callback_data=req.ad_callback_data,
    )
    await db.commit()
    return AdUnlockResultOut(**result)
