"""真实智能筛选 Provider（Phase 1：L0 去重 + L1 技术质量 + L2 人像质量）

分层流水线（详见《技术方案-人像质量打分筛选.md》）：
- L0  去重 / 废片剔除：aHash 感知哈希 + 拉普拉斯方差（本地 CV，无需凭据）
- L1  技术质量分：清晰度（拉普拉斯方差）+ 曝光（直方图）+ 构图（中性/阿里云）
- L2  人像质量分：人脸检测 API（阿里云，未配置时降级为中性 0.7）

依赖：numpy + Pillow（本地 CV 基线）。阿里云 IQA / 人脸检测为可升级钩子，
未配置 IQA_ACCESS_KEY_ID/SECRET 时自动降级为本地 CV，保证流程始终可用。

与 MockScreener 接口一致（ScreenerProvider.screen），pipeline 第 73 行调用无需改动。
"""

import asyncio
import io
import logging
from typing import Optional

import httpx
import numpy as np
from PIL import Image, ImageFilter

# Pillow 兼容：新版把 LANCZOS 移到 Image.Resampling
_Resampling = getattr(Image, "Resampling", Image)
_RESAMPLE = _Resampling.LANCZOS

from app.ai.base import (
    PhotoInfo,
    PhotoType,
    ScreeningResult,
    SelectedPhoto,
    ScreenerProvider,
)
from app.ai.aliyun_vision import assess_iqa, detect_face as aliyun_detect_face
from app.ai.tencent_vision import (
    assess_quality as tencent_assess_quality,
    compare_face as tencent_compare_face,
    detect_face as tencent_detect_face,
    key_from_url,
)
# P0 修复：用后端 COS 密钥生成预签名 GET URL 下载（而非裸 URL 匿名 GET），
# 这样无论桶 ACL / 对象 ACL 是私有都能正常读取，不依赖公有读配置。
from app.services.photo_service import _get_cos_client as _get_cos_client_for_dl
# 聚类：统一人物 + 相似背景即可同组 → Qwen-VL-Plus 输出结构化标签
# （不再要求动作一致，并放宽背景元素重叠阈值，让照片更易并入同组）
from app.ai.qwen_vl_labeller import (
    background_match,
    label_images,
    people_match,
)
# P1-12 修复：启用 Qwen multimodal-embedding-v1 余弦相似度聚类。
# 背景：qwen_embedding.py 早已实现完整 embed_images/cosine_similarity，
# settings 也开了 CLUSTER_USE_QWEN_EMBEDDING=True + 配了 LLM_API_KEY，但
# screener_real._cluster_photos 从未调用过它。导致"同人物同背景但构图/角度
# 略不同"的照片（旅行照常见）只能靠 VL 文字标签 + 像素哈希兜底，而 VL 对
# 同一景点常给出不同 background_type（"花海"/"其他"）或不同 elements
# （"樱花" vs "樱花树"），致使 background_match 直接 False → 不同组。
# Embedding 走语义层（高维向量包含人物/构图/背景全部特征），能补这一层。
from app.ai.qwen_embedding import embed_images, cosine_similarity
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class ScreeningFatalError(Exception):
    """筛选致命错误：不应降级到 MockScreener，应直接让任务进入 FAILED。

    典型场景：全部照片图片下载失败（重试后仍 403/超时），无法做任何分析，
    继续"闷头降级"会给用户错误的"全部保留"结果，且无任何提示。
    """

# 兜底：确保 screener 日志也写到 backend-restart.log
# （uvicorn 默认接管 logger 后，子 logger 的 propagation 可能被切断）
_CLUSTER_LOG_PATH = r"d:\个人\workbuddy工作区\travel-photo\backend\backend-restart.log"
try:
    import os as _os
    if _os.path.exists(_CLUSTER_LOG_PATH) and not any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == _CLUSTER_LOG_PATH
        for h in logger.handlers
    ):
        _fh = logging.FileHandler(_CLUSTER_LOG_PATH, encoding="utf-8")
        _fh.setLevel(logging.INFO)
        _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(_fh)
except Exception:
    pass

# 本地 CV 基线下，人脸质量未知时使用的中性分（避免人像被不公平惩罚）
_FACE_UNKNOWN_NEUTRAL = 0.7
# 构图分本地无法可靠估计，使用中性值；配置阿里云后由 API 覆盖
_COMPOSITION_NEUTRAL = 0.7
# 单图下载+推理并发上限，避免瞬时打爆 COS / 阿里云配额
_CONCURRENCY = 10
# 缩略预处理尺寸（足够判模糊/曝光/哈希，省带宽）
_PREPROCESS_SIZE = (256, 256)
# 传给阿里云 RPC 的图片尺寸上限（base64 传参，控制体积与时延；人脸检测/质量打分足够）
_ALIYUN_MAX_SIZE = (1024, 1024)


class RealScreener(ScreenerProvider):
    """真实智能筛选（分层混合，CV 基线 + 腾讯云/阿里云可升级）"""

    def __init__(self):
        provider = settings.IQA_PROVIDER
        self._use_tencent = provider == "tencent" and bool(
            settings.COS_SECRET_ID and settings.COS_SECRET_KEY and settings.COS_BUCKET
        )
        self._use_aliyun = provider == "aliyun" and bool(
            settings.IQA_ACCESS_KEY_ID and settings.IQA_ACCESS_KEY_SECRET
        )
        if self._use_tencent:
            logger.info(
                "[real_screener] 使用腾讯云 COS 质量评分 + IAI 人脸检测（图片零转存）"
            )
        elif self._use_aliyun:
            logger.info("[real_screener] 使用阿里云 IQA + 人脸检测（已配置凭据）")
        else:
            logger.info("[real_screener] 未配置真实 provider，使用本地 CV 基线（清晰度/曝光/去重）")

    async def screen(
        self, photos: list[PhotoInfo], max_per_group: int = 2
    ) -> ScreeningResult:
        if not photos:
            return ScreeningResult(groups=[], selected=[], total_photos=0, total_groups=0)

        logger.info(f"[real_screener] 开始筛选 {len(photos)} 张照片")

        semaphore = asyncio.Semaphore(_CONCURRENCY)
        async with httpx.AsyncClient(timeout=20) as client:
            tasks = [
                self._analyze(client, semaphore, photo) for photo in photos
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # 汇总每图分析结果。
        # 关键修复：下载失败（DownloadFailed）不再"闷头降级"为中性分，
        # 若全部/绝大多数照片都无法下载（典型：COS 私有桶 403），则判定为致命错误，
        # 抛 ScreeningFatalError 让 pipeline 进入 FAILED 分支（前端报错 + 返还额度）。
        analyses: list[dict] = []
        download_failed = 0
        fatal_errors: list[Exception] = []
        for photo, r in zip(photos, results):
            if isinstance(r, DownloadFailed):
                download_failed += 1
                fatal_errors.append(r)
                # 仍垫一份中性分，避免后续聚类因缺字段崩溃（仅在非致命时使用）
                analyses.append(self._neutral_analysis(photo))
            elif isinstance(r, Exception):
                logger.warning(f"[real_screener] 分析失败 photo={photo.photo_id}: {r}")
                analyses.append(self._neutral_analysis(photo))
            else:
                analyses.append(r)

        # 全部（或 >80%）图片下载失败 → 视为筛选无法进行
        if photos and download_failed == len(photos):
            raise ScreeningFatalError(
                f"全部 {len(photos)} 张照片图片下载失败，筛选无法执行"
                f"（疑似 COS 授权/网络问题）。首条错误：{fatal_errors[0] if fatal_errors else '未知'}"
            )
        if photos and download_failed > int(len(photos) * 0.8):
            raise ScreeningFatalError(
                f"{download_failed}/{len(photos)} 张照片图片下载失败，筛选结果不可信"
                f"（疑似 COS 授权/网络问题），已中止筛选。"
            )
        if download_failed > 0:
            logger.error(
                f"[real_screener] 有 {download_failed}/{len(photos)} 张图片下载失败"
                f"（已降级为中性分，去重可能不准确）"
            )

        # L0 去重：Qwen embedding 优先 + 多哈希 OR 投票（同一构图/同人物簇）
        cluster_of, group_count = await self._cluster_photos(analyses)

        # 组内按综合分排序，分配 rank_in_group
        selected = self._build_selected(photos, analyses, cluster_of, max_per_group)

        # 组装 groups（与 MockScreener 输出结构一致）
        groups_map: dict[int, dict] = {}
        for item in selected:
            gid = item.cluster_group_id
            groups_map.setdefault(
                gid,
                {"group_id": gid, "group_type": item.type, "photos": []},
            )
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
            total_photos=len(photos),
            total_groups=group_count,
        )

    # ---------- 单图分析 ----------

    async def _analyze(
        self, client: httpx.AsyncClient, sem: asyncio.Semaphore, photo: PhotoInfo
    ) -> dict:
        async with sem:
            # 下载失败（重试后）会抛 DownloadFailed → 冒泡到 screen 的 gather，
            # 由 screen 汇总判断是否为致命错误（不在此静默降级）。
            img = await self._download_image(client, photo.original_url)

            gray = img.convert("L").resize(_PREPROCESS_SIZE, _RESAMPLE)
            sharpness = self._sharpness(gray)
            exposure = self._exposure(gray)
            ahash = self._ahash(gray)
            dhash = self._dhash(gray)
            phash = self._phash(gray)
            composition = _COMPOSITION_NEUTRAL  # 默认值，云端成功时覆盖
            low_penalty = 1.0  # 低质内容惩罚系数（腾讯云 LowQualityScore 命中时下调）

            # L1/L2：云端质量评分 + 人脸检测（未配置/未开通则返回 None，使用本地/中性值）
            face = None
            if self._use_tencent:
                # 腾讯云：质量评分用 COS Key，人脸检测直接传 COS 公网 Url
                key = key_from_url(photo.original_url)
                quality = await self._maybe_tencent_quality(key)
                face = await self._maybe_tencent_face(photo.original_url)
                if quality is not None:
                    clarity, aesthetic, low_quality = quality
                    if clarity is not None:
                        sharpness = clarity  # ClarityScore 已综合噪声/曝光/模糊
                    if aesthetic is not None:
                        composition = aesthetic  # AestheticScore：构图/色彩
                    # 内容质量越低（LowQualityScore 越高）越重罚，最高打 6 折
                    if low_quality is not None:
                        low_penalty = 1.0 - 0.4 * low_quality
                    else:
                        low_penalty = 1.0
            elif self._use_aliyun:
                # 阿里云：base64 传参绕开 COS 域名限制
                aliyun_bytes = self._to_aliyun_bytes(img)
                iqa = await self._maybe_aliyun_iqa(aliyun_bytes)
                face = await self._maybe_aliyun_face(aliyun_bytes)
                if iqa is not None:
                    clarity, exp_api, comp_api = iqa
                    if clarity is not None:
                        sharpness = clarity
                    if exp_api is not None:
                        exposure = exp_api
                    if comp_api is not None:
                        composition = comp_api

            if face is not None:
                if len(face) == 4:
                    face_count, face_quality, face_gender, face_age = face
                else:
                    # 阿里云等只返回 (face_count, face_quality)，性别/年龄未知
                    face_count, face_quality = face
                    face_gender, face_age = None, None
            else:
                face_count, face_quality, face_gender, face_age = 0, _FACE_UNKNOWN_NEUTRAL, None, None

            photo_type: PhotoType = "portrait"  # 仅人像类，不再区分风景

            weights = settings.score_weights(photo_type)
            score = (
                weights.get("sharpness", 0) * sharpness
                + weights.get("exposure", 0) * exposure
                + weights.get("composition", 0) * composition
                + weights.get("face", 0) * face_quality
            )
            # 低质内容惩罚（LowQualityScore 越高打的折越多）
            score = score * low_penalty

            return {
                "photo_id": photo.photo_id,
                "original_url": photo.original_url,
                "sharpness": sharpness,
                "exposure": exposure,
                "composition": composition,
                "face_count": face_count,
                "face_quality": face_quality,
                "face_gender": face_gender,
                "face_age": face_age,
                "type": photo_type,
                "ahash": ahash,
                "dhash": dhash,
                "phash": phash,
                "quality_score": round(float(score), 3),
                "embedding": None,  # 在 _cluster_photos 阶段异步补齐
            }

    @staticmethod
    async def _download_image(client: httpx.AsyncClient, url: str, retries: int = 3):
        """下载图片为 PIL Image。

        P0 修复：不再依赖裸 URL 匿名 GET（私有桶会 403），改为用后端 COS 密钥
        生成预签名 GET URL 再下载——无论桶 ACL / 对象 ACL 是否公有读，owner
        密钥签名的 URL 都可读。下载失败按 retries 重试，全部失败抛 DownloadFailed。
        """
        # 1) 优先用后端密钥生成带签名的 GET URL（对任意私有对象都可读）
        signed_url = None
        try:
            cos_client = _get_cos_client_for_dl()
            if cos_client is not None:
                key = key_from_url(url)
                if key:
                    signed_url = cos_client.get_presigned_url(
                        Method="GET",
                        Bucket=settings.COS_BUCKET,
                        Key=key,
                        Expired=120,
                    )
        except Exception as e:
            logger.warning(f"[real_screener] 生成签名 GET URL 失败，回退裸 URL: {e}")
            signed_url = None

        effective_url = signed_url or url
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                r = await client.get(effective_url)
                if r.status_code != 200:
                    last_err = RuntimeError(f"HTTP {r.status_code}")
                    logger.warning(
                        f"[real_screener] 图片下载失败(第{attempt}次) status={r.status_code} "
                        f"url={url[:60]}"
                    )
                else:
                    return Image.open(io.BytesIO(r.content))
            except Exception as e:
                last_err = e
                logger.warning(
                    f"[real_screener] 图片下载异常(第{attempt}次): {e} url={url[:60]}"
                )
            # 退避后重试（最后一次不睡）
            if attempt < retries:
                await asyncio.sleep(0.5 * attempt)
        raise DownloadFailed(url=url, reason=str(last_err))

    @staticmethod
    def _neutral_analysis(photo: PhotoInfo) -> dict:
        """图片不可用时给出中性分，保证照片不被丢弃"""
        return {
            "photo_id": photo.photo_id,
            "original_url": photo.original_url,
            "sharpness": _FACE_UNKNOWN_NEUTRAL,
            "exposure": _FACE_UNKNOWN_NEUTRAL,
            "composition": _COMPOSITION_NEUTRAL,
            "face_count": 0,
            "face_quality": _FACE_UNKNOWN_NEUTRAL,
            "type": "portrait",
            "ahash": None,
            "dhash": None,
            "phash": None,
            "quality_score": 0.7,
        }

    # ---------- 本地 CV 指标 ----------

    @staticmethod
    def _sharpness(gray: Image.Image) -> float:
        """拉普拉斯方差 → 归一化清晰度（0~1）。值越高越清晰。"""
        lap = gray.filter(
            ImageFilter.Kernel(
                (3, 3), (-1, -1, -1, -1, 8, -1, -1, -1, -1), scale=1
            )
        )
        arr = np.asarray(lap, dtype=np.float32)
        var = float(arr.var())
        # 经验归一化：清晰图方差常 >300，糊图 <50
        return float(np.clip(var / 600.0, 0.0, 1.0))

    @staticmethod
    def _exposure(gray: Image.Image) -> float:
        """直方图分析 → 归一化曝光分（0~1）。正常曝光接近 1。"""
        hist = gray.histogram()  # 256 bins
        total = sum(hist) or 1
        mean = sum(i * h for i, h in enumerate(hist)) / total
        over = sum(hist[245:]) / total
        under = sum(hist[:10]) / total
        # 理想均值 ~128；过曝/欠曝占比越高扣分越多
        score = (
            1.0
            - min(abs(mean - 128) / 128.0, 1.0) * 0.5
            - min(over, 0.2) / 0.2 * 0.3
            - min(under, 0.2) / 0.2 * 0.2
        )
        return float(np.clip(score, 0.0, 1.0))

    @staticmethod
    def _ahash(gray: Image.Image) -> int:
        """平均哈希（aHash）：8x8 灰度二值化，返回 64-bit 整数。"""
        small = gray.resize((8, 8), _RESAMPLE)
        arr = np.asarray(small, dtype=np.float32)
        mean = arr.mean()
        bits = arr > mean
        h = 0
        for bit in bits.flatten():
            h = (h << 1) | int(bit)
        return h

    @staticmethod
    def _dhash(gray: Image.Image) -> int:
        """差异哈希（dHash）：9x8 灰度，比较相邻像素亮度差，返回 64-bit 整数。

        对「亮度突变」敏感，能识别构图相同的轻微色调变化（如曝光/滤镜差异）。
        """
        small = gray.resize((9, 8), _RESAMPLE)
        arr = np.asarray(small, dtype=np.float32)
        bits = arr[:, 1:] > arr[:, :-1]   # 8x8 差值位
        h = 0
        for bit in bits.flatten():
            h = (h << 1) | int(bit)
        return h

    @staticmethod
    def _phash(gray: Image.Image) -> int:
        """感知哈希（pHash）：32x32 → DCT 低频 → 8x8 主频率二值化。

        对「整体频率结构」最鲁棒，对亮度/对比度变化不敏感，
        对轻微裁剪/旋转的构图变化敏感。
        依赖 numpy.fft 实现 2D DCT（无需 scipy）。
        """
        small = gray.resize((32, 32), _RESAMPLE)
        arr = np.asarray(small, dtype=np.float32)
        # 2D DCT via FFT（去直流分量后实部 = 余弦变换）
        dct = np.real(np.fft.fft2(arr * 1.0))
        # 取左上 8x8 低频
        low = dct[:8, :8]
        # 去掉直流项（最大幅值位于 [0,0]），用剩余 63 项均值
        med = np.median(low)
        # 第一项是 DC，用 med 作阈值通常比 mean 更稳
        bits = low > med
        h = 0
        for bit in bits.flatten():
            h = (h << 1) | int(bit)
        return h

    @staticmethod
    def _hamming(a: int | None, b: int | None) -> int:
        if a is None or b is None:
            return 999
        return bin(a ^ b).count("1")

    @staticmethod
    def _hash_vote_same(
        a_hashes: dict[str, int | None],
        b_hashes: dict[str, int | None],
        thresholds: dict[str, int],
    ) -> bool:
        """三哈希 AND 投票：三种哈希距离全部 ≤ 阈值 → 才判为同组（近重复）。

        沙龙场景改为 AND：只有构图几乎完全一致（同角度同姿势的连拍/复制）
        才会三种哈希同时贴近，从而被合并；某一种偶然接近（如纯色背景）不再误合并。
        这与「仅像素级连拍去重」的口径一致——放宽 OR 会把同人同背景不同构图的
        照片误判为重复。

        Args:
            a_hashes: {"ahash": int|None, "dhash": int|None, "phash": int|None}
            b_hashes: 同上
            thresholds: {"ahash": int, "dhash": int, "phash": int}
        """
        for kind, th in thresholds.items():
            if a_hashes.get(kind) is None or b_hashes.get(kind) is None:
                return False
            dist = bin(a_hashes[kind] ^ b_hashes[kind]).count("1")
            if dist > th:
                return False
        return True

    # ---------- 腾讯云钩子（未开通/未配置时返回 None） ----------

    async def _maybe_tencent_quality(self, key):
        """腾讯云数据万象图片质量评分：返回 (clarity, aesthetic, low_quality) 各 0~1。

        未开启/未开通/失败返回 None，由本地 CV 值顶替。
        """
        if not self._use_tencent or not settings.IQA_ENABLE_TENCENT_QUALITY or not key:
            return None
        try:
            return await asyncio.to_thread(tencent_assess_quality, key)
        except Exception as e:
            logger.warning(f"[real_screener] 腾讯云质量评分异常，回退 CV: {e}")
            return None

    async def _maybe_tencent_face(self, url: str):
        """腾讯云 IAI 人脸检测：返回 (face_count, face_quality:0~1, gender, age)。

        gender: 1=男/0=女/2=未知；age: 整数年龄。二者用于人物类别判定。
        未开启/失败返回 None，face_count=0 / face_quality=中性 / gender,age=None。
        """
        if not self._use_tencent or not settings.IQA_ENABLE_TENCENT_FACE:
            return None
        try:
            return await asyncio.to_thread(tencent_detect_face, url, None)
        except Exception as e:
            logger.warning(f"[real_screener] 腾讯云人脸检测异常，回退中性: {e}")
            return None

    # ---------- 阿里云可升级钩子（未配置凭据时返回 None） ----------

    @staticmethod
    def _to_aliyun_bytes(img: Image.Image) -> bytes:
        """缩放并编码为 JPEG 字节，用于 base64 传给阿里云（绕开 COS 域名限制）。"""
        src = img.convert("RGB")
        src.thumbnail(_ALIYUN_MAX_SIZE, _RESAMPLE)
        buf = io.BytesIO()
        src.save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    async def _maybe_aliyun_iqa(self, image_data: bytes):
        """调用阿里云视觉智能开放平台：图像清晰度/曝光/构图评分。

        返回 (clarity, exposure, composition) 各 0~1；失败/未开启/未配置返回 None，
        由本地 CV 值顶替（composition 用中性）。
        """
        if not self._use_aliyun or not settings.IQA_ENABLE_IMAGEENHAN:
            return None
        try:
            return await asyncio.to_thread(assess_iqa, None, image_data)
        except Exception as e:
            logger.warning(f"[real_screener] IQA RPC 异常，回退 CV: {e}")
            return None

    async def _maybe_aliyun_face(self, image_data: bytes):
        """调用阿里云人脸检测：返回 (face_count, face_quality:0~1)。

        失败/未配置返回 None，face_count=0 / face_quality=中性。
        """
        if not self._use_aliyun:
            return None
        try:
            return await asyncio.to_thread(aliyun_detect_face, None, image_data)
        except Exception as e:
            logger.warning(f"[real_screener] 人脸 RPC 异常，回退中性: {e}")
            return None

    # ---------- 聚类与精选 ----------

    async def _cluster_photos(self, analyses: list[dict]) -> tuple[dict[str, int], int]:
        """统一聚类入口：Qwen-VL 结构化标签（人物+背景 AND）+ 多哈希 OR 投票兜底。

        用户定义"同组"需满足（不再要求动作一致，降低门槛让照片更易同组）：
        1. 人物同一个人（gender + hair + clothing 一致）
        2. 背景相似（background_type 相同 + elements 重叠 ≥ CLUSTER_BG_OVERLAP_THRESHOLD，默认 0.3）

        降级链：
        - VL 标签成功 → 用三维度 AND 合并
        - VL 部分失败 / 全失败 → 退化为多哈希 OR 投票（保留旧行为，不破坏鲁棒性）

        Returns:
            {photo_id: cluster_id} 与簇总数。
        """
        # ===== 阶段 1：Qwen-VL 结构化标签（人物 + 背景 + 动作） =====
        labels: list[dict] = []
        if settings.CLUSTER_USE_QWEN_EMBEDDING and settings.LLM_API_KEY:
            try:
                urls = [a["original_url"] for a in analyses]
                logger.info(f"[cluster] Qwen-VL 提取标签 {len(urls)} 张照片")
                labels = await label_images(urls)
                # 写入 analyses（供调试/降级判断）
                for a, lab in zip(analyses, labels):
                    a["label"] = lab
                # 诊断：打印每张标签，便于定位"为何 label 层零合并"
                for _idx, (a, lab) in enumerate(zip(analyses, labels)):
                    logger.info(
                        f"[cluster][diag] #{_idx} "
                        f"people={lab.get('people_count')} "
                        f"bg={lab.get('background_type')} "
                        f"elements={lab.get('background_elements')} "
                        f"people_detail={lab.get('people')}"
                    )
            except Exception as e:
                logger.warning(f"[cluster] Qwen-VL 标签提取失败，回退到多哈希: {e}")
        else:
            logger.info("[cluster] Qwen-VL 未启用/未配置，仅用多哈希聚类")

        # ===== 阶段 1.5：人脸比对预计算（仅对"共享背景"的候选对，限制 API 调用量） =====
        face_same = await self._precompute_face_compare(analyses, labels)

        # ===== 阶段 2：基于三维度标签的 AND 合并（人脸比对优先，文字匹配兜底） =====
        label_clusters = self._cluster_by_labels(analyses, labels, face_same)

        # ===== 阶段 3：多哈希 AND 投票兜底（构图层，仅近重复连拍合并） =====
        hash_clusters = self._cluster_by_hash(analyses)

        # ===== 阶段 3.5：Qwen multimodal-embedding 余弦相似度聚类（语义层，P1-12 新增） =====
        embedding_clusters = await self._cluster_by_embedding(analyses)

        # ===== 阶段 4：合并三路聚类结果（OR 投票：标签 / 哈希 / embedding 任一同组即合并） =====
        final_mapping, group_count = self._merge_clusters(
            analyses, label_clusters, hash_clusters, embedding_clusters
        )
        logger.info(
            f"[cluster] 最终聚类：{len(analyses)} 张照片 → {group_count} 组 "
            f"(label={len(label_clusters)} 组, hash={len(hash_clusters)} 组, "
            f"embedding={len(embedding_clusters)} 组)"
        )
        return final_mapping, group_count

    async def _precompute_face_compare(
        self, analyses: list[dict], labels: list[dict]
    ) -> dict[tuple[int, int], Optional[float]]:
        """对"共享背景"的候选照片对预计算人脸比对相似度。

        仅当开启 CLUSTER_USE_FACE_COMPARE 且两张标签有效时，对背景相似的对调用
        腾讯云 CompareFace，避免 O(n^2) 全量比对（旅行照通常同背景才同人）。
        返回 {(i,j): score|None}：None 表示无脸/未开通/失败（需回退文字匹配）。

        P1-13 修复：VL 标签 people_count=0 的图不参与人脸比对。
        - 之前：6 张图 VL 全部 people_count=0（因 IAI 403 导致 face_count=0 传导），
          但 compare_face 仍被调用并返回 score=100（腾讯云在图异常时的假信号），
          导致 6 张全部误判同组。
        - 现在：VL 标签明确无人物（people_count<=0）的对直接跳过，不调比对，
          避免假信号把无脸图强行 union。
        """
        face_same: dict[tuple[int, int], Optional[float]] = {}
        if not settings.CLUSTER_USE_FACE_COMPARE:
            return face_same
        n = len(analyses)
        candidate_pairs: list[tuple[int, int]] = []
        skipped_no_face = 0
        for i in range(n):
            for j in range(i + 1, n):
                li = labels[i] if i < len(labels) else None
                lj = labels[j] if j < len(labels) else None
                if not li or not lj:
                    continue
                # P1-13：VL 标签明确无人物的对不参与人脸比对
                pc_i = li.get("people_count", 0) or 0
                pc_j = lj.get("people_count", 0) or 0
                if pc_i <= 0 or pc_j <= 0:
                    skipped_no_face += 1
                    continue
                if background_match(
                    li["background_type"], li["background_elements"],
                    lj["background_type"], lj["background_elements"],
                    overlap_threshold=settings.CLUSTER_BG_OVERLAP_THRESHOLD,
                ):
                    candidate_pairs.append((i, j))
        if skipped_no_face > 0:
            logger.info(
                f"[cluster][face] 跳过 {skipped_no_face} 对（VL 标签 people_count<=0，不参与比对）"
            )
        if not candidate_pairs:
            return face_same

        sem = asyncio.Semaphore(4)

        async def _cmp(i: int, j: int) -> None:
            async with sem:
                try:
                    score = await asyncio.to_thread(
                        tencent_compare_face,
                        analyses[i]["original_url"],
                        analyses[j]["original_url"],
                    )
                except Exception as e:
                    logger.warning(f"[cluster] 人脸比对异常 #{i}/#{j}: {e}")
                    score = None
                # P1-13：合理性校验——score=100 且两图 VL 标签人物数不同时降为 None
                # （腾讯云在图片下载失败/异常时可能返回满分假信号）
                if score is not None and score >= 100.0:
                    li = labels[i] if i < len(labels) else None
                    lj = labels[j] if j < len(labels) else None
                    if li and lj:
                        if li.get("people_count") != lj.get("people_count"):
                            logger.warning(
                                f"[cluster][face] #{i}/#{j} score=100 但 people_count 不同"
                                f"({li.get('people_count')} vs {lj.get('people_count')})，判为假信号→None"
                            )
                            score = None
                face_same[(i, j)] = score
                logger.info(
                    f"[cluster][face] #{i} vs #{j} "
                    f"score={score if score is None else round(score, 1)} "
                    f"same={score is not None and score >= settings.CLUSTER_FACE_SAME_THRESHOLD}"
                )

        logger.info(f"[cluster] 人脸比对候选对 {len(candidate_pairs)} 对")
        await asyncio.gather(*(_cmp(i, j) for (i, j) in candidate_pairs))
        # 汇总：便于一眼看出人脸比对是否真正生效（全 None 通常意味着未开通权限）
        _scored = [v for v in face_same.values() if isinstance(v, float)]
        _same = sum(1 for v in _scored if v >= settings.CLUSTER_FACE_SAME_THRESHOLD)
        logger.info(
            f"[cluster][face] 汇总：候选={len(candidate_pairs)} "
            f"有效比对={len(_scored)} 判同人={_same} "
            f"{( '⚠ 全为None，可能未开通「人脸比对」权限，已回退文字匹配' if not _scored else '')}"
        )
        return face_same

    def _cluster_by_labels(
        self,
        analyses: list[dict],
        labels: list[dict],
        face_same: dict[tuple[int, int], Optional[float]] | None = None,
    ) -> list[list[int]]:
        """基于 Qwen-VL 结构化标签的「统一人物 + 相似背景」AND 合并聚类。

        用户定义"同组"需满足（不要求动作一致）：
        1. 同一人：优先用人脸比对（compare_face score ≥ 阈值，权威信号）；
           无比对结果（无脸/未开通/失败）时回退 Qwen 文字匹配（gender/hair/clothing）
        2. 背景相似（background_match: type 相同 + elements Jaccard ≥ CLUSTER_BG_OVERLAP_THRESHOLD）

        仅人物+背景都满足 → 同组；任意不满足 → 拆为不同组。
        空标签/失败图自成一组（不影响其他聚类）。

        Returns:
            List[List[int]]：簇 → 照片在 analyses 中的 index。
        """
        n = len(analyses)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # 同一人判定：人脸比对优先，文字匹配兜底
        face_same = face_same or {}

        def _is_same_person(i: int, j: int) -> bool:
            score = face_same.get((i, j), "MISSING")
            if isinstance(score, float):
                return score >= settings.CLUSTER_FACE_SAME_THRESHOLD
            # 无比对结果（无脸/未开通/失败）→ 回退 Qwen 文字匹配
            return people_match(labels[i]["people"], labels[j]["people"])

        # O(n^2) 配对，n 通常 ≤ 50，单批计算在 ms 级
        for i in range(n):
            for j in range(i + 1, n):
                li = labels[i] if i < len(labels) else None
                lj = labels[j] if j < len(labels) else None
                # 空标签 / 失败图：直接跳过合并（拆为不同组）
                if not li or not lj:
                    continue
                # 同组判定：统一人物 + 相似背景（不再要求动作一致，降低分组门槛）
                if (
                    _is_same_person(i, j)
                    and background_match(
                        li["background_type"], li["background_elements"],
                        lj["background_type"], lj["background_elements"],
                        overlap_threshold=settings.CLUSTER_BG_OVERLAP_THRESHOLD,
                    )
                ):
                    union(i, j)

        # 收集簇
        clusters: dict[int, list[int]] = {}
        for i in range(n):
            clusters.setdefault(find(i), []).append(i)
        return list(clusters.values())

    def _cluster_by_hash(self, analyses: list[dict]) -> list[list[int]]:
        """基于「多哈希 OR 投票」近重复聚类（构图层）。

        对每张照片计算 aHash / dHash / pHash 三种 64-bit 哈希，OR 投票。

        Returns:
            List[List[int]]：每个元素是一个簇，含照片在 analyses 中的 index。
        """
        thresholds = {
            "ahash": settings.DEDUP_AHASH_THRESHOLD,
            "dhash": settings.DEDUP_DHASH_THRESHOLD,
            "phash": settings.DEDUP_PHASH_THRESHOLD,
        }
        cluster_reps: list[dict[str, int | None]] = []
        cluster_members: list[list[int]] = []
        for idx, a in enumerate(analyses):
            cur_hashes = {
                "ahash": a.get("ahash"),
                "dhash": a.get("dhash"),
                "phash": a.get("phash"),
            }
            matched = -1
            for cid, rep in enumerate(cluster_reps):
                if self._hash_vote_same(cur_hashes, rep, thresholds):
                    matched = cid
                    break
            if matched < 0:
                cluster_reps.append(cur_hashes)
                cluster_members.append([idx])
            else:
                cluster_members[matched].append(idx)
        return cluster_members

    async def _cluster_by_embedding(self, analyses: list[dict]) -> list[list[int]]:
        """基于 Qwen multimodal-embedding-v1 余弦相似度的语义聚类（P1-12 新增）。

        设计动机：旅行照里"同一人 + 相似背景但构图/角度不同"（如连拍、近远景），
        VL 文字标签常常不一致（"花海"/"其他"，elements 子串/同义不匹配），而多
        哈希只对像素近重复有效——结果就是分不到同组。

        Embedding 是 1024 维语义向量，包含人物/构图/背景全部特征，对"同景点多角度
        多构图"的照片天然鲁棒。余弦相似度 ≥ CLUSTER_QWEN_SIM_THRESHOLD（默认 0.7）
        即视为同组。

        失败/未配置/单图时不调用，调用方 fallback 到 _merge_clusters 的 OR 合并。

        Returns:
            List[List[int]]：每个元素是一个簇，含照片在 analyses 中的 index。
        """
        n = len(analyses)
        if n < 2:
            return [[i] for i in range(n)]
        if not (settings.CLUSTER_USE_QWEN_EMBEDDING and settings.LLM_API_KEY):
            logger.info("[cluster] embedding 跳过（未启用或未配置）")
            return [[i] for i in range(n)]

        urls = [a["original_url"] for a in analyses]
        try:
            # P1-15 修复：原图直传私有桶，set_object_public 有最终一致性延迟，
            # 并发取图 GET 裸 URL 会 403。用 owner 密钥预签名 GET URL 规避。
            from app.services.photo_service import get_presigned_get_url

            def _presign(url: str) -> str | None:
                key = get_presigned_get_url(url)
                return key

            logger.info(f"[cluster] embedding 调用 {len(urls)} 张照片（带签名 URL 取图）")
            vectors = await embed_images(urls, presign_fn=_presign)
        except Exception as e:
            logger.warning(f"[cluster] embedding 调用失败，回退单图自成一组: {e}")
            return [[i] for i in range(n)]

        ok = sum(1 for v in vectors if v is not None)
        if ok < 2:
            logger.info(
                f"[cluster] embedding 有效 {ok}/{n} 张（<2），跳过聚类回退单图自成一组"
            )
            return [[i] for i in range(n)]

        # 把 vectors 写回 analyses（便于后续 _merge / 调试）
        for a, v in zip(analyses, vectors):
            a["embedding"] = v

        threshold = settings.CLUSTER_QWEN_SIM_THRESHOLD
        # Union-Find 聚合：cosine >= threshold → union
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        sim_count = 0
        for i in range(n):
            vi = vectors[i]
            if vi is None:
                continue
            for j in range(i + 1, n):
                vj = vectors[j]
                if vj is None:
                    continue
                sim = cosine_similarity(vi, vj)
                if sim >= threshold:
                    union(i, j)
                    sim_count += 1

        logger.info(
            f"[cluster][embed] 阈值={threshold} 触发合并={sim_count} 对 "
            f"（{n} 张 / embedding 有效={ok}）"
        )

        clusters: dict[int, list[int]] = {}
        for i in range(n):
            clusters.setdefault(find(i), []).append(i)
        return list(clusters.values())

    @staticmethod
    def _merge_clusters(
        analyses: list[dict],
        label_clusters: list[list[int]],
        hash_clusters: list[list[int]],
        embedding_clusters: list[list[int]] | None = None,
    ) -> tuple[dict[str, int], int]:
        """合并多路聚类结果（OR 投票：任一判定同组 → 最终同组）。

        用户视角：
        - 标签组强约束（人物+背景 AND）→ 应优先
        - 哈希组兜底（构图层 OR 投票）→ 应对 VL 失败
        - embedding 组（P1-12 新增）→ 语义层兜底，应对 VL 文字标签漂移
        三者 OR 合并：在任一路径里被判为同组的两张照片最终都视为同组。

        Returns:
            ({photo_id: cluster_id}, total_group_count)
        """
        n = len(analyses)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # 把所有簇成员两两 union（标签组 + 哈希组 + embedding 组 OR 合并）
        for cluster in (label_clusters or []) + (hash_clusters or []) + (embedding_clusters or []):
            if not cluster:
                continue
            base = cluster[0]
            for m in cluster[1:]:
                union(base, m)

        # 分配连续 cluster_id（0, 1, 2, ...），并映射到 photo_id
        root_to_id: dict[int, int] = {}
        next_id = 0
        mapping: dict[str, int] = {}
        for i in range(n):
            r = find(i)
            if r not in root_to_id:
                root_to_id[r] = next_id
                next_id += 1
            mapping[analyses[i]["photo_id"]] = root_to_id[r]
        return mapping, next_id

    def _build_selected(
        self,
        photos: list[PhotoInfo],
        analyses: list[dict],
        cluster_of: dict[str, int],
        max_per_group: int,  # 组内精选上限（下游使用 rank_in_group 消费）
    ) -> list[SelectedPhoto]:
        # 按簇分组，组内按综合分降序排名
        by_cluster: dict[int, list[dict]] = {}
        for a in analyses:
            by_cluster.setdefault(cluster_of[a["photo_id"]], []).append(a)

        rank_map: dict[str, int] = {}
        for _cid, items in by_cluster.items():
            items.sort(key=lambda x: x["quality_score"], reverse=True)
            for rank, it in enumerate(items):
                rank_map[it["photo_id"]] = rank

        selected: list[SelectedPhoto] = []
        for photo in photos:
            rank = rank_map[photo.photo_id]
            # 每组只保留质量最高的前 max_per_group 张（PRD：每组精选 1 张）
            if rank >= max_per_group:
                continue
            a = next(x for x in analyses if x["photo_id"] == photo.photo_id)
            selected.append(
                SelectedPhoto(
                    photo_id=photo.photo_id,
                    original_url=photo.original_url,
                    processed_url=photo.original_url,  # 筛选阶段尚未精修
                    thumbnail_url=photo.original_url,
                    quality_score=a["quality_score"],
                    face_count=a["face_count"],
                    face_gender=a.get("face_gender"),
                    face_age=a.get("face_age"),
                    type=a["type"],
                    retouch_style="auto",  # type: ignore
                    retouch_style_label="智能配风格",
                    cluster_group_id=cluster_of[photo.photo_id],
                    rank_in_group=rank_map[photo.photo_id],
                )
            )
        # 诊断：打印精选结果，核对每组选了几张、分数与排名
        for _gid, _items in by_cluster.items():
            _top = [
                f"{it['photo_id']}(s={it['quality_score']},r={rank_map[it['photo_id']]})"
                for it in _items
            ]
            logger.info(
                f"[select][diag] group={_gid} size={len(_items)} photos={_top}"
            )
        logger.info(
            f"[select][diag] total_groups={len(by_cluster)} "
            f"selected={len(selected)} max_per_group={max_per_group}"
        )
        return selected


class DownloadFailed(Exception):
    """单张图片下载失败（重试后仍失败）。

    P0：RealScreener._download_image 重试全部失败时抛出。
    screen 汇总若全部/绝大多数图片都 DownloadFailed → 抛 ScreeningFatalError，
    让任务进入 FAILED 分支（前端报错 + 返还额度）。
    """

    def __init__(self, url: str = "", reason: str = ""):
        self.url = url
        self.reason = reason
        super().__init__(f"图片下载失败 url={url[:60]} reason={reason}")
