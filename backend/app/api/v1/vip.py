"""VIP 套餐路由

- GET  /api/v1/vip/plans     列出所有可购买的 VIP 月卡套餐
"""

import json

from fastapi import APIRouter

from app.db.session import DbSession
from app.models.vip_plan import VipPlan
from app.schemas.vip import VipPlanOut

router = APIRouter()


@router.get(
    "/plans",
    response_model=list[VipPlanOut],
    summary="获取 VIP 套餐列表",
    description="返回所有可购买的 VIP 月卡（按 sort_order 升序）。用于前端开通/续费页展示。",
)
async def list_vip_plans(db: DbSession) -> list[VipPlanOut]:
    """列出所有上架的 VIP 套餐（按 sort_order 升序）"""
    from sqlalchemy import select

    stmt = (
        select(VipPlan)
        .where(VipPlan.is_active.is_(True))
        .order_by(VipPlan.sort_order.asc(), VipPlan.id.asc())
    )
    result = await db.execute(stmt)
    plans = result.scalars().all()
    return [VipPlanOut.from_orm_obj(p) for p in plans]
