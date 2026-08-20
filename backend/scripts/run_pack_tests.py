"""次数套餐包全量功能测试

执行：python scripts/run_pack_tests.py
输出：控制台实时打印 + scripts/_test_results.json
配套文档：TEST_CASES.md
"""
import asyncio
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./smoke_test.db"
os.environ["ENABLE_MOCK_MODE"] = "true"
os.environ["PYTHONIOENCODING"] = "utf-8"

from app.core.security import create_access_token
from app.db.session import Base, engine
from app import models  # noqa
from scripts.seed_data import seed_all

# ---------- 全局测试上下文 ----------
RESULTS = []
TEST_DB = Path(__file__).resolve().parent.parent / "smoke_test.db"


def record(tc_id, name, status, detail=""):
    """记录一条用例结果"""
    RESULTS.append({
        "id": tc_id,
        "name": name,
        "status": status,
        "detail": detail,
        "time": datetime.now().isoformat(timespec="seconds"),
    })
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[status]
    line = f"  {icon} {tc_id} {name}"
    if status != "PASS":
        line += f"  -- {detail}"
    print(line, flush=True)


def step(msg):
    print(f"\n>>> {msg}", flush=True)


# ---------- Bootstrap ----------

async def bootstrap():
    if TEST_DB.exists():
        TEST_DB.unlink()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_all()
    await engine.dispose()
    print(f"[BOOT] DB ready at {TEST_DB}")


# ---------- Test Helper ----------

def make_token(user_id: int) -> str:
    return create_access_token(subject=str(user_id))


def query_db(sql: str, params=()) -> list:
    conn = sqlite3.connect(str(TEST_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------- 主测试 ----------

def run_all_tests():
    from fastapi.testclient import TestClient
    from app.main import app

    step("TC-1xx: GET /api/v1/packs")

    with TestClient(app) as client:
        # ----- TC-101 -----
        try:
            r = client.get("/api/v1/packs")
            assert r.status_code == 200, r.text
            data = r.json()
            assert len(data) == 3, f"len={len(data)}"
            assert [p["code"] for p in data] == ["daily", "enjoy", "unlimited"]
            record("TC-101", "正常列出 3 个上架包", "PASS")
        except Exception as e:
            record("TC-101", "正常列出 3 个上架包", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-102 -----
        try:
            r = client.get("/api/v1/packs")
            data = r.json()
            for p in data:
                for field in ["price", "original_price", "task_quota", "photos_per_task",
                              "max_refine_per_task", "valid_days", "features"]:
                    assert field in p, f"{p['code']} 缺字段 {field}"
            record("TC-102", "字段完整性校验", "PASS")
        except Exception as e:
            record("TC-102", "字段完整性校验", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-103 -----
        try:
            r = client.get("/api/v1/packs")
            data = {p["code"]: p for p in r.json()}
            assert data["daily"]["price"] == 9.9, f"daily.price={data['daily']['price']}"
            assert data["enjoy"]["price"] == 19.9, f"enjoy.price={data['enjoy']['price']}"
            assert data["unlimited"]["price"] == 39.9, f"unlimited.price={data['unlimited']['price']}"
            record("TC-103", "价格单位校验（分→元）", "PASS")
        except Exception as e:
            record("TC-103", "价格单位校验（分→元）", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-104 -----
        try:
            r = client.get("/api/v1/packs")
            data = {p["code"]: p for p in r.json()}
            assert "3次批量处理" in data["enjoy"]["features"]
            assert data["enjoy"]["badge"] == "推荐"
            assert data["enjoy"]["highlight"] is True
            record("TC-104", "features 数组正确解析", "PASS")
        except Exception as e:
            record("TC-104", "features 数组正确解析", "FAIL", f"{type(e).__name__}: {e}")

        step("TC-2xx: POST /api/v1/packs/purchase")

        # ----- TC-201/202/203 -----
        for code, expected_remaining, tc_id in [
            ("daily", 1, "TC-201"),
            ("enjoy", 3, "TC-202"),
            ("unlimited", 7, "TC-203"),
        ]:
            try:
                r = client.post("/api/v1/packs/purchase", json={"pack_code": code})
                assert r.status_code == 200, r.text
                data = r.json()
                assert data["pay_status"] == "success", data
                assert data["user_pack"]["remaining_tasks"] == expected_remaining
                assert data["user_pack"]["expire_in_seconds"] > 0
                record(tc_id, f"mock 模式购买 {code} 包", "PASS")
            except Exception as e:
                record(tc_id, f"mock 模式购买 {code} 包", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-204 -----
        try:
            r = client.post("/api/v1/packs/purchase", json={"pack_code": "enjoy"})
            data = r.json()
            assert data["order_no"].startswith("PK"), data["order_no"]
            assert len(data["order_no"]) >= 18
            record("TC-204", "订单号格式校验", "PASS")
        except Exception as e:
            record("TC-204", "订单号格式校验", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-205 -----
        try:
            r = client.post("/api/v1/packs/purchase", json={"pack_code": "enjoy"})
            data = r.json()
            assert data["pack"]["code"] == "enjoy"
            assert data["pack"]["price"] == 19.9
            assert data["pack"]["photos_per_task"] == 50
            record("TC-205", "同时返回套餐快照", "PASS")
        except Exception as e:
            record("TC-205", "同时返回套餐快照", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-206 -----
        try:
            r = client.post("/api/v1/packs/purchase", json={"pack_code": "invalid"})
            assert r.status_code == 422, r.text
            record("TC-206", "非法 pack_code 被 Pydantic 拦截", "PASS")
        except Exception as e:
            record("TC-206", "非法 pack_code 被 Pydantic 拦截", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-207 -----
        try:
            r = client.post("/api/v1/packs/purchase", json={})
            assert r.status_code == 422, r.text
            record("TC-207", "缺字段校验", "PASS")
        except Exception as e:
            record("TC-207", "缺字段校验", "FAIL", f"{type(e).__name__}: {e}")

        step("TC-3xx: GET /api/v1/user/quota")

        # ----- TC-301：free 用户买包后 source 切换为 pack -----
        # 此时 TC-2xx 共购买 5 个包（TC-201/202/203 各 1 个 + TC-204/205 各再购 1 个 enjoy）
        try:
            r = client.get("/api/v1/user/quota")
            data = r.json()
            assert data["member_type"] == "free"
            assert len(data["user_packs"]) == 5, f"user_packs={len(data['user_packs'])}"
            assert data["current_quota"]["source"] == "pack"
            record("TC-301a", "free 用户买包后 source 切换为 pack", "PASS")
        except Exception as e:
            record("TC-301a", "free 用户买包后 source 切换为 pack", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-302：user_packs 列表字段完整性 -----
        try:
            r = client.get("/api/v1/user/quota")
            data = r.json()
            assert len(data["user_packs"]) == 5
            for p in data["user_packs"]:
                for field in ["user_pack_id", "pack_code", "remaining_tasks", "total_tasks",
                              "photos_per_task", "expire_at", "expire_in_seconds"]:
                    assert field in p, f"user_pack 缺字段 {field}"
            record("TC-302", "user_packs 列表字段完整", "PASS")
        except Exception as e:
            record("TC-302", "user_packs 列表字段完整", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-303：多包叠加取最大张数 -----
        try:
            r = client.get("/api/v1/user/quota")
            data = r.json()
            # 已买 daily(30) + enjoy(50) + unlimited(100) → 应取 100
            assert data["current_quota"]["photos_per_task"] == 100, \
                f"photos_per_task={data['current_quota']['photos_per_task']}"
            record("TC-303", "多包叠加取最大张数", "PASS")
        except Exception as e:
            record("TC-303", "多包叠加取最大张数", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-304：包过期后切回 trial -----
        try:
            # 把所有 user_pack 的 expire_at 改成昨天
            conn = sqlite3.connect(str(TEST_DB))
            yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
            conn.execute("UPDATE user_packs SET expire_at = ?", (yesterday,))
            conn.commit()
            conn.close()

            r = client.get("/api/v1/user/quota")
            data = r.json()
            # 包全部过期，user_packs 仍展示（status 仍可能是 ACTIVE，但 expire_in_seconds 应 < 0）
            # current_quota.source 切回 trial（因为 free + 试用未用）
            assert data["current_quota"]["source"] == "trial", data["current_quota"]
            record("TC-304", "包过期后切回 trial", "PASS")
        except Exception as e:
            record("TC-304", "包过期后切回 trial", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-305：重置回正常状态，准备后续用例 -----
        try:
            conn = sqlite3.connect(str(TEST_DB))
            future = (datetime.utcnow() + timedelta(days=30)).isoformat()
            conn.execute("UPDATE user_packs SET expire_at = ?", (future,))
            conn.commit()
            conn.close()
            record("TC-305", "DB 状态重置（test fixture）", "PASS")
        except Exception as e:
            record("TC-305", "DB 状态重置（test fixture）", "FAIL", f"{type(e).__name__}: {e}")

        step("TC-4xx: POST /api/v1/quota/pack-consume")

        # 拿一个 user_pack_id 用于扣减
        rows = query_db("SELECT id, remaining_tasks, pack_code FROM user_packs ORDER BY id LIMIT 1")
        assert rows, "user_packs 为空"
        target_pack_id = rows[0]["id"]
        target_initial = rows[0]["remaining_tasks"]

        # ----- TC-401：扣 1 次 -----
        try:
            r = client.post("/api/v1/quota/pack-consume", json={"user_pack_id": target_pack_id})
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["remaining_tasks"] == target_initial - 1
            record("TC-401", "正常扣减 1 次", "PASS")
        except Exception as e:
            record("TC-401", "正常扣减 1 次", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-402：扣到 0 -----
        try:
            current = query_db("SELECT remaining_tasks FROM user_packs WHERE id=?", (target_pack_id,))[0]["remaining_tasks"]
            for _ in range(current):
                r = client.post("/api/v1/quota/pack-consume", json={"user_pack_id": target_pack_id})
                assert r.status_code == 200, r.text
            final = query_db("SELECT remaining_tasks, status FROM user_packs WHERE id=?", (target_pack_id,))[0]
            assert final["remaining_tasks"] == 0
            # SQLite 直接查 enum 列是字符串；状态值大小写以 seed/代码为准
            assert str(final["status"]).lower() == "exhausted", f"status={final['status']}"
            record("TC-402", "连续扣减到 0（状态变 exhausted）", "PASS")
        except Exception as e:
            record("TC-402", "连续扣减到 0（状态变 exhausted）", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-403：第 N+1 次返回 400 -----
        try:
            r = client.post("/api/v1/quota/pack-consume", json={"user_pack_id": target_pack_id})
            assert r.status_code == 400, f"status={r.status_code}, body={r.text}"
            assert "已用完" in r.json()["detail"] or "不可用" in r.json()["detail"]
            record("TC-403", "用完后再扣返回 400", "PASS")
        except Exception as e:
            record("TC-403", "用完后再扣返回 400", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-404：不存在的 user_pack_id -----
        try:
            r = client.post("/api/v1/quota/pack-consume", json={"user_pack_id": 999999})
            assert r.status_code == 404, r.text
            record("TC-404", "不存在的 user_pack_id", "PASS")
        except Exception as e:
            record("TC-404", "不存在的 user_pack_id", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-405：跨用户保护 -----
        try:
            # 用户 1 (free) 拥有 target_pack_id
            # 用用户 2 (vip1) 的 token 调 consume，应该 404
            user2_token = make_token(2)
            r = client.post(
                "/api/v1/quota/pack-consume",
                json={"user_pack_id": target_pack_id},
                headers={"Authorization": f"Bearer {user2_token}"},
            )
            assert r.status_code == 404, f"status={r.status_code}, body={r.text}"
            record("TC-405", "跨用户保护（用其他用户 token 不能扣）", "PASS")
        except Exception as e:
            record("TC-405", "跨用户保护（用其他用户 token 不能扣）", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-406：缺字段 -----
        try:
            r = client.post("/api/v1/quota/pack-consume", json={})
            assert r.status_code == 422, r.text
            record("TC-406", "缺字段校验", "PASS")
        except Exception as e:
            record("TC-406", "缺字段校验", "FAIL", f"{type(e).__name__}: {e}")

        step("TC-5xx: 跨场景组合")

        # 重新 bootstrap 一个干净环境做完整链路
        # （TestClient 上下文还在，复用即可）
        try:
            # 选一个仍有 remaining 的 user_pack
            avail = query_db("SELECT id, remaining_tasks, pack_code FROM user_packs WHERE remaining_tasks > 0 LIMIT 1")
            if not avail:
                # 没剩余了，再买一个
                r = client.post("/api/v1/packs/purchase", json={"pack_code": "enjoy"})
                assert r.status_code == 200
                avail = query_db("SELECT id, remaining_tasks, pack_code FROM user_packs WHERE remaining_tasks > 0 LIMIT 1")

            ap = avail[0]
            ap_id = ap["id"]
            ap_initial = ap["remaining_tasks"]

            # 步骤 1：查询（应有 source=pack）
            r = client.get("/api/v1/user/quota")
            q1 = r.json()
            assert q1["current_quota"]["source"] == "pack"

            # 步骤 2：扣 1 次
            r = client.post("/api/v1/quota/pack-consume", json={"user_pack_id": ap_id})
            assert r.status_code == 200
            r1 = query_db("SELECT remaining_tasks FROM user_packs WHERE id=?", (ap_id,))[0]["remaining_tasks"]
            assert r1 == ap_initial - 1

            # 步骤 3：再扣到 0
            for _ in range(r1):
                client.post("/api/v1/quota/pack-consume", json={"user_pack_id": ap_id})
            r2 = query_db("SELECT remaining_tasks, status FROM user_packs WHERE id=?", (ap_id,))[0]
            assert r2["remaining_tasks"] == 0
            assert str(r2["status"]).lower() == "exhausted", f"status={r2['status']}"

            # 步骤 4：再次查询（如果所有包都用完，source 切回 trial）
            r = client.get("/api/v1/user/quota")
            q2 = r.json()
            # 如果还有包未用完，source 仍是 pack；全用完则切 trial
            if all(p["remaining_tasks"] == 0 for p in q2["user_packs"]):
                assert q2["current_quota"]["source"] == "trial", q2["current_quota"]
            record("TC-501", "完整链路：买→查→扣→扣完→查 source 切换", "PASS")
        except Exception as e:
            record("TC-501", "完整链路：买→查→扣→扣完→查 source 切换", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-502：quota_log 写入校验 -----
        try:
            logs = query_db("SELECT change_type, COUNT(*) as cnt FROM quota_logs GROUP BY change_type")
            # 枚举值是大写，用 lower 比较
            types = {str(l["change_type"]).lower(): l["cnt"] for l in logs}
            assert types.get("pack_purchase", 0) >= 3, f"pack_purchase={types.get('pack_purchase', 0)}"
            assert types.get("pack_consume", 0) >= 1, f"pack_consume={types.get('pack_consume', 0)}"
            record("TC-502", "quota_log 写入校验（PACK_PURCHASE + PACK_CONSUME）", "PASS")
        except Exception as e:
            record("TC-502", "quota_log 写入校验（PACK_PURCHASE + PACK_CONSUME）", "FAIL", f"{type(e).__name__}: {e}")

        # ----- TC-503：跳过（生产微信回调未实现） -----
        try:
            r = client.post("/api/v1/packs/purchase/notify", json={})
            assert r.status_code == 501, r.text
            record("TC-503", "微信支付回调当前 501（生产待 WBS 2.x）", "PASS")
        except Exception as e:
            record("TC-503", "微信支付回调当前 501（生产待 WBS 2.x）", "FAIL", f"{type(e).__name__}: {e}")


# ---------- 报告输出 ----------

def print_summary():
    print("\n" + "=" * 60, flush=True)
    print("TEST SUMMARY", flush=True)
    print("=" * 60, flush=True)
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    skipped = sum(1 for r in RESULTS if r["status"] == "SKIP")
    print(f"  Total:   {total}", flush=True)
    print(f"  Passed:  {passed}", flush=True)
    print(f"  Failed:  {failed}", flush=True)
    print(f"  Skipped: {skipped}", flush=True)
    print(f"  Pass rate: {passed / total * 100:.1f}%" if total else "  N/A", flush=True)

    # 写结果到 JSON
    out = Path(__file__).resolve().parent / "_test_results.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Results saved to: {out}", flush=True)
    return passed == total


if __name__ == "__main__":
    asyncio.run(bootstrap())
    run_all_tests()
    ok = print_summary()
    sys.exit(0 if ok else 1)
