"""次数套餐包路由

- GET  /api/v1/packs                  列出所有可购买的次数包
- POST /api/v1/packs/purchase         创建订单（mock 模式同步到账）
- POST /api/v1/packs/purchase/notify  微信支付回调（生产环境）
- POST /api/v1/quota/pack-consume     任务创建时原子扣减
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser
from app.db.session import DbSession
from app.models.pack_order import PackOrder, PackOrderStatus
from app.models.user_pack import UserPack
from app.schemas.pack import (
    PackConsumeReq,
    PackConsumeResp,
    PurchasePackReq,
    PurchasePackResp,
    QuotaPackOut,
    UserPackBrief,
)
from app.services import pack_service

router = APIRouter()

# 把 quota/pack-consume 单独挂到 /quota 前缀（不进 /packs）
quota_consume_router = APIRouter()


# ==================== GET /packs ====================

@router.get("", response_model=list[QuotaPackOut], summary="获取次数套餐包列表")
async def list_packs(db: DbSession) -> list[QuotaPackOut]:
    packs = await pack_service.list_active_packs(db)
    return [QuotaPackOut.from_orm_obj(p) for p in packs]


# ==================== POST /packs/purchase ====================

@router.post("/purchase", response_model=PurchasePackResp, summary="购买次数包")
async def purchase_pack(
    payload: PurchasePackReq,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> PurchasePackResp:
    pack = await pack_service.get_pack_by_code(db, payload.pack_code)
    if not pack or not pack.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"次数包 {payload.pack_code} 不存在或已下架",
        )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    order, user_pack = await pack_service.create_purchase_order(
        db, user, pack, pay_channel=payload.pay_channel,
        client_ip=client_ip, user_agent=user_agent,
    )

    pack_out = QuotaPackOut.from_orm_obj(pack)
    if user_pack:
        # mock 模式：同步到账
        return PurchasePackResp(
            order_no=order.order_no,
            pack=pack_out,
            pay_status="success",
            user_pack=UserPackBrief.from_orm_obj(user_pack),
            message="Mock 模式：已自动到账",
        )
    # 真实模式：等待支付
    # TODO: 调用微信统一下单，拿到 prepay_id 后填入 prepay_params
    return PurchasePackResp(
        order_no=order.order_no,
        pack=pack_out,
        pay_status="pending",
        prepay_params=None,
        user_pack=None,
        message="订单已创建，请调起微信支付",
    )


# ==================== POST /packs/purchase/notify ====================

@router.post(
    "/purchase/notify",
    summary="微信支付回调（生产）",
    description="微信支付结果通知，验签后激活 user_pack。Mock 模式不会调用此接口。",
)
async def purchase_notify(request: Request, db: DbSession) -> dict:
    """微信支付回调

    生产环境需要：
    1. 解析微信 XML 回调
    2. 验签（用 WECHAT_PAY_KEY）
    3. 成功：订单置 PAID，调用 activate_user_pack_from_order
    4. 返回 SUCCESS / FAIL 给微信
    """
    # 简化：WBS 阶段占位。真实实现依赖微信支付 SDK。
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="微信支付回调待 WBS 2.x 接入",
    )


# ==================== POST /quota/pack-consume ====================

@quota_consume_router.post(
    "/pack-consume",
    response_model=PackConsumeResp,
    summary="原子扣减用户持有的次数包",
)
async def pack_consume(
    payload: PackConsumeReq,
    user: CurrentUser,
    db: DbSession,
) -> PackConsumeResp:
    user_pack = await pack_service.consume_user_pack(db, user, payload.user_pack_id)
    return PackConsumeResp(
        user_pack_id=user_pack.id,
        remaining_tasks=user_pack.remaining_tasks,
        message="扣减成功",
    )
