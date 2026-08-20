"""AI 服务层基础数据类型和 Provider 接口定义

对应 PRD：
- FR-201~209 智能筛选
- FR-301~310 智能精修
- FR-401~408 文案生成
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


# ---------- 修图风格 ----------
RetouchStyle = Literal[
    "auto",       # 智能配风格
    "natural",    # 自然商务（新增）
    "clean",      # 清透干净（新增）
    "warm",       # 暖色调（新增）
    "film",       # 胶片风
    "fresh",      # 小清新
    # 旧版兼容
    "hk",
    "cyber",
    "soft",
]

RETOUCH_STYLE_LABELS: dict[str, str] = {
    "auto": "智能配风格",
    "natural": "自然商务",
    "clean": "清透干净",
    "warm": "暖色调",
    "film": "胶片风",
    "fresh": "小清新",
    # 旧版兼容
    "hk": "港风（旧版）",
    "cyber": "赛博风（旧版）",
    "soft": "柔光风（旧版）",
}

# ---------- 文案风格 ----------
CaptionStyle = Literal[
    "professional",  # 专业干练
    "energetic",     # 积极正能量
    "warm",          # 温暖有温度
    "minimal",       # 简约高级
    "reflective",    # 深度思考
    # 旧版兼容（保留以支持历史数据回显）
    "literary",
    "humor",
    "emotional",
    "checkin",
]

CAPTION_STYLE_LABELS: dict[str, str] = {
    "professional": "专业干练",
    "energetic": "积极正能量",
    "warm": "温暖有温度",
    "minimal": "简约高级",
    "reflective": "深度思考",
    # 旧版兼容
    "literary": "文艺清新（旧版）",
    "humor": "幽默风趣（旧版）",
    "emotional": "情感故事（旧版）",
    "checkin": "地点打卡（旧版）",
}

PhotoType = Literal["portrait"]  # 仅人像类，不再区分风景


@dataclass
class PhotoInfo:
    """输入照片信息"""

    photo_id: str
    original_url: str
    order_index: int = 0


@dataclass
class SelectedPhoto:
    """筛选+精修后的单张照片结果"""

    photo_id: str
    original_url: str
    processed_url: str
    thumbnail_url: str
    quality_score: float
    face_count: int
    type: PhotoType
    retouch_style: RetouchStyle
    retouch_style_label: str
    cluster_group_id: int
    rank_in_group: int
    caption: str | None = None
    # 人脸结构化属性（来自腾讯云 IAI / 阿里云人脸检测）
    # 用于在精修阶段确定性选择美图预设，无需大模型
    face_gender: int | None = None  # 腾讯约定 1=男 / 0=女 / 2=未知；阿里云为 None
    face_age: int | None = None
    # 人物分类（确定性 API 推导优先，LLM 兜底）：man / woman / child / elderly / group / None
    # 用于选择对应的美图预设 ID
    category: str | None = None


@dataclass
class ScreeningResult:
    """智能筛选结果"""

    groups: list[dict] = field(default_factory=list)
    selected: list[SelectedPhoto] = field(default_factory=list)
    total_photos: int = 0
    total_groups: int = 0


@dataclass
class RetouchResult:
    """精修单张结果"""

    photo_id: str
    processed_url: str
    success: bool
    error: str | None = None


@dataclass
class CaptionResult:
    """文案生成结果"""

    captions: list[str] = field(default_factory=list)
    style: str = "literary"
    location: str | None = None


# ============ Provider 接口 ============


class ScreenerProvider(ABC):
    """智能筛选 Provider 接口（FR-201~209）"""

    @abstractmethod
    async def screen(
        self, photos: list[PhotoInfo], max_per_group: int = 2
    ) -> ScreeningResult:
        """对照片列表执行智能筛选

        - 构图聚类（相同构图分组）
        - 质量评分
        - 人脸检测
        - 每组精选 max_per_group 张
        """
        ...


class RetoucherProvider(ABC):
    """智能精修 Provider 接口（FR-301~310）"""

    @abstractmethod
    async def retouch(
        self,
        photo: SelectedPhoto,
    ) -> RetouchResult:
        """对单张照片执行精修

        - 人像照：按人物类型（男/女/儿童/老人/合照）匹配合适的美图预设
        """
        ...


class CaptionProvider(ABC):
    """文案生成 Provider 接口（FR-401~408）"""

    @abstractmethod
    async def generate(
        self,
        photo_urls: list[str],
        location: str | None,
        style: CaptionStyle,
        count: int = 3,
    ) -> CaptionResult:
        """生成多条朋友圈文案"""
        ...
