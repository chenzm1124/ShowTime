"""AI 处理流水线编排

串联：智能筛选 → 人物分类 → 智能精修 → 文案生成
对应 PRD FR-201~408，WBS 3.1~3.8

使用方式：
    result = await ai_pipeline.process(photos, retouch_styles, location)
"""

import asyncio
import logging
import random
import time
from typing import Any

from app.ai.base import (
    CaptionResult,
    CaptionStyle,
    PhotoInfo,
    RetouchResult,
    ScreeningResult,
    SelectedPhoto,
    RETOUCH_STYLE_LABELS,
)
from app.ai.photo_classifier import classify_photos, infer_person_type
from app.ai.screener import MockScreener
from app.ai.screener_real import RealScreener, ScreeningFatalError
from app.ai.retoucher import MockRetoucher
from app.ai.caption_gen import QwenCaptionProvider
from app.core.config import get_settings
from app.services.photo_service import update_photo_processed

settings = get_settings()
logger = logging.getLogger(__name__)


class AIPipeline:
    """AI 处理流水线

    策略：
    - 配置了美图 API Key + media_code 时使用真实精修 Provider
    - 否则使用 Mock Provider（开发期不阻塞）
    - 任一阶段失败时降级到 Mock，保证流程不中断
    """

    def __init__(self):
        if settings.IQA_PROVIDER == "mock":
            self.screener = MockScreener()
            logger.info("[ai_pipeline] 使用 Mock 筛选 Provider（IQA_PROVIDER=mock）")
        else:
            self.screener = RealScreener()
            logger.info("[ai_pipeline] 使用真实筛选 Provider（RealScreener）")
        # 精修 Provider：配置了美图密钥时用真实，否则用 Mock
        if settings.MEITU_API_KEY and settings.MEITU_MEDIA_CODE:
            from app.ai.meitu_pro import MeituProRetoucher
            self.retoucher = MeituProRetoucher()
            logger.info("[ai_pipeline] 使用美图云修 Pro 精修 Provider")
        else:
            self.retoucher = MockRetoucher()
            logger.info("[ai_pipeline] 使用 Mock 精修 Provider（未配置美图密钥）")
        self.caption_provider = QwenCaptionProvider()

    async def process(
        self,
        photos: list[PhotoInfo],
        retouch_styles: list[str] | None = None,
        location: str | None = None,
        max_per_group: int = 1,
        db: Any | None = None,
        task_id: int | None = None,
        skip_screening: bool = False,
    ) -> dict:
        """执行完整 AI 处理流水线

        每组精选上限 max_per_group（默认 1：每组只挑质量最高的一张）。
        返回格式与 task_service extra_params 兼容：
        {
            "total_photos": int,
            "total_groups": int,
            "selected_photos": list[dict],
            "groups": list[dict],
        }

        skip_screening=True 时跳过聚类筛选，把传入的 photos 全部当作 selected
        直接进入精修阶段。用于「先筛选、再确认」流程：前端 preview 阶段已
        让用户确认过精选列表，create_task 阶段不应再做二次聚类去重，否则
        会出现"用户确认 4 张、结果页只精修 1 张"的矛盾（task_id=106 bug）。
        """
        styles = retouch_styles or ["auto"]

        # 1. 智能筛选（含耗时埋点，供耗时分析）
        t_screen_start = time.monotonic()
        if skip_screening:
            # 用户已在 /tasks/preview 确认过精选列表，跳过二次聚类。
            # 把每张图作为自己一组的 selected（rank=0），保留全部照片进精修。
            screening = self._screening_from_photos(photos)
            logger.info(
                f"[ai_pipeline] skip_screening=True，跳过聚类筛选，"
                f"直接精修全部 {len(photos)} 张"
            )
        else:
            screening = await self._screen(photos, max_per_group)
        t_screen_end = time.monotonic()

        # 2. 应用修图风格
        # P1-02 修复：尊重用户选择
        # - 旧逻辑：random.choice(styles) → 用户选 [hk,soft] 时被随机一个，丢失"我想要哪个"
        # - 新逻辑：
        #   1) 若用户只选了 1 个（含 ["auto"]）→ 用该 style
        #   2) 若用户选了多个（"风格探索"场景）→ 按 selected 顺序循环 / 选 score 最高的分到该 style
        #   3) styles 为空 → fallback "auto"
        if not styles:
            chosen_default = "auto"
            for item in screening.selected:
                item.retouch_style = chosen_default  # type: ignore
                item.retouch_style_label = RETOUCH_STYLE_LABELS.get(chosen_default, chosen_default)
        elif len(styles) == 1:
            for item in screening.selected:
                item.retouch_style = styles[0]  # type: ignore
                item.retouch_style_label = RETOUCH_STYLE_LABELS.get(styles[0], styles[0])
        else:
            # 多风格：按 score 排序分组
            sorted_items = sorted(
                screening.selected,
                key=lambda x: x.quality_score or 0,
                reverse=True,
            )
            n = len(sorted_items)
            for idx, item in enumerate(sorted_items):
                chosen = styles[idx % len(styles)]
                item.retouch_style = chosen  # type: ignore
                item.retouch_style_label = RETOUCH_STYLE_LABELS.get(chosen, chosen)

        # 3. 人物分类（多模态大模型判断每张图属于 man/woman/child/elderly/group）
        #    失败时 category=None，美图精修会回退到默认 media_code
        await self._classify(screening.selected)

        # 4. 智能精修（含耗时埋点）
        t_retouch_start = time.monotonic()
        await self._retouch(screening.selected, db=db, task_id=task_id)
        t_retouch_end = time.monotonic()

        # 5. 文案生成已移出主流程：按业务需求，文案由用户在结果页
        #    主动选择"生成朋友圈文案"后调用 /captions/generate 生成。
        #    此处不再自动生成单条 caption（避免无谓的 LLM 调用与 token 消耗）。

        result = self._to_dict(screening)
        # 耗时埋点：筛选 / 精修（秒，保留 2 位）。用于优化耗时分析。
        result["_timing"] = {
            "screening_s": round(t_screen_end - t_screen_start, 2),
            "retouch_s": round(t_retouch_end - t_retouch_start, 2),
            "n_selected": len(screening.selected),
            "n_groups": screening.total_groups,
        }
        logger.info(
            f"[ai_pipeline] 耗时统计 screening={result['_timing']['screening_s']}s "
            f"retouch={result['_timing']['retouch_s']}s "
            f"selected={result['_timing']['n_selected']} groups={result['_timing']['n_groups']}"
        )
        return result

    async def screen_only(
        self,
        photos: list[PhotoInfo],
        max_per_group: int = 1,
    ) -> dict:
        """仅做智能筛选（分组 + 评分排序），不精修、不文案、不扣额度。

        用于「先筛选、再确认」流程：前端上传完原图后调用，拿到分组/去重
        结果展示给用户确认，用户点「确认精修」才进入完整 process 并扣额度。
        这样用户能直观看到「14 张 → 9 组 → 精选 9 张（5 张相似已去重）」，
        而非蒙在鼓里被截断。
        """
        screening = await self._screen(photos, max_per_group)
        result = self._to_dict(screening)
        # 计算被去重的照片：在组内排名 >= max_per_group 的（非精选）
        # 注意：PhotoInfo 仅含 photo_id/original_url/order_index，
        # 评分细节在 screener 内部，这里只回传可用的原图信息 + 组归属。
        selected_ids = {s["photo_id"] for s in result["selected_photos"]}
        dropped: list[dict] = []
        for p in photos:
            if p.photo_id not in selected_ids:
                dropped.append(
                    {
                        "photo_id": p.photo_id,
                        "original_url": p.original_url,
                        "order_index": p.order_index,
                    }
                )
        dropped.sort(key=lambda x: x["order_index"])
        result["selected_count"] = len(result["selected_photos"])
        result["dropped_photos"] = dropped
        result["dropped_count"] = len(dropped)
        return result

    async def generate_captions_only(
        self,
        photo_urls: list[str],
        location: str | None,
        styles: list[str],
        count_per_style: int = 3,
        event_name: str | None = None,
    ) -> dict[str, list[str]]:
        """单独生成文案（供 /captions/generate 端点调用）

        业务约定：
        - styles 1~2 个，每风格生成 count_per_style 条（默认 3）
        - 不消耗套餐次数（由调用方保证，本方法不做额度校验）
        - event_name 非必填；存在时会与 location 一起作为提示词传给 LLM，
          也参与模板降级路径（"活动名称 · 地点"拼接）
        返回：{style_code: [text, ...]}
        """
        return await self.caption_provider.generate_multi(  # type: ignore[attr-defined]
            photo_urls, location, styles, count_per_style, event_name=event_name
        )

    # ---------- 内部方法 ----------

    async def _screen(
        self, photos: list[PhotoInfo], max_per_group: int
    ) -> ScreeningResult:
        try:
            return await self.screener.screen(photos, max_per_group)
        except ScreeningFatalError as e:
            # 致命错误（如全部图片下载失败）：不降级 Mock，直接向上抛出，
            # 让上层任务进入 FAILED 分支（前端报错 + 返还额度）。
            logger.error(f"[ai_pipeline] RealScreener 致命错误，中止筛选：{e}")
            raise
        except Exception as e:
            # 其他非致命异常（如单张分析偶发失败）→ 降级到 MockScreener。
            # 用 ERROR 级别（原 WARNING 太安静，被运维忽略导致重复踩坑）。
            # Mock 看不到图片内容，分组结果可能与预期不符，应立即被发现。
            logger.error(
                f"[ai_pipeline] RealScreener 异常，降级到 MockScreener（任务继续，"
                f"但分组可能不准确）：{type(e).__name__}: {e}"
            )
            self.screener = MockScreener()
            return await self.screener.screen(photos, max_per_group)

    def _screening_from_photos(
        self, photos: list[PhotoInfo]
    ) -> ScreeningResult:
        """skip_screening=True 时构造 ScreeningResult：所有照片都入选，每张自成一组的精选项。

        - 不调用任何外部 API（不下载图、不调 IAI、不调 LLM），所以零耗时。
        - quality_score/face_count 等字段留默认值（0），后续 _classify 阶段会尝试补全
          category；不补也没关系，MeituProRetoucher 会回退到默认预设。
        - cluster_group_id 用 order_index，保证每张独立成组，total_groups == 入选数。
        """
        selected: list[SelectedPhoto] = []
        for i, p in enumerate(photos):
            selected.append(
                SelectedPhoto(
                    photo_id=p.photo_id,
                    original_url=p.original_url,
                    processed_url=p.original_url,  # 筛选阶段尚未精修
                    thumbnail_url=p.original_url,
                    quality_score=0.0,
                    face_count=0,
                    type="portrait",
                    retouch_style="auto",
                    retouch_style_label="智能配风格",
                    cluster_group_id=i,
                    rank_in_group=0,
                )
            )
        return ScreeningResult(
            total_photos=len(photos),
            total_groups=len(photos),
            selected=selected,
        )

    async def _classify(self, selected: list[SelectedPhoto]) -> None:
        """对筛选后的图片做人物分类（5 类：man/woman/child/elderly/group）

        主路径：用筛选阶段已拿到的人脸结构化属性（腾讯云 IAI / 阿里云）
        确定性推导，零额外调用、零大模型依赖。
        兜底：仅对属性不足以判定的图，且配置了 LLM_API_KEY 时，调大模型补全。
        最终 category=None 的图，MeituProRetoucher 会用 MEITU_MEDIA_CODE 兜底。
        """
        if not selected:
            return

        # 1) API 属性优先：确定性推导
        inferred: dict[str, str] = {}
        for item in selected:
            cat = infer_person_type(item.face_count, item.face_gender, item.face_age)
            if cat:
                inferred[item.photo_id] = cat

        # 2) LLM 兜底：仅属性不足且有 key 的图
        need_llm = [item for item in selected if item.photo_id not in inferred]
        if need_llm and settings.LLM_API_KEY:
            try:
                url_to_category = await classify_photos([i.original_url for i in need_llm])
                for item in need_llm:
                    c = url_to_category.get(item.original_url)
                    if c:
                        inferred[item.photo_id] = c
            except Exception as e:
                logger.warning(f"[ai_pipeline] LLM 兜底分类失败（不影响精修）: {e}")

        for item in selected:
            cat = inferred.get(item.photo_id)
            item.category = cat
            if cat:
                logger.info(f"[ai_pipeline] 分类 photo={item.photo_id} → {cat} "
                            f"(face_count={item.face_count}, gender={item.face_gender}, age={item.face_age})")
            else:
                logger.debug(f"[ai_pipeline] 分类未命中 photo={item.photo_id}，用默认预设")

        # 自检：若检测到人脸的人像图仍没分类，说明分类链路未真正生效
        # （典型原因：跑的是旧进程 / 分类代码没加载 / IAI 与 LLM 兜底都没拿到属性）。
        # 之前「_classify 在旧进程不生效」正是因为旧进程无此逻辑却静默跑完，
        # 没有任何报错，导致误判为业务 bug。这里升级为 ERROR 日志，让问题可见。
        undetected = [
            item for item in selected
            if item.face_count and item.face_count > 0 and not item.category
        ]
        if undetected:
            ids = ", ".join(str(i.photo_id) for i in undetected)
            reason = (
                "LLM_API_KEY 未配置，且 IAI/阿里云未返回可判定属性"
                if not settings.LLM_API_KEY
                else "IAI/阿里云与 LLM 兜底均未返回可判定属性"
            )
            logger.error(
                f"[ai_pipeline][WARN] 检测到人脸但分类为 None 的图 {len(undetected)} 张 "
                f"(photo_ids={ids})。疑似分类链路未生效：{reason}。"
                f"这些图将回退到默认美图预设（男人）。若需按人物类型精修，请排查上述链路或配置 LLM_API_KEY。"
            )

    # 精修并发上限 + 提交间隔。
    # 业务诉求：N 张筛选后的照片「并行」提交给美图云修 Pro，同时处理，
    # 大幅缩短整体耗时（而非串行 N×单张）。
    #
    # P1-11 修复：之前 _RETOUCH_CONCURRENCY=5 + asyncio.gather 立刻同时发起 5 个提交，
    # 在美图云修 Pro 上触发了隐性限流（同一 API key 短时间内多次提交时只有 1 张被
    # 真正处理，其余都在 query.json 上持续返回 processing，直到 600s 超时降级原图）。
    # 修复：
    # - 并发上限从 5 降到 2（避免超过美图侧短时并发承载）
    # - 提交间隔从 0 → 2 秒（错峰避免被风控判定为机器请求）
    # 实测 6 张耗时 ≈ 6×(单张 + 2s) / 2 ≈ 3 倍单张时间，仍比串行 6 倍快很多。
    _RETOUCH_CONCURRENCY = 2
    _RETOUCH_SUBMIT_INTERVAL = 2.0  # 秒

    async def _retouch(
        self,
        selected: list[SelectedPhoto],
        db: Any | None = None,
        task_id: int | None = None,
    ) -> list[RetouchResult]:
        """精修阶段：限流并行提交 + 错峰间隔。

        优化前：for 循环串行 → 6 张图 × 4 分钟 = 24 分钟
        优化后：Semaphore(2) + 2s 错峰 → 6 张图 ≈ 3-5 分钟（提速 5+ 倍且避免限流）

        逐张即时落库：每张精修（成功/失败）完成后立即把 processed_url 写回
        对应 Photo 记录，使前端轮询 status 时能「先处理好的先显示」，
        未处理好的位置用蒙版 + loading 占位，无需等全部完成。
        """
        if not selected:
            return []

        sem = asyncio.Semaphore(self._RETOUCH_CONCURRENCY)

        async def _retouch_one(photo: SelectedPhoto, submit_idx: int) -> RetouchResult:
            result: RetouchResult | None = None
            # 错峰：每张提交前等 2 秒 * 序号（被并发数摊薄），避免瞬时 5 并发把美图打挂
            delay = self._RETOUCH_SUBMIT_INTERVAL * submit_idx / max(self._RETOUCH_CONCURRENCY, 1)
            if delay > 0:
                await asyncio.sleep(delay)
            async with sem:
                try:
                    result = await self.retoucher.retouch(photo)
                    # 无论成功/失败都更新 processed_url：
                    # - 成功 → 真实精修图 COS 地址
                    # - 失败 → 原图 + _retouch_failed 标记（前端可检测并提示）
                    photo.processed_url = result.processed_url
                    if not result.success:
                        logger.warning(
                            f"[ai_pipeline] 精修失败 photo={photo.photo_id} "
                            f"reason={result.error}, 已降级为带标记的原图"
                        )
                    return result
                except Exception as e:
                    logger.warning(f"[ai_pipeline] 精修异常 photo={photo.photo_id}: {e}")
                    result = RetouchResult(
                        photo_id=photo.photo_id,
                        processed_url=photo.processed_url,
                        success=False,
                        error=str(e),
                    )
                    return result
                finally:
                    # 逐张即时回写 Photo 表（先好先显示）
                    if db is not None and task_id is not None and result is not None:
                        try:
                            await update_photo_processed(
                                db,
                                photo_id=int(photo.photo_id),
                                task_id=task_id,
                                processed_url=result.processed_url,
                                success=result.success,
                            )
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"[ai_pipeline] 写回 Photo {photo.photo_id} 失败: {e}")

        # 按输入顺序 gather（保证结果顺序与输入一致）
        results = await asyncio.gather(
            *[_retouch_one(p, i) for i, p in enumerate(selected)],
            return_exceptions=False,  # 单张异常已在 _retouch_one 内捕获
        )
        logger.info(
            f"[ai_pipeline] 精修完成: {len(results)} 张（并发={self._RETOUCH_CONCURRENCY}，"
            f"错峰={self._RETOUCH_SUBMIT_INTERVAL}s）"
        )
        return list(results)

    async def _generate_captions(
        self, screening: ScreeningResult, location: str | None
    ):
        """为每组第一张照片生成文案"""
        if not screening.selected:
            return

        # 取每组第一张的 URL
        group_first_urls: list[str] = []
        seen_groups: set[int] = set()
        for item in screening.selected:
            if item.cluster_group_id not in seen_groups:
                seen_groups.add(item.cluster_group_id)
                group_first_urls.append(item.original_url)

        try:
            result = await self.caption_provider.generate(
                group_first_urls[:3],  # 最多用 3 张图
                location,
                "literary",  # type: ignore
                count=len(seen_groups),
            )
        except Exception as e:
            logger.warning(f"[ai_pipeline] 文案生成失败: {e}")
            return

        # 把文案分配到对应组的第一张照片
        caption_idx = 0
        seen_groups_2: set[int] = set()
        for item in screening.selected:
            if item.cluster_group_id not in seen_groups_2:
                seen_groups_2.add(item.cluster_group_id)
                if caption_idx < len(result.captions):
                    item.caption = result.captions[caption_idx]
                    caption_idx += 1

    def _to_dict(self, screening: ScreeningResult) -> dict:
        """转换为 task_service 兼容的 dict 格式"""
        selected_dicts = []
        groups_map: dict[int, dict] = {}

        for item in screening.selected:
            d = {
                "photo_id": item.photo_id,
                "original_url": item.original_url,
                "processed_url": item.processed_url,
                "thumbnail_url": item.thumbnail_url,
                "quality_score": item.quality_score,
                "face_count": item.face_count,
                "type": item.type,
                "retouch_style": item.retouch_style,
                "retouch_style_label": item.retouch_style_label,
                "caption": item.caption,
                "cluster_group_id": item.cluster_group_id,
                "rank_in_group": item.rank_in_group,
                "category": item.category,  # 人物分类：man/woman/child/elderly/group/None
            }
            selected_dicts.append(d)

            gid = item.cluster_group_id
            if gid not in groups_map:
                groups_map[gid] = {
                    "group_id": gid,
                    "group_type": item.type,
                    "photos": [],
                }
            groups_map[gid]["photos"].append(d)

        return {
            "total_photos": screening.total_photos,
            "total_groups": screening.total_groups,
            "selected_photos": selected_dicts,
            "groups": list(groups_map.values()),
        }


# 全局单例
ai_pipeline = AIPipeline()
