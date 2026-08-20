"""任务业务服务

- 创建任务（调用 AI pipeline 生成处理结果）
- 查询任务状态（基于时间的状态流转）
- 获取处理结果
- 历史记录
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import PhotoInfo, ai_pipeline
from app.ai.base import SelectedPhoto
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.photo import Photo
from app.models.task import Task, TaskStatus
from app.models.user import User

settings = get_settings()
logger = logging.getLogger(__name__)

# P0-13 修复：进程级幂等集合，防止 _recover_interrupted_tasks 多次执行时
# 对同一 task 启动多个后台协程（→ 套餐二次扣减 / 美图多次提交）
_recovered_task_ids: set[int] = set()

# P1-03 修复：retry_retouch 进程级并发锁（防同 task 多次触发重试）
_retrying_task_ids: set[int] = set()


def _use_real_retouch() -> bool:
    """是否启用真实美图精修（配置了 API Key + media_code）"""
    return bool(settings.MEITU_API_KEY and settings.MEITU_MEDIA_CODE)

# Mock 模式下各阶段耗时（秒）
_STAGE_UPLOADING = 1
_STAGE_SCREENING = 2
_STAGE_RETOUCHING = 3
_TOTAL_MOCK_TIME = _STAGE_UPLOADING + _STAGE_SCREENING + _STAGE_RETOUCHING


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _calc_photo_expire_at(user: User) -> str | None:
    """根据用户等级计算图片过期时间

    - 免费用户：7天后过期
    - VIP1/VIP2：30天后过期
    - VIP3：永久保留（返回 None）
    """
    member_type = getattr(user, "member_type", "free")
    if member_type == "vip3":
        return None  # 永久保留

    from datetime import timedelta
    if member_type in ("vip1", "vip2"):
        expire = datetime.now(timezone.utc) + timedelta(days=30)
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=7)
    return expire.isoformat()


def _is_task_expired(task: Task, user: User) -> bool:
    """检查任务照片是否已过期

    VIP3 永久不过期；其他用户按 expire_at 判断。
    """
    member_type = getattr(user, "member_type", "free")
    if member_type == "vip3":
        return False

    # 查询该任务的 Photo 记录中的 expire_at
    # 简化：用 task 的 created_at + 对应天数判断
    if not task.created_at:
        return False
    created = task.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    from datetime import timedelta
    if member_type in ("vip1", "vip2"):
        expire_days = 30
    else:
        expire_days = 7
    expire_time = created + timedelta(days=expire_days)
    return datetime.now(timezone.utc) > expire_time


async def _sync_photos_from_ai_result(
    db: AsyncSession, task_id: int, ai_result: dict
) -> int:
    """P0-2 修复：把 AI 处理结果写回 Photo 表，让 Photo 行的真实字段与 extra_params JSON 一致。

    历史问题：_run_ai_pipeline_background 完成后只写 task.extra_params，从不写 Photo 行
    → history/详情/统计等所有读 Photo 表的页面都拿不到 quality_score/cluster_id/retouch_style。

    Returns: 成功同步的照片数（0 = 全部失败或无 selected_photos，不报错）。
    """
    selected = ai_result.get("selected_photos", []) or []
    if not selected:
        return 0

    synced = 0
    for sp in selected:
        pid_raw = sp.get("photo_id")
        if pid_raw is None:
            continue
        try:
            pid = int(pid_raw)
        except (TypeError, ValueError):
            continue
        ph = (
            await db.execute(select(Photo).where(Photo.id == pid, Photo.task_id == task_id))
        ).scalar_one_or_none()
        if not ph:
            continue

        # 1. 精修图：美图成功 → processed_url，失败 → 仍写回（带 _retouch_failed 标记）
        processed_url = sp.get("processed_url") or sp.get("original_url")
        if processed_url and "_retouch_failed=" not in (processed_url or ""):
            ph.processed_url = processed_url
            ph.status = "done"
        elif "_retouch_failed=" in (processed_url or ""):
            ph.processed_url = processed_url
            ph.status = "failed"
            ph.error_msg = "meitu_retouch_failed"

        # 2. 缩略图：有就写
        thumb = sp.get("thumbnail_url")
        if thumb:
            ph.thumb_url = thumb

        # 3. 智能筛选字段
        if sp.get("quality_score") is not None:
            ph.quality_score = float(sp["quality_score"])
        if sp.get("face_count") is not None:
            ph.face_count = int(sp["face_count"])
        # cluster_id 在 DB 是 String(64)，AI 侧是 int（构图组号），转成 "g{0}" 格式便于后续按前缀查询
        if sp.get("cluster_group_id") is not None:
            ph.cluster_id = f"g{sp['cluster_group_id']}"
        if sp.get("type"):
            # scene_tags 存 JSON：type + category 一起
            scene = {"type": sp.get("type"), "category": sp.get("category")}
            ph.scene_tags = json.dumps(scene, ensure_ascii=False)

        # 4. 精修字段
        if sp.get("retouch_style"):
            ph.retouch_style = sp["retouch_style"]

        db.add(ph)
        synced += 1

    if synced:
        logger.info(
            f"[task_service] Photo 行同步完成 task_id={task_id} synced={synced}/{len(selected)}"
        )
    return synced


async def _backfill_processed_urls(db: AsyncSession, ai_result: dict) -> None:
    """P1 修复：把真实精修 URL 从 Photo 表回写到 ai_result 的 selected_photos / groups。

    背景：精修是异步回调（美图云修），update_photo_processed 只更新了 DB 的
    Photo.processed_url；而 ai_result 中的 selected_photos[].processed_url 仍是筛选阶段
    写入的「精修前原图 URL」。若不回写：
    - 结果页（get_task_result 读 task.extra_params）拿到的 processed_url 是原图；
    - 用户点击缩略图放大 → 看到的是原图，看不到精修效果。

    同时处理 groups[].photos（分组列表里也可能展示缩略图）。
    失败时保持原值（不抛异常，避免影响主线完成流程）。
    """
    selected = ai_result.get("selected_photos", []) or []
    if not selected:
        return

    # 收集所有 photo_id，一次性查 DB
    ids = []
    for sp in selected:
        raw = sp.get("photo_id")
        if raw is not None:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                pass
    if not ids:
        return

    from sqlalchemy import select as _select

    rows = (
        await db.execute(
            _select(Photo.id, Photo.processed_url, Photo.thumb_url).where(
                Photo.id.in_(ids)
            )
        )
    ).all()

    url_map: dict[int, str] = {}
    thumb_map: dict[int, str] = {}
    for pid, purl, turl in rows:
        if purl:
            url_map[pid] = purl
        if turl:
            thumb_map[pid] = turl

    if not url_map:
        return

    for sp in selected:
        raw = sp.get("photo_id")
        if raw is None:
            continue
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid in url_map and url_map[pid]:
            # 仅当 DB 有真实精修 URL 时才覆盖（含 _retouch_failed 降级的也覆盖，
            # 保证结果页与原图对比一致）
            sp["processed_url"] = url_map[pid]
            sp["thumbnail_url"] = thumb_map.get(pid) or url_map[pid]

    for g in ai_result.get("groups", []) or []:
        for sp in g.get("photos", []) or []:
            raw = sp.get("photo_id")
            if raw is None:
                continue
            try:
                pid = int(raw)
            except (TypeError, ValueError):
                continue
            if pid in url_map and url_map[pid]:
                sp["processed_url"] = url_map[pid]
                sp["thumbnail_url"] = thumb_map.get(pid) or url_map[pid]


async def _generate_ai_result(
    photos: list[Photo], retouch_styles: list[str], location: str | None
) -> dict:
    """调用 AI pipeline 生成处理结果（筛选 + 精修 + 文案）"""
    photo_infos = [
        PhotoInfo(
            photo_id=str(p.id),
            original_url=p.original_url,
            order_index=p.order_index,
        )
        for p in photos
    ]

    result = await ai_pipeline.process(
        photos=photo_infos,
        retouch_styles=retouch_styles,
        location=location,
        max_per_group=settings.SELECT_TOP_PER_GROUP,
    )
    return result


async def _run_ai_pipeline_background(
    task_id: int,
    photo_infos: list[PhotoInfo],
    retouch_styles: list[str],
    location: str | None,
) -> None:
    """后台执行 AI 流水线（真实美图精修是异步回调，耗时较长）

    create_task 立即返回 task_id，本协程在后台：
    1. 置任务为 processing
    2. 启动 watchdog 协程：每 5 秒查 DB 推 progress（20% → 90%，基于已精修张数）
    3. 跑筛选 + 精修（MeituProRetoucher 会等待美图回调）
    4. 取消 watchdog，把含真实精修图地址的结果写入 extra_params
    5. 置任务为 completed
    任何异常置 failed，不阻塞前端轮询。
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            task = (
                await db.execute(select(Task).where(Task.id == task_id))
            ).scalar_one_or_none()
            if not task:
                return
            task.status = TaskStatus.PROCESSING
            task.progress = 20
            task.started_at = datetime.now(timezone.utc)
            total_count = task.total_count
            await db.commit()

            # ===== 启动进度 watchdog：每 5 秒推 progress 20% → 90% =====
            watchdog_task = asyncio.create_task(
                _progress_watchdog(task_id, total_count, interval=5)
            )

            try:
                ai_result = await ai_pipeline.process(
                    photos=photo_infos,
                    retouch_styles=retouch_styles,
                    location=location,
                    max_per_group=settings.SELECT_TOP_PER_GROUP,
                    db=db,
                    task_id=task_id,
                    # P0 修复：前端 /tasks/preview 已让用户确认过精选列表，
                    # 此处不应再做二次聚类去重，否则会出现"用户确认 4 张、
                    # 结果页只精修 1 张"的矛盾（task_id=106 bug）。
                    skip_screening=True,
                )
            finally:
                # 无论成功/异常，都取消 watchdog
                watchdog_task.cancel()
                try:
                    await watchdog_task
                except (asyncio.CancelledError, Exception):
                    pass

            # P1 修复：精修是异步回调，update_photo_processed 只更新了 DB 的 Photo.processed_url，
            # 但 ai_result 里的 selected_photos[].processed_url 仍是筛选阶段写入的精修前原图 URL。
            # 若不回写，结果页读到的就是原图，点击放大看不到精修效果。
            # 这里从 DB 读回真实精修 URL，覆盖 ai_result 的 selected_photos 与 groups。
            await _backfill_processed_urls(db, ai_result)

            task.extra_params = json.dumps(ai_result, ensure_ascii=False)
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.processed_count = task.total_count
            task.finished_at = datetime.now(timezone.utc)

            # P0-2 修复：把 selected_photos 里的真实处理结果写回 Photo 表
            # 之前只写 task.extra_params JSON，Photo 表全空 → 历史/详情页读不到真实分数/分组/精修风格
            await _sync_photos_from_ai_result(db, task_id, ai_result)

            await db.commit()
            logger.info(f"[task_service] 后台流水线完成 task_id={task_id}")
        except Exception as e:
            logger.exception(f"[task_service] 后台流水线失败 task_id={task_id}: {e}")
            try:
                t = (
                    await db.execute(select(Task).where(Task.id == task_id))
                ).scalar_one_or_none()
                if t:
                    t.status = TaskStatus.FAILED
                    # 给用户可见的友好报错（不含内部堆栈）
                    t.error_msg = (
                        "图片批量处理筛选失败：无法正常筛选照片。"
                    )
                    # P0 修复：筛选/处理失败 → 返还本次任务消耗的处理次数
                    # （原来只置 FAILED，额度白扣）。quota_reason 由 create_task
                    # 在扣减时记录（vip/pack/trial/ad），未扣则为空、release 自动跳过。
                    if t.quota_reason and t.quota_reason not in ("refunded",):
                        try:
                            from app.services.pack_service import (
                                release_quota_for_failed_task,
                            )
                            from sqlalchemy import select as _sel
                            u = (
                                await db.execute(
                                    _sel(User).where(User.id == t.user_id)
                                )
                            ).scalar_one_or_none()
                            if u:
                                await release_quota_for_failed_task(
                                    db, u, t.quota_reason
                                )
                                t.quota_reason = "refunded"
                                logger.info(
                                    f"[task_service] 任务失败已返还额度 task_id={task_id} "
                                    f"user_id={t.user_id} reason={t.quota_reason}"
                                )
                        except Exception as re:
                            logger.error(
                                f"[task_service] 返还额度失败 task_id={task_id}: {re}"
                            )
                    await db.commit()
            except Exception:
                pass


async def _progress_watchdog(task_id: int, total_count: int, interval: int = 5) -> None:
    """精修阶段进度推送 watchdog。

    每 `interval` 秒查 DB 统计「已精修张数」= 已有 processed_url 的 Photo 数，
    推 task.progress = 20 + 70 * (processed / total)。
    上限 90%（最后 10% 留给「写结果 + 标记 completed」）。

    设计取舍：
    - 不通过回调更新 processed_count：避免热路径加锁
    - 独立 DB 连接：避免和主流程争抢连接
    - 捕获所有异常：单次失败不影响后续推送
    """
    from app.db.session import AsyncSessionLocal
    from app.models.photo import Photo as PhotoModel
    from sqlalchemy import func as sa_func

    if total_count <= 0:
        return

    while True:
        try:
            await asyncio.sleep(interval)
            async with AsyncSessionLocal() as db:
                # 统计该任务下已精修的照片数（processed_url IS NOT NULL）
                result = await db.execute(
                    select(sa_func.count(PhotoModel.id)).where(
                        PhotoModel.task_id == task_id,
                        PhotoModel.processed_url.isnot(None),
                    )
                )
                processed = result.scalar() or 0

                # 推 progress：20% (筛选完成) → 90% (精修完成)，中间线性
                progress = 20 + int(70 * processed / total_count)
                # 至少推 1 次，让人看到进度在动（即使 0 张完成也保持 20%）
                progress = max(20, min(90, progress))

                t = (
                    await db.execute(select(Task).where(Task.id == task_id))
                ).scalar_one_or_none()
                if t and t.status == TaskStatus.PROCESSING:
                    # 只升不降（避免 watchdog 和最终 commit 冲突）
                    if progress > (t.progress or 0):
                        t.progress = progress
                        t.processed_count = processed
                        await db.commit()
                        logger.info(
                            f"[task_service] watchdog 推进度 task_id={task_id} "
                            f"processed={processed}/{total_count} progress={progress}%"
                        )
        except asyncio.CancelledError:
            # 正常取消（主流程结束）
            return
        except Exception as e:
            # 单次失败不影响后续推送
            logger.warning(f"[task_service] watchdog 单次失败 task_id={task_id}: {e}")
            continue


async def retry_retouch(task_id: int, user: User) -> dict:
    """对任务中「精修失败」的照片重新提交美图精修。

    适用场景：回调隧道（花生壳/ngrok）抖动 / 美图限频导致的 callback_timeout
    降级——用户在前端结果页看到「精修失败，已保留原图」，点「重试精修」即调用本函数。

    仅重试带 _retouch_failed 标记的照片，已成功的保留不动；
    没有失败项时直接返回，不消耗额外额度。

    P1-03 修复：状态机保护
    - 旧逻辑：可重复刷重试 → 同一张照片被多次提交给美图，浪费配额 + 回调串味
    - 新逻辑：
      1) 状态机保护：仅 COMPLETED 任务才能重试
      2) 进程级 _retrying_task_ids 锁：同一 task 同时只能有一个重试协程
    """
    # P1-03 修复：进程级幂等锁
    global _retrying_task_ids
    try:
        retrying = _retrying_task_ids
    except NameError:
        retrying = set()
        _retrying_task_ids = retrying  # type: ignore[assignment]

    async with AsyncSessionLocal() as db:
        task = (
            await db.execute(
                select(Task).where(Task.id == task_id, Task.user_id == user.id)
            )
        ).scalar_one_or_none()
        if not task:
            raise ValueError("任务不存在")
        if task.status == TaskStatus.PROCESSING:
            raise ValueError("任务正在处理中，请稍候再试")
        if task.status == TaskStatus.FAILED:
            raise ValueError("任务已失败，无法重试精修")
        if task.status == TaskStatus.PENDING:
            raise ValueError("任务尚未开始，无法重试精修")
        # 仅 COMPLETED 状态可重试
        if task.status != TaskStatus.COMPLETED:
            raise ValueError(f"任务状态 {task.status.value} 不可重试")
        if not task.extra_params:
            raise ValueError("任务无处理结果，无法重试")

        # P1-03：同 task 同时只允许一个重试
        if task_id in retrying:
            raise ValueError("已有重试在进行中，请稍候")
        retrying.add(task_id)

        extra = json.loads(task.extra_params)
        selected = extra.get("selected_photos", []) or []
        failed = [
            p for p in selected
            if "_retouch_failed=" in (p.get("processed_url") or "")
        ]
        if not failed:
            retrying.discard(task_id)
            return {"retried": 0, "message": "没有需要重试的失败照片"}

        # 重建 SelectedPhoto（仅失败项）交给他 _retouch 重新提交
        items: list[SelectedPhoto] = []
        for p in failed:
            items.append(
                SelectedPhoto(
                    photo_id=str(p["photo_id"]),
                    original_url=p["original_url"],
                    processed_url=p.get("processed_url") or p["original_url"],
                    thumbnail_url=p.get("thumbnail_url") or p["original_url"],
                    quality_score=p.get("quality_score", 0),
                    face_count=p.get("face_count", 0),
                    type=p.get("type", "portrait"),
                    retouch_style=p.get("retouch_style", "auto"),
                    retouch_style_label=p.get("retouch_style_label", "智能配风格"),
                    cluster_group_id=p.get("cluster_group_id", 0),
                    rank_in_group=p.get("rank_in_group", 0),
                    caption=p.get("caption"),
                    face_gender=p.get("face_gender"),
                    face_age=p.get("face_age"),
                    category=p.get("category"),
                )
            )

        task.status = TaskStatus.PROCESSING
        task.progress = 20
        await db.commit()

        # P1-03 修复：DB 状态已转 PROCESSING，立即释放进程级锁（让用户能再次重试）
        # 下次重试会被 DB 状态机（PROCESSING）拒绝
        retrying.discard(task_id)

        # 后台跑：复用真实精修 Provider（MeituProRetoucher 会再等回调/轮询）
        asyncio.create_task(_retry_retouch_background(task.id, items, extra))
        logger.info(
            f"[task_service] 提交重试精修 task_id={task_id} 共 {len(items)} 张失败照片"
        )
        return {
            "retried": len(items),
            "message": f"已提交 {len(items)} 张失败照片重新精修",
        }


async def _retry_retouch_background(
    task_id: int, items: list[SelectedPhoto], extra: dict
) -> None:
    """重试精修后台协程：重新提交 → 写回 extra_params + Photo 行 → 标记完成。"""
    # P1-03 修复：进入后台时也要从锁集合移除（让用户能再次触发重试）
    # 原 retry_retouch 加锁后 → 用户每次手动重试都会因"已有重试"被拒
    # 改为：retry_retouch 立刻释放锁（任务已转 PROCESSING，DB 状态机保护并发）；
    # 这里只是 try/finally 双保险
    try:
        results = await ai_pipeline._retouch(items)
        url_map = {str(r.photo_id): r.processed_url for r in results}

        # 写回 extra_params 的 selected_photos 与 groups
        for sp in extra.get("selected_photos", []) or []:
            if str(sp["photo_id"]) in url_map:
                sp["processed_url"] = url_map[str(sp["photo_id"])]
                sp["thumbnail_url"] = url_map[str(sp["photo_id"])]
        for g in extra.get("groups", []) or []:
            for sp in g.get("photos", []) or []:
                if str(sp["photo_id"]) in url_map:
                    sp["processed_url"] = url_map[str(sp["photo_id"])]
                    sp["thumbnail_url"] = url_map[str(sp["photo_id"])]

        async with AsyncSessionLocal() as db:
            task = (
                await db.execute(select(Task).where(Task.id == task_id))
            ).scalar_one_or_none()
            if task:
                task.extra_params = json.dumps(extra, ensure_ascii=False)
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.finished_at = datetime.now(timezone.utc)
                db.add(task)
            # 同步 Photo 行 processed_url / status
            for pid, url in url_map.items():
                try:
                    ph = (
                        await db.execute(select(Photo).where(Photo.id == int(pid)))
                    ).scalar_one_or_none()
                    if ph:
                        ph.processed_url = url
                        ph.status = "done" if "_retouch_failed=" not in url else "failed"
                        db.add(ph)
                except Exception as e:
                    logger.warning(f"[task_service] 重试写回 Photo {pid} 失败: {e}")
            await db.commit()
        logger.info(f"[task_service] 重试精修完成 task_id={task_id}")
    except Exception as e:
        logger.exception(f"[task_service] 重试精修失败 task_id={task_id}: {e}")


async def _recover_interrupted_tasks() -> None:
    """启动时恢复因 reload/重启而中断的后台任务

    asyncio.create_task 创建的协程在进程重启后会丢失，
    但 DB 中任务仍处于 processing/pending 状态。
    本函数查询这些任务并重新启动后台流水线。

    P0-13 修复：幂等保护
    - 旧逻辑：进程启动一次就创建一次 asyncio.create_task
      → 同一 task 多次恢复时（reload 时尤其），可能双跑 → 套餐二次扣减
    - 新逻辑：用 _recovered_task_ids 集合守住，重复调用直接跳过
    """
    if not _use_real_retouch():
        return

    # P0-13：进程级幂等集合
    global _recovered_task_ids
    try:
        already = _recovered_task_ids
    except NameError:
        already = set()
        _recovered_task_ids = already  # type: ignore[assignment]

    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Task).where(
                Task.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING])
            )
        )
        stuck_tasks = result.scalars().all()

        if not stuck_tasks:
            return

        logger.info(f"[task_service] 发现 {len(stuck_tasks)} 个中断任务，开始恢复...")

        for task in stuck_tasks:
            # P0-13 修复：同一 task 进程内只恢复一次
            if task.id in already:
                logger.info(f"[task_service] 任务 {task.id} 已在恢复集合内，跳过（幂等保护）")
                continue
            already.add(task.id)

            # 查询该任务的 Photo 记录，重建 photo_infos
            photos_result = await db.execute(
                select(Photo).where(Photo.task_id == task.id).order_by(Photo.order_index)
            )
            photos = photos_result.scalars().all()

            if not photos:
                logger.warning(f"[task_service] 任务 {task.id} 无关联照片，跳过恢复")
                task.status = TaskStatus.FAILED
                task.error_msg = "恢复时未找到关联照片"
                await db.commit()
                continue

            # 解析精修风格
            styles = []
            if task.retouch_style:
                styles = [s.strip() for s in task.retouch_style.split(",") if s.strip()]
            if not styles:
                styles = ["auto"]

            photo_infos = [
                PhotoInfo(
                    photo_id=str(p.id),
                    original_url=p.original_url,
                    order_index=p.order_index,
                )
                for p in photos
            ]

            # 重新启动后台协程（不 await，让它跑着）
            asyncio.create_task(
                _run_ai_pipeline_background(task.id, photo_infos, styles, task.location)
            )
            logger.info(f"[task_service] 已恢复任务 {task.id} 的后台流水线（{len(photos)} 张照片）")


async def create_task(
    db: AsyncSession,
    user: User,
    photo_urls: list[str],
    retouch_styles: list[str] | None = None,
    location: str | None = None,
) -> Task:
    """创建处理任务

    1. 创建 Task 记录
    2. 为每张 photo_url 创建 Photo 记录
    3. 生成 Mock 处理结果存入 extra_params
    """
    styles = retouch_styles or ["auto"]

    # P0-05 修复：先扣额度（拒绝 = 不创建 task）→ 再 AI 处理 → 失败回滚
    # 旧顺序：先创建 task + 启动 background，再扣额度 → AI 失败也白扣
    # 新顺序：先 consume_quota_for_task 决定是否放行，再创建 task
    from app.services.pack_service import (
        QuotaExhaustedError,
        consume_quota_for_task,
        release_quota_for_failed_task,
    )
    try:
        quota_reason = await consume_quota_for_task(db, user)
    except QuotaExhaustedError as e:
        # 额度不足：不创建 task，直接抛业务错误
        logger.info(f"[task_service] 额度不足拒绝创建 task user_id={user.id} reason={e}")
        raise

    task = Task(
        user_id=user.id,
        task_type="photo_process",
        status=TaskStatus.PENDING,
        location=location,
        retouch_style=",".join(styles),
        total_count=len(photo_urls),
        processed_count=0,
        progress=0,
        quota_reason=quota_reason,
    )
    db.add(task)
    await db.flush()


    # 创建 Photo 记录
    photos: list[Photo] = []
    # 根据用户等级设置图片过期时间
    expire_at = _calc_photo_expire_at(user)
    for i, url in enumerate(photo_urls):
        photo = Photo(
            user_id=user.id,
            task_id=task.id,
            original_url=url,
            original_size=0,
            status="uploaded",
            order_index=i,
            expire_at=expire_at,
        )
        db.add(photo)
        photos.append(photo)
    await db.flush()

    # 把已上传的 COS 对象设为临时公开，否则美图/前端无法下载原图（默认 ACL 私有会 403）
    from app.services import photo_service
    for photo in photos:
        if settings.COS_SECRET_ID:
            await photo_service.set_object_public(photo.original_url)

    # P1-13 修复：设公开后做匿名 HEAD 校验，等 ACL 传播生效再启动筛选。
    # COS put_object_acl 存在最终一致性延迟，新上传对象在 ACL 设置完成后的
    # 短窗口内仍可能对匿名请求返回 403，导致腾讯云 IAI / 美图拉图失败。
    # 这里用「匿名 HEAD」校验每张图是否真正公开可读，最多重试 3 次，每次间隔 1s。
    if settings.COS_SECRET_ID:
        not_public: list[str] = []
        for _attempt in range(3):
            not_public = []
            for photo in photos:
                ok = await asyncio.to_thread(
                    photo_service.is_object_public, photo.original_url
                )
                if not ok:
                    not_public.append(photo.original_url)
            if not not_public:
                break
            logger.warning(
                f"[task_service] ACL 未生效（attempt={_attempt+1}），"
                f"{len(not_public)} 张图匿名 HEAD 失败，1s 后重试"
            )
            if _attempt < 2:
                await asyncio.sleep(1.0)
        if not_public:
            logger.warning(
                f"[task_service] 仍有 {len(not_public)} 张图 ACL 未公开，"
                f"筛选阶段可能 403（已尽力重试，继续执行依赖预签名兜底）: "
                f"{not_public[0][:80]}..."
            )


    # 生成 AI 处理结果
    if _use_real_retouch():
        # 真实美图精修：异步回调耗时较长，放到后台执行，create_task 立即返回
        task.status = TaskStatus.PROCESSING
        task.progress = 10
        photo_infos = [
            PhotoInfo(
                photo_id=str(p.id),
                original_url=p.original_url,
                order_index=p.order_index,
            )
            for p in photos
        ]
        # 先提交，保证 task / photo 落库，后台协程用自己的 session 才能查到
        await db.commit()
        asyncio.create_task(
            _run_ai_pipeline_background(task.id, photo_infos, styles, location)
        )
    else:
        # Mock 模式：同步生成结果（含 mock_retouch 标记，便于对比 UI 调试）
        try:
            ai_result = await _generate_ai_result(photos, styles, location)
            task.extra_params = json.dumps(ai_result, ensure_ascii=False)
        except Exception as e:
            # P0-06 修复：mock 模式 AI 失败也回滚额度
            logger.error(f"[task_service] mock AI pipeline 失败: {e}")
            task.extra_params = json.dumps(
                {
                    "total_photos": len(photos),
                    "total_groups": 0,
                    "selected_photos": [],
                    "groups": [],
                },
                ensure_ascii=False,
            )
            await release_quota_for_failed_task(db, user, quota_reason)
            task.quota_reason = "refunded"

    return task


async def get_task_status(db: AsyncSession, task_id: int, user: User) -> dict:
    """查询任务状态

    Mock 模式下基于创建时间自动推进状态：
    - 0-1s:  uploading (10%)
    - 1-3s:  screening (10%→40%)
    - 3-5s:  retouching (40%→90%)
    - 5s+:   completed (100%)
    """
    task = (
        await db.execute(
            select(Task).where(Task.id == task_id, Task.user_id == user.id)
        )
    ).scalar_one_or_none()

    if not task:
        raise ValueError("任务不存在")

    now = _now_ts()
    # SQLite 不保留时区信息，需统一视为 UTC
    if task.created_at.tzinfo is None:
        created_ts = task.created_at.replace(tzinfo=timezone.utc).timestamp()
    else:
        created_ts = task.created_at.timestamp()
    elapsed = now - created_ts

    if (
        not _use_real_retouch()
        and settings.ENABLE_MOCK_MODE
        and task.status != TaskStatus.FAILED
    ):
        if elapsed < _STAGE_UPLOADING:
            stage, progress, status = "uploading", 10, "processing"
        elif elapsed < _STAGE_UPLOADING + _STAGE_SCREENING:
            stage, progress, status = "screening", int(10 + 30 * (elapsed - _STAGE_UPLOADING) / _STAGE_SCREENING), "processing"
        elif elapsed < _TOTAL_MOCK_TIME:
            stage, progress, status = "retouching", int(40 + 50 * (elapsed - _STAGE_UPLOADING - _STAGE_SCREENING) / _STAGE_RETOUCHING), "processing"
        else:
            stage, progress, status = "completed", 100, "completed"
            # 更新数据库状态
            if task.status != TaskStatus.COMPLETED:
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.processed_count = task.total_count
                task.finished_at = datetime.now(timezone.utc)
                await db.flush()
    else:
        # 真实精修：以数据库里后台流水线写入的状态为准
        status = task.status.value
        progress = task.progress
        if status == "pending":
            stage = "uploading"
        elif status == "processing":
            stage = "retouching"
        elif status == "completed":
            stage = "completed"
        else:
            stage = "uploading"

    remaining = max(0, int(_TOTAL_MOCK_TIME - elapsed)) if status == "processing" and not _use_real_retouch() else 0

    # 逐张状态：查询该任务下所有 Photo，按 order_index 排序，供前端「先好先显示」
    photos_out = []
    try:
        from app.models.photo import Photo as _Photo

        photo_rows = (
            await db.execute(
                select(_Photo)
                .where(_Photo.task_id == task.id)
                .order_by(_Photo.order_index.asc())
            )
        ).scalars().all()
        for ph in photo_rows:
            purl = ph.processed_url or ""
            # Photo.status 合法值：uploaded|processing|done|failed。
            # 美图回调成功会把 status 写成 "done"（meitu_pro._update_photo_and_task），
            # 失败降级写成 "failed"。前端只认 completed/failed 终态，其它一律当 processing。
            # P1-17 修复：若此处只白名单 "completed"，"done" 会被误判为 processing，
            # 导致照片已精修完成、页面却一直显示「处理中」。统一把 done 也映射为 completed。
            _db_status = ph.status or "processing"
            _api_status = (
                "completed" if _db_status in ("completed", "done")
                else "failed" if _db_status == "failed"
                else "processing"
            )
            photos_out.append({
                "photo_id": str(ph.id),
                "original_url": ph.original_url,
                "processed_url": purl or None,
                "thumbnail_url": ph.thumb_url,
                "status": _api_status,
                "order_index": ph.order_index,
                "is_retouch_failed": bool(purl) and "_retouch_failed" in purl,
            })
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[get_task_status] 查询逐张照片状态失败: {e}")

    return {
        "task_id": str(task.id),
        "status": status,
        "progress": progress,
        "current_stage": stage,
        "estimated_remaining_time": remaining,
        "processed_photos": task.processed_count if status == "completed" else int(task.total_count * progress / 100),
        "total_photos": task.total_count,
        "photos": photos_out,
    }


async def get_task_result(db: AsyncSession, task_id: int, user: User) -> dict:
    """获取任务处理结果"""
    task = (
        await db.execute(
            select(Task).where(Task.id == task_id, Task.user_id == user.id)
        )
    ).scalar_one_or_none()

    if not task:
        raise ValueError("任务不存在")

    created_at_str = task.created_at.strftime("%Y-%m-%dT%H:%M:%S") if task.created_at else ""

    # 从 extra_params 读取 Mock 结果
    if task.extra_params:
        result = json.loads(task.extra_params)

        # P1 修复：聚类去重导致 selected_photos < total_photos（如 5 张上传只筛出 3 张去精修），
        # 未入选的 Photo 不会出现在 selected_photos 里，导致结果页"几张成功/几张失败"对不上总数。
        # 这里从 Photo 表读回全部 Photo 行，未入选的补成 status='skipped' 项，
        # 前端可显示原图 + "未入选"角标，让用户看到 task 的全部照片。
        selected_photos = list(result.get("selected_photos", []))
        selected_photo_ids = {str(p.get("photo_id")) for p in selected_photos}

        try:
            from app.models.photo import Photo
            from sqlalchemy import select as _sa_select

            all_photos = (
                await db.execute(
                    _sa_select(Photo)
                    .where(Photo.task_id == task.id)
                    .order_by(Photo.order_index)
                )
            ).scalars().all()

            for p in all_photos:
                pid = str(p.id)
                if pid in selected_photo_ids:
                    continue
                # 未入选：补一个 skipped 项，前端显示原图 + 角标
                # P0 修复：Photo 表里未入选照片的 quality_score/face_count/cluster_id 可能为 NULL，
                # 必须做 None 兜底，否则 TaskResultOut schema 校验会 500（quality_score: float
                # 不允许 None；type: str 不允许 None）。
                _qg_raw = p.quality_score
                try:
                    _qg_score = float(_qg_raw) if _qg_raw is not None else 0.0
                except (TypeError, ValueError):
                    _qg_score = 0.0
                _cg_raw = p.cluster_id
                # cluster_id 在 DB 是字符串（如 'g0'/'None'/数字），统一转 int；无法转则 None
                _cg_id: int | None
                if _cg_raw is None or _cg_raw == "" or _cg_raw == "None":
                    _cg_id = None
                else:
                    try:
                        _cg_id = int(_cg_raw)
                    except (TypeError, ValueError):
                        _cg_id = None
                selected_photos.append({
                    "photo_id": pid,
                    "original_url": p.original_url,
                    "processed_url": p.original_url,
                    "thumbnail_url": p.thumb_url or p.original_url,
                    "quality_score": _qg_score,
                    "face_count": int(p.face_count) if p.face_count is not None else 0,
                    "type": "portrait",   # 与 _to_dict 输出一致；schema type: str 不接受 None
                    "retouch_style": None,
                    "retouch_style_label": None,
                    "caption": None,
                    "cluster_group_id": _cg_id,
                    "rank_in_group": None,
                    "category": None,
                    "status": "skipped",  # 关键：未入选标记，前端据此显示"未入选"角标
                })
        except Exception as _e:
            logger.warning(f"[task_service] 补齐未入选照片失败 task_id={task.id}: {_e}")

        # 检查图片是否已过期
        is_expired = _is_task_expired(task, user)

        return {
            "task_id": str(task.id),
            "status": "completed",
            "total_photos": result.get("total_photos", task.total_count),
            "total_groups": result.get("total_groups", 0),
            "selected_photos": selected_photos,
            "groups": result.get("groups", []),
            "created_at": created_at_str,
            "is_expired": is_expired,
        }

    # 无 Mock 结果时返回空壳
    return {
        "task_id": str(task.id),
        "status": task.status.value,
        "total_photos": task.total_count,
        "total_groups": 0,
        "selected_photos": [],
        "groups": [],
        "created_at": created_at_str,
    }


async def get_task_history(
    db: AsyncSession, user: User, page: int = 1, page_size: int = 20
) -> dict:
    """获取用户任务历史"""
    offset = (page - 1) * page_size

    total = (
        await db.execute(
            select(func.count(Task.id)).where(Task.user_id == user.id)
        )
    ).scalar() or 0

    tasks = (
        await db.execute(
            select(Task)
            .where(Task.user_id == user.id)
            .order_by(desc(Task.created_at))
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()

    items = []
    for t in tasks:
        thumbnail = None
        if t.extra_params:
            try:
                result = json.loads(t.extra_params)
                if result.get("selected_photos"):
                    thumbnail = result["selected_photos"][0].get("thumbnail_url")
            except (json.JSONDecodeError, KeyError, IndexError):
                pass

        items.append({
            "task_id": str(t.id),
            "status": t.status.value,
            "total_photos": t.total_count,
            "total_groups": 0,
            "created_at": t.created_at.strftime("%Y-%m-%dT%H:%M:%S") if t.created_at else "",
            "thumbnail_url": thumbnail,
        })

    return {"total": total, "list": items}
