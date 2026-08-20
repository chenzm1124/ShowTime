# 旅行照片AI处理工具 · 技术实现方案

> **📌 产品名确认**：本技术方案所述产品正式名称为 **"途吖"**（英文名：Tuya）。
> **文档版本**：V1.0
> **编制日期**：2026年7月2日
> **基于文档**：[PRD V1.1](./PRD-旅行照片AI处理工具-产品需求文档.md)
> **目标读者**：研发团队、技术负责人、架构师
> **核心目标**：基于PRD中的会员体系（20/50/80/150张+3次试用+广告解锁），设计端到端可落地的技术方案

---

## 📋 文档结构

1. [总体技术架构](#一总体技术架构)
2. [前端技术栈与架构](#二前端技术栈与架构)
3. [后端技术栈与架构](#三后端技术栈与架构)
4. [AI服务层技术方案](#四ai服务层技术方案)
5. [核心模块详细设计](#五核心模块详细设计)
6. [数据库设计](#六数据库设计)
7. [第三方服务集成](#七第三方服务集成)
8. [部署与运维](#八部署与运维)
9. [研发计划（10周冲刺）](#九研发计划10周冲刺)
10. [团队配置与预算](#十团队配置与预算)
11. [风险与质量保障](#十一风险与质量保障)

---

## 一、总体技术架构

### 1.1 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                        【客户端层】                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ 微信小程序   │  │  iOS App    │  │ Android App  │  (V2.0)  │
│  │  (uni-app)  │  │  (Flutter)  │  │  (Flutter)   │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────────┬───────────────────────────────────┘
                               │ HTTPS / WebSocket
┌──────────────────────────────▼───────────────────────────────────┐
│                       【接入层 / CDN】                             │
│  ┌──────────────┐  ┌──────────────┐                              │
│  │ 腾讯云CDN    │  │ API网关       │  (Nginx + Spring Cloud      │
│  │ 静态资源+图片 │  │ 限流/鉴权/日志 │   Gateway / Kong)          │
│  └──────────────┘  └──────────────┘                              │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                     【业务服务层 - 微服务】                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ 用户服务  │  │ 任务服务  │  │ 照片服务  │  │ 支付服务  │        │
│  │ (auth)   │  │ (task)   │  │ (photo)  │  │ (pay)    │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ 额度服务  │  │ 文案服务  │  │ 分享服务  │  │ 统计服务  │        │
│  │ (quota)  │  │ (caption)│  │ (share)  │  │ (stats)  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                     【AI能力层 - 核心】                            │
│  ┌──────────────────────────────────────────────────┐           │
│  │  AI 智能筛选服务 (screener)                       │           │
│  │  - CLIP特征提取 (CLIP ViT-B/32)                  │           │
│  │  - 人脸检测 (RetinaFace)                         │           │
│  │  - 构图聚类 (HDBSCAN)                            │           │
│  │  - 质量评分 (自训练CNN)                          │           │
│  └──────────────────────────────────────────────────┘           │
│  ┌──────────────────────────────────────────────────┐           │
│  │  AI 智能精修服务 (retoucher)                      │           │
│  │  - 美图云修API（外部，人像）                      │           │
│  │  - 醒图API（备选）                                │           │
│  │  - 自建（V2.0：GFPGAN+SD）                       │           │
│  └──────────────────────────────────────────────────┘           │
│  ┌──────────────────────────────────────────────────┐           │
│  │  AI 文案生成服务 (caption-gen)                    │           │
│  │  - 通义千问VL (国内主)                            │           │
│  │  - Gemini 2.0 Flash Lite (国际备)                │           │
│  │  - 模板引擎 (兜底)                                │           │
│  └──────────────────────────────────────────────────┘           │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                     【消息队列 & 任务调度】                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Redis       │  │  Celery      │  │  XXL-JOB     │          │
│  │  (缓存/限流) │  │  (异步任务)  │  │  (定时任务)  │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                       【数据层】                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │PostgreSQL│  │  Redis   │  │ COS/OSS  │  │  Faiss/  │        │
│  │(主业务)  │  │ (缓存)   │  │ (照片)   │  │  Milvus  │        │
│  └──────────┘  └──────────┘  └──────────┘  │(向量库)  │        │
│                                              └──────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 架构设计原则

| 原则 | 说明 | 应用 |
|------|------|------|
| **MVP优先** | 优先实现20张免费版+3次试用，VIP用配置化支持 | 服务配置化，避免硬编码 |
| **微服务化** | 业务模块按领域拆分，单服务可独立部署 | 8个核心微服务 |
| **AI异步化** | 照片处理是CPU/GPU密集型，必须异步 | 任务队列 + 状态轮询 |
| **可降级** | 第三方AI服务故障时降级到自建或基础算法 | 熔断器模式 |
| **成本可控** | 免费用户是最大群体，需严控成本 | 多档配额 + 缓存 + 批量调用 |
| **合规优先** | 国内用户为主，数据不出境 | 国内云为主+国内大模型 |

### 1.3 技术选型总览

| 层级 | 技术选型 | 理由 |
|------|---------|------|
| **客户端** | uni-app + Vue 3 | 跨端，团队熟悉度高 |
| **客户端语言** | TypeScript | 类型安全，提升可维护性 |
| **API网关** | Nginx + Spring Cloud Gateway | 成熟稳定，社区丰富 |
| **后端框架** | Python FastAPI (主) + Java Spring Boot (备) | AI生态完善，开发效率高 |
| **AI推理** | PyTorch 2.x + ONNX Runtime + Triton Inference Server | 业界标准 |
| **数据库** | PostgreSQL 15 + Redis 7 | 成熟稳定，支持JSON |
| **任务队列** | Celery + Redis | 异步处理，与FastAPI无缝集成 |
| **消息推送** | 微信小程序订阅消息 | 微信生态原生支持 |
| **对象存储** | 腾讯云COS | 微信小程序原生支持 |
| **向量数据库** | Faiss (小规模) / Milvus (大规模) | V1.0用Faiss，V2.0切换Milvus |
| **CI/CD** | GitHub Actions + Docker + 阿里云容器服务 | 自动化部署 |
| **监控** | Prometheus + Grafana + Sentry | 全链路监控 |

---

## 二、前端技术栈与架构

### 2.1 客户端技术栈

| 项目 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **框架** | uni-app | 3.x | 跨端开发，编译到微信小程序/H5/App |
| **语言** | TypeScript | 5.x | 类型安全 |
| **UI组件** | uView UI 2.x | 跨端UI | 减少重复开发 |
| **状态管理** | Pinia | 2.x | Vue 3官方推荐 |
| **网络请求** | uni.request + axios | - | 统一封装 |
| **图片处理** | uni.compressImage | - | 客户端压缩 |
| **支付** | wx.requestPayment | - | 微信支付 |
| **广告** | 微信广告SDK | - | Banner/激励视频/插屏 |
| **日志** | uni.$emit + Sentry | - | 错误上报 |

### 2.2 目录结构

```
miniprogram/
├── src/
│   ├── api/                      # API接口层
│   │   ├── request.ts            # 统一请求封装（带token/重试）
│   │   ├── auth.ts               # 微信登录
│   │   ├── photo.ts              # 照片相关
│   │   ├── task.ts               # 任务相关
│   │   ├── quota.ts              # 额度、广告
│   │   ├── vip.ts                # VIP套餐
│   │   └── recommend.ts          # 文案推荐
│   ├── pages/                    # 页面
│   │   ├── index/                # 首页
│   │   ├── upload/               # 上传照片
│   │   ├── processing/           # 处理进度
│   │   ├── result/               # 处理结果
│   │   ├── share/                # 分享
│   │   ├── history/              # 历史记录
│   │   ├── vip/                  # VIP中心
│   │   ├── quota/                # 额度管理
│   │   └── mine/                 # 我的
│   ├── components/               # 公共组件
│   │   ├── PhotoUploader.vue     # 照片上传组件
│   │   ├── QuotaIndicator.vue    # 额度指示器
│   │   ├── VipCard.vue           # VIP卡片
│   │   ├── AdDialog.vue          # 广告弹窗
│   │   ├── CaptionEditor.vue     # 文案编辑器
│   │   └── ProgressBar.vue       # 进度条
│   ├── composables/              # 组合式函数
│   │   ├── useQuota.ts           # 额度Hook
│   │   ├── useUpload.ts          # 上传Hook
│   │   ├── useTask.ts            # 任务Hook
│   │   ├── useAd.ts              # 广告Hook
│   │   └── useAudioPlayer.ts
│   ├── stores/                   # Pinia状态管理
│   │   ├── user.ts               # 用户状态
│   │   ├── quota.ts              # 额度状态
│   │   └── task.ts               # 任务状态
│   ├── utils/                    # 工具函数
│   │   ├── auth.ts               # 登录工具
│   │   ├── upload.ts             # 上传工具（分块+并发）
│   │   ├── format.ts             # 格式化
│   │   ├── analytics.ts          # 数据埋点
│   │   └── error.ts              # 错误处理
│   ├── static/                   # 静态资源
│   ├── App.vue                   # 根组件
│   ├── main.ts                   # 入口
│   ├── manifest.json             # uni-app配置
│   └── pages.json                # 页面配置
├── package.json
├── tsconfig.json
└── vite.config.ts
```

### 2.3 关键前端模块设计

#### 2.3.1 照片上传模块（核心难点）

**挑战**：
- 微信小程序 `wx.uploadFile` 单次仅1文件 + 并发上限10
- 500张照片需排队上传，体验差

**解决方案**：

```typescript
// src/utils/upload.ts
class BatchUploader {
  private queue: UploadTask[] = []
  private maxConcurrent = 5  // 保守并发，避免微信风控
  private chunkSize = 2 * 1024 * 1024  // 2MB分块
  private retryLimit = 3

  async uploadFiles(files: File[]): Promise<UploadResult[]> {
    // 1. 客户端压缩
    const compressed = await Promise.all(
      files.map(f => this.compress(f, { quality: 0.85 }))
    )

    // 2. 获取上传凭证（STS）
    const credentials = await this.getSTSCredentials(compressed.length)

    // 3. 分块+并发上传
    const tasks = compressed.map(file => ({
      file,
      chunks: this.createChunks(file),
      credentials
    }))

    // 4. 并发控制（5路并发）
    return await this.runWithConcurrency(tasks, this.maxConcurrent)
  }

  private async runWithConcurrency(
    tasks: UploadTask[],
    limit: number
  ): Promise<UploadResult[]> {
    const results: UploadResult[] = []
    const executing: Promise<void>[] = []

    for (const task of tasks) {
      const p = this.uploadOne(task).then(r => results.push(r))
      executing.push(p)
      if (executing.length >= limit) {
        await Promise.race(executing)
        executing.splice(executing.findIndex(p => p), 1)
      }
    }
    await Promise.all(executing)
    return results
  }
}
```

**性能指标**：
- 20张照片：1-2分钟（10Mbps带宽）
- 50张照片：3-4分钟
- 150张照片：8-10分钟

#### 2.3.2 额度管理 Hook

```typescript
// src/composables/useQuota.ts
export function useQuota() {
  const quota = ref<QuotaInfo | null>(null)
  const loading = ref(false)

  const fetchQuota = async () => {
    loading.value = true
    try {
      const res = await quotaApi.getQuota()
      quota.value = res.data
    } finally {
      loading.value = false
    }
  }

  // 检查是否可处理N张
  const canProcess = (photoCount: number): { ok: boolean; reason?: string } => {
    if (!quota.value) return { ok: false, reason: '额度未加载' }

    // 检查等级上限
    const maxPerTask = quota.value.current_quota.photos_per_task
    if (photoCount > maxPerTask) {
      return {
        ok: false,
        reason: `当前等级单次最多${maxPerTask}张，VIP可处理更多`
      }
    }

    // 检查剩余次数
    if (quota.value.member_type === 'free') {
      if (quota.value.trial_remaining > 0) return { ok: true }
      if (quota.value.ad_unlock_remaining_today > 0) return { ok: true }
      return { ok: false, reason: '免费次数已用完，请看广告或升级VIP' }
    }

    // VIP用户检查有效期
    if (new Date(quota.value.vip_expire_date) < new Date()) {
      return { ok: false, reason: 'VIP已到期，请续费' }
    }

    return { ok: true }
  }

  // 看广告解锁次数
  const watchAdForUnlock = async (): Promise<boolean> => {
    // 1. 调用微信广告SDK播放激励视频
    const adResult = await adService.showRewardedVideo()
    if (!adResult.completed) return false

    // 2. 通知后端解锁
    const res = await quotaApi.adUnlock({
      ad_type: 'rewarded_video',
      ad_platform: 'pangle',
      watch_duration_seconds: adResult.duration,
      ad_callback_data: adResult.verifyData
    })
    quota.value = res.data
    return res.code === 0
  }

  return { quota, loading, fetchQuota, canProcess, watchAdForUnlock }
}
```

#### 2.3.3 微信广告SDK集成

```typescript
// src/composables/useAd.ts
export function useAd() {
  // 激励视频广告实例
  const rewardedVideoAd = ref<any>(null)

  onMounted(() => {
    // 1. 创建激励视频广告
    rewardedVideoAd.value = uni.createRewardedVideoAd({
      adUnitId: 'adunit-xxxxxxxxxxxx'  // 微信广告平台申请
    })

    // 2. 监听广告加载
    rewardedVideoAd.value.onLoad(() => {
      console.log('激励视频加载成功')
    })

    // 3. 监听广告关闭
    rewardedVideoAd.value.onClose((res) => {
      // res.isEnded 表示是否完整观看
      if (res.isEnded) {
        // 用户完整观看，调用后端解锁
        onAdCompleted()
      } else {
        uni.showToast({ title: '需看完视频才能解锁', icon: 'none' })
      }
    })

    // 4. 预加载
    rewardedVideoAd.value.load()
  })

  const showRewardedVideo = (): Promise<{ completed: boolean; duration: number }> => {
    return new Promise((resolve) => {
      rewardedVideoAd.value.show()
        .then(() => {
          // 记录开始时间
          const startTime = Date.now()
          // 等待onClose回调
          // ...
        })
        .catch(err => {
          console.error('广告显示失败', err)
          resolve({ completed: false, duration: 0 })
        })
    })
  }

  return { showRewardedVideo }
}
```

### 2.4 前端关键页面设计

| 页面 | 核心组件 | 关键交互 |
|------|---------|---------|
| **首页** | QuotaIndicator, UploadButton | 显示当前额度，引导上传 |
| **上传页** | PhotoUploader, QuotaWarning | 选择照片，校验额度 |
| **处理进度** | ProgressBar, StageIndicator | 实时显示AI处理进度 |
| **筛选结果** | PhotoGroupCard, SelectedPhotoCard | 左右对比，支持手动调整 |
| **处理结果** | PhotoPreview, CaptionEditor | 预览精修效果，编辑文案 |
| **VIP中心** | VipCard, VipPlanTable | 展示3档套餐 |
| **额度管理** | QuotaDetail, AdButton | 查看额度，看广告解锁 |
| **历史记录** | HistoryList, HistoryItem | 展示过往处理 |

---

## 三、后端技术栈与架构

### 3.1 后端技术栈

| 项目 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **Web框架** | Python FastAPI | 0.110+ | 高性能异步框架 |
| **语言** | Python | 3.11+ | AI生态最佳 |
| **ORM** | SQLAlchemy 2.0 + asyncpg | - | 异步ORM |
| **数据库驱动** | asyncpg / aiomysql | - | 异步驱动 |
| **缓存** | redis-py (异步) | 5.x | Redis客户端 |
| **任务队列** | Celery + Redis broker | 5.x | 异步任务 |
| **对象存储** | 腾讯云COS SDK (Python) | - | COS客户端 |
| **认证** | python-jose + passlib | - | JWT Token |
| **日志** | loguru | - | 结构化日志 |
| **API文档** | FastAPI内置Swagger | - | 自动生成 |
| **测试** | pytest + pytest-asyncio | - | 单元/集成测试 |
| **依赖管理** | Poetry / pip-tools | - | 依赖锁定 |
| **部署** | Uvicorn + Gunicorn | - | ASGI服务器 |
| **容器化** | Docker + Docker Compose | - | 容器化 |

### 3.2 后端目录结构

```
backend/
├── app/
│   ├── main.py                    # FastAPI应用入口
│   ├── core/                      # 核心配置
│   │   ├── config.py              # 配置（环境变量）
│   │   ├── security.py            # JWT、加密
│   │   ├── deps.py                # 依赖注入
│   │   └── exceptions.py          # 自定义异常
│   ├── api/                       # API路由
│   │   └── v1/
│   │       ├── auth.py            # 微信登录、JWT
│   │       ├── user.py            # 用户信息
│   │       ├── photo.py           # 照片上传
│   │       ├── task.py            # 任务管理
│   │       ├── quota.py           # 额度管理⭐
│   │       ├── vip.py             # VIP套餐⭐
│   │       ├── ad.py              # 广告解锁⭐
│   │       ├── pay.py             # 支付
│   │       ├── caption.py         # 文案
│   │       └── share.py           # 分享
│   ├── models/                    # SQLAlchemy模型
│   │   ├── base.py
│   │   ├── user.py                # 用户（含试用、广告、VIP字段）⭐
│   │   ├── task.py
│   │   ├── photo.py
│   │   ├── order.py               # VIP订单
│   │   ├── ad_unlock.py           # 广告解锁记录⭐
│   │   ├── quota_log.py           # 额度流水⭐
│   │   └── vip_plan.py            # VIP套餐配置
│   ├── schemas/                   # Pydantic schemas
│   │   ├── user.py
│   │   ├── task.py
│   │   ├── quota.py
│   │   ├── vip.py
│   │   └── common.py
│   ├── services/                  # 业务服务层
│   │   ├── auth_service.py
│   │   ├── user_service.py
│   │   ├── task_service.py        # 任务编排（核心）
│   │   ├── quota_service.py       # 额度服务⭐
│   │   ├── vip_service.py         # VIP服务⭐
│   │   ├── ad_service.py          # 广告验证服务⭐
│   │   ├── pay_service.py
│   │   ├── oss_service.py         # 对象存储
│   │   ├── caption_service.py     # 文案生成
│   │   ├── anti_fraud.py          # 反作弊服务⭐
│   │   └── notification.py        # 消息通知
│   ├── ai/                        # AI服务层
│   │   ├── screener/              # 智能筛选
│   │   │   ├── feature_extractor.py  # CLIP特征提取
│   │   │   ├── face_detector.py      # 人脸检测
│   │   │   ├── clustering.py         # 构图聚类
│   │   │   └── quality_scorer.py     # 质量评分
│   │   ├── retoucher/             # 精修
│   │   │   ├── meitu_api.py       # 美图云修
│   │   │   └── pipeline.py        # 精修流水线
│   │   ├── caption_gen/           # 文案生成
│   │   │   ├── qwen_client.py     # 通义千问
│   │   │   ├── template_engine.py # 模板引擎（兜底）
│   │   │   └── prompt.py          # Prompt模板
│   │   └── common/
│   │       ├── model_loader.py    # 模型加载
│   │       ├── gpu_pool.py        # GPU资源池
│   │       └── cache.py           # AI结果缓存
│   ├── tasks/                     # Celery任务
│   │   ├── celery_app.py
│   │   ├── photo_tasks.py         # 照片处理任务
│   │   ├── cleanup_tasks.py       # 清理任务
│   │   └── scheduled_tasks.py     # 定时任务（每日重置广告次数等）
│   ├── db/                        # 数据库
│   │   ├── session.py             # 异步Session
│   │   ├── base.py
│   │   └── migrations/            # Alembic迁移
│   ├── utils/                     # 工具
│   │   ├── logger.py
│   │   ├── retry.py               # 重试装饰器
│   │   ├── circuit_breaker.py     # 熔断器
│   │   └── validators.py
│   └── middleware/                # 中间件
│       ├── auth.py                # JWT认证
│       ├── rate_limit.py          # 限流
│       ├── logging.py             # 日志
│       └── error_handler.py       # 统一错误处理
├── tests/                         # 测试
│   ├── conftest.py
│   ├── test_quota.py
│   ├── test_vip.py
│   ├── test_task.py
│   └── test_ai.py
├── scripts/                       # 运维脚本
│   ├── deploy.sh
│   ├── init_db.sh
│   └── seed_data.py
├── alembic.ini
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

### 3.3 微服务拆分

为简化MVP部署，V1.0采用**单体FastAPI应用**（8个业务模块共存一个进程），V2.0再按需拆分为微服务。

| 模块 | 路由前缀 | 主要职责 | 关键依赖 |
|------|---------|---------|---------|
| **auth** | /api/v1/auth | 微信登录、Token签发 | Redis |
| **user** | /api/v1/user | 用户信息、VIP状态 | PostgreSQL |
| **photo** | /api/v1/photos | 上传STS、删除 | COS, PostgreSQL |
| **task** | /api/v1/tasks | 创建任务、查询、回调 | Celery, Redis |
| **quota** ⭐ | /api/v1/quota | 额度查询、广告解锁、扣减 | PostgreSQL, Redis |
| **vip** ⭐ | /api/v1/vip | 套餐查询、升级、续费 | PostgreSQL |
| **ad** ⭐ | /api/v1/ads | 广告回调、奖励发放 | PostgreSQL, Redis |
| **pay** | /api/v1/pay | 微信支付订单、回调 | 微信支付SDK |
| **caption** | /api/v1/captions | 文案生成 | Qwen/Gemini |
| **share** | /api/v1/share | 分享统计 | PostgreSQL |

### 3.4 后端核心服务设计

#### 3.4.1 额度服务（核心难点）⭐

```python
# app/services/quota_service.py
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.models.quota_log import QuotaLog
from app.core.exceptions import QuotaExceededError

class QuotaService:
    """
    额度管理服务
    - 试用次数（3次/30天）
    - 广告解锁（每日2次）
    - VIP用户（50/80/150张/次，每日 3/5/7 次）
    - 反作弊
    """

    # 用户等级对应的单次处理上限
    PHOTOS_PER_TASK = {
        'free': 20,
        'vip1': 50,
        'vip2': 80,
        'vip3': 150
    }

    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis

    async def check_and_consume(
        self,
        user_id: str,
        photo_count: int
    ) -> QuotaCheckResult:
        """检查额度并扣减（创建任务时调用）"""
        # 1. 加分布式锁（防并发）
        lock_key = f"quota:lock:{user_id}"
        async with self.redis.lock(lock_key, timeout=5):
            user = await self._get_user(user_id)

            # 2. 校验上传数量
            max_per_task = self.PHOTOS_PER_TASK[user.member_type]
            if photo_count > max_per_task:
                raise QuotaExceededError(
                    f"当前等级单次最多{max_per_task}张",
                    code=4002
                )

            # 3. VIP用户：检查有效期
            if user.member_type != 'free':
                if user.member_expire_date < datetime.now():
                    raise QuotaExceededError("VIP已到期", code=4004)

                # VIP按日限速：3/5/7 次/天（vip1/vip2/vip3），跨天重置
                remaining = self._get_vip_daily_remaining(user)
                if remaining <= 0:
                    raise QuotaExceededError("VIP当日次数已用完", code=4003)
                await self._log_quota_change(
                    user_id, 'task_consume', 0, 0, 0,
                    remark=f'VIP{user.member_type}处理{photo_count}张'
                )
                return QuotaCheckResult(ok=True, remaining='unlimited')

            # 4. 免费用户：检查试用/广告次数
            if user.trial_remaining > 0:
                new_trial = user.trial_remaining - 1
                user.trial_remaining = new_trial
                await self.db.commit()
                await self._log_quota_change(
                    user_id, 'trial_consume', -1,
                    user.trial_remaining + 1, new_trial
                )
                return QuotaCheckResult(
                    ok=True,
                    remaining=f"试用{new_trial}次"
                )

            if user.ad_unlock_count_today > 0:
                # 注意：广告解锁的次数只能在当日使用
                new_ad = user.ad_unlock_count_today - 1
                user.ad_unlock_count_today = new_ad
                await self.db.commit()
                await self._log_quota_change(
                    user_id, 'ad_consume', -1,
                    user.ad_unlock_count_today + 1, new_ad
                )
                return QuotaCheckResult(
                    ok=True,
                    remaining=f"广告{new_ad}次"
                )

            raise QuotaExceededError(
                "免费次数已用完，请看广告或升级VIP",
                code=4001
            )

    async def ad_unlock(
        self,
        user_id: str,
        ad_data: AdUnlockRequest
    ) -> AdUnlockResult:
        """广告解锁处理"""
        user = await self._get_user(user_id)

        # 1. 反作弊检查
        await self._anti_fraud_check(user, ad_data)

        # 2. 检查每日上限
        if user.ad_unlock_count_today >= 2:
            raise QuotaExceededError("今日广告次数已达上限", code=4006)

        # 3. VIP不能使用广告
        if user.member_type != 'free':
            raise QuotaExceededError("VIP用户无需看广告", code=4008)

        # 4. 校验广告观看完成
        if ad_data.watch_duration_seconds < 15:
            raise QuotaExceededError("广告未看完", code=4005)

        # 5. 增加次数
        user.ad_unlock_count_today += 1
        user.last_ad_unlock_date = datetime.now()

        # 6. 记录广告解锁
        ad_record = AdUnlock(
            user_id=user_id,
            ad_type=ad_data.ad_type,
            ad_platform=ad_data.ad_platform,
            watch_duration_seconds=ad_data.watch_duration_seconds,
            is_completed=True,
            unlocked_count=1,
            expire_date=datetime.now().replace(hour=23, minute=59, second=59)
        )
        self.db.add(ad_record)

        await self.db.commit()

        await self._log_quota_change(
            user_id, 'ad_unlock', 1,
            user.ad_unlock_count_today - 1, user.ad_unlock_count_today
        )

        return AdUnlockResult(
            unlocked_count=1,
            expire_at=ad_record.expire_date,
            ad_unlock_remaining_today=2 - user.ad_unlock_count_today
        )

    async def _anti_fraud_check(self, user: User, ad_data: AdUnlockRequest):
        """反作弊校验"""
        # 1. 同一用户30秒内仅可解锁1次
        recent = await self._get_recent_ad_unlock(user.id, seconds=30)
        if recent:
            raise QuotaExceededError("操作过于频繁", code=4007)

        # 2. 新用户24小时内不开放（防黑产）
        if (datetime.now() - user.created_at) < timedelta(hours=24):
            if user.created_at > datetime.now() - timedelta(minutes=5):
                # 刚注册+立即看广告 = 高风险
                raise QuotaExceededError("新用户保护期", code=4007)

        # 3. 设备/IP维度去重
        # （如发现同一设备指纹/IP当日超过N次，触发风控）
        device_count = await self._count_device_unlocks_today(
            ad_data.device_fingerprint
        )
        if device_count >= 6:
            raise QuotaExceededError("设备异常", code=4007)

    async def reset_daily_ad_count(self):
        """每日0点重置广告解锁次数（定时任务）"""
        await self.db.execute(
            update(User)
            .values(ad_unlock_count_today=0, last_ad_unlock_date=datetime.now())
        )
        await self.db.commit()
```

#### 3.4.2 任务编排服务

```python
# app/services/task_service.py
class TaskService:
    """任务编排服务 - 串联筛选/精修/文案"""

    async def create_task(
        self,
        user_id: str,
        photo_urls: List[str],
        options: TaskOptions
    ) -> Task:
        # 1. 额度校验与扣减
        await quota_service.check_and_consume(
            user_id, len(photo_urls)
        )

        # 2. 创建任务记录
        task = Task(
            user_id=user_id,
            status='pending',
            total_photos=len(photo_urls),
            options=options.dict()
        )
        self.db.add(task)
        await self.db.commit()

        # 3. 创建Photo记录
        photos = [
            Photo(
                task_id=task.id,
                user_id=user_id,
                original_url=url,
                composition_group=None,  # 待AI处理
                quality_score=None
            )
            for url in photo_urls
        ]
        self.db.add_all(photos)
        await self.db.commit()

        # 4. 异步派发AI处理任务
        process_photo_task.delay(task.id)

        return task

    async def get_task_status(self, task_id: str) -> TaskStatus:
        """查询任务状态（含进度）"""
        task = await self._get_task(task_id)
        # 从Redis获取实时进度
        progress = await self.redis.get(f"task:progress:{task_id}")
        return TaskStatus(
            task_id=task.id,
            status=task.status,
            progress=progress or 0,
            current_stage=self._get_current_stage(task),
            result_url=task.result_url if task.status == 'completed' else None
        )
```

---

## 四、AI服务层技术方案

### 4.1 AI服务总体设计

```
┌─────────────────────────────────────────────────────────────┐
│                  AI服务层架构                                 │
│                                                              │
│  ┌──────────────────────────────────────────────┐           │
│  │  API层：FastAPI（独立端口8001）              │           │
│  │  /screener/cluster  /retoucher/portrait      │           │
│  │  /caption/generate  /health                   │           │
│  └──────────────────────────────────────────────┘           │
│       ↓                                                     │
│  ┌──────────────────────────────────────────────┐           │
│  │  调度层：任务队列 (Celery) + GPU资源池         │           │
│  │  - GPU Pool: 2x A10 / 4x T4                 │           │
│  │  - 任务优先级: VIP > Free                     │           │
│  └──────────────────────────────────────────────┘           │
│       ↓                                                     │
│  ┌──────────────────────────────────────────────┐           │
│  │  模型层：模型仓库（按需加载）                  │           │
│  │  - CLIP ViT-B/32 (特征提取)                   │           │
│  │  - RetinaFace (人脸检测)                      │           │
│  │  - 美图云修API (人像精修)                     │           │
│  │  - 通义千问VL (文案生成)                      │           │
│  │  - 自训练质量评分模型                          │           │
│  └──────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 智能筛选服务

**核心流程**（PRD FR-201~FR-209）：

```
输入：150张照片URL列表
       ↓
Step 1: 客户端预筛（用户已选20~150张）
       ↓
Step 2: 服务端拉取 + 解压
       ↓
Step 3: 特征提取（CLIP ViT-B/32）
       - 输出: 512维向量 × 150
       - 耗时: ~2秒（GPU批处理）
       ↓
Step 4: 构图聚类（HDBSCAN）
       - 算法: 层次密度聚类
       - 阈值: 余弦相似度 ≥ 0.92
       - 输出: N个构图组
       - 耗时: <1秒
       ↓
Step 5: 人脸检测（RetinaFace）
       - 标记每张照片是否含人脸
       - 区分人物照 vs 景观照
       - 耗时: ~3秒
       ↓
Step 6: 质量评分（自训练CNN）
       - 维度: 清晰度、曝光、构图、表情
       - 输出: 0-100分
       - 耗时: ~3秒
       ↓
Step 7: 每组精选
       - 人物最佳1张（人脸分最高的）
       - 景观最佳1张（构图分最高的）
       - 输出: 2N张精修候选
       - 耗时: <1秒
       ↓
总计: 约10秒/150张
```

**核心代码**：

```python
# app/ai/screener/pipeline.py
import torch
import clip
from PIL import Image
import hdbscan
import numpy as np
from typing import List, Tuple
from app.ai.screener.face_detector import detect_faces
from app.ai.screener.quality_scorer import QualityScorer

class PhotoScreener:
    """智能筛选器 - 输入照片列表，输出每组最佳2张"""

    def __init__(self, device='cuda'):
        self.device = device
        # 1. 加载CLIP
        self.clip_model, self.clip_preprocess = clip.load(
            "ViT-B/32", device=device
        )
        # 2. 加载人脸检测
        self.face_detector = RetinaFaceDetector(device=device)
        # 3. 加载质量评分
        self.quality_scorer = QualityScorer(device=device)

    async def screen(
        self,
        photo_urls: List[str]
    ) -> ScreeningResult:
        """主入口"""
        # 1. 并发下载图片
        images = await self._download_batch(photo_urls, max_concurrent=20)

        # 2. CLIP特征提取
        features = await self._extract_features_batch(images)

        # 3. 构图聚类
        groups = self._cluster_by_composition(features)

        # 4. 人脸检测 + 质量评分
        face_results = self.face_detector.batch_detect(images)
        quality_scores = self.quality_scorer.batch_score(images)

        # 5. 每组精选2张
        selected = self._select_best_per_group(
            images, groups, face_results, quality_scores
        )

        return ScreeningResult(
            groups=groups,
            selected_photos=selected,
            total_original=len(images),
            total_selected=len(selected)
        )

    def _select_best_per_group(
        self,
        images: List[Image.Image],
        groups: np.ndarray,  # 构图组标签
        face_results: List[FaceResult],
        quality_scores: List[float]
    ) -> List[SelectedPhoto]:
        """每组选1人物+1景观，共2张"""
        unique_groups = set(groups)
        selected = []

        for group_id in unique_groups:
            group_indices = np.where(groups == group_id)[0]
            if len(group_indices) == 0:
                continue

            # 分类：人物照 vs 景观照
            portrait_indices = [
                i for i in group_indices
                if face_results[i].has_face
            ]
            landscape_indices = [
                i for i in group_indices
                if not face_results[i].has_face
            ]

            # 选最佳人物照
            if portrait_indices:
                best_portrait = max(
                    portrait_indices,
                    key=lambda i: quality_scores[i] * 0.6 +
                                  face_results[i].face_quality * 0.4
                )
                selected.append(SelectedPhoto(
                    original_index=best_portrait,
                    group_id=group_id,
                    type='portrait',
                    quality_score=quality_scores[best_portrait]
                ))

            # 选最佳景观照
            if landscape_indices:
                best_landscape = max(
                    landscape_indices,
                    key=lambda i: quality_scores[i]
                )
                selected.append(SelectedPhoto(
                    original_index=best_landscape,
                    group_id=group_id,
                    type='landscape',
                    quality_score=quality_scores[best_landscape]
                ))

        return selected

    async def _extract_features_batch(
        self,
        images: List[Image.Image]
    ) -> np.ndarray:
        """CLIP批处理特征提取"""
        batch_size = 32
        features_list = []

        for i in range(0, len(images), batch_size):
            batch = images[i:i+batch_size]
            # 预处理
            tensors = torch.stack([
                self.clip_preprocess(img) for img in batch
            ]).to(self.device)

            # 推理
            with torch.no_grad():
                features = self.clip_model.encode_image(tensors)
            features_list.append(features.cpu().numpy())

        return np.vstack(features_list)

    def _cluster_by_composition(
        self,
        features: np.ndarray
    ) -> np.ndarray:
        """HDBSCAN构图聚类"""
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=3,        # 至少3张才成组
            min_samples=2,
            metric='cosine',
            cluster_selection_epsilon=0.08
        )
        return clusterer.fit_predict(features)
```

### 4.3 智能精修服务

**精修策略**：
- 人物照：磨皮+瘦脸+美颜+调色 → 美图云修API
- 景观照：HDR+调色+构图优化 → 美图云修API

```python
# app/ai/retoucher/pipeline.py
import aiohttp
from typing import List

class PhotoRetoucher:
    """精修服务 - 调用美图云修API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.api_url = "https://openapi.meitu.com/v1/retouch"

    async def batch_retouch(
        self,
        photo_urls: List[str],
        types: List[str]  # 'portrait' or 'landscape'
    ) -> List[RetouchResult]:
        """批量精修"""
        tasks = [
            self._retouch_one(url, t)
            for url, t in zip(photo_urls, types)
        ]
        # 并发控制（5个/批，避免API限流）
        results = []
        for i in range(0, len(tasks), 5):
            batch = tasks[i:i+5]
            results.extend(await asyncio.gather(*batch))
        return results

    async def _retouch_one(
        self,
        url: str,
        photo_type: str
    ) -> RetouchResult:
        """单张精修"""
        # 人物照 vs 景观照用不同模板
        template = 'portrait_v2' if photo_type == 'portrait' else 'landscape_v2'

        params = {
            'api_key': self.api_key,
            'image_url': url,
            'template': template,
            'beauty_level': 3 if photo_type == 'portrait' else 0,
            'color_grade': 'travel_fresh'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_url,
                json=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()

        if data['code'] != 0:
            raise RetouchError(f"美图API错误: {data['message']}")

        return RetouchResult(
            original_url=url,
            retouched_url=data['data']['output_url'],
            cost=data['data'].get('cost', 0.10)  # 单张成本
        )
```

### 4.4 文案生成服务

```python
# app/ai/caption_gen/service.py
from openai import AsyncOpenAI

class CaptionService:
    """文案生成服务 - 主用通义千问VL，备Gemini"""

    def __init__(self):
        # 通义千问（国内主）
        self.qwen_client = AsyncOpenAI(
            api_key=settings.QWEN_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        # Gemini（国际备）
        self.gemini_client = AsyncOpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai"
        )

    async def generate_captions(
        self,
        photo_urls: List[str],
        location: Optional[str] = None,
        style: str = 'literary',
        count: int = 3
    ) -> List[str]:
        """生成多条候选文案"""
        # 1. 视觉理解（用VL模型读图）
        photo_descriptions = await self._describe_photos(photo_urls[:3])

        # 2. Prompt工程
        prompt = self._build_prompt(
            photo_descriptions, location, style, count
        )

        # 3. 调用大模型
        try:
            response = await self.qwen_client.chat.completions.create(
                model="qwen-vl-max",
                messages=[
                    {
                        "role": "system",
                        "content": "你是朋友圈文案高手，专为旅行照片创作简洁优美的中文文案。"
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.8
            )
            captions_text = response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Qwen API失败，降级到Gemini: {e}")
            captions_text = await self._gemini_fallback(prompt)

        # 4. 解析为列表
        captions = self._parse_captions(captions_text, count)
        return captions

    def _build_prompt(
        self,
        photo_descriptions: List[str],
        location: str,
        style: str,
        count: int
    ) -> str:
        style_map = {
            'literary': '文艺清新风',
            'humor': '幽默风趣风',
            'minimal': '简约高级风',
            'emotional': '情感故事风',
            'checkin': '地点打卡风'
        }
        return f"""请根据以下旅行照片信息，生成{count}条{style_map.get(style, '文艺清新风')}的朋友圈文案。

地点：{location or '未知'}
照片描述：{'; '.join(photo_descriptions)}

要求：
- 每条15-50字
- 风格：{style_map.get(style, '文艺清新风')}
- 不出现"#话题#"等标签
- 适合微信朋友圈发布

请直接输出{count}条文案，每行一条，不要编号。"""

    async def _gemini_fallback(self, prompt: str) -> str:
        """降级到Gemini"""
        response = await self.gemini_client.chat.completions.create(
            model="gemini-2.0-flash-lite",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.8
        )
        return response.choices[0].message.content
```

---

## 五、核心模块详细设计

### 5.1 任务处理全流程（端到端）

```
[客户端] 用户选择20张/50张/80张/150张照片
    ↓
[客户端] 批量上传到COS（带分块+并发控制）
    ↓
[客户端] 调用 POST /api/v1/tasks
    ↓
[后端 - quota_service] 校验用户额度（核心）
    ├─ VIP：检查有效期 + 等级上限
    └─ 免费：检查试用/广告次数
    ↓
[后端 - task_service] 创建Task + Photo记录
    ↓
[后端 - celery] 派发 process_photo_task 异步任务
    ↓
[AI - screener] 智能筛选（10-30秒）
    ├─ 特征提取 (CLIP)
    ├─ 构图聚类 (HDBSCAN)
    ├─ 人脸检测 (RetinaFace)
    └─ 质量评分 + 每组选2张
    ↓
[AI - retoucher] 精修（5-15秒/张，可并行）
    ├─ 人物照 → 美图云修人像模板
    └─ 景观照 → 美图云修景观模板
    ↓
[AI - caption_gen] 文案生成（5-10秒）
    ├─ VL模型理解图片
    └─ 大模型生成3-5条候选
    ↓
[后端] 保存结果到PostgreSQL
    ├─ 更新Photo.processed_url
    ├─ 写入caption
    └─ 更新Task.status = 'completed'
    ↓
[客户端] 轮询到完成，展示结果
```

### 5.2 微信支付集成

**支付流程**（用户购买VIP1/2/3）：

```
[客户端] 用户点击"升级VIP" → 选择套餐
    ↓
[客户端] POST /api/v1/pay/orders
    ↓
[后端] 创建Order记录
    ↓
[后端] 调用微信统一下单API
    ↓
[后端] 返回 prepay_id
    ↓
[客户端] wx.requestPayment 唤起支付
    ↓
[用户] 完成支付
    ↓
[微信] 回调 /api/v1/pay/wechat-callback
    ↓
[后端] 验签 + 更新Order状态 + 更新User.member_type
    ↓
[后端] 返回支付成功
    ↓
[客户端] 展示支付成功页
```

---

## 六、数据库设计

### 6.1 ER图

```
┌────────────────┐         ┌────────────────┐
│     User       │         │      Task      │
├────────────────┤         ├────────────────┤
│ user_id (PK)   │────────<│ task_id (PK)   │
│ openid (UK)    │         │ user_id (FK)   │
│ member_type    │         │ status         │
│ trial_remaining│         │ total_photos   │
│ ad_unlock_count│         │ result_photos  │
│ ...            │         │ ...            │
└────────────────┘         └────────────────┘
       │                          │
       │                          │
       ↓                          ↓
┌────────────────┐         ┌────────────────┐
│     Order      │         │     Photo      │
├────────────────┤         ├────────────────┤
│ order_id (PK)  │         │ photo_id (PK)  │
│ user_id (FK)   │         │ task_id (FK)   │
│ vip_level      │         │ user_id (FK)   │
│ amount         │         │ original_url   │
│ ...            │         │ processed_url  │
└────────────────┘         │ composition_grp│
                           │ quality_score  │
                           │ photo_type     │ ⭐新增（人物/景观）
                           │ caption        │
                           └────────────────┘
       │                          
       ↓                          
┌────────────────┐         ┌────────────────┐
│  AdUnlock      │         │  QuotaLog      │
├────────────────┤         ├────────────────┤
│ ad_unlock_id   │         │ log_id (PK)    │
│ user_id (FK)   │         │ user_id (FK)   │
│ ad_type        │         │ change_type    │
│ watch_duration │         │ change_count   │
│ unlocked_count │         │ before/after   │
│ expire_date    │         │ created_at     │
└────────────────┘         └────────────────┘
```

### 6.2 核心表结构（PostgreSQL）

```sql
-- 用户表（PRD实体1，含反作弊字段）
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    openid VARCHAR(64) UNIQUE NOT NULL,
    unionid VARCHAR(64),
    nickname VARCHAR(64),
    avatar_url TEXT,
    -- 会员
    member_type VARCHAR(16) DEFAULT 'free'
        CHECK (member_type IN ('free', 'vip1', 'vip2', 'vip3')),
    member_expire_date TIMESTAMPTZ,
    member_start_date TIMESTAMPTZ,
    -- 试用
    trial_remaining INT DEFAULT 3 CHECK (trial_remaining >= 0),
    trial_expire_date TIMESTAMPTZ,
    -- 广告
    ad_unlock_count_today INT DEFAULT 0,
    last_ad_unlock_date DATE,
    -- 反作弊
    device_fingerprint VARCHAR(128),
    register_ip VARCHAR(45),
    last_login_ip VARCHAR(45),
    -- 时间
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_openid ON users(openid);
CREATE INDEX idx_users_member_type ON users(member_type);
CREATE INDEX idx_users_device_fingerprint ON users(device_fingerprint);

-- 任务表（PRD实体2）
CREATE TABLE tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id),
    status VARCHAR(16) DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
    current_stage VARCHAR(32),  -- uploading/screening/retouching/captioning
    progress INT DEFAULT 0,     -- 0-100
    total_photos INT NOT NULL,
    processed_photos INT DEFAULT 0,
    result_photos INT DEFAULT 0,  -- 精修后产出
    options JSONB,               -- 用户选项
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC);

-- 照片表（PRD实体3，增加photo_type字段）
CREATE TABLE photos (
    photo_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id),
    original_url TEXT NOT NULL,
    processed_url TEXT,
    thumbnail_url TEXT,
    composition_group INT,            -- 构图分组
    photo_type VARCHAR(16),           -- ⭐新增: portrait/landscape/mixed
    quality_score DECIMAL(5,2),      -- 0-100
    face_count INT DEFAULT 0,         -- ⭐新增: 人脸数
    face_quality_score DECIMAL(5,2),  -- ⭐新增: 0-100
    is_selected BOOLEAN DEFAULT FALSE,
    caption TEXT,
    retouch_status VARCHAR(16),       -- pending/processing/done/failed
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_photos_task_id ON photos(task_id);
CREATE INDEX idx_photos_user_id ON photos(user_id);
CREATE INDEX idx_photos_composition_group ON photos(task_id, composition_group);
CREATE INDEX idx_photos_is_selected ON photos(task_id, is_selected);

-- VIP订单表（PRD实体4）
CREATE TABLE orders (
    order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id),
    order_no VARCHAR(32) UNIQUE NOT NULL,  -- 业务订单号
    vip_level VARCHAR(16) NOT NULL
        CHECK (vip_level IN ('vip1', 'vip2', 'vip3')),
    duration VARCHAR(16) NOT NULL
        CHECK (duration IN ('monthly', 'yearly')),
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(16) DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'cancelled', 'refunded')),
    payment_method VARCHAR(16),  -- wechat/alipay
    payment_time TIMESTAMPTZ,
    transaction_id VARCHAR(64),   -- 微信交易号
    member_start_date TIMESTAMPTZ,
    member_end_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_status ON orders(status);

-- 广告解锁记录（PRD实体5）
CREATE TABLE ad_unlocks (
    ad_unlock_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id),
    ad_type VARCHAR(32) NOT NULL,  -- rewarded_video/interstitial
    ad_platform VARCHAR(32),        -- pangle/tencent
    watch_duration_seconds INT,
    is_completed BOOLEAN DEFAULT FALSE,
    unlocked_count INT DEFAULT 1,
    expire_date TIMESTAMPTZ,
    device_fingerprint VARCHAR(128),
    ip_address VARCHAR(45),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ad_unlocks_user_id ON ad_unlocks(user_id);
CREATE INDEX idx_ad_unlocks_created_at ON ad_unlocks(created_at DESC);

-- 额度流水表（PRD实体6）
CREATE TABLE quota_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id),
    change_type VARCHAR(32) NOT NULL,
        -- trial_consume/ad_unlock/task_consume/refund/admin_grant
    change_count INT NOT NULL,  -- 正数增加，负数减少
    before_count INT,
    after_count INT,
    related_id VARCHAR(64),  -- 关联ID
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_quota_logs_user_id ON quota_logs(user_id);
CREATE INDEX idx_quota_logs_created_at ON quota_logs(created_at DESC);

-- VIP套餐配置表（V1.0新增）
CREATE TABLE vip_plans (
    plan_id SERIAL PRIMARY KEY,
    level VARCHAR(16) UNIQUE NOT NULL,  -- vip1/vip2/vip3
    name VARCHAR(32) NOT NULL,          -- 基础/高级/旗舰
    price_monthly DECIMAL(10,2) NOT NULL,
    price_yearly DECIMAL(10,2) NOT NULL,
    photos_per_task INT NOT NULL,
    features JSONB,                     -- 特性列表
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 初始化数据
INSERT INTO vip_plans (level, name, price_monthly, price_yearly, photos_per_task, features) VALUES
('vip1', '基础会员', 19.9, 199, 50, '["50张/次", "3次/天", "去水印", "在线客服"]'::jsonb),
('vip2', '高级会员', 39.9, 399, 80, '["80张/次", "5次/天", "去水印", "优先客服", "加速50%"]'::jsonb),
('vip3', '旗舰会员', 69.9, 699, 150, '["150张/次", "7次/天", "去水印", "专属客服", "加速100%", "永久历史"]'::jsonb);
-- 注：daily_limit 字段已省略，实际生产建议加 daily_limit INT NOT NULL 字段
--    vip1=3 / vip2=5 / vip3=7，见后端 models/vip_plan.py
```

### 6.3 Redis数据结构

```yaml
# 用户额度缓存
quota:{user_id}:photos_per_task: 20|50|80|150
quota:{user_id}:vip_expire: timestamp

# 任务进度（实时）
task:progress:{task_id}: 0-100
task:stage:{task_id}: uploading|screening|retouching|captioning|completed

# 分布式锁
quota:lock:{user_id}: 1 (TTL=5s)
ad:unlock:lock:{user_id}: 1 (TTL=30s)

# 限流
ratelimit:api:{user_id}:{endpoint}: count (TTL=60s)
ratelimit:upload:{user_id}: count (TTL=1d)

# 微信Token
wechat:access_token: token (TTL=7200s)
wechat:jsapi_ticket: ticket (TTL=7200s)
```

---

## 七、第三方服务集成

### 7.1 第三方服务清单

| 服务 | 提供商 | 用途 | 计费 | 接入方式 |
|------|-------|------|------|---------|
| **对象存储COS** | 腾讯云 | 照片存储 | 0.099元/GB/月 | SDK + STS临时凭证 |
| **CDN** | 腾讯云 | 静态资源分发 | 0.21元/GB | 域名绑定 |
| **人像精修** | 美图云修 | AI精修API | ~0.10元/张 | HTTP API |
| **视觉理解** | 通义千问VL | 图片描述+文案 | ~0.02元/千tokens | DashScope SDK |
| **大模型** | 通义千问/Qwen | 文案生成 | ~0.02元/千tokens | DashScope SDK |
| **向量检索** | Faiss(自建) | 特征向量检索 | 0 | 自部署 |
| **微信支付** | 微信 | 支付 | 0.6%手续费 | JSAPI/Native |
| **微信广告** | 微信优量汇 | 激励视频/插屏 | 收益分成 | SDK |
| **短信** | 阿里云 | 验证码/通知 | 0.045元/条 | SDK |
| **监控** | Sentry | 错误追踪 | 免费 | SaaS |
| **日志** | 阿里云SLS | 日志存储 | 0.0115元/GB/天 | SDK |

### 7.2 第三方API降级策略

| 服务 | 故障场景 | 降级方案 |
|------|---------|---------|
| 美图云修 | 不可用 | 切换到自建GFPGAN+SD方案（效果略差但可用）|
| 通义千问 | 不可用 | 切换到Gemini 2.0 Flash Lite |
| Gemini | 不可用 | 切换到DeepSeek或本地Qwen |
| 微信支付 | 不可用 | 切换到支付宝 |
| Redis | 不可用 | 内存缓存兜底（重启丢失但不影响功能）|
| COS | 不可用 | 切换到本地临时存储（限7天）|

### 7.3 熔断器实现

```python
# app/utils/circuit_breaker.py
from functools import wraps
import asyncio
from enum import Enum

class CircuitState(Enum):
    CLOSED = 'closed'      # 正常
    OPEN = 'open'          # 熔断
    HALF_OPEN = 'half_open' # 半开

class CircuitBreaker:
    def __init__(self, name: str, failure_threshold=5, timeout=60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.state = CircuitState.CLOSED
        self.opened_at = None

    def call(self, func, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if (time.time() - self.opened_at) > self.timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitOpenError(f"{self.name} is open")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        self.failures = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED

    def _on_failure(self):
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.time()

# 使用示例
meitu_breaker = CircuitBreaker('meitu', failure_threshold=5, timeout=60)

@meitu_breaker.call
def call_meitu_api(...):
    ...
```

---

## 八、部署与运维

### 8.1 部署架构

```
┌────────────────────────────────────────────────────────────┐
│                       生产环境架构                           │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                │
│  │  微信小程序端    │  │  Web管理端       │                │
│  └────────┬────────┘  └────────┬────────┘                │
│           │ HTTPS              │ HTTPS                    │
│           ↓                    ↓                          │
│  ┌──────────────────────────────────────────┐             │
│  │  阿里云SLB（负载均衡）                     │             │
│  └─────────────────┬────────────────────────┘             │
│                    ↓                                       │
│  ┌──────────────────────────────────────────┐             │
│  │  API网关集群（2台 K8s Pod）               │             │
│  └─────────────────┬────────────────────────┘             │
│                    ↓                                       │
│  ┌─────────────────┴────────────────────────┐             │
│  │   FastAPI 应用集群（4-8 Pod，K8s HPA）    │             │
│  │   - 业务服务（4 Pod）                      │             │
│  │   - AI服务（2-4 Pod）                      │             │
│  └────────┬────────────────────────────────┘             │
│           ↓                                                │
│  ┌────────┴────────────────────────────────┐              │
│  │  Celery Worker（4-8 Worker，K8s部署）    │              │
│  └────────┬────────────────────────────────┘              │
│           ↓                                                │
│  ┌────────┴─────┬─────────────┬──────────────┐            │
│  │  PostgreSQL  │   Redis     │  腾讯云COS   │            │
│  │  (主+从)     │  (主+从)    │              │            │
│  └──────────────┴─────────────┴──────────────┘            │
│                                                             │
│  ┌──────────────────────────────────────────┐             │
│  │  监控告警：Prometheus + Grafana           │             │
│  │  日志：阿里云SLS                          │             │
│  │  错误追踪：Sentry                          │             │
│  └──────────────────────────────────────────┘             │
└────────────────────────────────────────────────────────────┘
```

### 8.2 资源清单（V1.0生产环境）

| 资源 | 规格 | 数量 | 月成本（估算）|
|------|------|------|--------------|
| **API服务器** | 阿里云ECS 4C8G | 2台 | 800元 |
| **AI服务器** | GPU云服务器 A10 | 1台 | 6,800元 |
| **PostgreSQL主库** | 阿里云RDS 4C16G 100GB | 1 | 1,200元 |
| **PostgreSQL从库** | 阿里云RDS只读 | 1 | 800元 |
| **Redis** | 阿里云Redis 4G | 1 | 300元 |
| **COS存储** | 500GB | - | 50元 |
| **CDN** | 200GB流量 | - | 50元 |
| **对象存储API调用** | - | - | 100元 |
| **监控 + 日志** | - | - | 200元 |
| **域名 + SSL** | - | - | 100元 |
| **总月度成本** | | | **~10,400元** |

### 8.3 CI/CD流水线

```yaml
# .github/workflows/deploy.yml
name: Build and Deploy

on:
  push:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          cd backend
          pip install -r requirements.txt
          pytest --cov=app tests/

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build Docker image
        run: |
          docker build -t travel-photo-ai:${{ github.sha }} ./backend
      - name: Push to ACR (阿里云容器)
        run: |
          docker push registry.cn-hangzhou.aliyuncs.com/travel-photo-ai:${{ github.sha }}

  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to K8s
        run: |
          kubectl set image deployment/api api=registry.cn-hangzhou.aliyuncs.com/travel-photo-ai:${{ github.sha }}
          kubectl rollout status deployment/api
```

### 8.4 Docker Compose（开发环境）

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: travel_photo
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backend/app/db/migrations/init.sql:/docker-entrypoint-initdb.d/init.sql

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/travel_photo
      REDIS_URL: redis://redis:6379/0
      COS_SECRET_ID: ${COS_SECRET_ID}
      COS_SECRET_KEY: ${COS_SECRET_KEY}
      MEITU_API_KEY: ${MEITU_API_KEY}
      QWEN_API_KEY: ${QWEN_API_KEY}
    depends_on:
      - postgres
      - redis

  celery-worker:
    build: ./backend
    command: celery -A app.tasks.celery_app worker -l info -Q default,vip
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/travel_photo
      REDIS_URL: redis://redis:6379/0
    depends_on:
      - postgres
      - redis
      - backend

  ai-service:
    build: ./backend
    ports:
      - "8001:8001"
    command: uvicorn app.ai.main:app --host 0.0.0.0 --port 8001
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/travel_photo
      REDIS_URL: redis://redis:6379/0
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    depends_on:
      - postgres
      - redis

volumes:
  postgres_data:
  redis_data:
```

---

## 九、研发计划（10周冲刺）

### 9.1 总体时间线

```
Week 1-2:  [环境搭建 + 数据库 + 基础API]
Week 3-4:  [核心功能MVP - 筛选+精修+文案]
Week 5-6:  [会员体系 - 试用/广告/VIP]
Week 7:    [支付集成 + 管理后台]
Week 8:    [性能优化 + 压测]
Week 9:    [内测 + 修复]
Week 10:   [正式发布准备]

总工期：10周（~2.5个月）
```

### 9.2 详细WBS

#### **第1周：基础架构与数据库搭建**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 1.1 后端项目初始化（FastAPI + Poetry） | 后端1 | 项目骨架 | 1天 |
| 1.2 数据库设计 + 初始化SQL + Alembic | 后端1 | 6张表 + 迁移 | 1天 |
| 1.3 Docker Compose环境搭建 | 后端1 | dev环境可启动 | 0.5天 |
| 1.4 微信小程序初始化（uni-app） | 前端1 | 项目结构 | 1天 |
| 1.5 前端UI组件库搭建（uView） | 前端1 | 基础组件 | 1天 |
| 1.6 API请求层封装（token/重试/拦截） | 前端1 | request.ts | 0.5天 |
| 1.7 微信登录接口（code2session） | 后端1 | /api/v1/auth | 1天 |
| 1.8 JWT签发 + 中间件 | 后端1 | auth middleware | 0.5天 |
| 1.9 阿里云/COS SDK 集成 + STS | 后端1 | /api/v1/photos/sts | 1天 |
| 1.10 客户端照片上传组件（分块+并发） | 前端1 | PhotoUploader.vue | 1.5天 |

#### **第2周：核心API + AI基础**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 2.1 任务模型 + 任务创建API | 后端1 | /api/v1/tasks | 1天 |
| 2.2 Celery异步任务框架搭建 | 后端1 | celery_app | 1天 |
| 2.3 AI服务骨架（FastAPI 8001） | AI工程师 | AI服务可启动 | 1天 |
| 2.4 CLIP特征提取模块 | AI工程师 | feature_extractor.py | 1.5天 |
| 2.5 HDBSCAN聚类模块 | AI工程师 | clustering.py | 1天 |
| 2.6 RetinaFace人脸检测模块 | AI工程师 | face_detector.py | 1天 |
| 2.7 质量评分模型（自训练或预训练） | AI工程师 | quality_scorer.py | 2天 |
| 2.8 任务进度查询API | 后端1 | /api/v1/tasks/{id}/status | 0.5天 |
| 2.9 客户端进度展示组件 | 前端1 | ProgressBar.vue | 0.5天 |
| 2.10 上传页+处理页UI实现 | 前端1/2 | 上传流程 | 2天 |

#### **第3周：智能筛选 + 精修**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 3.1 筛选Pipeline（端到端） | AI工程师 | screener/pipeline.py | 2天 |
| 3.2 美图云修API集成 | 后端1 | retoucher/meitu_api.py | 1天 |
| 3.3 精修Pipeline（人像vs景观） | 后端1 | retoucher/pipeline.py | 1.5天 |
| 3.4 文案生成 - 通义千问VL集成 | 后端1 | caption_gen/qwen_client.py | 1.5天 |
| 3.5 文案生成 - 模板引擎兜底 | 后端1 | template_engine.py | 1天 |
| 3.6 任务处理Celery任务编排 | 后端1 | photo_tasks.py | 1.5天 |
| 3.7 筛选结果展示UI | 前端1 | result page | 2天 |
| 3.8 文案展示+编辑UI | 前端2 | CaptionEditor.vue | 1天 |

#### **第4周：处理流程整合**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 4.1 端到端联调（上传→处理→展示） | 全员 | 完整流程 | 2天 |
| 4.2 错误处理 + 重试机制 | 后端1 | retry/circuit | 1天 |
| 4.3 进度推送优化（轮询→长连接） | 后端1 | websocket | 1天 |
| 4.4 历史记录页面 | 前端2 | history page | 1.5天 |
| 4.5 个人中心页面 | 前端2 | mine page | 1天 |
| 4.6 性能优化（图片懒加载、缓存） | 前端1 | - | 1天 |
| 4.7 单元测试覆盖（核心服务） | 后端1+测试 | 70%覆盖率 | 2天 |
| 4.8 集成测试 | 测试 | 测试报告 | 1天 |

#### **第5周：会员体系 - 试用/广告**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 5.1 User表扩展（试用/广告字段） | 后端1 | 迁移脚本 | 0.5天 |
| 5.2 QuotaService实现 | 后端1 | quota_service.py | 2天 |
| 5.3 额度查询API | 后端1 | /api/v1/quota | 0.5天 |
| 5.4 广告解锁API | 后端1 | /api/v1/ads/unlock | 1天 |
| 5.5 反作弊机制 | 后端1 | anti_fraud.py | 1.5天 |
| 5.6 微信广告SDK集成 | 前端1 | useAd.ts | 1.5天 |
| 5.7 客户端额度管理Hook | 前端1 | useQuota.ts | 1天 |
| 5.8 客户端免费次数用完弹窗 | 前端1 | AdDialog.vue | 1天 |
| 5.9 VIP套餐展示页 | 前端2 | vip page | 1.5天 |
| 5.10 每日重置广告次数的定时任务 | 后端1 | scheduled_tasks.py | 0.5天 |

#### **第6周：VIP体系 + 支付**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 6.1 VIP套餐配置表 + 初始化 | 后端1 | vip_plans.sql | 0.5天 |
| 6.2 套餐查询API | 后端1 | /api/v1/vip/plans | 0.5天 |
| 6.3 微信支付SDK集成 | 后端1 | pay/wechat.py | 2天 |
| 6.4 创建订单 + 统一下单 | 后端1 | /api/v1/pay/orders | 1.5天 |
| 6.5 支付回调处理 | 后端1 | /api/v1/pay/callback | 1天 |
| 6.6 VIP状态更新逻辑 | 后端1 | vip_service.py | 1天 |
| 6.7 客户端VIP购买流程 | 前端2 | 完整购买 | 2天 |
| 6.8 客户端VIP状态展示 | 前端1 | VipCard.vue | 1天 |
| 6.9 VIP升级引导场景 | 前端1 | 5个触发点 | 1.5天 |

#### **第7周：管理后台 + 监控**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 7.1 简易管理后台（Web） | 前端2 | admin page | 3天 |
| 7.2 数据统计接口 | 后端1 | /api/v1/stats | 1天 |
| 7.3 用户管理（查询/封禁） | 后端1 | /api/v1/admin/users | 1天 |
| 7.4 Prometheus + Grafana 部署 | 后端1 | 监控面板 | 1天 |
| 7.5 Sentry 错误追踪集成 | 后端1 | 错误上报 | 0.5天 |
| 7.6 阿里云SLS日志接入 | 后端1 | 日志查询 | 0.5天 |
| 7.7 微信支付退款流程 | 后端1 | 退款API | 1天 |

#### **第8周：性能优化 + 压测**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 8.1 数据库索引优化 | 后端1 | 慢查询分析 | 1天 |
| 8.2 Redis缓存策略 | 后端1 | 热点缓存 | 1天 |
| 8.3 客户端性能优化（首屏、滚动） | 前端1 | 性能报告 | 1天 |
| 8.4 AI服务批处理优化 | AI工程师 | 吞吐量提升 | 2天 |
| 8.5 压测（1000并发） | 测试 | 压测报告 | 1天 |
| 8.6 CDN配置 + 缓存策略 | 后端1 | CDN加速 | 0.5天 |
| 8.7 限流配置（接口级） | 后端1 | rate_limit | 0.5天 |
| 8.8 应急预案文档 | 后端1 | runbook | 0.5天 |

#### **第9周：内测 + 修复**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 9.1 灰度发布（10%用户） | 后端1+运维 | 灰度方案 | 1天 |
| 9.2 收集内测反馈 | 全员 | 反馈表 | 持续 |
| 9.3 Bug修复（P0/P1） | 全员 | 修复报告 | 3天 |
| 9.4 用户体验优化 | 前端 | UI优化 | 2天 |
| 9.5 隐私政策 + 用户协议 | 产品 | 文档 | 1天 |
| 9.6 客户支持FAQ | 运营 | 文档 | 0.5天 |

#### **第10周：正式发布准备**

| 任务 | 负责人 | 交付物 | 估时 |
|------|--------|-------|------|
| 10.1 微信小程序提审 | 前端1 | 审核通过 | 1天 |
| 10.2 运营物料准备（海报、引导） | 运营 | 物料 | 2天 |
| 10.3 客服培训 | 运营 | 培训完成 | 0.5天 |
| 10.4 应急预案演练 | 全员 | 演练报告 | 0.5天 |
| 10.5 正式发布 | 全员 | 1.0上线 | 1天 |
| 10.6 上线后监控（24h值班） | 全员 | 监控报告 | 3天 |

### 9.3 关键里程碑

| 里程碑 | 时间点 | 验收标准 |
|-------|--------|---------|
| **M1: 技术方案完成** | 第1周末 | 文档评审通过 |
| **M2: MVP完成（免费版）** | 第4周末 | 20张照片可端到端处理 |
| **M3: 会员体系完成** | 第6周末 | 试用/广告/VIP全流程 |
| **M4: 内测启动** | 第9周末 | 100个内测用户 |
| **M5: 正式发布** | 第10周末 | V1.0上线 |

---

## 十、团队配置与预算

### 10.1 团队配置（核心团队）

| 角色 | 人数 | 主要职责 |
|------|------|---------|
| **产品经理** | 1 | 需求管理、PRD、运营数据 |
| **UI/UX设计师** | 1 | 视觉设计、交互设计、原型 |
| **前端工程师** | 2 | 微信小程序、H5 |
| **后端工程师** | 2 | FastAPI、数据库、API |
| **AI工程师** | 1 | AI模型集成与优化 |
| **测试工程师** | 1 | 功能测试、性能测试 |
| **运维/DevOps** | 0.5 | CI/CD、监控（可外包）|
| **运营** | 1 | 用户反馈、市场推广 |
| **总计** | **9.5人** | |

### 10.2 预算估算（10周项目）

| 项目 | 金额 | 备注 |
|------|------|------|
| **人力成本**（10周） | 80-120万 | 9.5人 × 平均1.5-2.5万/月 × 2.5月 |
| **云服务（开发+测试）** | 3-5万 | 10周的dev/test环境 |
| **第三方服务（开发期）** | 2-3万 | 美图/通义/微信支付的测试调用 |
| **办公+管理** | 3-5万 | 沟通协作工具等 |
| **总预算** | **88-133万** | |

### 10.3 V1.0上线后月度运营成本

| 项目 | 月成本 | 备注 |
|------|--------|------|
| 云服务 | 10,400元 | 见8.2节 |
| 第三方API（按1万付费用户） | ~30,000元 | AI精修+大模型 |
| 人力（运维+客服） | 50,000元 | 3人小团队 |
| 总月度运营 | **~90,000元** | |

---

## 十一、风险与质量保障

### 11.1 技术风险与应对

| 风险 | 等级 | 概率 | 影响 | 应对措施 |
|------|------|------|------|---------|
| **AI处理效果不达预期** | 高 | 中 | 高 | 接入多模型（A/B测试）、人工审核兜底 |
| **美图API调用成本超预算** | 高 | 中 | 高 | 监控单张成本、设置月度预算告警、达到阈值自动降级 |
| **微信小程序审核被拒** | 中 | 中 | 高 | 提前了解审核规则，避开敏感功能 |
| **付费用户激增导致AI服务撑不住** | 中 | 低 | 高 | K8s HPA自动扩缩容、消息队列削峰 |
| **数据隐私泄露** | 极高 | 低 | 极高 | 端到端加密、临时存储（30天清理）、合规审计 |
| **黑产刷广告/刷试用** | 中 | 中 | 中 | 设备指纹+IP+手机号三重去重、验证码、行为分析 |
| **微信支付回调丢失** | 中 | 低 | 中 | 主动查询订单状态 + 回调双重确认 |
| **数据库性能瓶颈** | 中 | 中 | 中 | 索引优化、读写分离、分库分表预案 |

### 11.2 质量保障措施

#### 11.2.1 测试策略

| 层级 | 覆盖率 | 工具 |
|------|--------|------|
| **单元测试** | >80% | pytest |
| **集成测试** | 关键流程100% | pytest + httpx |
| **端到端测试** | 主流程100% | Playwright（Web）/ miniprogram-automator |
| **性能测试** | 关键接口 | Locust |
| **AI算法测试** | 准确率>85% | 自建测试集 |
| **安全测试** | 季度一次 | 第三方安全公司 |

#### 11.2.2 监控告警

| 指标 | 告警阈值 |
|------|---------|
| API响应时间P99 | > 1秒 |
| API错误率 | > 1% |
| 任务队列长度 | > 1000 |
| 美图API成本 | > 1万元/天 |
| 数据库连接数 | > 80% |
| Redis内存使用 | > 80% |
| GPU使用率 | > 90% 持续5分钟 |

#### 11.2.3 数据备份与恢复

- PostgreSQL：每日全量备份 + 实时WAL归档
- COS：跨地域复制（主+备）
- 备份保留：30天
- 恢复演练：季度一次

### 11.3 隐私与合规

- 用户照片30天后自动清理（VIP3永久保留）
- 端到端HTTPS + 客户端到COS直传
- 符合《个人信息保护法》《数据安全法》
- 提供数据导出 + 账号注销功能
- 第三方AI服务（美图/通义）签订数据处理协议

---

## 📌 总结

### 核心交付物

| 类别 | 内容 |
|------|------|
| **架构** | 客户端 + API网关 + 8个微服务 + AI层 + 数据层 |
| **技术栈** | uni-app + FastAPI + PostgreSQL + Redis + Celery + PyTorch |
| **AI能力** | CLIP筛选 + 美图云修精修 + 通义千问文案 |
| **关键模块** | QuotaService（额度）+ 任务编排 + 反作弊 |
| **数据库** | 8张核心表 + Redis缓存 |
| **部署** | Docker + K8s + 阿里云 |
| **研发周期** | 10周 |
| **团队规模** | 9.5人 |
| **预算** | 88-133万 |

### 下一步行动

1. **第1周内**：完成本方案评审，启动项目
2. **第1-2周**：技术选型确认 + 团队到位
3. **第3-4周**：完成MVP（20张免费版）
4. **第5-6周**：完成会员体系
5. **第7-8周**：完成支付 + 性能优化
6. **第9-10周**：内测 + 正式发布

---

*本文档将作为研发团队的指导手册，每周根据实际进展进行更新。*
