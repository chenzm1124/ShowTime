# 图轻松（Tuya）· 个人创业者沙龙照片 AI 处理工具

> 一款面向 **个人创业者（一人公司 / OPC）** 的微信小程序，聚焦 **线下沙龙活动** 照片的 AI 一站式处理：
> **智能筛选 → AI 精修 → 品牌文案生成**。
>
> 解决创业者"活动照片堆积、没时间挑图修图、文案不会写"的痛点，让每次沙龙结束后都能快速产出可分享、有质感、体现个人品牌的内容。

---

## 项目简介

**图轻松（Tuya）** 帮助个人创业者把一场线下沙龙（分享会、工作坊、客户交流会、私董会、品鉴会等）拍摄的几十上百张照片，自动收敛为几组高质量精修图 + 多条匹配个人品牌调性的朋友圈/公众号配图文案。

| 维度 | 沙龙场景（当前） |
|------|------------------|
| 目标用户 | 一人公司主理人、个人品牌创业者（独立顾问、私教、律师、设计师、保险代理人等） |
| 照片内容 | 多人合影、讲师特写、会场氛围、互动花絮 |
| 照片数量 | 30-150 张/次 |
| 精修风格 | 商务自然调色、保留质感、不过度美颜 |
| 文案调性 | 正能量、干练专业、有温度 |

---

## 核心能力

- 📷 **批量智能筛选**：分层质量打分（清晰度 / 曝光 / 构图 / 人像）+ 三路聚类分组（VL 标签 + 感知哈希 + 语义 embedding），组内按综合分精选 TOP N
- 🔍 **严格去重**：沙龙场景采用"仅像素级连拍去重"口径，只有构图几乎一致的连拍才会被合并，同人同背景不同姿势/角度不再误删
- ✨ **AI 精修**：按人物类别（男 / 女 / 儿童 / 长者 / 合照）选择对应预设，商务自然风格
- 📝 **文案生成**：多风格可选，支持地点 + 活动名称作为提示词注入，文案自然带出活动主题
- 🎯 **VIP 会员体系**：分档套餐 + 每日次数限制 + 次数套餐包
- 📦 **历史记录**：处理任务本地保存，支持回看与统计

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | uni-app 3.0 + Vue 3 + TypeScript + Pinia + Sass |
| 后端 | FastAPI + Python 3.11 + SQLAlchemy 2.0 |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 迁移 | Alembic |
| 任务队列 | Celery + Redis（生产） |
| 对象存储 | 阿里云 OSS / 腾讯云 COS |
| AI 能力 | 美图云修（精修）/ 腾讯云 IAI（人脸）/ 通义千问 Qwen-VL（标签/embedding）/ LLM（文案） |
| 部署 | Docker Compose |

---

## 项目结构

```
travel-photo/
├── backend/                        # FastAPI 后端
│   ├── app/
│   │   ├── ai/                     # AI 能力（筛选/聚类/精修/文案/分类）
│   │   │   ├── screener_real.py    # 真实智能筛选（分层打分 + 三路聚类）
│   │   │   ├── caption_gen.py      # 文案生成（RAG + LLM）
│   │   │   ├── photo_classifier.py # 人物分类（男/女/儿童/长者/合照）
│   │   │   └── ...
│   │   ├── api/v1/                 # RESTful 端点
│   │   │   ├── auth.py             # 认证
│   │   │   ├── photos.py           # 照片上传
│   │   │   ├── tasks.py            # 处理任务
│   │   │   ├── captions.py         # 文案生成
│   │   │   ├── quota.py            # 额度
│   │   │   ├── vip.py              # VIP 会员
│   │   │   ├── packs.py            # 次数套餐包
│   │   │   └── health.py           # 健康检查
│   │   ├── core/                   # 核心（config/security）
│   │   ├── db/                     # 数据库会话、迁移
│   │   ├── models/                 # SQLAlchemy ORM 模型
│   │   ├── schemas/                # Pydantic 数据模型
│   │   ├── services/               # 业务服务层（存储、任务）
│   │   └── main.py                 # FastAPI 入口
│   ├── tests/                      # pytest 测试
│   ├── alembic.ini
│   ├── Dockerfile
│   └── pyproject.toml
│
├── travel-photo-miniprogram/       # 微信小程序前端
│   └── src/
│       ├── api/                    # 请求封装
│       ├── components/             # 公共组件（照片上传、额度指示等）
│       ├── pages/                  # 12 个页面
│       │   ├── index/              # 首页
│       │   ├── upload/             # 照片上传
│       │   ├── processing/         # AI 处理进度
│       │   ├── result/             # 筛选结果
│       │   ├── preview/            # 预览
│       │   ├── screen-preview/     # 筛选预览
│       │   ├── retouching/         # 精修
│       │   ├── caption/            # 文案生成
│       │   ├── vip/                # VIP 中心
│       │   ├── quota/              # 我的额度
│       │   ├── history/            # 历史记录
│       │   └── mine/               # 个人中心
│       ├── stores/                 # Pinia 状态管理
│       ├── utils/                  # 工具函数
│       ├── App.vue
│       ├── main.ts
│       ├── manifest.json           # uni-app 应用配置
│       └── pages.json              # 路由配置
│
├── scripts/                        # 运维脚本
├── test_e2e/                       # 端到端测试
├── docker-compose.yml
└── 产品 & 技术文档（BRD/MRD/PRD/技术方案/成本拆解）
```

---

## 快速开始

### 前端（微信小程序）

```bash
cd travel-photo-miniprogram
npm install --registry https://registry.npmmirror.com
npm run dev:mp-weixin
```

在微信开发者工具中导入 `travel-photo-miniprogram/dist/dev/mp-weixin` 目录，使用测试号或自有 AppID 编译运行。

> 默认支持 Mock 模式，无需后端即可完整体验「上传 → 筛选 → 精修 → 文案」全流程。

### 后端

```bash
cd backend
pip install -e ".[dev]"
cp .env.example .env   # 按需填写 LLM_API_KEY、COS 密钥、IQA 凭据等
uvicorn app.main:app --reload --port 8000
```

### 测试

```bash
cd backend
pytest tests/ -v
```

---

## 核心链路说明

一次完整的照片处理任务（`backend/app/ai/`）大致流程：

```
照片上传（COS 预签名直传）
  → 单图下载与预处理
  → 分层质量打分（清晰度/曝光/构图/人像）
  → 三路聚类分组（VL 标签 + 感知哈希 + 语义 embedding，OR 合并）
  → 组内按综合分精选 TOP N
  → 美图云修精修（按人物类别选预设）
  → 文案生成（RAG + LLM，注入地点与活动名称）
```

去重策略详见 `backend/app/core/config.py` 中的 `DEDUP_*` 阈值与 `backend/app/ai/screener_real.py` 的聚类实现。

---

## 文档索引

- 📘 [BRD 商业需求文档](./BRD-旅行照片AI处理工具-商业需求文档.md)
- 📗 [MRD 市场需求文档](./MRD-旅行照片AI处理工具-市场需求文档.md)
- 📕 [PRD 产品需求文档](./PRD-旅行照片AI处理工具-产品需求文档.md)
- 🔧 [技术实现方案-旅行照片AI处理工具](./技术实现方案-旅行照片AI处理工具.md)
- 🔧 [技术实现方案-个人创业者沙龙场景改版](./技术实现方案-个人创业者沙龙场景改版.md)
- 📋 [产品改版需求文档-个人创业者沙龙场景](./产品改版需求文档-个人创业者沙龙场景.md)
- 🔬 [技术方案-人像质量打分筛选](./技术方案-人像质量打分筛选.md)
- 💰 [成本拆解-500张照片单次处理](./成本拆解-500张照片单次处理.md)
- 🔭 [技术可行性调研报告](./技术可行性调研报告-500张批量处理与AI精修.md)
- 📑 [文档索引总览](./README-旅行照片AI处理工具-文档索引.md)

---

## License

Private - All rights reserved
