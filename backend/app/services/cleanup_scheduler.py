"""精修图自动清理调度器

业务规则（PRD 2026-07-19）：
- 所有精修过的照片统一保留 3 天（不分 VIP 等级）
- 第 3 天的北京时间 24:00（UTC 16:00）触发清理
- 清理目标：COS 上 ``processed/{YYYYMMDD}/`` 整个目录及其中所有 key
- 同步清 DB：把 Photo.processed_url 命中已删 key 的行置 None（保留 status=done 等业务事实）

实现：
- 启动时先跑一次（兜底：服务停机期间可能漏删过期目录）
- 之后每 24h 跑一次（北京 24:00 触发）
- 失败也不死循环（异常 try/except + 日志）

时区说明：
- meitu_pro 写入时用 ``datetime.now(timezone.utc).strftime("%Y%m%d")`` 按 UTC 日期分目录
- 本清理也按 UTC 日期解析对比，与写入端保持一致，零误差
- 触发时间用北京时区算"下个北京 24:00"，符合业务语义
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.photo import Photo
from app.services.photo_service import _get_cos_client, extract_object_key

settings = get_settings()
_BJ_TZ = ZoneInfo("Asia/Shanghai")
_RETENTION_DAYS = 3
_LIST_PAGE_SIZE = 1000
_DELETE_BATCH_SIZE = 1000  # COS delete_objects 单批上限


# ============== 结构化追踪日志 ==============

def _trace(event: str, **fields) -> None:
    """[CLEANUP-DEBUG] 前缀结构化日志。"""
    parts = [f"event={event}"]
    for k, v in fields.items():
        if v is None:
            parts.append(f"{k}=None")
        elif isinstance(v, float):
            parts.append(f"{k}={v:.2f}")
        else:
            s = str(v)
            if len(s) > 200 and not k.endswith("url"):
                s = s[:200] + "..."
            parts.append(f"{k}={s}")
    logger.info(f"[CLEANUP-DEBUG] {' '.join(parts)}")


# ============== 同步 COS 工具（包到 asyncio.to_thread） ==============

def _list_processed_keys_sync() -> list[str]:
    """列出 COS processed/ 前缀下所有 key（自动分页）。"""
    client = _get_cos_client()
    if client is None:
        _trace("list_skipped", reason="cos_client_unavailable")
        return []
    keys: list[str] = []
    marker = ""
    pages = 0
    while True:
        kwargs = {
            "Bucket": settings.COS_BUCKET,
            "Prefix": "processed/",
            "MaxKeys": _LIST_PAGE_SIZE,
        }
        if marker:
            kwargs["Marker"] = marker
        resp = client.list_objects(**kwargs)
        for item in (resp.get("Contents") or []):
            key = item.get("Key", "")
            if key and not key.endswith("/"):  # 跳过目录占位
                keys.append(key)
        pages += 1
        if not resp.get("IsTruncated"):
            break
        marker = resp.get("NextMarker", "")
        if not marker:
            break
    _trace("list_paginated", total_keys=len(keys), pages=pages)
    return keys


def _delete_keys_sync(keys: list[str]) -> int:
    """批量删除 key，返回成功删除数。失败的单批不影响其他批。"""
    if not keys:
        return 0
    client = _get_cos_client()
    if client is None:
        _trace("delete_skipped", reason="cos_client_unavailable")
        return 0
    success = 0
    for i in range(0, len(keys), _DELETE_BATCH_SIZE):
        batch = keys[i:i + _DELETE_BATCH_SIZE]
        try:
            client.delete_objects(
                Bucket=settings.COS_BUCKET,
                Delete={"Object": [{"Key": k} for k in batch], "Quiet": "true"},
            )
            success += len(batch)
        except Exception as e:
            _trace("delete_batch_failed", batch_size=len(batch),
                   error_type=type(e).__name__, error=str(e)[:200])
    return success


# ============== 核心清理逻辑 ==============

_DATE_RE = re.compile(r"^processed/(\d{8})/")


def _parse_dir_date(key: str) -> Optional[str]:
    """从 ``processed/20260718/161.jpg`` 解析出 ``20260718``。"""
    m = _DATE_RE.match(key)
    return m.group(1) if m else None


async def cleanup_expired_retouch() -> dict:
    """执行一次过期精修图清理，返回统计 dict。

    Returns: { scanned, deleted_dirs, deleted_keys, db_cleared }
    """
    now_utc = datetime.now(timezone.utc)
    now_bj = now_utc.astimezone(_BJ_TZ)
    # 距今 ≥ 7 天的目录（即 7 天前的目录）都视为过期
    cutoff_utc_date = (now_utc - timedelta(days=_RETENTION_DAYS)).strftime("%Y%m%d")
    _trace("cleanup_start", now_utc=now_utc.isoformat(),
           now_bj=now_bj.strftime("%Y-%m-%d %H:%M:%S"),
           retention_days=_RETENTION_DAYS,
           cutoff_utc_date=cutoff_utc_date)

    # 1. 列出所有 processed/* key
    keys = await asyncio.to_thread(_list_processed_keys_sync)
    if not keys:
        _trace("cleanup_no_keys", hint="processed/ 下没有任何文件")
        return {"scanned": 0, "deleted_dirs": 0, "deleted_keys": 0, "db_cleared": 0}

    # 2. 按 YYYYMMDD 目录分组
    by_dir: dict[str, list[str]] = {}
    unparsed: list[str] = []
    for k in keys:
        d = _parse_dir_date(k)
        if d:
            by_dir.setdefault(d, []).append(k)
        else:
            unparsed.append(k)
    _trace("group_done", n_dirs=len(by_dir), unparsed=len(unparsed),
           dir_list=sorted(by_dir.keys()))

    # 3. 找出过期的目录
    expired_dirs = {d: ks for d, ks in by_dir.items() if d < cutoff_utc_date}
    _trace("expired_dirs", n_expired=len(expired_dirs),
           dirs=sorted(expired_dirs.keys()),
           cutoff=cutoff_utc_date)

    if not expired_dirs:
        return {"scanned": len(keys), "deleted_dirs": 0, "deleted_keys": 0, "db_cleared": 0}

    # 4. 删 COS
    keys_to_delete = [k for ks in expired_dirs.values() for k in ks]
    _trace("cos_delete_start", n_keys=len(keys_to_delete),
           sample=keys_to_delete[:3])
    deleted_count = await asyncio.to_thread(_delete_keys_sync, keys_to_delete)
    _trace("cos_delete_done", requested=len(keys_to_delete), deleted=deleted_count)

    # 5. 同步清 DB：把命中已删 key 的 Photo.processed_url 置 None
    db_cleared = 0
    if deleted_count > 0:
        deleted_set = set(keys_to_delete)
        async with AsyncSessionLocal() as s:
            rows = (await s.execute(
                select(Photo).where(Photo.processed_url.is_not(None))
            )).scalars().all()
            for p in rows:
                pk = extract_object_key(p.processed_url) if p.processed_url else None
                if pk and pk in deleted_set:
                    p.processed_url = None
                    db_cleared += 1
            await s.commit()
        _trace("db_cleanup_done", cleared=db_cleared)

    return {
        "scanned": len(keys),
        "deleted_dirs": len(expired_dirs),
        "deleted_keys": deleted_count,
        "db_cleared": db_cleared,
    }


# ============== 调度循环 ==============

async def _seconds_until_next_bj_midnight() -> float:
    """距离下个北京时间 24:00 还有多少秒。"""
    now_bj = datetime.now(timezone.utc).astimezone(_BJ_TZ)
    next_midnight_bj = (now_bj + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1.0, (next_midnight_bj - now_bj).total_seconds())


async def run_loop() -> None:
    """清理调度循环：启动跑一次，之后每北京 24:00 跑一次。异常不会死循环。"""
    _trace("scheduler_start")

    # 启动时先跑一次（兜底：服务停机期间可能漏删过期目录）
    try:
        stats = await cleanup_expired_retouch()
        _trace("scheduler_initial_done", **stats)
    except Exception as e:
        _trace("scheduler_initial_failed",
               error_type=type(e).__name__, error=str(e)[:300])

    while True:
        wait_s = await _seconds_until_next_bj_midnight()
        _trace("scheduler_sleep", wait_seconds=f"{wait_s:.0f}")
        await asyncio.sleep(wait_s)
        try:
            stats = await cleanup_expired_retouch()
            _trace("scheduler_tick_done", **stats)
        except Exception as e:
            _trace("scheduler_tick_failed",
                   error_type=type(e).__name__, error=str(e)[:300])
            # 失败也继续循环，不让 scheduler 死掉
