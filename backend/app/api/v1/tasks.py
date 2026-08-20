"""任务管理路由

- POST /api/v1/tasks               创建处理任务
- GET  /api/v1/tasks/{id}/status   查询任务状态
- GET  /api/v1/tasks/{id}/result   获取处理结果
- GET  /api/v1/tasks               历史记录列表
"""

import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser
from app.db.session import DbSession
from app.schemas.task import (
    CreateTaskResultOut,
    PhotoGroupOut,
    PreviewDroppedPhotoOut,
    PreviewOut,
    PreviewReq,
    SelectedPhotoOut,
    TaskCreateReq,
    TaskHistoryOut,
    TaskResultOut,
    TaskStatusOut,
)
from app.services import task_service
from app.services.pack_service import QuotaExhaustedError
from app.ai import ai_pipeline
from app.ai.base import PhotoInfo
from app.ai.screener_real import ScreeningFatalError
from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])

_settings = get_settings()


@router.post(
    "/preview",
    response_model=PreviewOut,
    summary="筛选预览（先筛选、再确认）",
)
async def preview_screen(
    req: PreviewReq,
    user: CurrentUser,
) -> PreviewOut:
    """上传完原图后调用：仅做智能筛选（分组 + 评分排序），不精修、不扣额度。

    返回 total_photos / total_groups / selected_photos（精选）/ dropped_photos（被去重），
    前端据此展示筛选进度与结果，用户确认后才调用 POST /tasks 创建任务并扣额度。

    注意：screen_only 是真实执行（下载原图 → aHash 聚类 → 拉普拉斯方差/人脸检测评分排序），
    非假跑。照片顺序按上传顺序保留，便于前端映射缩略图。
    """
    # P0 修复：筛选前预校验 COS 对象真实存在。
    # 前端 PUT 在微信开发者工具模拟器偶发"success 但未真正持久化"（devtools bug），
    # 直接拿 presign 的 accessUrl 当已上传 URL 用，从不调用 /photos/confirm。
    # 若不预校验，筛选阶段才发现全部 404 → 闷头降级或 ScreeningFatalError。
    # 这里提前 head_object 校验，全部不存在直接返回业务级 error。
    from app.services import photo_service
    missing = 0
    for url in req.photo_urls:
        if not photo_service.object_exists(url):
            missing += 1
            logger.warning(f"[tasks] preview 预校验：COS 对象不存在 url={url}")
    if missing > 0 and missing == len(req.photo_urls):
        # 全部不存在 → 直接报错，不进入筛选（避免无谓的下载重试 + 致命错误链路）
        logger.error(
            f"[tasks] preview 全部 {missing} 张照片 COS 对象不存在，拒绝筛选"
        )
        return PreviewOut(
            error="图片批量处理筛选失败：无法正常筛选照片。",
        )
    if missing > 0:
        logger.warning(
            f"[tasks] preview 有 {missing}/{len(req.photo_urls)} 张照片 COS 对象不存在"
            f"（将继续筛选存在的照片）"
        )

    photos = [
        PhotoInfo(photo_id=str(i), original_url=url, order_index=i)
        for i, url in enumerate(req.photo_urls)
    ]
    try:
        result = await ai_pipeline.screen_only(
            photos, max_per_group=_settings.SELECT_TOP_PER_GROUP
        )
    except ScreeningFatalError as e:
        # 筛选致命错误（典型：全部图片下载失败）。preview 阶段还没创建任务、
        # 也没扣额度，不需要返还；但必须友好地告诉用户，不能闷头 500。
        # 业务级返回：HTTP 200 + PreviewOut.error，前端直接展示文案。
        logger.error(f"[tasks] preview 致命错误：{e}")
        return PreviewOut(
            error="图片批量处理筛选失败：无法正常筛选照片。",
        )

    selected_photos = [SelectedPhotoOut(**p) for p in result["selected_photos"]]
    groups = [PhotoGroupOut(**g) for g in result["groups"]]
    dropped_photos = [PreviewDroppedPhotoOut(**d) for d in result["dropped_photos"]]

    return PreviewOut(
        total_photos=result["total_photos"],
        total_groups=result["total_groups"],
        selected_count=len(selected_photos),
        dropped_count=result["dropped_count"],
        selected_photos=selected_photos,
        groups=groups,
        dropped_photos=dropped_photos,
    )


@router.post(
    "",
    response_model=CreateTaskResultOut,
    summary="创建处理任务",
)
async def create_task(
    req: TaskCreateReq,
    user: CurrentUser,
    db: DbSession,
) -> CreateTaskResultOut:
    """创建照片处理任务（Mock 模式下立即生成模拟结果）"""
    if not req.photo_urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="photo_urls 不能为空",
        )

    try:
        task = await task_service.create_task(
            db,
            user,
            photo_urls=req.photo_urls,
            retouch_styles=req.options.retouch_styles,
            location=req.options.location,
        )
        await db.commit()
    except QuotaExhaustedError as e:
        # P0-02 修复：额度不足返回 402 Payment Required
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e) or "额度已用完，请购买套餐或开通 VIP",
        )

    # 计算剩余额度（简化版）
    remaining = user.trial_remaining - 1 if user.trial_remaining > 0 else 0

    return CreateTaskResultOut(
        task_id=str(task.id),
        status="pending",
        estimated_time=5,
        quota_used=1,
        quota_remaining=remaining,
    )


@router.get(
    "/{task_id}/status",
    response_model=TaskStatusOut,
    summary="查询任务状态",
)
async def get_task_status(
    task_id: str,
    user: CurrentUser,
    db: DbSession,
) -> TaskStatusOut:
    """查询任务处理进度"""
    try:
        result = await task_service.get_task_status(db, int(task_id), user)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    await db.commit()
    return TaskStatusOut(**result)


@router.get(
    "/{task_id}/result",
    response_model=TaskResultOut,
    summary="获取处理结果",
)
async def get_task_result(
    task_id: str,
    user: CurrentUser,
    db: DbSession,
) -> TaskResultOut:
    """获取任务处理结果（筛选+精修后的照片）"""
    try:
        result = await task_service.get_task_result(db, int(task_id), user)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return TaskResultOut(**result)


@router.get(
    "",
    response_model=TaskHistoryOut,
    summary="获取处理历史",
)
async def get_history(
    user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> TaskHistoryOut:
    """获取用户的任务历史记录"""
    result = await task_service.get_task_history(db, user, page, page_size)
    return TaskHistoryOut(**result)


@router.post(
    "/{task_id}/retry-retouch",
    summary="重试精修（仅重跑失败照片）",
)
async def retry_retouch(
    task_id: str,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    """对任务中「精修失败」的照片重新提交美图精修。

    用于回调隧道抖动 / 美图限频导致的 callback_timeout 降级。
    仅重试带 _retouch_failed 标记的照片，已成功的保留不动。
    """
    try:
        result = await task_service.retry_retouch(int(task_id), user)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    await db.commit()
    return result
