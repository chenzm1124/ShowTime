"""应用配置管理（pydantic-settings）"""

import warnings
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，从环境变量和 .env 文件读取"""

    # ---------- 应用 ----------
    APP_NAME: str = "图轻松 Pro 后端"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # ---------- 数据库 ----------
    DATABASE_URL: str = "postgresql+asyncpg://travelphoto:travelphoto@localhost:5432/travelphoto"
    DATABASE_URL_SYNC: str = "postgresql://travelphoto:travelphoto@localhost:5432/travelphoto"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # ---------- Redis ----------
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 20

    # ---------- 微信小程序 ----------
    WECHAT_APPID: str = ""
    WECHAT_SECRET: str = ""
    WECHAT_MCHID: str = ""
    WECHAT_PAY_KEY: str = ""
    WECHAT_PAY_CERT_PATH: str = ""
    WECHAT_PAY_KEY_PATH: str = ""

    # ---------- JWT ----------
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # ---------- CORS ----------
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"

    # ---------- 对象存储 ----------
    OSS_TYPE: Literal["oss", "cos"] = "cos"
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_ENDPOINT: str = ""
    OSS_BUCKET: str = "travelphoto-dev"
    OSS_REGION: str = "cn-hangzhou"
    OSS_STS_DURATION_SECONDS: int = 3600

    # ---------- 腾讯云 COS ----------
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = ""
    COS_BUCKET: str = ""
    COS_REGION: str = "ap-shanghai"
    COS_STS_DURATION_SECONDS: int = 1800

    # ---------- 美图云修 Pro ----------
    # 兜底默认预设：男人 / 未确定性别（category=None）共用
    MEITU_API_KEY: str = ""
    MEITU_API_SECRET: str = ""
    MEITU_MEDIA_CODE: str = "MTyunxiu1be9f7b9a5"  # 男人 / 未确定性别 兜底默认
    MEITU_API_URL: str = "https://openapi-yunxiu.meitu.com/openapi/chain.json"
    # 结果查询接口（轮询兜底用）。美图文档未给出确切路径，此为基于公共接入地址的合理猜测；
    # 若回调因隧道抖动未达，会按此地址轮询 reqid。回调成功则轮询自动失效，无副作用。
    MEITU_QUERY_URL: str = "https://openapi-yunxiu.meitu.com/openapi/query.json"
    # 美图回调公网地址（内网穿透域名，如 https://xxx.xicp.net）
    CALLBACK_BASE_URL: str = "https://your-domain.com"
    # 美图回调是否强制 HMAC 签名校验
    # - True: 必须带 X-Meitu-Signature HMAC-SHA256 头，否则 401
    # - False: 不强制签名校验（默认）。美图云修 Pro 默认不会主动添加任何自定义
    #   签名头，强制开启会导致所有回调被拒（task 90 惨案：6 张只有 1 张靠轮询兜底成功）。
    # 生产环境若美图侧已配置密钥对接，可置 True 加强安全。
    MEITU_CALLBACK_REQUIRE_SIG: bool = False

    # ---------- 美图云修 Pro：按人物类型分预设 ----------
    # 5 种人物类型：man / woman / child / elderly / group
    # 未配置对应预设的类别会 fallback 到 MEITU_MEDIA_CODE（男人/未确定）
    MEITU_MEDIA_CODE_MAN: str = "MTyunxiu1be9f7b9a5"      # 男人 / 未确定性别
    MEITU_MEDIA_CODE_WOMAN: str = "MTyunxiu1adfddbc85"     # 女人
    MEITU_MEDIA_CODE_CHILD: str = "MTyunxiu1b2f208515"     # 儿童
    MEITU_MEDIA_CODE_ELDERLY: str = "MTyunxiu14007efa05"   # 老人
    MEITU_MEDIA_CODE_GROUP: str = "MTyunxiu1c7999db65"     # 合照

    # ---------- 大模型 ----------
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen-vl-plus"
    LLM_MAX_TOKENS: int = 2000
    LLM_TIMEOUT: int = 30

    # ---------- 图像质量评估 / 智能筛选 ----------
    # tencent = 腾讯云（COS 数据万象质量评分 + IAI 人脸检测，图片在 COS 零转存，推荐）
    # aliyun  = 阿里云视觉智能开放平台（需图片在上海 OSS，链路较重）
    # mock    = 随机评分（开发期占位，等同原 MockScreener）
    # 任一真实 provider 缺凭据/未开通时，对应能力自动降级为本地 CV 基线。
    IQA_PROVIDER: Literal["tencent", "aliyun", "mock"] = "tencent"

    # 腾讯云人脸识别 IAI 地域（复用 COS_SECRET_ID/KEY）；需开通「人脸识别」服务。
    TENCENT_IAI_REGION: str = "ap-shanghai"
    # 腾讯云数据万象「图片质量评估」开关；需在 COS 桶开通该增值功能。
    IQA_ENABLE_TENCENT_QUALITY: bool = True
    # 腾讯云人脸检测开关。
    IQA_ENABLE_TENCENT_FACE: bool = True

    # 阿里云视觉智能开放平台（图像清晰度/曝光/构图评分 + 人脸检测质量）
    IQA_ACCESS_KEY_ID: str = ""
    IQA_ACCESS_KEY_SECRET: str = ""
    IQA_REGION: str = "cn-shanghai"
    # 图像分析处理（AssessSharpness/Exposure/Composition）开关。
    # 注意：该服务需单独在视觉智能开放平台开通；若开通失败（如页面报错），
    # 设为 False，仅使用人脸人体 + 本地 CV 基线，避免每次白跑 3 次 RPC。
    IQA_ENABLE_IMAGEENHAN: bool = False
    # 打分权重（仅人像类），冒号分隔 key:value，逗号分隔项
    # 人脸权重最高（0.4），清晰度次之（0.25），曝光/构图各 0.2/0.15
    SCORE_WEIGHTS: str = "sharpness:0.25,exposure:0.2,composition:0.15,face:0.4"
    # L3 语义精排候选数上限（控制 VLM 成本，Phase 3）
    SEMANTIC_RERANK_TOPK: int = 30
    # 近重复判定的多哈希 hamming 阈值（<= 视为同一构图簇）。
    # 沙龙场景收紧（14/16/18 → 8/10/12）：去重口径改为「仅像素级连拍」——
    # 只有构图几乎完全一致（同角度同姿势的连拍/复制）才判重复并合并，
    # 同人同背景但换姿势/角度不再去重。screener 以 AND 方式使用这三个阈值
    # （三种哈希全部≤阈值才判为重复），进一步保证"同样构图"的严格性。
    DEDUP_AHASH_THRESHOLD: int = 8    # 平均哈希（对色调敏感）
    DEDUP_DHASH_THRESHOLD: int = 10   # 差异哈希（对构图结构敏感）
    DEDUP_PHASH_THRESHOLD: int = 12   # 感知哈希 DCT（对亮度/裁剪最鲁棒）
    # 是否启用 Qwen 多模态 embedding 聚类（语义层同组判定，替代/补充多哈希）
    CLUSTER_USE_QWEN_EMBEDDING: bool = True
    # Qwen embedding 余弦相似度阈值（>= 视为同组）。
    # 沙龙场景收紧（0.7 → 0.82）：避免把"同人同背景但不同构图"的照片
    # 通过语义层误合并为同组，仅当语义明显一致（近重复/强同场景）才判同组。
    CLUSTER_QWEN_SIM_THRESHOLD: float = 0.82
    # 背景元素重叠率阈值（Jaccard）。越低越容易并入同组。
    # 0.3 → 0.15：进一步放宽"同一人 + 相似背景即可同组"（相似背景不必强重叠元素）
    CLUSTER_BG_OVERLAP_THRESHOLD: float = 0.15
    # 是否用腾讯云 IAI「人脸比对」判定同一人（权威信号，替代衣服文字匹配）
    CLUSTER_USE_FACE_COMPARE: bool = True
    # 人脸比对相似度阈值（Score 0~100，≥ 视为同一人）。
    # 腾讯云算法版本差异：3.0 版"超过 50 分即同一人"，2.0 版"超过 80 分"。
    # 取 70 在两种版本下都等于/严于"同一人"阈值，最稳妥。
    CLUSTER_FACE_SAME_THRESHOLD: float = 70.0
    # 每组精选上限：从每个相似聚类组中挑出质量最高的前 N 张
    # 产品需求（步骤3）：每组只挑 1 张 → 1
    SELECT_TOP_PER_GROUP: int = 1

    # ---------- 精修服务 ----------
    RETOUCH_PROVIDER: Literal["meitu", "internal"] = "meitu"
    RETOUCH_API_URL: str = ""
    RETOUCH_API_KEY: str = ""

    # ---------- 监控 ----------
    SENTRY_DSN: str = ""

    # ---------- 业务开关 ----------
    # P0-12 修复：默认值改 False
    # - 旧默认 True：生产环境漏配 .env 时会"静默"开 mock 模式
    #   → 任意匿名请求 fallback 到第一个测试用户 = 严重越权
    # - 新默认 False：必须显式在 .env 写 ENABLE_MOCK_MODE=true 才生效
    ENABLE_MOCK_MODE: bool = False
    VIP_DEFAULT_DURATION_DAYS: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _validate_settings(self) -> "Settings":
        # P0-12 修复：生产环境严禁 mock 模式
        if self.APP_ENV == "production" and self.ENABLE_MOCK_MODE:
            raise ValueError(
                "生产环境严禁开启 ENABLE_MOCK_MODE！"
                "mock 模式会让任意匿名请求 fallback 到第一个测试用户，"
                "等价于全员可访问 + 全员共享额度，是严重安全风险。"
                "请在 .env 中设置 ENABLE_MOCK_MODE=false 或移除该配置。"
            )

        if not self.SECRET_KEY:
            if self.APP_ENV == "production":
                raise ValueError(
                    "生产环境必须设置 SECRET_KEY 环境变量。"
                    "生成方式: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            self.SECRET_KEY = "dev-secret-key-for-local-testing-only-not-for-production"
        elif len(self.SECRET_KEY) < 32:
            warnings.warn(
                f"SECRET_KEY 长度不足 ({len(self.SECRET_KEY)} chars)，建议至少 32 字符",
                UserWarning,
                stacklevel=2,
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def get_meitu_media_code_for_category(self, category: str | None) -> str:
        """根据人物分类返回对应的美图预设 ID

        5 类：man / woman / child / elderly / group
        任何未配置/未匹配的 category 都会回退到 MEITU_MEDIA_CODE（兜底默认）
        """
        mapping: dict[str, str] = {
            "man": self.MEITU_MEDIA_CODE_MAN,
            "woman": self.MEITU_MEDIA_CODE_WOMAN,
            "child": self.MEITU_MEDIA_CODE_CHILD,
            "elderly": self.MEITU_MEDIA_CODE_ELDERLY,
            "group": self.MEITU_MEDIA_CODE_GROUP,
        }
        if category and mapping.get(category):
            return mapping[category]
        return self.MEITU_MEDIA_CODE

    def score_weights(self, photo_type: "str | None" = None) -> dict[str, float]:
        """解析打分权重为归一化 dict（仅人像一套权重）

        photo_type 参数保留以兼容旧调用，不再区分人像/风景。
        """
        raw = self.SCORE_WEIGHTS
        weights: dict[str, float] = {}
        for part in raw.split(","):
            k, _, v = part.partition(":")
            k = k.strip()
            if k and v:
                try:
                    weights[k] = float(v)
                except ValueError:
                    continue
        total = sum(weights.values()) or 1.0
        return {k: w / total for k, w in weights.items()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
