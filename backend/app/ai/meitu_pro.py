"""美图云修 Pro 版精修 Provider

对应 PRD FR-301~310 智能精修

调用流程（异步回调 + 进程内等待）：
1. 提交精修任务 → POST /openapi/chain.json（repost_url 带 photo_id）
2. retouch 注册一个 asyncio.Future 并等待（不立即返回原图）
3. 美图处理完成 → 回调 /api/v1/photos/meitu-callback?photo_id=xxx
4. 后端下载精修图 → 转存到自己的 COS → 回写 DB → resolve Future
5. retouch 拿到真实精修图 URL 后返回，流水线把真地址写进任务结果

说明：进程内 Future 仅在单进程（单 worker）下生效；多 worker 部署需换成 Redis Pub/Sub。

文档：https://meitu.feishu.cn/wiki/SbGawSE15ihYLTk91DWcLxJ2npf
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import RetouchResult, RetoucherProvider, SelectedPhoto
from app.core.config import get_settings
from app.models.photo import Photo
from app.models.task import Task
from app.services.photo_service import upload_to_cos

settings = get_settings()
logger = logging.getLogger(__name__)

# 美图云修 Pro API 基础信息
_MEITU_API_URL = settings.MEITU_API_URL or "https://openapi-yunxiu.meitu.com/openapi/chain.json"

# 等待美图回调的超时时间（秒）。超时则标记精修失败，避免流水线卡死。
# 实测美图云修 Pro 处理耗时可达 3~5 分钟，调大到 600 避免过早降级。
_CALLBACK_TIMEOUT = 600

# photo_id(str) -> Future[cos_url]：retouch 提交后在此等待，回调到达时 resolve
_pending_futures: dict[str, asyncio.Future[str]] = {}

# 结果查询（轮询兜底）候选端点。
# 美图云修 Pro 文档确认接口为异步，结果可通过「回调」或「结果查询」获取，
# 但未在公开片段给出查询接口地址。这里按 openapi-yunxiu.meitu.com 的命名规律
# 穷举若干候选；MEITU_QUERY_URL（.env 可配）优先级最高。
# 轮询不依赖公网回调隧道，是「隧道抖动/未运行」场景下仍能拿到精修图的关键兜底。
# P1-16 修复：实测 /openapi/query.json 才能真正返回结果，
# 而 chain_query.json / result.json 稳定返回 HTTP 400（端点不存在/不支持）。
# 把有效的 query.json 放最前，无效端点降权，避免每次轮询都撞 400 刷屏。
_CANDIDATE_QUERY_URLS = (
    "https://openapi-yunxiu.meitu.com/openapi/query.json",
    "https://openapi-yunxiu.meitu.com/openapi/chain/query.json",
    "https://openapi-yunxiu.meitu.com/openapi/chain_query.json",
    "https://openapi-yunxiu.meitu.com/openapi/result.json",
)

# 回调/查询结果里「精修图 URL」常见字段名（不同版本/接口可能不同）
_URL_CANDIDATE_KEYS = (
    # 美图结果查询接口（/openapi/query.json）返回的真实字段
    "after_url", "after_url_backup",
    # 美图回调（repost_url）返回字段（历史抓包格式）
    "media_data", "media_data_backup", "url", "result_url", "image_url",
    "pic_url", "pic", "output", "output_url", "oss_url", "img_url",
    "image", "result", "processed_url", "download_url",
)

# URL 字段名的「关键字提示」，用于递归兜底扫描时判断某字符串是不是图片地址
_URL_KEY_HINTS = ("url", "pic", "image", "media", "output", "result", "oss", "img", "download")


# ====================== 美图精修深度追踪日志 ======================
# 用法：grep "\[MEITU-DEBUG\]" 后端日志，再按 photo_id 过滤，即可看到
# 单张照片从「选预设 → 提交美图 → 等待回调 → 下载精修图 → COS 转存」全链路。
# 之前截断 media_code 到 8 位 + 缺少体积/时延是「精修效果与预设不符」无法定位的根因。
def _mask(v: str | None, keep: int = 4) -> str:
    """脱敏显示凭据字段，仅保留前 keep 位 + 总长度"""
    if not v:
        return "<EMPTY>"
    return f"{v[:keep]}***{len(v) - keep}" if len(v) > keep else "***"


def _trace(photo_id, event: str, **fields) -> None:
    """结构化追踪日志（前缀 [MEITU-DEBUG]）"""
    parts = [f"photo_id={photo_id}", f"event={event}"]
    for k, v in fields.items():
        if v is None:
            parts.append(f"{k}=None")
        elif isinstance(v, float):
            parts.append(f"{k}={v:.2f}")
        else:
            s = str(v)
            # 长字段截断避免日志爆炸
            if len(s) > 200 and not k.endswith("url"):
                s = s[:200] + "..."
            parts.append(f"{k}={s}")
    logger.info(f"[MEITU-DEBUG] {' '.join(parts)}")


def _take_future(photo_id: str) -> asyncio.Future[str] | None:
    """取出并移除待处理的 Future"""
    return _pending_futures.pop(photo_id, None)


def _fail_future(photo_id: str | None, reason: str) -> None:
    """回调/轮询拿到明确失败（或无可用 URL）时，立即以异常唤醒等待中的
    retouch 协程，避免其傻等 300s 超时。

    异常会被 pipeline._retouch_one 捕获，转为「精修失败（降级原图）」，
    不再把用户卡在 processing 24 分钟。
    """
    if not photo_id:
        return
    fut = _pending_futures.pop(photo_id, None)
    if fut is not None and not fut.done():
        fut.set_exception(RuntimeError(f"meitu_retouch_failed: {reason}"))
        _trace(photo_id, "future_failed_fast", reason=reason)


def _scan_urls(obj, depth: int = 0):
    """递归扫描任意嵌套结构里的「图片 URL 字符串」。

    兜底用：某些版本回调把精修图地址放在 data.result / data.list[0] 等
    非顶层字段，顶层候选键扫不到时用它捞出来。最多 3 层避免爆栈。
    """
    if depth > 3 or not isinstance(obj, (dict, list)):
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("http") and any(
                h in str(k).lower() for h in _URL_KEY_HINTS
            ):
                return v
            if isinstance(v, (dict, list)):
                r = _scan_urls(v, depth + 1)
                if r:
                    return r
    else:
        for item in obj:
            r = _scan_urls(item, depth + 1)
            if r:
                return r
    return None


def _mark_retouch_failed(original_url: str, reason: str) -> str:
    """标记精修失败的 URL（追加失败标记，前端可据此显示降级提示）

    COS 会忽略未知 query 参数，所以图片仍能正常加载（显示原图），
    但 URL 带有 ?_retouch_failed=xxx 标记，前端可以检测到并给出提示。
    """
    sep = "&" if "?" in original_url else "?"
    return f"{original_url}{sep}_retouch_failed={reason}"


class MeituProRetoucher(RetoucherProvider):
    """美图云修 Pro 版精修

    提交后通过进程内 Future 等待回调，拿到真实精修图地址再返回，
    这样流水线才能把真正的精修图写进任务结果。
    """

    async def retouch(self, photo: SelectedPhoto) -> RetouchResult:
        """提交单张照片到美图云修 Pro，并等待回调返回精修图地址

        P1 修复：回调阶段收到美图网关 90024 GATEWAY_QPS_LIMIT 限流时，
        退避 60/120s 后整张图重新提交一次。提交阶段（submit）的限流重试
        退避只有 1/2/4/8s 不够覆盖美图网关的冷却时间（实测约 30-60s）。
        现在外层包一层整图重试，覆盖「提交+回调」全链路的限流场景。
        """
        if not settings.MEITU_API_KEY or not settings.MEITU_MEDIA_CODE:
            logger.warning("[meitu_pro] 未配置 API Key 或 media_code，跳过精修")
            return RetouchResult(
                photo_id=photo.photo_id,
                processed_url=photo.processed_url,
                success=True,
            )

        # P1 修复：90024 限流自动重试（整图级别）。
        # 第一次直接执行；后续重试退避 60s/120s 后重新提交。
        # 只对 90024/429/GATEWAY_QPS_LIMIT 等限流类错误重试，其它错误立即返回。
        _BACKOFFS = [60, 120]
        _RATE_LIMIT_HINTS = ("90024", "GATEWAY_QPS_LIMIT", "429")
        for round_idx, backoff in enumerate([-1] + _BACKOFFS):
            if backoff > 0:
                logger.warning(
                    f"[meitu_pro] photo={photo.photo_id} 上一轮收到美图限流，"
                    f"{backoff}s 后整图重试（round={round_idx}/3）"
                )
                _trace(photo.photo_id, "callback_90024_retry",
                       round=round_idx, backoff_s=backoff)
                await asyncio.sleep(backoff)
            result = await self._retouch_once(photo)
            if result.success:
                return result
            err = str(result.error or "")
            # 仅对限流码继续重试，其它错误立即返回
            if not any(hint in err for hint in _RATE_LIMIT_HINTS):
                return result
            # 已达到最后一轮也直接返回（不无限重试）
            if round_idx >= len(_BACKOFFS):
                logger.error(
                    f"[meitu_pro] photo={photo.photo_id} 限流重试 {len(_BACKOFFS)} 轮仍失败，"
                    f"放弃重试 err={err[:200]}"
                )
                return result
        return result

    async def _retouch_once(self, photo: SelectedPhoto) -> RetouchResult:
        """单轮 retouch 提交+等待回调（不含外层重试）"""
        callback_url = _build_callback_url(photo.photo_id)
        # 根据 photo.category 选对应的人物预设 media_code
        # 兜底：未分类 / 未配置对应预设 → 使用 MEITU_MEDIA_CODE 默认值
        media_code = settings.get_meitu_media_code_for_category(photo.category)
        # 精修效果与预设不符时，【此处】可一眼看出「选错预设」或「API key 不是你以为的那个」
        _trace(
            photo.photo_id, "retouch_start",
            category=photo.category,
            media_code=media_code,           # 完整预设 ID（之前 [:8] 截断无法核对）
            preset_source=(
                f"MEITU_MEDIA_CODE_{photo.category.upper()}"
                if photo.category in {"man", "woman", "child", "elderly", "group"}
                else "FALLBACK_MEITU_MEDIA_CODE"
            ),
            callback_url=callback_url,
            original_url=photo.original_url,
            api_key=_mask(settings.MEITU_API_KEY),
            api_secret=_mask(settings.MEITU_API_SECRET),
        )
        logger.info(
            f"[meitu_pro] 开始精修 photo={photo.photo_id} category={photo.category} "
            f"media_code={media_code} callback={callback_url}"
        )
        logger.info(f"[meitu_pro] 原图URL: {photo.original_url[:100]}...")

        # 注册等待回调的 Future
        # P0-08 修复：二次提交覆盖问题
        # - 旧逻辑：直接 dict[photo_id] = fut，覆盖前一个未完成的 future
        #   → 前一个 retouch 协程永远得不到结果（set_result 不到旧的）
        # - 新逻辑：若已有未完成的 future，把旧的 cancel 掉再覆盖
        loop = asyncio.get_event_loop()
        old_fut = _pending_futures.get(photo.photo_id)
        if old_fut is not None and not old_fut.done():
            old_fut.cancel()
            _trace(photo.photo_id, "pending_future_replaced",
                   note="前一次 retouch 的 future 被覆盖（疑似重复提交）")
        fut: asyncio.Future[str] = loop.create_future()
        _pending_futures[photo.photo_id] = fut

        # 构建请求体
        # P1-11 修复：把 photo_id 加回 repost_url 的 query 参数。
        # 原因：之前依赖美图自动透传 X-Meitu-Photo-Id header，但美图默认不会
        # 主动添加任何自定义 header → 回调到达时 sig_prefix= 空 + 拿不到 photo_id
        # → 全部回调签名校验失败 + 无法关联照片，6 张只能靠轮询兜底救回 1 张。
        # 现在重新带 photo_id query（美图会原样回传），回调路由同时兼容 header 与 query。
        # P1-13 修复：media_data 改用预签名 GET URL。
        # 之前直接传 photo.original_url（私有桶裸 URL），美图网关拉取时 403 → 90002。
        # 预签名 URL 无论对象 ACL 是私有还是公开都可读，消除时序竞态。
        media_data_url = _presigned_media_url(photo.original_url, expired=600)
        payload = {
            "api_key": settings.MEITU_API_KEY,
            "api_secret": settings.MEITU_API_SECRET,
            "repost_url": callback_url,
            "media_code": media_code,
            "media_data": media_data_url,
        }

        try:
            t_submit_start = time.monotonic()
            async with httpx.AsyncClient(timeout=30) as client:
                # 提交前 HEAD 原图拿 content-length；用于事后比对「精修前/后体积比」
                # P1-13：裸 URL 可能因 ACL 未公开 403，回退用预签名 URL 再 HEAD。
                original_size_bytes: int | None = None
                try:
                    head = await client.head(photo.original_url, timeout=10)
                    if head.status_code < 400:
                        cl = head.headers.get("content-length")
                        if cl and cl.isdigit():
                            original_size_bytes = int(cl)
                    else:
                        head = await client.head(media_data_url, timeout=10)
                        if head.status_code < 400:
                            cl = head.headers.get("content-length")
                            if cl and cl.isdigit():
                                original_size_bytes = int(cl)
                except Exception as head_err:
                    _trace(photo.photo_id, "original_head_failed", error=str(head_err)[:200])

                masked_payload = {
                    **payload,
                    "api_key": _mask(payload.get("api_key")),
                    "api_secret": _mask(payload.get("api_secret")),
                }
                _trace(photo.photo_id, "submit_start",
                       api_url=_MEITU_API_URL,
                       media_code=media_code,
                       media_data_url=photo.original_url,
                       repost_url=callback_url,
                       original_size_bytes=original_size_bytes,
                       payload=json.dumps(masked_payload, ensure_ascii=False),
                )

                result: dict = {}
                # 限流感知重试：并行提交（并发=5）时美图网关可能返回
                # 90024 GATEWAY_QPS_LIMIT 等限流码。此处退避重试，避免单张
                # 因瞬时限流直接失败降级。最多重试 4 次，退避 1/2/4/8s。
                _RETRY_CODES = {90024, 429001, 429, "GATEWAY_QPS_LIMIT"}
                for attempt in range(5):
                    resp = await client.post(
                        _MEITU_API_URL,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    submit_ms = (time.monotonic() - t_submit_start) * 1000
                    try:
                        result = resp.json()
                    except Exception as parse_err:
                        result = {"_parse_error": str(parse_err), "_raw": resp.text[:500]}
                    _trace(photo.photo_id, "submit_done",
                           http_status=resp.status_code,
                           attempt=attempt,
                           submit_ms=f"{submit_ms:.0f}",
                           response_size_bytes=len(resp.content),
                           result_code=result.get("code"),
                           result_reqid=result.get("reqid"),
                           result_msg=result.get("msg"),
                    )
                    if result.get("code") == 0:
                        break
                    # 仅对可重试的限流码退避重试，其它错误码直接失败
                    if result.get("code") not in _RETRY_CODES and not (
                        isinstance(result.get("msg"), str)
                        and "QPS" in result.get("msg", "").upper()
                    ):
                        break
                    wait = 2 ** attempt
                    logger.warning(
                        f"[meitu_pro] 提交限流(attempt={attempt}) photo={photo.photo_id} "
                        f"code={result.get('code')} msg={result.get('msg')}，{wait}s 后重试"
                    )
                    await asyncio.sleep(wait)

            logger.info(f"[meitu_pro] API 响应: {json.dumps(result, ensure_ascii=False)}")

            if result.get("code") != 0:
                logger.error(f"[meitu_pro] 任务提交失败: code={result.get('code')} msg={result.get('msg', result)}")
                _take_future(photo.photo_id)
                return RetouchResult(
                    photo_id=photo.photo_id,
                    processed_url=_mark_retouch_failed(photo.original_url, f"meitu_code_{result.get('code')}"),
                    success=False,
                    error=f"meitu_submit_failed code={result.get('code')}",
                )

            reqid = result.get("reqid", "?")
            chain_id = (result.get("data") or {}).get("chain_id")
            logger.info(
                f"[meitu_pro] 任务提交成功 photo={photo.photo_id} reqid={reqid} chain_id={chain_id}，开始等待回调（超时{_CALLBACK_TIMEOUT}s）..."
            )
            _trace(photo.photo_id, "wait_start", reqid=reqid, timeout_s=_CALLBACK_TIMEOUT)

            # 启动结果查询轮询兜底：与回调竞速，任一先拿到精修图即闭环。
            # P1-1 修复：保存 task 句柄，wait 成功时立即 cancel 避免无谓 30 次 RPC
            # 回调成功会移除 future，轮询发现 future 已空即自动放弃，无副作用。
            poll_task = asyncio.create_task(_poll_meitu_result(photo.photo_id, reqid, chain_id))

            # 等待美图回调把真实精修图地址 resolve 进 Future
            t_wait_start = time.monotonic()
            try:
                cos_url = await asyncio.wait_for(fut, timeout=_CALLBACK_TIMEOUT)
                wait_ms = (time.monotonic() - t_wait_start) * 1000
                _trace(photo.photo_id, "wait_done",
                       reqid=reqid, wait_ms=f"{wait_ms:.0f}", cos_url=cos_url)
                logger.info(f"[meitu_pro] [OK] 精修完成 photo={photo.photo_id} cos_url={cos_url}")
                # P1-1 修复：wait 成功时立即取消轮询任务，避免后续 ~30 次无谓 RPC
                if not poll_task.done():
                    poll_task.cancel()
                return RetouchResult(
                    photo_id=photo.photo_id,
                    processed_url=cos_url,
                    success=True,
                )
            except asyncio.TimeoutError:
                wait_ms = (time.monotonic() - t_wait_start) * 1000
                _trace(photo.photo_id, "wait_timeout",
                       reqid=reqid, wait_ms=f"{wait_ms:.0f}",
                       hint="花生壳/CALLBACK_BASE_URL 未达 or 美图处理极慢 or 回调格式不匹配")
                logger.error(
                    f"[meitu_pro] [FAIL] 等待回调超时 photo={photo.photo_id} "
                    f"（已等{_CALLBACK_TIMEOUT}s，reqid={reqid}）。"
                    f"可能原因：1)花生壳未运行/未映射 2)美图处理极慢 3)回调格式不匹配"
                )
                _take_future(photo.photo_id)
                return RetouchResult(
                    photo_id=photo.photo_id,
                    processed_url=_mark_retouch_failed(photo.original_url, "callback_timeout"),
                    success=False,
                    error="callback_timeout",
                )
        except Exception as e:
            _trace(photo.photo_id, "retouch_exception", error_type=type(e).__name__, error=str(e)[:200])
            logger.exception(f"[meitu_pro] [FAIL] 调用异常 photo={photo.photo_id}: {e}")
            _take_future(photo.photo_id)
            return RetouchResult(
                photo_id=photo.photo_id,
                processed_url=_mark_retouch_failed(photo.original_url, str(e)[:50]),
                success=False,
                error=str(e),
            )


def _build_callback_url(photo_id: str) -> str:
    """构建美图回调 URL

    美图处理完成后会 POST 到此 URL。
    通过 query 参数带上 photo_id，方便回调时回写 Photo.processed_url 与任务结果。
    本地开发用内网穿透（花生壳/ngrok）获取公网域名。
    生产环境用实际公网域名。
    """
    base_url = settings.CALLBACK_BASE_URL or "https://your-domain.com"
    return f"{base_url}/api/v1/photos/meitu-callback?photo_id={photo_id}"


def _presigned_media_url(original_url: str, expired: int = 600) -> str:
    """返回提交给美图的 media_data URL。

    P1-13 修复过程说明（重要）：
    - 初版：直接传 photo.original_url（私有桶裸 URL），美图拉取 403 → 90002。
    - 二版：改用 owner 密钥预签名 GET URL，但实测美图网关 *不认* 预签名格式
      （回调仍 90002 GATEWAY_AUTHORIZED_ERROR），而 7 天前用裸公开 URL 是成功的。
    - 终版（本实现）：对象已在 create_task 阶段 set_object_public 并做匿名 HEAD
      校验（task_service 方案 A），public-read 已生效。因此 media_data 直接传
      **裸公开 URL** 即可，美图能正常拉取。预签名反而引入格式不兼容问题，弃用。

    Args:
        original_url: 原图 COS 公网 URL（此时应已是 public-read）

    Returns:
        裸公开 URL（与输入相同）
    """
    _trace(None, "media_data_presigned",
           original_url=original_url[:100],
           note="直接使用 public-read 裸 URL（方案A已设公开+校验），不预签名")
    return original_url


async def _push_photo_done(db: AsyncSession, photo: "Photo", cos_url: str) -> None:
    """单张精修完成 → 通过 WebSocket 向前端推送（带完整结果）。

    在所有入队路径（回调 / 轮询兜底）统一回写 DB 后调用。
    若此时该 task 全部被挑选出的照片都已 done，则再推一条 task_completed 总信号。
    """
    if not photo.task_id:
        return
    task_id = str(photo.task_id)
    # 轻量取 style（优先 extra_params 里的 selected_photos/ groups）
    retouch_style = ""
    retouch_style_label = ""
    try:
        task = (
            await db.execute(select(Task).where(Task.id == photo.task_id))
        ).scalar_one_or_none()
        if task and task.extra_params:
            extra = json.loads(task.extra_params)
            for p in extra.get("selected_photos", []):
                if str(p.get("photo_id")) == str(photo.id):
                    retouch_style = p.get("retouch_style", "") or ""
                    retouch_style_label = p.get("retouch_style_label", "") or ""
                    break
            if not retouch_style:
                for g in extra.get("groups", []):
                    for p in g.get("photos", []):
                        if str(p.get("photo_id")) == str(photo.id):
                            retouch_style = p.get("retouch_style", "") or ""
                            retouch_style_label = p.get("retouch_style_label", "") or ""
                            break
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[meitu_pro] 取 retouch_style 失败(忽略): {e}")

    photo_done_payload = {
        "type": "photo_done",
        "task_id": task_id,
        "photo_id": str(photo.id),
        "status": "completed",
        "original_url": photo.original_url,
        "processed_url": cos_url,
        "thumbnail_url": photo.thumb_url or cos_url,
        "retouch_style": retouch_style,
        "retouch_style_label": retouch_style_label,
    }
    try:
        from app.api.ws_manager import ws_manager

        await ws_manager.send_to_task(task_id, photo_done_payload)
        logger.info(f"[meitu_pro] [WS] 已推送 photo_done task_id={task_id} photo_id={photo.id}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[meitu_pro] [WS] 推送 photo_done 失败 task_id={task_id}: {e}")

    # 检测全任务完成：统计该 task 下所有 photo 是否都已 done/failed
    try:
        from app.api.ws_manager import ws_manager as _wm
        rows = (
            await db.execute(select(Photo).where(Photo.task_id == photo.task_id))
        ).scalars().all()
        if rows:
            all_done = all(str(r.status) in ("done", "failed") for r in rows)
            if all_done and _wm.has_subscriber(task_id):
                photos_out = []
                for r in rows:
                    photos_out.append({
                        "photo_id": str(r.id),
                        "status": "completed" if str(r.status) == "done" else "failed",
                        "original_url": r.original_url,
                        "processed_url": r.processed_url or None,
                        "thumbnail_url": r.thumb_url,
                    })
                await _wm.send_to_task(task_id, {
                    "type": "task_completed",
                    "task_id": task_id,
                    "total": len(rows),
                    "done": sum(1 for r in rows if str(r.status) == "done"),
                    "photos": photos_out,
                })
                logger.info(f"[meitu_pro] [WS] 已推送 task_completed task_id={task_id} total={len(rows)}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[meitu_pro] [WS] 检测/推送 task_completed 失败 task_id={task_id}: {e}")


async def _update_photo_and_task(
    db: AsyncSession,
    photo_id: int,
    cos_url: str,
) -> None:
    """美图回调成功后回写数据库

    - 更新 Photo.processed_url 与 status
    - 更新所属 Task 的 extra_params 中对应照片的 processed_url
      （这样 get_task_result 返回的才是精修图地址）
    - 回写后通过 WebSocket 推送单张完成事件 + 必要时推送总任务完成信号
    """
    photo = (
        await db.execute(select(Photo).where(Photo.id == photo_id))
    ).scalar_one_or_none()
    if not photo:
        logger.warning(f"[meitu_pro] 回调找不到 photo_id={photo_id}，跳过回写")
        return

    photo.processed_url = cos_url
    photo.status = "done"
    db.add(photo)

    if photo.task_id:
        task = (
            await db.execute(select(Task).where(Task.id == photo.task_id))
        ).scalar_one_or_none()
        if task and task.extra_params:
            try:
                extra = json.loads(task.extra_params)
                updated = False
                for p in extra.get("selected_photos", []):
                    if str(p.get("photo_id")) == str(photo_id):
                        p["processed_url"] = cos_url
                        p["thumbnail_url"] = cos_url
                        updated = True
                for g in extra.get("groups", []):
                    for p in g.get("photos", []):
                        if str(p.get("photo_id")) == str(photo_id):
                            p["processed_url"] = cos_url
                            p["thumbnail_url"] = cos_url
                            updated = True
                if updated:
                    task.extra_params = json.dumps(extra, ensure_ascii=False)
                    db.add(task)
                    logger.info(f"[meitu_pro] 已更新 task_id={task.id} 中 photo_id={photo_id} 的精修图地址")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"[meitu_pro] 更新 task extra_params 失败: {e}")

    await db.commit()

    # P1-17 续：回写成功后立即推送实时进度（单张完成 + 总完成）
    try:
        await _push_photo_done(db, photo, cos_url)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[meitu_pro] 推送完成事件异常(忽略): {e}")


async def _extract_processed_url(payload: dict) -> str | None:
    """从回调/查询结果的多变结构中提取精修图 URL（兼容格式变化）。

    美图云修 Pro 接口在不同版本/文档下字段名不一致（已发现顶层 media_data、
    data.media_data、chain_id 等）。这里做三层兜底：
      1. 顶层候选键（media_data/url/result_url/image_url/...）
      2. data 子对象候选键
      3. 递归扫描任意嵌套结构里的 http 图片地址
    任一命中即返回，避免「格式一变就判无 URL → 静默降级原图」。
    """
    if not isinstance(payload, dict):
        return None
    # 1) 顶层候选键
    for k in _URL_CANDIDATE_KEYS:
        v = payload.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    # 2) data 子对象候选键
    data = payload.get("data")
    if isinstance(data, dict):
        for k in _URL_CANDIDATE_KEYS:
            v = data.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
    # 3) 递归兜底
    return _scan_urls(payload)


async def _store_and_resolve(photo_id: str | None, processed_url: str) -> dict:
    """下载精修图 → 转存 COS → 回写 DB → resolve 等待中的 Future

    回调路径与轮询兜底路径共用，确保无论精修结果从哪个通道到达，
    都能一致地完成「存储 + 唤醒流水线」。

    返回 {"success": bool, "processed_url": str}
    """
    # 下载精修图
    t_dl = time.monotonic()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(processed_url)
        resp.raise_for_status()
        image_data = resp.content
    download_ms = (time.monotonic() - t_dl) * 1000
    output_size_bytes = len(image_data)
    _trace(photo_id, "download_done",
           processed_url=processed_url,
           output_size_bytes=output_size_bytes,
           download_ms=f"{download_ms:.0f}")

    # 转存到 COS（用 photo_id 作文件名，确保每个 photo 的精修图唯一）
    # 注意：之前用 reqid 导致同一任务多张图都被覆盖为 unknown.jpg；
    # photo_id（回调 query / 提交关联）一定存在，更稳定。
    safe_photo_id = str(photo_id) if photo_id else f"ts_{int(datetime.now(timezone.utc).timestamp())}"
    object_key = f"processed/{datetime.now(timezone.utc).strftime('%Y%m%d')}/{safe_photo_id}.jpg"
    t_up = time.monotonic()
    cos_url = await upload_to_cos(object_key, image_data, "image/jpeg")
    upload_ms = (time.monotonic() - t_up) * 1000
    _trace(photo_id, "cos_upload_done",
           object_key=object_key, cos_url=cos_url,
           upload_size_bytes=output_size_bytes, upload_ms=f"{upload_ms:.0f}")

    # 【关键】精修效果与预期不符时看这里：input/output 体积比能直接判断
    # 美图是否真的处理过（ratio≈1.0 通常意味着原图未处理或预设未生效）。
    # 通过 Photo.original_url 反查原图体积，HEAD 一次。
    _trace(photo_id, "summary_block_start", output_size_bytes=output_size_bytes)
    input_size_bytes: int | None = None
    try:
        # 这里取的是 SelectedPhoto 的 original_url（已上传 COS），需要从 DB 取
        from app.db.session import AsyncSessionLocal
        from app.models.photo import Photo as PhotoModel
        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(PhotoModel).where(PhotoModel.id == int(photo_id)))).scalar_one_or_none()
            _trace(photo_id, "summary_db_lookup", found=row is not None)
            if row and row.original_url:
                async with httpx.AsyncClient(timeout=10) as cli:
                    head = await cli.head(row.original_url)
                    _trace(photo_id, "summary_head_done",
                           status=head.status_code, has_cl=bool(head.headers.get("content-length")))
                    if head.status_code < 400:
                        cl = head.headers.get("content-length")
                        if cl and cl.isdigit():
                            input_size_bytes = int(cl)
    except Exception as e:
        _trace(photo_id, "input_size_lookup_failed",
               error_type=type(e).__name__, error=str(e)[:200])

    _trace(photo_id, "summary_block_end", input_size_bytes=input_size_bytes)

    _trace(photo_id, "summary_before_if", will_take_if=bool(input_size_bytes and input_size_bytes > 0))
    if input_size_bytes and input_size_bytes > 0:
        ratio = output_size_bytes / input_size_bytes
        verdict = (
            "yes_processed" if abs(ratio - 1.0) > 0.05
            else "near_original"
        )
        _trace(photo_id, "retouch_summary",
               input_size_bytes=input_size_bytes,
               output_size_bytes=output_size_bytes,
               size_ratio=f"{ratio:.3f}",
               verdict=verdict,
               cos_url=cos_url)
        logger.info(
            f"[meitu_pro] [SUMMARY] photo_id={photo_id} "
            f"input={input_size_bytes}B output={output_size_bytes}B ratio={ratio:.3f} -> {verdict}"
        )
    else:
        _trace(photo_id, "retouch_summary",
               output_size_bytes=output_size_bytes,
               input_size_bytes="<unknown>",
               cos_url=cos_url)
    _trace(photo_id, "summary_after_if")

    logger.info(f"[meitu_pro] 精修图转存成功: {cos_url} (photo_id={safe_photo_id})")

    # 注意：精修完成后【不再】立即删除原图。
    # 原图需保留到用户「对比查看」并「下载精修图」之后，
    # 由 /api/v1/photos/{photo_id}/download 在确认下载时再清理。

    # 回写数据库：Photo.processed_url + Task.extra_params
    # 回调路径会传入 db；轮询兜底路径自己开 session（回调未达时 DB 也得写）。
    if photo_id:
        try:
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as s:
                await _update_photo_and_task(s, int(photo_id), cos_url)
        except Exception as e:
            logger.error(f"[meitu_pro] 回写精修图地址失败 photo_id={photo_id}: {e}")

    # 唤醒正在等待的 retouch 协程（回调已取到则 future 已被取走，这里自然跳过）
    # 若此前已被 _fail_future 以异常唤醒（回调格式异常），则不再重复 set_result
    fut = _take_future(photo_id)
    if fut is not None and not fut.done():
        fut.set_result(cos_url)

    return {"success": True, "processed_url": cos_url}


async def process_meitu_callback(
    callback_data: dict,
    photo_id: str | None = None,
    db: AsyncSession | None = None,
) -> dict:
    """处理美图云修回调

    美图处理完成后会 POST 回调数据到此函数。
    回调数据包含精修后的图片 URL。

    设计原则（修复"照片没变化"根因）：
    - 回调一旦到达，默认当作「成功提交的结果」处理；仅当出现明确失败信号
      （error_code 非 0 / status 含 fail）才判失败。
    - 无论成功与否，都立即 resolve/fail 等待中的 Future，绝不让 retouch
      傻等 300s 超时（旧逻辑：格式一变就 early-return 且不唤醒 → 全量降级原图）。
    - 回调到达但提取不到 URL 时，全量打印 payload，便于定位美图格式变化。

    返回：{"success": bool, "processed_url": str}
    """
    logger.info(f"[meitu_pro] [CALLBACK] 收到回调 photo_id={photo_id}")
    logger.info(f"[meitu_pro] 回调原始数据: {json.dumps(callback_data, ensure_ascii=False)}")
    _trace(photo_id, "callback_received",
           data_keys=list(callback_data.keys()),
           data_bytes=len(json.dumps(callback_data, ensure_ascii=False)))

    # 解析回调数据
    # 美图云修 Pro 真实回调格式（已通过实际抓包确认）：
    # {
    #   "chain_id": "1870521483532615",
    #   "media_data": "https://oss-open-platform.meitudata.com/mtopen/...",
    #   "media_data_backup": "https://...（备用地址）",
    #   "status": "success",
    #   "error_code": 0,
    #   "error_msg": "success"
    # }
    # 注：美图文档（2025-07 更新）公共响应体字段为 code(int)/data，
    # 与旧抓包格式（error_code/media_data 顶层）并存。两种都兼容。

    # 1. 判定成功/失败（默认成功；仅明确失败信号才判失败）
    raw_code = callback_data.get("error_code")
    if raw_code is None:
        raw_code = callback_data.get("code")
    status_field = str(
        callback_data.get("status") or callback_data.get("error_msg") or ""
    ).lower()
    # P0-09 修复：异常值正确判定
    # - 旧逻辑：白名单只覆盖 "0"/"200"/"none"/""/"success"/"ok"/"done"
    #   → "0x0"/"0.0"/"00000"/"OK" 等异常字符串被当成"非 0"→ 判为失败
    #   但实际：这些字符串的语义模糊，不应单凭 string 等价就判失败
    # - 新逻辑：把异常字符串归一化（去前缀 0x/.0/全 0）后再判
    def _normalize_code(v) -> str:
        if v is None:
            return ""
        s = str(v).strip().lower()
        # 去 "0x" 前缀 / 尾部 ".0" / 全 0 数字
        if s.startswith("0x"):
            try:
                s = str(int(s, 16))
            except ValueError:
                pass
        # 末尾 ".0" 去掉（处理 "0.0"/"0.00" 等）
        while s.endswith(".0") and s != ".0":
            s = s[:-2]
        return s
    norm = _normalize_code(raw_code)
    is_explicit_failure = (
        isinstance(raw_code, (int, str))
        and norm not in ("", "0", "200", "none", "success", "ok", "done", "true")
    ) or ("fail" in status_field)
    if is_explicit_failure:
        _trace(photo_id, "callback_failed",
               error_code=raw_code,
               error_msg=callback_data.get("error_msg") or callback_data.get("msg"))
        logger.error(
            f"[meitu_pro] [FAIL] 回调明确失败 error_code={raw_code} full_data={callback_data}"
        )
        _fail_future(photo_id, f"callback_error_code_{raw_code}")
        return {"success": False, "error": f"meitu error code={raw_code}"}

    # 2. 提取精修图 URL（加宽兼容，见 _extract_processed_url）
    processed_url = await _extract_processed_url(callback_data)
    if not processed_url:
        # 回调已到达但提取不到 URL：全量打印 payload 便于定位格式变化，
        # 并立即 fail-fast 唤醒等待协程（避免傻等 300s 超时）。
        logger.error(
            f"[meitu_pro] [FAIL] 回调已到达但无精修图 URL，"
            f" full_data={json.dumps(callback_data, ensure_ascii=False)}"
        )
        _trace(photo_id, "callback_no_url",
               top_keys=list(callback_data.keys()),
               data_keys=(list(callback_data.get("data", {}).keys())
                          if isinstance(callback_data.get("data"), dict) else None))
        _fail_future(photo_id, "no_url_in_callback")
        return {"success": False, "error": "no processed url in callback"}

    _trace(photo_id, "callback_parsed",
           error_code=raw_code, processed_url=processed_url)
    logger.info(f"[meitu_pro] [OK] 回调校验通过，精修图URL: {processed_url[:100]}...")

    # 回调去重：花生壳抖动 + 美图重发场景下，同一 photo_id 会被回调多次。
    # 第一次回调成功时 _update_photo_and_task 已把 Photo.processed_url 写成真实 COS URL；
    # 第二次回调进来时只要发现已存在 processed_url，就直接复用并跳过下载/上传。
    if photo_id:
        try:
            from app.db.session import AsyncSessionLocal
            from app.models.photo import Photo as PhotoModel
            async with AsyncSessionLocal() as s:
                row = (await s.execute(
                    select(PhotoModel).where(PhotoModel.id == int(photo_id))
                )).scalar_one_or_none()
                if row and row.processed_url:
                    _trace(photo_id, "callback_duplicate_skipped",
                           existing_processed_url=row.processed_url[:120])
                    logger.info(
                        f"[meitu_pro] 回调去重 photo_id={photo_id} 已处理过 "
                        f"(processed_url 已存在)，跳过重复下载+上传"
                    )
                    return {
                        "success": True,
                        "processed_url": row.processed_url,
                        "dedup": True,
                    }
        except Exception as e:
            # 查不到/异常都不阻塞正常流程（容错：宁可重做也别漏做）
            _trace(photo_id, "callback_dedup_check_failed",
                   error_type=type(e).__name__, error=str(e)[:200])

    try:
        return await _store_and_resolve(photo_id, processed_url)
    except Exception as e:
        logger.error(f"[meitu_pro] 精修图转存失败: {e}")
        return {"success": False, "error": str(e)}


# ---------- 结果查询轮询兜底 ----------
# 回调是首选闭环通道；若回调因隧道抖动/字段不符未达，按 MEITU_QUERY_URL 轮询 reqid，
# 拿到结果即写入并唤醒流水线。轮询与回调竞速，先到先得，无副作用。
# P1-11 修复：首轮延迟从 10s 缩到 3s，更快命中。轮询间隔从 8s 缩到 5s，更激进的兜底。
_POLL_INTERVAL = 5          # 轮询间隔（秒）
_POLL_MAX_ATTEMPTS = 116    # 最多轮询次数（3+115*5s≈578s < 回调超时600s）
_POLL_INITIAL_DELAY = 3     # 首次轮询前的等待（给美图处理留时间）


async def _poll_meitu_result(photo_id: str, reqid: str, chain_id: str | None = None) -> None:
    """结果查询轮询兜底：不依赖公网回调隧道，直接从美图拉结果。

    回调是首选通道（需 花生壳/ngrok 隧道映射到本机），但隧道易抖动/未运行 →
    导致 callback_timeout 全量降级原图。轮询走美图服务器直连，是更稳的兜底。

    美图文档未公开查询接口地址，这里穷举若干候选端点（MEITU_QUERY_URL 优先），
    命中任一即写入并唤醒流水线；全部未命中则静默退出，最终仍由回调兜底。
    """
    if not reqid or reqid == "?":
        return
    # 候选端点：.env 配置的 MEITU_QUERY_URL 优先，其后内置若干命名规律猜测
    candidate_urls = []
    if settings.MEITU_QUERY_URL:
        candidate_urls.append(settings.MEITU_QUERY_URL)
    candidate_urls.extend([u for u in _CANDIDATE_QUERY_URLS if u not in candidate_urls])

    await asyncio.sleep(_POLL_INITIAL_DELAY)
    for attempt in range(1, _POLL_MAX_ATTEMPTS + 1):
        # 若回调已处理（future 已不存在），提前结束
        if _pending_futures.get(photo_id) is None:
            logger.info(f"[meitu_pro] 轮询兜底提前退出（回调已闭环）photo_id={photo_id}")
            return
        tried_urls: list[str] = []
        for query_url in candidate_urls:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    poll_payload = {
                        "api_key": settings.MEITU_API_KEY,
                        "api_secret": settings.MEITU_API_SECRET,
                        "reqid": reqid,
                    }
                    if chain_id:
                        # 美图 /openapi/query.json 需要 reqid + chain_id 才返回结果
                        poll_payload["chain_id"] = chain_id
                    resp = await client.post(
                        query_url,
                        json=poll_payload,
                        headers={"Content-Type": "application/json"},
                    )
                    tried_urls.append(query_url)
                    # P1-16 修复：无效端点稳定返回 400（端点不存在），属预期内，
                    # 用 debug 级静默跳过，避免每次轮询都刷 warning 噪音。
                    if resp.status_code != 200:
                        logger.debug(
                            f"[meitu_pro] 轮询兜底 {query_url} HTTP {resp.status_code}（端点不支持，跳过）"
                        )
                        continue
                    try:
                        data = resp.json()
                    except Exception:
                        logger.debug(f"[meitu_pro] 轮询兜底 {query_url} 响应非 JSON, 跳过")
                        continue
                    # P1-10 修复：data 非 dict 时不要 AttributeError 吞掉
                    # - 旧逻辑：data.get("code") 在 data=str/list/None 时抛 AttributeError
                    #   被外层 except 兜底成"无异常"，但实际是数据格式异常
                    # - 新逻辑：先 isinstance 检查，异常时打 WARNING + 继续
                    if not isinstance(data, dict):
                        logger.warning(
                            f"[meitu_pro] 轮询兜底 {query_url} 返回非 dict 数据: type={type(data).__name__} "
                            f"value={str(data)[:100]!r}"
                        )
                        continue
                # 兼容 code(int) / data.code / status 多种成功信号
                code = data.get("code")
                if code is None:
                    code = (data.get("data") or {}).get("code") if isinstance(data.get("data"), dict) else None
                status_field = str(data.get("status") or data.get("msg") or "").lower()
                is_done = (str(code) in ("0", "200") or "success" in status_field
                           or "done" in status_field)
                if not is_done:
                    continue
                url = await _extract_processed_url(data)
                if url:
                    _trace(photo_id, "poll_resolved",
                           attempt=attempt, processed_url=url, query_url=query_url)
                    logger.info(
                        f"[meitu_pro] 轮询兜底拿到结果 photo_id={photo_id} "
                        f"attempt={attempt} via {query_url}"
                    )
                    await _store_and_resolve(photo_id, url)
                    return
            except Exception as e:
                logger.debug(f"[meitu_pro] 轮询兜底 {query_url} 第{attempt}次异常（忽略）: {e}")
        # 本轮所有候选端点都未命中，记一条便于排查（不刷屏，用 debug）
        logger.debug(
            f"[meitu_pro] 轮询兜底第{attempt}次未命中（已试 {len(tried_urls)} 个端点）"
            f" photo_id={photo_id} reqid={reqid}"
        )
        await asyncio.sleep(_POLL_INTERVAL)
