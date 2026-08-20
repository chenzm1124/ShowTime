# 途吖（Tuya）· 旅行照片AI处理工具

> **📌 产品名确认**：本仓库项目正式名称为 **"途吖"**（英文名：Tuya），定位为"帮助用户处理旅途照片的AI小助手"。"旅行照片AI处理工具"为产品类型描述。
> 本地工作区目录：`travel-photo/`。

## 项目简介

**途吖** 是一款基于微信小程序的旅行照片 AI 智能处理工具，专注于解决旅行用户"照片太多挑不过来、修图太累、文案不会写"的三大痛点。通过 AI 一站式完成 **智能筛选 → AI 精修 → 文案生成**，让用户从几百张旅行照片中快速获得可分享的高质量内容。

核心场景：旅行结束当晚，把 100-500 张照片丢给途吖，几分钟后得到 9 张精修图 + 一条朋友圈文案。

## 核心能力

- 📷 **批量智能筛选**：从上传照片中识别重复构图、相似场景，自动挑选质量最高的 1-2 张/人/景
- ✨ **AI 精修**：人像照与景观照分别走专属模板，输出朋友圈分享标准的高质量图片
- 📝 **文案生成**：5 种风格可选（轻松调侃 / 文艺清新 / 简洁有力 / 温暖治愈 / 幽默搞怪），每种风格生成 5 条候选，可编辑可复制
- 🎯 **VIP 会员体系**：3 档套餐（19.9 / 39.9 / 69.9 元），免费 20 张/次，VIP1-3 分别 50/80/150 张/次、**每日 3/5/7 次**；另设次数套餐包 9.9~39.9 元（1~7 次批量处理，过期清零）
- 📦 **历史记录**：所有处理任务本地保存，支持九宫格回看与统计概览
- 🪙 **额度管理**：3 次免费试用 + 每日 2 次广告解锁

## 产品截图（占位）

| 首页 | 上传 | 处理进度 | 结果 | 文案 | VIP |
|------|------|---------|------|------|-----|
| 🌸 LOGO + 渐变 Hero | 步骤条 + 网格上传 | 圆环进度 | 分组卡片 | 5 种风格 | 3 档套餐 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | uni-app 3.0 + Vue 3 + TypeScript + Pinia + Sass |
| 后端 | FastAPI + Python 3.11 + SQLAlchemy 2.0 |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 迁移 | Alembic |
| 任务队列 | Celery + Redis（生产） |
| 对象存储 | 阿里云 OSS / 腾讯云 COS（生产） |
| AI 能力 | 美图云修（精修）/ 阿里通义 / Gemini（文案）/ CLIP（特征） |
| 部署 | Docker Compose |

## 项目结构

```
travel-photo/
├── backend/                       # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/                # RESTful 端点 (auth/quiz/photo/task/quota/caption/recommend)
│   │   ├── core/                  # 核心 (config/security/database)
│   │   ├── db/                    # 数据库会话、迁移
│   │   ├── models/                # SQLAlchemy ORM 模型
│   │   ├── schemas/               # Pydantic 数据模型
│   │   ├── services/              # 业务服务层（AI 调用、存储）
│   │   └── main.py                # FastAPI 入口
│   ├── data/                      # 静态配置
│   ├── tests/                     # pytest 测试
│   ├── alembic.ini
│   ├── Dockerfile
│   └── pyproject.toml
│
├── travel-photo-miniprogram/      # 途吖微信小程序（主前端）
│   └── src/
│       ├── api/                   # 请求封装 (auth/photo/task/quota/caption/request)
│       ├── components/            # 公共组件
│       │   ├── tp-photo-uploader/ # 照片上传
│       │   ├── tp-quota-indicator/# 额度指示
│       │   └── tp-vip-card/       # VIP 卡片
│       ├── pages/                 # 9 个页面
│       │   ├── index/             # 首页
│       │   ├── upload/            # 照片上传
│       │   ├── processing/        # AI 处理进度
│       │   ├── result/            # 筛选结果
│       │   ├── caption/           # 文案生成
│       │   ├── vip/               # VIP 中心
│       │   ├── quota/             # 我的额度
│       │   ├── history/           # 历史记录
│       │   └── mine/              # 个人中心
│       ├── stores/                # Pinia 状态 (user/quota/task)
│       ├── utils/                 # 工具 (upload/mock/format)
│       ├── polyfills.ts           # 运行时 polyfill 兜底
│       ├── App.vue
│       ├── main.ts
│       ├── manifest.json          # uni-app 应用配置
│       ├── pages.json             # 路由配置
│       └── uni.scss               # 全局样式变量
│
├── miniprogram/                   # 早期版本的备份（人格测评，弃用）
├── scripts/                       # 运维脚本
├── docker-compose.yml
└── docs/                          # 文档目录
    ├── BRD-旅行照片AI处理工具-商业需求文档.md
    ├── MRD-旅行照片AI处理工具-市场需求文档.md
    ├── PRD-旅行照片AI处理工具-产品需求文档.md
    ├── 技术实现方案-旅行照片AI处理工具.md
    ├── 成本拆解-500张照片单次处理.md
    └── 技术可行性调研报告-500张批量处理与AI精修.md
```

## 快速开始

### 前端（微信小程序）

```bash
cd travel-photo-miniprogram
npm install --registry https://registry.npmmirror.com
npm run dev:mp-weixin
```

在微信开发者工具中导入 `travel-photo-miniprogram/dist/build/mp-weixin` 目录，使用测试号或自有 AppID 编译运行。

**Mock 模式**：默认 `useMock = true`，无需后端即可完整体验"上传→筛选→精修→文案"全流程。

### 后端

```bash
cd backend
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 测试

```bash
cd backend
pytest tests/ -v
```

## 商业模式

| 角色 | 权益 | 价格 |
|------|------|------|
| 免费用户 | 20 张/次，3 次免费试用 + 每日 2 次广告解锁 | ¥0 |
| VIP1 | 50 张/次，**3 次/天**，无广告 | ¥19.9/月 |
| VIP2 | 80 张/次，**5 次/天**，无广告 | ¥39.9/月 |
| VIP3 | 150 张/次，**7 次/天**，无广告 | ¥69.9/月 |
| 次数套餐包 | 9.9 ~ 39.9 元（1~7 次批量处理，30~100 张/次，过期清零） | 按次 |

500 张照片单次处理真实成本 **0.30 ~ 1.42 元**，VIP 套餐毛利率可达 75% ~ 96%，商业模型健康。

## 核心数据

| 指标 | 数值 | 来源 |
|------|------|------|
| 旅拍市场规模（2024） | ~400 亿元 | 行业报告 |
| 旅游摄影市场（2025 预测） | 2000 亿元+ | 行业报告 |
| 用户平均旅行拍摄量 | 200-500 张/次 | 用户调研 |
| 照片最终分享率 | <5% | 用户调研 |
| 用户付费意愿 | 72% | 用户调研 |

## 文档索引

- 📘 [BRD 商业需求文档](./BRD-旅行照片AI处理工具-商业需求文档.md)
- 📗 [MRD 市场需求文档](./MRD-旅行照片AI处理工具-市场需求文档.md)
- 📕 [PRD 产品需求文档](./PRD-旅行照片AI处理工具-产品需求文档.md)
- 🔧 [技术实现方案](./技术实现方案-旅行照片AI处理工具.md)
- 💰 [成本拆解报告](./成本拆解-500张照片单次处理.md)
- 🔬 [技术可行性调研报告](./技术可行性调研报告-500张批量处理与AI精修.md)
- 📑 [文档索引总览](./README-旅行照片AI处理工具-文档索引.md)

## 开发状态

✅ **第一阶段完成** - 核心功能开发完毕（演示模式）

- ✅ 首页、9 个页面、Pinia 状态管理
- ✅ Mock 模式可独立运行（无后端）
- ⏳ 真实 AI 筛选/精修接口对接
- ⏳ 后端 FastAPI 全量实现
- ⏳ 微信支付集成
- ⏳ iOS/Android 独立 App

## License

Private - All rights reserved
