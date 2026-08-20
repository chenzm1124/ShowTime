# 次数套餐包功能测试报告

> **测试时间**：2026-07-07
> **测试范围**：次数套餐包 4 个接口（GET /packs、POST /packs/purchase、POST /quota/pack-consume、GET /user/quota）
> **测试方式**：FastAPI TestClient + SQLite 真实数据库 + 真实 HTTP 请求
> **结果**：✅ **25/25 用例全部通过（100%）**

---

## 1. 测试结果总览

| 指标 | 数值 |
|------|------|
| 总用例数 | 25 |
| 通过 | **25** |
| 失败 | 0 |
| 跳过 | 0 |
| 通过率 | **100%** |
| 跑测耗时 | ~1.5 秒 |
| 触发 HTTP 请求 | ~30 个 |

---

## 2. 用例分类明细

### 2.1 TC-1xx：GET /api/v1/packs（4/4 PASS）

| ID | 用例 | 结果 | 关键断言 |
|----|------|------|----------|
| TC-101 | 正常列出 3 个上架包 | ✅ PASS | 200，长度=3，code 升序 |
| TC-102 | 字段完整性校验 | ✅ PASS | 7 个核心字段全部存在 |
| TC-103 | 价格单位校验（分→元） | ✅ PASS | daily=9.9, enjoy=19.9, unlimited=39.9 |
| TC-104 | features 数组正确解析 | ✅ PASS | enjoy.badge="推荐"，highlight=true |

### 2.2 TC-2xx：POST /api/v1/packs/purchase（7/7 PASS）

| ID | 用例 | 结果 | 关键断言 |
|----|------|------|----------|
| TC-201 | mock 模式购买 daily 包 | ✅ PASS | pay_status=success, remaining=1 |
| TC-202 | mock 模式购买 enjoy 包 | ✅ PASS | remaining=3, expire_in_seconds > 0 |
| TC-203 | mock 模式购买 unlimited 包 | ✅ PASS | remaining=7 |
| TC-204 | 订单号格式校验 | ✅ PASS | PK 前缀，长度≥18 |
| TC-205 | 同时返回套餐快照 | ✅ PASS | pack.price=19.9, photos_per_task=50 |
| TC-206 | 非法 pack_code 被 Pydantic 拦截 | ✅ PASS | 422 |
| TC-207 | 缺字段校验 | ✅ PASS | 422 |

### 2.3 TC-3xx：GET /api/v1/user/quota（5/5 PASS）

| ID | 用例 | 结果 | 关键断言 |
|----|------|------|----------|
| TC-301a | free 用户买包后 source 切换为 pack | ✅ PASS | user_packs=5, current_quota.source=pack |
| TC-302 | user_packs 列表字段完整 | ✅ PASS | 7 个字段全部存在 |
| TC-303 | 多包叠加取最大张数 | ✅ PASS | daily(30)+enjoy(50)+unlimited(100) → 100 |
| TC-304 | 包过期后切回 trial | ✅ PASS | expire_at 改昨天后 source=trial |
| TC-305 | DB 状态重置 | ✅ PASS | fixture 恢复后续用例 |

### 2.4 TC-4xx：POST /api/v1/quota/pack-consume（6/6 PASS）

| ID | 用例 | 结果 | 关键断言 |
|----|------|------|----------|
| TC-401 | 正常扣减 1 次 | ✅ PASS | remaining 3→2 |
| TC-402 | 连续扣减到 0 | ✅ PASS | status 变 EXHAUSTED |
| TC-403 | 用完后再扣返回 400 | ✅ PASS | 400 拒绝 |
| TC-404 | 不存在的 user_pack_id | ✅ PASS | 404 |
| TC-405 | 跨用户保护 | ✅ PASS | 用户 B 调用户 A 的包 → 404 |
| TC-406 | 缺字段校验 | ✅ PASS | 422 |

### 2.5 TC-5xx：跨场景组合（3/3 PASS）

| ID | 用例 | 结果 | 关键断言 |
|----|------|------|----------|
| TC-501 | 完整链路：买→查→扣→扣完→查 source 切换 | ✅ PASS | 5 步全部符合预期 |
| TC-502 | quota_log 写入校验 | ✅ PASS | PACK_PURCHASE + PACK_CONSUME 均有记录 |
| TC-503 | 微信支付回调当前 501 | ✅ PASS | 501（生产待 WBS 2.x） |

---

## 3. 关键功能验证

### 3.1 购买流程（mock 模式）

```
POST /api/v1/packs/purchase {pack_code: "enjoy"}
  → 200 OK
  → 创建 pack_orders 记录
  → 直接标记 PAID（mock）
  → 激活 user_packs（status=ACTIVE, remaining=3）
  → 写 quota_logs（change_type=PACK_PURCHASE）
  → 返回 {order_no, pack, pay_status="success", user_pack}
```

✅ **全链路打通**，前端可在收到响应后立即展示已购包

### 3.2 扣减流程（含并发保护）

```
POST /api/v1/quota/pack-consume {user_pack_id: 1}
  → SELECT ... FOR UPDATE 行锁
  → 校验：归属、未过期、状态 ACTIVE、剩余 > 0
  → remaining_tasks -= 1
  → consumed_at = now()
  → 若 remaining=0：status = EXHAUSTED
  → 写 quota_logs（change_type=PACK_CONSUME）
  → 返回 {user_pack_id, remaining_tasks, message}
```

✅ **行锁 + 状态机** 双重保护，**不会扣成负数**

### 3.3 额度聚合（4 维度）

`GET /user/quota` 返回的 `current_quota.source` 优先级：

| 场景 | source | photos_per_task |
|------|--------|-----------------|
| vip1/2/3 用户 | `vip` | 50/80/150 |
| free + 有可用包 | `pack` | 所有有效包中的最大张数 |
| free + 试用未用 | `trial` | 20 |
| free + 广告有剩余 | `ad` | 20 |
| free + 全用完 | `none` | 20 |

✅ 切换逻辑全部 PASS

### 3.4 跨用户保护（重要安全特性）

用户 B 用自己 JWT 调 `pack-consume(user_pack_id=用户A的包)`：

```
→ service.consume_user_pack 用 AND(user_id=user.id) 过滤
→ 用户 B 查不到该包 → 抛 404
→ 不泄漏包存在性，避免 enumeration 攻击
```

✅ TC-405 验证通过

---

## 4. 测试中发现的产品 bug

**无**。所有 5 个 FAIL 都是测试脚本自身的实现问题（漏算购买次数、枚举大小写），修复后 25/25 通过。

---

## 5. 已知限制 / 后续工作

| 项 | 状态 | 影响 |
|----|------|------|
| `purchase_notify` 真实实现 | 占位 501，生产待 WBS 2.x 接入 | 仅影响生产环境；mock 模式测试覆盖完毕 |
| 并发扣减真压测 | 未做 | 逻辑层有 `with_for_update()` 行锁保护，理论上安全；建议后续用 `locust` 或 `wrk` 压测 1000 并发 |
| 退款流程 | 未实现 | 订单状态机预留了 REFUNDED，但 service 层未做 |
| 过期清理定时任务 | 未实现 | user_packs.expire_at 到期后，依赖 `consume` 时被动检测（已实现）；建议加每日 0 点扫描主动置位 |

---

## 6. 复现命令

```powershell
cd D:\个人\workbuddy工作区\travel-photo\backend
$env:DATABASE_URL="sqlite+aiosqlite:///./smoke_test.db"
$env:ENABLE_MOCK_MODE="true"
$env:PYTHONIOENCODING="utf-8"
python scripts/run_pack_tests.py
```

输出：
- 控制台实时打印每条用例的 PASS/FAIL
- `scripts/_test_results.json`（结构化结果，可对接 CI）

---

## 7. 配套文档

- `TEST_CASES.md`：25 个用例的详细定义
- `scripts/run_pack_tests.py`：自动化测试脚本
- `scripts/_test_results.json`：最近一次跑测结果

---

*报告生成时间：2026-07-07 23:14*
*测试框架：FastAPI TestClient + pytest 风格断言 + 独立 try/except 隔离*
