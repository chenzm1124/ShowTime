"""AI 服务层

按 WBS Week 3-4 开发计划实现：
- 智能筛选（screener）：CLIP 特征 + 聚类 + 质量评分
- 智能精修（retoucher）：人像美颜 + 风景调色
- 文案生成（caption_gen）：多风格朋友圈文案

架构：Provider 模式
- MockProvider：默认，生成模拟数据（开发期不阻塞）
- 真实 Provider：接口已定义，配置 API Key 后自动切换
"""

from app.ai.base import (
    PhotoInfo,
    ScreeningResult,
    SelectedPhoto,
    RetouchResult,
    CaptionResult,
)
from app.ai.pipeline import ai_pipeline

__all__ = [
    "PhotoInfo",
    "ScreeningResult",
    "SelectedPhoto",
    "RetouchResult",
    "CaptionResult",
    "ai_pipeline",
]
