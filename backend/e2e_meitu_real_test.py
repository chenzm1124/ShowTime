#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""途吖 - 美图云修 Pro 真机端到端批量链路测试脚本

从「测试照片」文件夹读取多张图片，逐张跑完整链路，验证整条链路真正闭环：
  准备照片 -> 创建任务(create_task) -> 后端提交美图 -> 美图回调/轮询兜底
  -> 精修图转存 COS -> 任务 completed -> 结果含真实 processed_url

用法:
  # 默认从桌面「测试照片」文件夹读取全部图片，逐张测试
  python e2e_meitu_real_test.py

  # 指定文件夹
  python e2e_meitu_real_test.py --folder "D:/我的照片/测试"

  # 只测前 3 张、递归子目录、自定义后端
  python e2e_meitu_real_test.py --limit 3 --recursive --base-url http://127.0.0.1:8000

  # 批量模式：把文件夹所有图放进【单个任务】，一次跑完
  # 同时验证「筛选去重 + 分类路由 + 真实精修」，最贴近真实用户一次上传几十张的用法
  python e2e_meitu_real_test.py --batch
  python e2e_meitu_real_test.py --batch --limit 14

  # 批量模式 + 注入重复图：每张图重复上传 N 次（模拟连拍/同场景），用于直观验证去重
  # 去重后仅对精选图精修，因此不会多消耗美图额度
  python e2e_meitu_real_test.py --batch --dup 2

  # 兼容旧的单图模式
  python e2e_meitu_real_test.py --image-url "https://xxx.cos.ap-xxx.myqcloud.com/xxx.jpg"
  python e2e_meitu_real_test.py --image-path "D:/photos/person.jpg"

前提:
  1. 后端已在运行（建议单 worker: uvicorn app.main:app --workers 1）
  2. 花生壳/ngrok 隧道已把 .env 的 CALLBACK_BASE_URL 映射到本机后端
     （美图回调会经公网隧道打回 /api/v1/photos/meitu-callback）
  3. .env 已配置 MEITU_API_KEY + MEITU_MEDIA_CODE（真实精修）；
     若未配置则走 mock，processed_url 会是原图，脚本会明确提示「未走真实精修」。

说明:
  - 脚本是纯 HTTP 客户端，不 import 后端代码，因此可独立于后端进程运行。
  - 逐张串行处理（单 worker 下最稳）；每张图会真实消耗一次美图额度 + 一次 trial 额度。
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.stderr.write("缺少依赖 httpx，请先: pip install httpx\n")
    sys.exit(2)

# 让 Windows 控制台尽量用 UTF-8 输出（避免 UnicodeEncodeError）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _data(r) -> dict:
    """解包统一响应 {code, message, data}；无 data 字段时退回顶层 JSON"""
    try:
        j = r.json()
    except Exception:
        return {}
    if isinstance(j, dict) and "data" in j:
        return j["data"]
    return j


def _load_env() -> dict:
    """轻量读取 backend/.env（不依赖 python-dotenv，避免额外依赖）"""
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


def _default_test_folder() -> str:
    """探测桌面「测试照片」文件夹（兼容英文 Desktop 与中文 桌面）"""
    home = Path.home()
    candidates = [
        home / "Desktop" / "测试照片",
        home / "桌面" / "测试照片",
        home / "Desktop" / "test_photos",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    # 默认返回英文路径（即便不存在，下面会报错提示）
    return str(home / "Desktop" / "测试照片")


def _scan_images(folder: str, limit: int, recursive: bool) -> list[Path]:
    p = Path(folder)
    if not p.exists():
        raise SystemExit(f"测试照片文件夹不存在: {folder}")
    it = p.rglob("*") if recursive else p.glob("*")
    files = sorted(f for f in it if f.is_file() and f.suffix.lower() in IMG_EXT)
    if not files:
        raise SystemExit(f"文件夹内未找到图片（支持 {sorted(IMG_EXT)}）: {folder}")
    if limit and limit > 0:
        files = files[:limit]
    return files


async def _health_check(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get("/api/v1/health")
        if r.status_code == 200:
            log(f"[准备] 后端健康检查 OK: {r.json()}")
            return True
        log(f"[准备] 后端健康检查异常 status={r.status_code} body={r.text[:200]}")
        return False
    except Exception as e:
        log(f"[准备] 无法连接后端: {e}")
        return False


async def _prepare_photo_url(
    client: httpx.AsyncClient,
    image_path: str | None,
    image_url: str | None,
) -> str:
    """准备用于建任务的原图 URL

    优先用 --image-url；否则用 --image-path 经 presign 直传 COS。
    """
    if image_url:
        log(f"  使用直接传入的图片 URL: {image_url[:80]}...")
        try:
            r = await client.head(image_url, timeout=20)
            if r.status_code >= 400:
                r = await client.get(image_url, headers={"Range": "bytes=0-0"}, timeout=20)
            ct = r.headers.get("content-type", "")
            log(f"  直接 URL 可访问: status={r.status_code} content-type={ct}")
        except Exception as e:
            log(f"  警告: 直接 URL 预检失败（美图可能仍可达）: {e}")
        return image_url

    p = Path(image_path)
    if not p.exists():
        raise SystemExit(f"本地图片不存在: {image_path}")

    suffix = p.suffix or ".jpg"
    object_key = f"uploads/e2e_test/{int(datetime.now().timestamp())}/{p.stem}{suffix}"
    log(f"  本地图片上传 COS: {image_path} -> {object_key}")

    r = await client.post("/api/v1/photos/presign", json={"object_key": object_key})
    if r.status_code != 200:
        raise SystemExit(f"presign 失败 status={r.status_code} body={r.text[:300]}")
    presign = _data(r)
    presigned_url = presign["presigned_url"]
    access_url = presign["access_url"]
    log(f"  presign OK, access_url={access_url[:80]}...")

    data = p.read_bytes()
    put_r = await client.put(
        presigned_url, content=data, headers={"Content-Type": "image/jpeg"}, timeout=60
    )
    if put_r.status_code not in (200, 201):
        raise SystemExit(f"COS PUT 失败 status={put_r.status_code} body={put_r.text[:300]}")
    log(f"  COS PUT OK (size={len(data)} bytes)")

    confirm_r = await client.post(
        "/api/v1/photos/confirm",
        json={
            "file_id": f"e2e_{int(datetime.now().timestamp())}",
            "url": access_url,
            "size": len(data),
            "width": None,
            "height": None,
        },
    )
    if confirm_r.status_code != 200:
        raise SystemExit(f"confirm 失败 status={confirm_r.status_code} body={confirm_r.text[:300]}")
    cdata = _data(confirm_r)
    confirmed_url = cdata.get("url", access_url)
    log(f"  confirm OK, photo_id={cdata.get('photo_id')}")
    return confirmed_url


async def _create_task(client: httpx.AsyncClient, photo_urls) -> str:
    if isinstance(photo_urls, str):
        photo_urls = [photo_urls]
    r = await client.post(
        "/api/v1/tasks",
        json={"photo_urls": photo_urls, "options": {"retouch_styles": ["auto"], "location": None}},
    )
    if r.status_code == 401:
        raise SystemExit(
            "401 未授权：当前非 mock 模式，请加 --token <JWT>，"
            "或在 .env 设置 ENABLE_MOCK_MODE=true 后重启后端"
        )
    if r.status_code != 200:
        raise SystemExit(f"create_task 失败 status={r.status_code} body={r.text[:400]}")
    task_id = _data(r)["task_id"]
    log(f"  任务创建成功 task_id={task_id}")
    return task_id


async def _wait_until_done(
    client: httpx.AsyncClient, task_id: str, timeout: float, poll_interval: float
) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    last_stage = None
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/v1/tasks/{task_id}/status")
        if r.status_code != 200:
            log(f"  状态查询异常 status={r.status_code} body={r.text[:200]}")
            await asyncio.sleep(poll_interval)
            continue
        st = _data(r)
        stage = st.get("current_stage")
        if stage != last_stage:
            log(
                f"  status={st.get('status')} progress={st.get('progress')}% "
                f"stage={stage} processed={st.get('processed_photos')}/{st.get('total_photos')}"
            )
            last_stage = stage
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


def _verify_processed_urls(result: dict) -> tuple[bool, str]:
    """校验 selected_photos 里的 processed_url 是真实可下载的精修图（非原图降级）

    返回 (all_ok, category_info)
    """
    selected = result.get("selected_photos", [])
    if not selected:
        return False, "(无 selected_photos)"
    category = selected[0].get("category") or selected[0].get("type") or "?"
    all_ok = True
    for i, ph in enumerate(selected):
        processed = ph.get("processed_url", "")
        original = ph.get("original_url", "")
        if not processed:
            log(f"    [FAIL] 照片#{i + 1} processed_url 为空")
            all_ok = False
            continue
        if "_retouch_failed=" in processed:
            log(f"    [FAIL] 照片#{i + 1} 精修失败（URL 含降级标记）: {processed}")
            all_ok = False
            continue
        if processed == original:
            log(f"    [WARN] 照片#{i + 1} processed_url 与原图相同，可能走 mock 降级")
            all_ok = False
            continue
        log(f"    [OK] 照片#{i + 1} 精修图: {processed[:90]}")
    return all_ok, category


async def _run_one_image(
    client: httpx.AsyncClient,
    *,
    image_path: str | None = None,
    image_url: str | None = None,
    timeout: float,
    poll_interval: float,
) -> dict:
    """跑单张图片的完整链路，返回汇总条目"""
    name = image_path or image_url or "?"
    entry = {"name": name, "task_id": "", "ok": False, "category": "?", "note": ""}
    try:
        photo_url = await _prepare_photo_url(client, image_path, image_url)
        task_id = await _create_task(client, photo_url)
        entry["task_id"] = task_id
        await _wait_until_done(client, task_id, timeout, poll_interval)
        result = await _fetch_result(client, task_id)
        ok, category = _verify_processed_urls(result)
        entry["ok"] = ok
        entry["category"] = category
        entry["note"] = "success" if ok else "verify_failed"
    except SystemExit as e:
        entry["note"] = f"error: {e}"
        log(f"  [该图失败] {e}")
    except Exception as e:  # noqa: BLE001
        entry["note"] = f"exception: {e!r}"
        log(f"  [该图异常] {e!r}")
    return entry


async def _run_batch(
    client: httpx.AsyncClient,
    images: list,
    dup: int,
    timeout: float,
    poll_interval: float,
) -> dict:
    """批量模式：把文件夹多张图放进【同一个任务】，验证筛选去重 + 分类路由 + 精修闭环。

    dup>1 时每张图重复上传 N 次（内容相同 → aHash 相同 → 应被聚为一组只选 1 张），
    用于直观验证去重；由于只对精选图精修，不会多消耗美图额度。
    """
    entry = {
        "task_id": "", "ok": False, "total_photos": 0,
        "total_groups": 0, "selected": 0, "note": "", "groups": [],
    }
    try:
        prep: list[tuple[str, str]] = []
        for img in images:
            for k in range(max(1, dup)):
                label = f"{img.name}#{k + 1}" if dup > 1 else img.name
                url = await _prepare_photo_url(client, image_path=str(img), image_url=None)
                prep.append((label, url))
        urls = [u for _, u in prep]
        log(f"[batch] 共准备 {len(urls)} 个原图 URL（{len(images)} 张 × dup={dup}），创建单个批量任务")
        task_id = await _create_task(client, urls)
        entry["task_id"] = task_id
        await _wait_until_done(client, task_id, timeout, poll_interval)
        result = await _fetch_result(client, task_id)
        entry.update(_verify_batch_result(result))
    except SystemExit as e:
        entry["note"] = f"error: {e}"
        log(f"[batch] 失败: {e}")
    except Exception as e:  # noqa: BLE001
        entry["note"] = f"exception: {e!r}"
        log(f"[batch] 异常: {e!r}")
    return entry


def _verify_batch_result(result: dict) -> dict:
    """校验批量结果：去重有效性 + 分类路由 + 精修图真实生成"""
    total_photos = result.get("total_photos", 0)
    total_groups = result.get("total_groups", 0)
    selected = result.get("selected_photos", []) or []
    groups = result.get("groups", []) or []
    selected_count = len(selected)

    all_ok = selected_count > 0
    for ph in selected:
        processed = ph.get("processed_url", "")
        original = ph.get("original_url", "")
        if not processed or "_retouch_failed=" in processed or processed == original:
            all_ok = False

    deduped = total_photos - total_groups  # 被合并掉的张数
    info = {
        "total_photos": total_photos,
        "total_groups": total_groups,
        "selected": selected_count,
        "ok": all_ok,
        "note": "success" if all_ok else "verify_failed",
        "groups": [
            {
                "group_id": g.get("group_id"),
                "type": g.get("group_type"),
                "n_photos": len(g.get("photos", []) or []),
                "category": ((g.get("photos", []) or [{}])[0].get("category"))
                if g.get("photos") else None,
            }
            for g in groups
        ],
    }
    log(f"[batch] 去重验证: 输入 {total_photos} 张 -> 聚类 {total_groups} 组 -> 精选 {selected_count} 张")
    if deduped > 0:
        log(f"[batch] ✅ 筛选去重生效：{deduped} 张同场景/重复图被合并到同组")
    else:
        log(f"[batch] ℹ️ 未检测到可去重的重复图（输入图彼此场景不同，各自成组）")
    log(f"[batch] 精修图全部真实生成: {'是' if all_ok else '否'}")
    for g in info["groups"]:
        log(f"        group#{g['group_id']} type={g['type']} category={g['category']} 组内照片={g['n_photos']} 张")
    return info


def _summary_batch(entry: dict, real_retouch: bool) -> None:
    log("=" * 60)
    log("批量测试汇总（单任务多图）")
    log("=" * 60)
    log(f"真实美图精修: {'是' if real_retouch else '否（走 mock）'}")
    log(f"task_id={entry.get('task_id')}")
    log(f"输入原图数={entry.get('total_photos')}  聚类组数={entry.get('total_groups')}  精选数={entry.get('selected')}")
    log(f"链路闭环: {'成功' if entry.get('ok') else '失败'}  note={entry.get('note')}")
    log("-" * 60)
    for g in entry.get("groups", []):
        log(f"  group#{g['group_id']} [{g['type']}] category={g['category']} 组内={g['n_photos']} 张")
    log("-" * 60)
    if entry.get("ok"):
        log("结论: 单任务批量链路闭环——筛选去重 + 分类路由 + 真实精修均生效。")
    else:
        log("结论: 存在失败项，请检查上方 note 与后端日志（花生壳/美图回调/预设配置）。")


def _summary(entries: list[dict], real_retouch: bool) -> None:
    log("=" * 60)
    log("测试汇总")
    log("=" * 60)
    ok_count = sum(1 for e in entries if e["ok"])
    log(f"真实美图精修: {'是' if real_retouch else '否（走 mock）'}")
    log(f"共 {len(entries)} 张，成功 {ok_count} 张，失败 {len(entries) - ok_count} 张")
    log("-" * 60)
    for i, e in enumerate(entries):
        status = "OK " if e["ok"] else "FAIL"
        log(f"[{status}] {e['name']}")
        log(f"        task_id={e['task_id']}  category={e['category']}  note={e['note']}")
    log("-" * 60)
    if not real_retouch:
        log("提示: 后端未配置 MEITU_API_KEY/MEITU_MEDIA_CODE，本次走的是 mock（processed=原图）。")
        log("      要验证真实美图精修，请在 .env 配置密钥并重启后端后重跑。")
    if ok_count == len(entries) and entries:
        log("结论: 全部图片链路闭环成功，精修图已真实生成并落库/COS。")
    else:
        log("结论: 存在失败项，请检查上方note与后端日志（花生壳/美图回调/预设配置）。")


async def main_async(args, real_retouch: bool) -> int:
    env = _load_env()
    base = args.base_url or "http://127.0.0.1:8000"
    # base_url 不带 /api/v1 前缀（下方所有端点路径已含 /api/v1）
    api_base = base.rstrip("/")

    log(f"后端地址: {api_base}")
    log(f"真实美图精修: {'是' if real_retouch else '否（走 mock）'}")
    log(f"CALLBACK_BASE_URL: {env.get('CALLBACK_BASE_URL', '(未配置)')}")

    # 决定照片来源
    folder = args.folder
    if not folder and not args.image_path and not args.image_url:
        folder = _default_test_folder()
        log(f"未指定照片来源，使用默认桌面文件夹: {folder}")

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    async with httpx.AsyncClient(base_url=api_base, headers=headers, timeout=120) as client:
        if not await _health_check(client):
            log("后端不可达，请先启动后端并确保地址正确。")
            return 1

        # ===== 批量模式：把文件夹所有图放进【单个任务】一次跑完 =====
        if args.batch:
            if not folder:
                folder = _default_test_folder()
                log(f"--batch 未指定 --folder，使用默认: {folder}")
            images = _scan_images(folder, args.limit, args.recursive)
            log(f"[batch] 扫描到 {len(images)} 张图片，单任务批量模式（dup={args.dup}）")
            # 批量任务等待时长按图数估算（含 dup 重复），避免超时
            batch_timeout = max(args.timeout, 60 + len(images) * max(1, args.dup) * 20)
            entry = await _run_batch(client, images, args.dup, batch_timeout, args.poll_interval)
            _summary_batch(entry, real_retouch)
            return 0 if entry.get("ok") else 1

        entries: list[dict] = []

        if folder:
            images = _scan_images(folder, args.limit, args.recursive)
            log(f"扫描到 {len(images)} 张图片，开始逐张测试...")
            for idx, img in enumerate(images, 1):
                log(f"\n===== 第 {idx}/{len(images)} 张: {img.name} =====")
                entry = await _run_one_image(
                    client,
                    image_path=str(img),
                    timeout=args.timeout,
                    poll_interval=args.poll_interval,
                )
                entries.append(entry)
        elif args.image_url:
            log(f"\n===== 单图测试 (image-url) =====")
            entries.append(
                await _run_one_image(
                    client,
                    image_url=args.image_url,
                    timeout=args.timeout,
                    poll_interval=args.poll_interval,
                )
            )
        elif args.image_path:
            log(f"\n===== 单图测试 (image-path) =====")
            entries.append(
                await _run_one_image(
                    client,
                    image_path=args.image_path,
                    timeout=args.timeout,
                    poll_interval=args.poll_interval,
                )
            )

        _summary(entries, real_retouch)

    return 0 if all(e["ok"] for e in entries) and entries else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="途吖 美图云修 Pro 真机端到端批量链路测试")
    parser.add_argument(
        "--folder",
        default=None,
        help="测试照片文件夹（默认自动探测桌面「测试照片」；与 image-* 互斥时 folder 优先）",
    )
    parser.add_argument("--image-path", default=None, help="[单图] 本地图片路径（自动 presign 上传 COS）")
    parser.add_argument("--image-url", default=None, help="[单图] 已存在的公网可下载图片 URL")
    parser.add_argument("--base-url", default=None, help="后端基地址，默认 http://127.0.0.1:8000")
    parser.add_argument("--token", default=None, help="JWT token（非 mock 模式必填）")
    parser.add_argument("--limit", type=int, default=0, help="仅测试前 N 张（默认 0=全部）")
    parser.add_argument("--recursive", action="store_true", help="递归子目录")
    parser.add_argument(
        "--batch", action="store_true",
        help="批量模式：把文件夹所有图放进【单个任务】一次跑完，验证筛选去重+分类路由+真实精修",
    )
    parser.add_argument(
        "--dup", type=int, default=1,
        help="批量模式下每张图重复上传 N 次（模拟连拍/同场景），用于验证去重。默认1=不去重",
    )
    parser.add_argument("--timeout", type=float, default=330.0, help="单张等待完成的最长秒数，默认330")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="轮询间隔秒数，默认5")
    args = parser.parse_args()

    if args.image_path and args.image_url:
        parser.error("--image-path 与 --image-url 不能同时指定")

    env = _load_env()
    real_retouch = bool(env.get("MEITU_API_KEY") and env.get("MEITU_MEDIA_CODE"))

    try:
        return asyncio.run(main_async(args, real_retouch))
    except SystemExit as e:
        code = e.code
        if isinstance(code, int) and code == 0:
            return 0
        return 1
    except KeyboardInterrupt:
        log("被用户中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
