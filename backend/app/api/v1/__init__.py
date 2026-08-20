"""API 路由聚合

WBS 1.x 阶段已注册：
- 1.x health.py    健康检查
- 2.x auth.py      微信登录 / 退出
- 2.x photos.py    照片上传（STS + confirm）
- 2.x tasks.py     任务管理（创建 / 状态 / 结果 / 历史）
- 5.x packs.py     次数套餐包（含购买 + 微信支付回调）
- 5.x quota.py     额度查询
- 5.x packs.py::quota_consume_router  原子扣减（挂到 /quota 前缀）
- 3.x captions.py  文案生成（风格列表 + 生成）
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.captions import router as captions_router
from app.api.v1.health import router as health_router
from app.api.v1.photos import router as photos_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.packs import router as packs_router, quota_consume_router
from app.api.v1.quota import router as quota_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router)
api_router.include_router(photos_router)
api_router.include_router(tasks_router)
api_router.include_router(captions_router)
api_router.include_router(packs_router, prefix="/packs", tags=["packs"])
api_router.include_router(quota_router, tags=["quota"])
api_router.include_router(quota_consume_router, prefix="/quota", tags=["quota"])
