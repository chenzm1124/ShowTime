# 数据库设计 · 途吖

> 最后更新：2026-07-05 · 版本：v0.1.0

## 概览

| 类别 | 表数 | 说明 |
|------|------|------|
| 用户与会员 | 1 | users |
| 业务核心 | 3 | photos / tasks / orders |
| 商业化配置 | 2 | vip_plans / ad_unlocks |
| 审计与运营 | 4 | quota_logs / share_records / anti_fraud_logs / operation_logs |
| **合计** | **10** | — |

## 实体关系图

```
                            ┌──────────────┐
                            │   vip_plans  │
                            └──────┬───────┘
                                   │ 1:N
                                   ▼
┌─────────┐ 1:N ┌───────┐ 1:N ┌──────┐ 1:N ┌──────────┐
│  users  │────▶│ tasks │◀────│photos│     │  orders  │
└────┬────┘     └───┬───┘     └──────┘     └──────────┘
     │              │
     │ 1:N          │ 1:N
     ▼              ▼
┌─────────────┐ ┌──────────────┐
│ ad_unlocks  │ │ quota_logs   │
└─────────────┘ └──────────────┘

┌──────────────┐ ┌──────────────────┐ ┌─────────────────┐
│share_records │ │anti_fraud_logs   │ │ operation_logs  │
└──────────────┘ └──────────────────┘ └─────────────────┘
```

## 表详情

### 1. users（用户表）

**核心字段**：
- `openid` (UNIQUE) — 微信 openid
- `member_type` — `free` | `vip1` | `vip2` | `vip3`
- `vip_expire_date` — VIP 过期日期
- `vip_daily_used` / `vip_daily_date` — VIP 每日次数（3/5/7）
- `trial_remaining` (默认 1) / `trial_first_used_date` — 账号终身 1 次试用
- `ad_unlock_remaining_today` (默认 2) / `ad_unlock_watched_today` / `ad_unlock_date` — 看广告每天 2 次
- `status` — `active` | `banned`
- `is_test` — 测试账号标记

**索引**：`openid`, `unionid`, `member_type`, `status`, `vip_expire_date`

### 2. photos（照片表）

- `user_id` → users.id（CASCADE）
- `task_id` → tasks.id（SET NULL）
- `original_url` / `processed_url` / `thumb_url` — OSS key
- `quality_score` / `aesthetic_score` / `face_count` / `is_blurry` / `is_duplicate` / `cluster_id` / `scene_tags` — 智能筛选结果
- `retouch_style` — `auto` | `hk` | `cyber` | `soft` | `film` | `fresh`
- `status` — `uploaded` | `processing` | `done` | `failed`
- `deleted_at` — 软删除

### 3. tasks（处理任务表）

- `user_id` → users.id（CASCADE）
- `status` — `pending` | `queued` | `processing` | `completed` | `failed` | `cancelled`
- `task_type` — `photo_process` 等
- `total_count` / `processed_count` / `failed_count` / `progress` — 进度
- `quota_reason` — 配额消费类型 `trial` | `ad` | `vip`
- `celery_task_id` — Celery 任务 ID（用于回查 / 取消）

**索引**：`(user_id, status)` 组合索引加速"我的任务列表"查询

### 4. vip_plans（VIP 套餐配置表）

- `level` (UNIQUE) — `vip1` | `vip2` | `vip3`
- `price_monthly` / `price_yearly` — **单位：分**（避免浮点）
- `original_price_*` — 原价（划线价，用于展示折扣）
- `photos_per_task` — 单次处理上限（50/80/150）
- `daily_limit` — 每日次数上限（3/5/7）
- `features` — JSON 字符串
- `badge` / `highlight` — UI 标记
- `is_active` / `sort_order` — 状态 + 排序

### 5. orders（VIP 订单表）

- `order_no` (UNIQUE) — 商户订单号
- `plan_id` → vip_plans.id
- `plan_level` / `plan_name` — 冗余（避免关联查询）
- `period` — `monthly` | `yearly`
- `amount` / `original_amount` — 金额（分）
- `pay_channel` — `wechat` | `alipay`
- `pay_status` / `status` — `pending` | `paid` | `refunding` | `refunded` | `cancelled` | `failed`
- `transaction_id` / `prepay_id` — 微信支付回执
- `vip_start_date` / `vip_end_date` — VIP 生效区间

### 6. ad_unlocks（广告解锁记录表）

- `user_id` → users.id（CASCADE）
- `provider` — `wechat` | `tencent` | `pangolin`
- `ad_type` — `rewarded_video`（激励视频）
- `status` — `pending` | `rewarded` | `invalid` | `failed`
- `callback_data` — 客户端上报的回调（JSON，用于反作弊）
- `watch_duration_seconds` / `device_id`

### 7. quota_logs（额度流水表）

- `user_id` → users.id（CASCADE）
- `change_type` — `trial_consume` | `ad_unlock_reward` | `vip_grant` | `vip_renew` | `vip_expire` | `task_fail_refund` | `admin_adjust` | `daily_reset`
- 关联字段：`related_task_id` / `related_order_no` / `related_ad_unlock_id`
- `change_detail` — JSON：变更前后对比
- `operator_id` — 操作人（管理员调整时记录）

### 8. share_records（分享记录表）

- `user_id` / `task_id`
- `channel` — `wechat_moments` | `wechat_friend` | `copy_link`
- `clicked_back` / `registered_user_id` / `converted_at` — 分享回流统计

### 9. anti_fraud_logs（反作弊日志表）

- `user_id` → users.id（SET NULL，删用户不删日志）
- `risk_level` — `low` | `medium` | `high` | `blocked`
- `risk_score` — 0-100
- `rule_code` / `rule_name` — 命中的规则（如 `DEVICE_FINGERPRINT_DUP`）
- `scene` — 触发场景
- `action` — `allow` | `warn` | `captcha` | `limit` | `block` | `ban`
- `detail` — 详细信息 JSON

### 10. operation_logs（操作日志表）

- `operator_id` / `operator_name` / `operator_type` — `admin` | `system` | `user`
- `module` — 9 个枚举
- `action` — 操作名
- `before_data` / `after_data` — 变更前后快照
- `cost_ms` / `success` / `error_msg` — 性能 + 结果

## 命名约定

通过 `MetaData.naming_convention` 统一约束名，便于 Alembic 维护：

| 类型 | 模板 |
|------|------|
| 索引 | `ix_<table>_<col>` |
| 唯一约束 | `uq_<table>_<col>` |
| 检查约束 | `ck_<table>_<name>` |
| 外键 | `fk_<table>_<col>_<ref_table>` |
| 主键 | `pk_<table>` |

## 金额处理

- 全部以**分**为单位（INTEGER），避免浮点精度问题
- 展示时前端除以 100 并 toFixed(2)

## 时间处理

- 所有 `DateTime` 字段带 `timezone=True`
- 服务端使用 `func.now()` 生成默认值（数据库时区）
- 跨天判断统一使用 `date.today()` 在应用层处理

## 软删除

- 仅 `photos` 表有 `deleted_at`，查询时需过滤
- 用户 / 订单等用 `status` 字段管理（active / banned / cancelled）
- 反作弊日志不软删（保留全部用于审计）

## 后续演进

- V2.0 考虑分库分表（按 `user_id` hash 拆分 orders / quota_logs）
- 大量历史 `quota_logs` / `operation_logs` 考虑按月分区
- `anti_fraud_logs` 可考虑接入 ClickHouse 做实时风控分析
