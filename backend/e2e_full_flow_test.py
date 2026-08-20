#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""途吖 - 完整业务流程端到端测试脚本

覆盖用户从「上传照片」一直到「生成朋友圈文案」的全链路，逐阶段打印进度并校验：

  1. [健康检查]  GET  /api/v1/health
  2. [上传照片]  presign -> COS PUT -> confirm（可多张）
  3. [创建任务]  POST /api/v1/tasks（筛选去重 + 分类路由 + 美图精修）
  4. [等待完成]  轮询 GET /api/v1/tasks/{id}/status 直到 completed
  5. [获取结果]  GET  /api/v1/tasks/{id}/result（精选照片 + processed_url）
  6. [生成朋友圈] POST /api/v1/captions/generate（用精修图 URL 出多风格文案）

用法:
  # 默认用 backend 目录自带的两张测试图跑完整流程（无需额外准备照片）
  python e2e_full_flow_test.py

  # 用指定文件夹的照片（例如桌面「测试照片」）
  python e2e_full_flow_test.py --folder "C:/Users/xxx/Desktop/测试照片" --limit 6

  # 指定文案风格（1~2 个）与地点
  python e2e_full_flow_test.py --styles literary,checkin --location "西湖"

  # 非 mock 模式需带 JWT
  python e2e_full_flow_test.py --token <JWT>

前提:
  1. 后端已在运行（uvicorn app.main:app，建议单 worker）
  2. mock 模式(ENABLE_MOCK_MODE=true) 免鉴权；否则需 --token
  3. 若配置了 MEITU_API_KEY + MEITU_MEDIA_CODE 且花生壳隧道可用，走真实精修；
     否则精修降级为原图，脚本会明确提示「未走真实精修」。

说明:
  纯 HTTP 客户端，不 import 后端代码，可独立于后端进程运行。
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.stderr.write("缺少依赖 httpx，请先: pip install httpx\n")
    sys.exit(2)

# Windows 控制台尽量 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VALID_STYLES = {"literary", "humor", "minimal", "emotional", "checkin"}


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def section(title: str) -> None:
    print("", flush=True)
    log("=" * 60)
    log(title)
    log("=" * 60)


def _data(r) -> dict | list:
    """解包统一响应 {code, message, data}；无 data 字段时退回顶层 JSON"""
    try:
        j = r.json()
    except Exception:
        return {}
    if isinstance(j, dict) and "data" in j:
        return j["data"]
    return j


def _load_env() -> dict:
    """轻量读取 backend/.env（不依赖 python-dotenv）"""
    env: dict = {}
    p = Path(__file__).resolve().parent / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _resolve_images(folder: str | None, limit: int) -> list[Path]:
    """决定测试照片来源：优先 --folder；否则用 backend 自带的 _cmp_orig*.jpg"""
    here = Path(__file__).resolve().parent
    if folder:
        p = Path(folder)
        if not p.exists():
            raise SystemExit(f"照片文件夹不存在: {folder}")
        files = sorted(f for f in p.glob("*") if f.is_file() and f.suffix.lower() in IMG_EXT)
        if not files:
            raise SystemExit(f"文件夹内未找到图片（支持 {sorted(IMG_EXT)}）: {folder}")
    else:
        files = sorted(here.glob("_cmp_orig*.jpg"))
        if not files:
            raise SystemExit(
                "未指定 --folder，且 backend 目录未找到自带测试图 _cmp_orig*.jpg，"
                "请用 --folder 指定照片文件夹。"
            )
    if limit and limit > 0:
        files = files[:limit]
    return files


async def _health_check(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get("/api/v1/health")
        if r.status_code == 200:
            log(f"后端健康检查 OK: {_data(r)}")
            return True
        log(f"后端健康检查异常 status={r.status_code} body={r.text[:200]}")
        return False
    except Exception as e:  # noqa: BLE001
        log(f"无法连接后端: {e}")
        return False


async def _upload_one(client: httpx.AsyncClient, img: Path) -> str:
    """单张上传：presign -> COS PUT -> confirm，返回可访问的原图 URL"""
    suffix = img.suffix or ".jpg"
    ts = int(datetime.now().timestamp() * 1000)
    object_key = f"uploads/e2e_full/{ts}/{img.stem}{suffix}"

    r = await client.post("/api/v1/photos/presign", json={"object_key": object_key})
    if r.status_code != 200:
        raise SystemExit(f"presign 失败 status={r.status_code} body={r.text[:300]}")
    presign = _data(r)
    presigned_url = presign["presigned_url"]
    access_url = presign["access_url"]

    data = img.read_bytes()
    put_r = await client.put(
        presigned_url, content=data, headers={"Content-Type": "image/jpeg"}, timeout=120
    )
    if put_r.status_code not in (200, 201):
        raise SystemExit(f"COS PUT 失败 status={put_r.status_code} body={put_r.text[:300]}")

    confirm_r = await client.post(
        "/api/v1/photos/confirm",
        json={
            "file_id": f"e2e_{ts}",
            "url": access_url,
            "size": len(data),
            "width": None,
            "height": None,
        },
    )
    if confirm_r.status_code != 200:
        raise SystemExit(f"confirm 失败 status={confirm_r.status_code} body={confirm_r.text[:300]}")
    cdata = _data(confirm_r)
    log(f"  [上传OK] {img.name} ({len(data)} bytes) -> photo_id={cdata.get('photo_id')}")
    return cdata.get("url", access_url)


async def _upload_photos(client: httpx.AsyncClient, images: list[Path]) -> list[str]:
    urls: list[str] = []
    for img in images:
        urls.append(await _upload_one(client, img))
    return urls


async def _create_task(client: httpx.AsyncClient, photo_urls: list[str], location: str | None) -> str:
    r = await client.post(
        "/api/v1/tasks",
        json={
            "photo_urls": photo_urls,
            "options": {"retouch_styles": ["auto"], "location": location},
        },
    )
    if r.status_code == 401:
        raise SystemExit(
            "401 未授权：当前非 mock 模式，请加 --token <JWT>，"
            "或在 .env 设置 ENABLE_MOCK_MODE=true 后重启后端"
        )
    if r.status_code == 402:
        raise SystemExit(f"402 额度已用完: {r.text[:200]}")
    if r.status_code != 200:
        raise SystemExit(f"create_task 失败 status={r.status_code} body={r.text[:400]}")
    task_id = _data(r)["task_id"]
    log(f"  任务创建成功 task_id={task_id}")
    return task_id


async def _wait_until_done(
    client: httpx.AsyncClient, task_id: str, timeout: float, poll_interval: float
) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    last_key = None
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/v1/tasks/{task_id}/status")
        if r.status_code != 200:
            log(f"  状态查询异常 status={r.status_code} body={r.text[:200]}")
            await asyncio.sleep(poll_interval)
            continue
        st = _data(r)
        key = (st.get("status"), st.get("current_stage"), st.get("progress"))
        if key != last_key:
            log(
                f"  status={st.get('status')} progress={st.get('progress')}% "
                f"stage={st.get('current_stage')} "
                f"processed={st.get('processed_photos')}/{st.get('total_photos')}"
            )
            last_key = key
        if st.get("status") == "completed":
            log("  任务 completed")
            return st
        if st.get("status") == "failed":
            rr = await client.get(f"/api/v1/tasks/{task_id}/result")
            err = _data(rr) if rr.status_code == 200 else {}
            raise SystemExit(f"  任务 failed: {json.dumps(err, ensure_ascii=False)[:400]}")
        await asyncio.sleep(poll_interval)
    raise SystemExit(f"  超时（{int(timeout)}s）仍未 completed，请检查后端/花生壳/美图回调")


async def _fetch_result(client: httpx.AsyncClient, task_id: str) -> dict:
    r = await client.get(f"/api/v1/tasks/{task_id}/result")
    if r.status_code != 200:
        raise SystemExit(f"获取结果失败 status={r.status_code} body={r.text[:400]}")
    return _data(r)


def _report_result(result: dict) -> tuple[list[str], bool]:
    """打印精修结果，返回 (用于生成文案的精修图URL列表, 精修是否全部真实生成)"""
    total_photos = result.get("total_photos", 0)
    total_groups = result.get("total_groups", 0)
    selected = result.get("selected_photos", []) or []
    log(f"  输入 {total_photos} 张 -> 聚类 {total_groups} 组 -> 精选 {len(selected)} 张")

    processed_urls: list[str] = []
    all_ok = len(selected) > 0
    for i, ph in enumerate(selected, 1):
        processed = ph.get("processed_url", "") or ""
        original = ph.get("original_url", "") or ""
        category = ph.get("category") or ph.get("type") or "?"
        use_url = processed or original
        if use_url:
            processed_urls.append(use_url)
        if not processed:
            log(f"    [FAIL] 精选#{i} processed_url 为空 category={category}")
            all_ok = False
        elif "_retouch_failed=" in processed:
            log(f"    [FAIL] 精选#{i} 精修失败(降级标记) category={category}: {processed[:80]}")
            all_ok = False
        elif processed == original:
            log(f"    [WARN] 精选#{i} 精修图==原图(可能 mock 降级) category={category}")
            all_ok = False
        else:
            log(f"    [OK]   精选#{i} category={category} 精修图: {processed[:80]}")
    return processed_urls, all_ok


async def _generate_captions(
    client: httpx.AsyncClient,
    photo_urls: list[str],
    styles: list[str],
    location: str | None,
    count: int,
) -> list[dict]:
    r = await client.post(
        "/api/v1/captions/generate",
        json={
            "photo_urls": photo_urls[:9],
            "location": location,
            "styles": styles[:2],
            "count": count,
        },
    )
    if r.status_code != 200:
        raise SystemExit(f"生成朋友圈文案失败 status={r.status_code} body={r.text[:400]}")
    groups = _data(r)
    if not isinstance(groups, list):
        raise SystemExit(f"文案返回格式异常: {str(groups)[:300]}")
    return groups


def _report_captions(groups: list[dict]) -> bool:
    ok = False
    for g in groups:
        emoji = g.get("emoji", "")
        label = g.get("style_label") or g.get("style")
        caps = g.get("captions", []) or []
        log(f"  【{emoji} {label}】共 {len(caps)} 条:")
        for j, c in enumerate(caps, 1):
            text = c.get("text", "")
            if text.strip():
                ok = True
            log(f"    {j}. {text}")
    return ok


async def main_async(args) -> int:
    env = _load_env()
    real_retouch = bool(env.get("MEITU_API_KEY") and env.get("MEITU_MEDIA_CODE"))
    base = (args.base_url or "http://127.0.0.1:8000").rstrip("/")

    styles = [s.strip() for s in (args.styles or "literary,checkin").split(",") if s.strip()]
    styles = [s for s in styles if s in VALID_STYLES] or ["literary"]

    section("完整业务流程 E2E 测试：上传 -> 精修 -> 生成朋友圈")
    log(f"后端地址: {base}")
    log(f"真实美图精修: {'是' if real_retouch else '否（走 mock，精修=原图）'}")
    log(f"CALLBACK_BASE_URL: {env.get('CALLBACK_BASE_URL', '(未配置)')}")
    log(f"文案风格: {styles}  地点: {args.location or '(无)'}")

    images = _resolve_images(args.folder, args.limit)
    log(f"照片来源: {'文件夹 ' + args.folder if args.folder else 'backend 自带测试图'}（{len(images)} 张）")

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    result_summary = {"ok": False, "note": ""}
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=180) as client:
        # ---- 1. 健康检查 ----
        section("阶段 1/6  健康检查")
        if not await _health_check(client):
            log("后端不可达，请先启动后端。")
            return 1

        # ---- 2. 上传照片 ----
        section("阶段 2/6  上传照片（presign -> COS PUT -> confirm）")
        photo_urls = await _upload_photos(client, images)
        log(f"  共上传 {len(photo_urls)} 张原图")

        # ---- 3. 创建任务 ----
        section("阶段 3/6  创建处理任务（筛选去重 + 分类路由 + 美图精修）")
        task_id = await _create_task(client, photo_urls, args.location)

        # ---- 4. 等待完成 ----
        section("阶段 4/6  等待任务完成（轮询状态）")
        timeout = max(args.timeout, 60 + len(images) * 30)
        await _wait_until_done(client, task_id, timeout, args.poll_interval)

        # ---- 5. 获取结果 ----
        section("阶段 5/6  获取处理结果")
        result = await _fetch_result(client, task_id)
        processed_urls, retouch_ok = _report_result(result)
        if not processed_urls:
            log("  [FAIL] 无可用精选照片 URL，终止后续文案生成")
            result_summary["note"] = "no_selected_photos"
            _final_summary(result_summary, real_retouch, task_id)
            return 1

        # ---- 6. 生成朋友圈文案 ----
        section("阶段 6/6  生成朋友圈文案（多风格）")
        groups = await _generate_captions(
            client, processed_urls, styles, args.location, args.count
        )
        caption_ok = _report_captions(groups)

        result_summary["ok"] = retouch_ok and caption_ok
        result_summary["note"] = (
            "success"
            if result_summary["ok"]
            else f"retouch_ok={retouch_ok} caption_ok={caption_ok}"
        )
        _final_summary(result_summary, real_retouch, task_id)

    return 0 if result_summary["ok"] else 1


def _final_summary(summary: dict, real_retouch: bool, task_id: str) -> None:
    section("测试汇总")
    log(f"task_id: {task_id}")
    log(f"真实美图精修: {'是' if real_retouch else '否（走 mock）'}")
    log(f"链路闭环: {'成功' if summary['ok'] else '失败'}  note={summary['note']}")
    if summary["ok"]:
        log("结论: 完整业务流程闭环成功——上传 -> 筛选精修 -> 生成朋友圈文案全部通过。")
    else:
        log("结论: 存在失败项，请检查上方各阶段输出与后端日志。")
        if not real_retouch:
            log("提示: 未配置美图密钥或走 mock，精修图为原图属正常降级。")


def main() -> int:
    parser = argparse.ArgumentParser(description="途吖 完整业务流程 E2E 测试（上传->精修->朋友圈）")
    parser.add_argument("--folder", default=None, help="测试照片文件夹（默认用 backend 自带测试图）")
    parser.add_argument("--limit", type=int, default=0, help="仅取前 N 张（默认 0=全部）")
    parser.add_argument("--base-url", default=None, help="后端基地址，默认 http://127.0.0.1:8000")
    parser.add_argument("--token", default=None, help="JWT token（非 mock 模式必填）")
    parser.add_argument(
        "--styles", default="literary,checkin",
        help="文案风格(逗号分隔,1~2个): literary,humor,minimal,emotional,checkin",
    )
    parser.add_argument("--location", default=None, help="拍摄地点（用于文案，如：西湖）")
    parser.add_argument("--count", type=int, default=3, help="每风格文案条数(1~3)，默认3")
    parser.add_argument("--timeout", type=float, default=700.0, help="等待完成最长秒数，默认700（美图处理可达5分钟）")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="轮询间隔秒数，默认5")
    args = parser.parse_args()

    try:
        return asyncio.run(main_async(args))
    except SystemExit as e:
        code = e.code
        if isinstance(code, int):
            return code
        log(str(code))
        return 1
    except KeyboardInterrupt:
        log("被用户中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
