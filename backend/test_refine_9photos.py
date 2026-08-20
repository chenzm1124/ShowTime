"""精修 9 张照片端到端耗时测试脚本

复刻小程序前端的完整调用链，专门用来定位"卡在照片处理中"的耗时瓶颈：
    1) previewScreen  —— POST /api/v1/tasks/preview   （真实筛选：aHash 聚类 + 清晰度 + 人脸 + IQA）
    2) createTask     —— POST /api/v1/tasks            （真实模式：立即返回 task_id，精修在后台异步跑）
    3) poll status    —— GET  /api/v1/tasks/{id}/status（前端每 2s 轮询一次，直到 completed/failed）

用法（在 backend 目录下，已启动后端的前提下）：
    # 真实模式（默认）：需要能访问腾讯云 IQA / 美图，会如实记录真实耗时
    python test_refine_9photos.py

    # 指定后端地址
    BASE_URL=http://127.0.0.1:8000 python test_refine_9photos.py

    # mock 模式后端（ENABLE_MOCK_MODE=true 重启后端）：走 skip 分支，秒级完成，用于对比基线
    python test_refine_9photos.py

说明：
- 鉴权走"软认证"：若后端开启了 ENABLE_MOCK_MODE，可无 token 直接调；
  否则脚本自动用后端内部的 build_token 给 is_test=True 的测试用户签发一个 token。
- 9 张图用 picsum 公开 URL（original_url），确保筛选/IQA 走真实路径。
"""
import asyncio
import os
import sys
import time
import httpx

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
NUM_PHOTOS = 9
POLL_INTERVAL = 2.0
POLL_TIMEOUT = 120  # 最多等 2 分钟，避免脚本永远挂住；超时即说明真实精修很慢

HEADERS = {"Content-Type": "application/json"}


def unwrap(r: httpx.Response) -> dict:
    """后端统一响应格式 {code,message,data}，这里解开取 data，并兼容直接返回对象的接口。"""
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        return {}
    if isinstance(body, dict) and "data" in body:
        return body.get("data") or {}
    return body if isinstance(body, dict) else {}


def banner(msg: str) -> None:
    print("\n" + "=" * 70)
    print(msg)
    print("=" * 70)


async def get_token(client: httpx.AsyncClient) -> str | None:
    """尝试拿 token：先试无 token（mock 模式会 fallback），失败则用内部 build_token 给测试用户签发。"""
    # 1) 先试一个需要鉴权的接口，看是否 mock 自动放行
    #    注意：真实模式无 token 会 401（说明需鉴权）；mock 模式会 200（已 fallback）
    r = await client.post(
        "/api/v1/tasks/preview",
        json={"photos": [make_photo_payload(0)]},
        headers=HEADERS,
    )
    if r.status_code == 200:
        print("[auth] mock 模式：无需 token，已放行")
        return None
    if r.status_code == 401:
        print("[auth] 真实模式：需要 token")
    else:
        print(f"[auth] preview 返回 {r.status_code}（非 200/401，按需 token 处理）")

    # 2) 真实模式：用后端内部函数给 is_test 测试用户签 token
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from app.db.session import AsyncSessionLocal
        from app.services.auth_service import build_token
        from sqlalchemy import select
        from app.models.user import User

        async with AsyncSessionLocal() as db:
            user = (
                await db.execute(select(User).where(User.is_test == True).order_by(User.id).limit(1))  # noqa: E712
            ).scalar_one_or_none()
            if not user:
                print("[auth] 未找到 is_test=True 的测试用户，无法签发 token")
                return None
            token = build_token(user)
            print(f"[auth] 已为测试用户 id={user.id} 签发 token")
            return token
    except Exception as e:  # noqa: BLE001
        print(f"[auth] 签发 token 失败：{e}")
        return None


def make_photo_url(i: int) -> str:
    """第 i 张照片的公开 URL（picsum 触发真实 IQA/筛选）。"""
    seed = 100 + i
    return f"https://picsum.photos/seed/{seed}/1200/1600"


def make_photo_payload(i: int) -> dict:
    """构造 9 张照片的对象（保留原始信息，便于展示）。"""
    return {
        "photo_id": f"test_photo_{i}",
        "original_url": make_photo_url(i),
        "object_key": f"test/photo_{i}.jpg",
        "width": 1200,
        "height": 1600,
        "order_index": i,
        "size_bytes": 1_000_000,
    }


async def main() -> None:
    banner("精修 9 张照片 端到端耗时测试")
    print(f"目标后端: {BASE_URL}")
    print(f"照片数量: {NUM_PHOTOS}")

    # trust_env=False：绕过系统/公司 HTTP 代理，直接访问本地后端
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=httpx.Timeout(120),
        trust_env=False,
    ) as client:
        token = await get_token(client)
        auth_headers = {**HEADERS, "Authorization": f"Bearer {token}"} if token else HEADERS

        photos = [make_photo_payload(i) for i in range(NUM_PHOTOS)]
        photo_urls = [p["original_url"] for p in photos]

        # ---------- 阶段 1：previewScreen ----------
        banner("阶段 1 / previewScreen  (POST /api/v1/tasks/preview)")
        t0 = time.perf_counter()
        try:
            r = await client.post(
                "/api/v1/tasks/preview",
                json={"photo_urls": photo_urls},
                headers=auth_headers,
            )
            dt_preview = time.perf_counter() - t0
            if r.status_code == 200:
                data = unwrap(r)
                print(f"[OK] preview 耗时 = {dt_preview:.2f}s")
                print(f"     选中 {data.get('selected_count')} 张，丢弃 {data.get('dropped_count')} 张，分组 {data.get('total_groups')} 组")
                dropped = data.get("dropped_photos") or []
                id_to_url = {p["photo_id"]: p["original_url"] for p in photos}
                for d in dropped[:8]:
                    pid = d.get("photo_id")
                    print(f"     - 丢弃 {pid} ({id_to_url.get(pid, d.get('original_url'))}): {d.get('reason')}")
            else:
                print(f"[FAIL] preview HTTP {r.status_code}: {r.text[:400]}")
                print(f"     preview 耗时 = {dt_preview:.2f}s（请求本身仍耗时）")
        except Exception as e:  # noqa: BLE001
            dt_preview = time.perf_counter() - t0
            print(f"[ERROR] preview 异常：{e}（已耗时 {dt_preview:.2f}s）")

        # ---------- 阶段 2：createTask ----------
        banner("阶段 2 / createTask  (POST /api/v1/tasks)")
        t0 = time.perf_counter()
        task_id = None
        try:
            r = await client.post(
                "/api/v1/tasks",
                json={
                    "photo_urls": photo_urls,
                    "options": {
                        "retouch_styles": ["清新"],
                        "location": "测试地点",
                    },
                },
                headers=auth_headers,
            )
            dt_create = time.perf_counter() - t0
            if r.status_code == 200:
                data = unwrap(r)
                task_id = data.get("task_id")
                print(f"[OK] createTask 耗时 = {dt_create:.2f}s，task_id = {task_id}")
                print(f"     status={data.get('status')} estimated_time={data.get('estimated_time')}s quota_remaining={data.get('quota_remaining')}")
            else:
                print(f"[FAIL] createTask HTTP {r.status_code}: {r.text[:400]}（耗时 {dt_create:.2f}s）")
        except Exception as e:  # noqa: BLE001
            dt_create = time.perf_counter() - t0
            print(f"[ERROR] createTask 异常：{e}（已耗时 {dt_create:.2f}s）")

        if not task_id:
            banner("无法创建任务，测试终止")
            return

        # ---------- 阶段 3：轮询 status ----------
        banner(f"阶段 3 / 轮询 status  (GET /api/v1/tasks/{task_id}/status，每 {POLL_INTERVAL}s 一次)")
        t_start = time.perf_counter()
        last_status = None
        poll_count = 0
        last_progress = None
        while True:
            elapsed = time.perf_counter() - t_start
            if elapsed > POLL_TIMEOUT:
                print(f"[TIMEOUT] 轮询超过 {POLL_TIMEOUT}s 仍未完成，停止。最后状态={last_status}")
                break

            try:
                r = await client.get(f"/api/v1/tasks/{task_id}/status", headers=auth_headers)
                if r.status_code != 200:
                    print(f"[WARN] status HTTP {r.status_code}: {r.text[:200]}")
                else:
                    data = unwrap(r)
                    status = data.get("status")
                    progress = data.get("progress")
                    processed = data.get("processed_photos")
                    total = data.get("total_photos")
                    if status != last_status or progress != last_progress:
                        photos = data.get("photos") or []
                        done = sum(1 for p in photos if p.get("status") == "completed")
                        failed = sum(1 for p in photos if p.get("status") == "failed")
                        print(
                            f"  +{elapsed:6.1f}s  状态={status}  进度={progress}  "
                            f"已处理={processed}/{total}  逐张完成={done} 失败={failed}  轮次={poll_count}"
                        )
                        last_status = status
                        last_progress = progress
                    if status in ("completed", "failed", "cancelled"):
                        dt_total = time.perf_counter() - t_start
                        print(f"[DONE] 任务 {status}，从创建到结束总耗时 = {dt_total:.1f}s，轮询 {poll_count} 次")
                        break
            except Exception as e:  # noqa: BLE001
                print(f"  +{elapsed:6.1f}s  [ERROR] 轮询异常：{e}")

            poll_count += 1
            await asyncio.sleep(POLL_INTERVAL)

        # ---------- 汇总 ----------
        banner("耗时汇总")
        print(f"previewScreen : {dt_preview:.2f}s")
        print(f"createTask    : {dt_create:.2f}s")
        print(f"轮询阶段总等待: {time.perf_counter() - t_start:.1f}s（含真实后台精修）")
        print("\n说明：真实模式下 N 张照片已并行提交美图云修 Pro（并发=5），")
        print("单张处理数分钟。逐张完成后即时可见（先好先显示），无需等全部完成。")


if __name__ == "__main__":
    asyncio.run(main())
