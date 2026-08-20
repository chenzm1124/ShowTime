# 途吖 · 旅行照片AI处理工具 — 后端

FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL + Redis + Celery (后续) + Alembic

## 技术栈

| 类别 | 选型 | 说明 |
|------|------|------|
| Web 框架 | FastAPI 0.115+ | 异步、自动 OpenAPI 文档 |
| ORM | SQLAlchemy 2.0 (async) | 配合 asyncpg 驱动 |
| 数据库 | PostgreSQL 16 | JSONB、GIN 索引、UUID 扩展 |
| 缓存/队列 | Redis 7 | 后续 Celery broker |
| 迁移 | Alembic 1.14+ | 自动生成 + 人工 review |
| 鉴权 | JWT (python-jose) | HS256，24h 默认 |
| 对象存储 | 阿里云 OSS / 腾讯云 COS | 抽象层统一 |
| 部署 | Docker Compose | dev 阶段单机编排 |

## 目录结构

```
backend/
├── app/
│   ├── main.py                # FastAPI 入口
│   ├── core/                  # 配置、鉴权、异常
│   ├── api/v1/                # 路由（health 在 WBS 1.1 阶段就绪）
│   ├── models/                # 10 张核心 ORM 模型
│   ├── schemas/               # Pydantic schemas（按模块）
│   ├── services/              # 业务服务层
│   ├── tasks/                 # Celery 任务（WBS 2.2）
│   ├── db/                    # session + migrations
│   ├── utils/                 # 工具
│   └── middleware/            # 中间件
├── scripts/
│   ├── init_db.py             # 初始化数据库
│   └── seed_data.py           # 种子数据
├── tests/                     # pytest
├── alembic.ini
├── pyproject.toml             # Poetry 依赖
├── Dockerfile
└── .env.example
```

## 快速开始

### 1. 复制环境变量

```bash
cp .env.example .env
# 编辑 .env 填入微信 / OSS / 大模型等配置（开发态可全部留空）
```

### 2. Docker 一键启动（推荐）

在项目根目录：

```bash
docker compose up -d
```

会自动：
- 启动 PostgreSQL + Redis + Backend
- 执行 `init_db --seed` 建表 + 写入种子数据（VIP 套餐 + 3 个测试用户）
- 启动 uvicorn 服务（带 reload）

### 3. 验证

```bash
# 健康检查
curl http://localhost:8000/api/v1/health
# {"status":"ok","service":"途吖后端","env":"development","version":"0.1.0"}

# 数据库连接
curl http://localhost:8000/api/v1/health/db
# {"status":"ok","database":"connected","version":"PostgreSQL 16.x ..."}

# API 文档
open http://localhost:8000/docs
```

### 4. 本地开发（无 Docker）

```bash
# 安装依赖
poetry install

# 启动本地 postgres + redis（用 docker）
docker compose up -d postgres redis

# 初始化数据库 + 种子
poetry run python -m scripts.init_db --seed

# 启动 dev server
poetry run uvicorn app.main:app --reload --port 8000
```

## 常用命令

```bash
# 进入 backend 容器
docker compose exec backend bash

# 重新生成迁移（ORM 变更后）
docker compose exec backend alembic revision --autogenerate -m "描述"

# 应用迁移
docker compose exec backend alembic upgrade head

# 跑测试
docker compose exec backend pytest

# 查看日志
docker compose logs -f backend
```

## 数据库

10 张核心表，详见 [DATABASE.md](./DATABASE.md)

| 表名 | 用途 | 关键索引 |
|------|------|---------|
| users | 用户（含会员/试用/广告字段） | openid (unique), member_type, vip_expire_date |
| photos | 照片元信息 | user_id, task_id, status |
| tasks | 处理任务 | user_id, status, (user_id, status) |
| vip_plans | VIP 套餐配置 | level (unique), (is_active, sort_order) |
| orders | VIP 订单 | order_no (unique), user_id, status |
| ad_unlocks | 广告解锁记录 | user_id, status, (user_id, created_at) |
| quota_logs | 额度流水 | user_id, change_type, (user_id, change_type, created_at) |
| share_records | 分享记录 | user_id, share_date, (user_id, share_date) |
| anti_fraud_logs | 反作弊日志 | user_id, risk_level, action |
| operation_logs | 操作日志 | operator_id, module, user_id, created_at |

## WBS 进度

- ✅ 1.1 后端项目初始化
- ✅ 1.2 数据库设计 + 初始化 + Alembic
- ✅ 1.3 Docker Compose 环境搭建
- ⏳ 1.4-1.6 待规划
- ⏳ 1.7 微信登录接口
- ⏳ 1.8 JWT 中间件

## 注意事项

- 生产环境必须设置强随机 `SECRET_KEY`
- 生产环境必须显式配置 `CORS_ORIGINS`（不要用 `*`）
- 数据库连接串分为 `DATABASE_URL`（异步）和 `DATABASE_URL_SYNC`（Alembic 用）
- 修改 ORM 后必须生成迁移并 review，不要直接 `create_all`（仅开发用）
