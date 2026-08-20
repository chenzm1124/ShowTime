"""Mock 智能筛选 Provider

兜底实现：仅在 RealScreener 抛异常时由 pipeline._screen 启用。
设计原则：行为尽量与 RealScreener 对齐——
- 整批共用一个稳定的 group_size（不再每张重选，避免 gid 错位）
- 严格遵守 max_per_group：每组只保留前 max_per_group 张
- 随机 quality_score / type 仅供开发期调试

注意：Mock 看不到图片内容，无法按"统一人物+相似背景"分组。
真正按内容分组必须由 RealScreener 完成（Qwen-VL 标签）。
"""
import random

from app.ai.base import (
    PhotoInfo,
    PhotoType,
    ScreeningResult,
    SelectedPhoto,
    ScreenerProvider,
    RETOUCH_STYLE_LABELS,
)


class MockScreener(ScreenerProvider):
    """Mock 智能筛选（仅作 RealScreener 异常时的兜底）"""

    async def screen(
        self, photos: list[PhotoInfo], max_per_group: int = 1
    ) -> ScreeningResult:
        if not photos:
            return ScreeningResult(groups=[], selected=[], total_photos=0, total_groups=0)

        selected: list[SelectedPhoto] = []
        groups_map: dict[int, dict] = {}
        n = len(photos)
        # 整批共用一个稳定的 group_size（修复：原代码每张 random.choice
        # 导致 gid = i // group_size 因 group_size 不同而错位，6 张分出 2+4）
        if n >= 2:
            group_size = random.choice([2, 3])
        else:
            group_size = 1

        for i, photo in enumerate(photos):
            gid = i // group_size
            rank_in_group = i % max_per_group
            # 严格遵守 max_per_group：超过上限不入选（修复：原代码无条件 append）
            if rank_in_group >= max_per_group:
                continue

            photo_type: PhotoType = "portrait"  # 仅人像类
            style = "auto"
            style_label = RETOUCH_STYLE_LABELS.get(style, style)

            item = SelectedPhoto(
                photo_id=photo.photo_id,
                original_url=photo.original_url,
                processed_url=photo.original_url,  # Mock：用原图代替
                thumbnail_url=photo.original_url,
                quality_score=round(random.uniform(0.65, 0.95), 2),
                face_count=random.randint(0, 3),  # 始终有人物
                type=photo_type,
                retouch_style=style,  # type: ignore
                retouch_style_label=style_label,
                cluster_group_id=gid,
                rank_in_group=rank_in_group,
            )
            selected.append(item)

            if gid not in groups_map:
                groups_map[gid] = {
                    "group_id": gid,
                    "group_type": photo_type,
                    "photos": [],
                }
            groups_map[gid]["photos"].append(
                {
                    "photo_id": item.photo_id,
                    "original_url": item.original_url,
                    "processed_url": item.processed_url,
                    "thumbnail_url": item.thumbnail_url,
                    "quality_score": item.quality_score,
                    "face_count": item.face_count,
                    "type": item.type,
                    "retouch_style": item.retouch_style,
                    "retouch_style_label": item.retouch_style_label,
                    "cluster_group_id": item.cluster_group_id,
                    "rank_in_group": item.rank_in_group,
                    "caption": item.caption,
                }
            )

        return ScreeningResult(
            groups=list(groups_map.values()),
            selected=selected,
            total_photos=n,
            total_groups=len(groups_map),
        )