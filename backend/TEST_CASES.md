# 次数套餐包功能测试用例

> 配套脚本：`scripts/run_pack_tests.py`（一键运行全部用例）
> 报告输出：`TEST_REPORT.md`

## 1. 测试范围

涉及 4 个接口（5 个 endpoint）：

| # | 方法 | 路径 | 用途 |
|---|------|------|------|
| 1 | GET | `/api/v1/packs` | 列出所有可购买的次数包 |
| 2 | POST | `/api/v1/packs/purchase` | 购买次数包（mock 模式自动到账） |
| 3 | POST | `/api/v1/packs/purchase/notify` | 微信支付回调（生产用，当前 501） |
| 4 | GET | `/api/v1/user/quota` | 当前用户额度快照 |
| 5 | POST | `/api/v1/quota/pack-consume` | 原子扣减次数包 |

## 2. 前置条件

- `ENABLE_MOCK_MODE=true`（购买同步到账，无须真实微信支付）
- `DATABASE_URL=sqlite+aiosqlite:///./smoke_test.db`（避免污染生产数据）
- 依赖：标准库 + `fastapi` + `httpx` + `sqlalchemy` + `aiosqlite`

## 3. 测试数据约定

| 字段 | 约定 |
|------|------|
| 三个 seed 包 | daily=9.9元/1次/30张/30天；enjoy=19.9元/3次/50张/60天；unlimited=39.9元/7次/100张/90天 |
| 测试用户 | test_openid_free_001（free）/ test_openid_vip1_001（vip1）/ test_openid_vip3_001（vip3） |
| Mock 模式登录 | 无 token 时 fallback 取第一个测试用户（id=1, free） |

---

## 4. 用例清单（25 例）

### TC-1xx：GET /api/v1/packs（4 例）

| ID | 用例 | 前置 | 输入 | 期望 |
|----|------|------|------|------|
| TC-101 | 正常列出 3 个上架包 | seed 完成 | GET /packs | 200，长度=3，code 升序 [daily, enjoy, unlimited] |
| TC-102 | 字段完整性校验 | seed 完成 | GET /packs | 200，每条记录含 price/original_price/task_quota/photos_per_task/max_refine_per_task/valid_days/features |
| TC-103 | 价格单位校验（分→元） | seed 完成 | GET /packs | 200，daily.price=9.9（不是 990） |
| TC-104 | features 数组正确解析 | seed 完成 | GET /packs | 200，enjoy.features 含 "3次批量处理"；badge="推荐"；highlight=true |

### TC-2xx：POST /api/v1/packs/purchase（7 例）

| ID | 用例 | 前置 | 输入 | 期望 |
|----|------|------|------|------|
| TC-201 | mock 模式购买日常包 | free 用户 | {pack_code:"daily"} | 200，pay_status=success，user_pack.remaining_tasks=1，user_pack.expire_in_seconds > 0 |
| TC-202 | mock 模式购买尽兴包 | free 用户 | {pack_code:"enjoy"} | 200，pay_status=success，user_pack.remaining_tasks=3 |
| TC-203 | mock 模式购买畅游包 | free 用户 | {pack_code:"unlimited"} | 200，pay_status=success，user_pack.remaining_tasks=7 |
| TC-204 | 订单号格式校验 | free 用户 | {pack_code:"enjoy"} | 200，order_no 以 "PK" 开头，长度≥18 |
| TC-205 | 同时返回套餐快照 | free 用户 | {pack_code:"enjoy"} | 200，pack.code="enjoy"、pack.price=19.9、pack.photos_per_task=50 |
| TC-206 | 非法 pack_code 被 Pydantic 拦截 | free 用户 | {pack_code:"invalid"} | 422 |
| TC-207 | 缺字段校验 | free 用户 | {} | 422 |

### TC-3xx：GET /api/v1/user/quota（5 例）

| ID | 用例 | 前置 | 期望 |
|----|------|------|------|
| TC-301 | free 用户首次查询 | 无任何购买 | 200，current_quota.source="trial"，user_packs=[] |
| TC-302 | 购买 1 个包后查询 | 刚买 daily | 200，current_quota.source="pack"，user_packs.length=1，photos_per_task=30 |
| TC-303 | 多包叠加取最大张数 | 买 daily(30张) + enjoy(50张) | 200，current_quota.photos_per_task=50（取最大） |
| TC-304 | 包过期后切回 trial | enjoy 包 expire_at 改为昨天 | 200，current_quota.source 切回 "trial"（需重查前先更新数据库） |
| TC-305 | pack 列表字段完整 | 买 1 个包 | 200，user_packs[0] 含 user_pack_id/pack_code/remaining_tasks/total_tasks/photos_per_task/expire_at/expire_in_seconds |

### TC-4xx：POST /api/v1/quota/pack-consume（6 例）

| ID | 用例 | 前置 | 输入 | 期望 |
|----|------|------|------|------|
| TC-401 | 正常扣减 1 次 | enjoy 包，remaining=3 | {user_pack_id} | 200，remaining_tasks=2 |
| TC-402 | 连续扣减到 0 | 同上 | 连续 3 次 | 200 → 200 → 200，最后 remaining=0 |
| TC-403 | 第 4 次扣减返回 400 | 包已用完 | {user_pack_id} | 400，detail="次数包已不可用" |
| TC-404 | 不存在的 user_pack_id | - | {user_pack_id: 99999} | 404 |
| TC-405 | 跨用户保护 | 用户 A 拥有包，用户 B 调用 | 用户 B 调 consume(用户A的包id) | 404（不应泄漏包存在性） |
| TC-406 | 缺字段 | - | {} | 422 |

### TC-5xx：跨场景组合（3 例）

| ID | 用例 | 前置 | 期望 |
|----|------|------|------|
| TC-501 | 完整链路：买 → 查 → 扣 → 查 → 扣到 0 → 查 source 切换 | free 用户 | 5 步全部符合预期；最后 current_quota.source 切回 trial |
| TC-502 | 配额扣减写入了 quota_log | 买 1 包 + 扣 1 次 | 查 DB：quota_logs 至少有 1 条 PACK_PURCHASE + 1 条 PACK_CONSUME |
| TC-503 | 订单幂等性（手动触发） | 模拟 2 次回调 | 不验证（生产才用），跳过 |

## 5. 通过标准

- **25/25 用例全部 PASS** ✅
- 任何 4xx/5xx 响应未在用例期望中 → 失败
- DB 校验（quota_logs、user_packs 状态机）需精确匹配
- 报错时打印完整堆栈和请求/响应

## 6. 已知限制

- `purchase_notify` 当前返回 501（生产待 WBS 2.x），TC-503 跳过
- mock 模式登录 fallback 到 free 用户；TC-405 跨用户保护需要手动切换 Authorization 头（用 create_access_token 签发）
