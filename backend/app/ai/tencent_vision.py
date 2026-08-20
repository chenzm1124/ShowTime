"""腾讯云视觉能力封装（图片质量评分 + 人脸检测）

与阿里云方案相比，图片本就在腾讯云 COS，全程零转存：

- 图片质量评分：数据万象 CI ``ci_image_assess_quality``
  返回 ClarityScore（清晰度，综合噪声/曝光/模糊/压缩）+ AestheticScore（美观度，构图/色彩），均 0~100。
  需要 COS 桶开通「图片质量评估」增值功能。

- 人脸检测：人脸识别 IAI ``DetectFace``（iai.v20200303）
  直接传 COS 公网 Url（同生态可访问），NeedQualityDetection=1 取 FaceQualityInfo.Score。
  需要在控制台开通「人脸识别」服务。

复用 COS_SECRET_ID / COS_SECRET_KEY（IAI 与 COS 同一套腾讯云密钥）。
任何依赖缺失 / 未开通 / 调用异常时返回 None，由调用方（RealScreener）降级为本地 CV 值。
"""

import base64
import io
import logging
from functools import lru_cache
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image
from PIL.Image import Resampling

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


# 腾讯云 IAI DetectFace 硬限制：图片 ≤ 5MB、分辨率 ≤ 5000×5000；
# 任一超限直接返回 FailedOperation.ImageSizeExceed / ImageResolutionExceed
# （与是否付费无关——参数校验阶段就拒，计费都没启动）。
# 缩到 2000×2000 + JPEG q=85 既留足余量、又保证人脸属性识别精度（避免过度压缩失真）。
_TENCENT_IAI_MAX_SIZE = (2000, 2000)
_TENCENT_IAI_JPEG_QUALITY = 85
_TENCENT_IAI_MAX_BYTES = 4_500_000  # 留 0.5MB 余量


def _trace(event: str, **fields) -> None:
    """结构化追踪日志（前缀 [IAI-DEBUG]），便于诊断「识别为男人/女人」与「图片预处理」。"""
    parts = [f"event={event}"]
    for k, v in fields.items():
        if v is None:
            parts.append(f"{k}=None")
        elif isinstance(v, float):
            parts.append(f"{k}={v:.2f}")
        else:
            s = str(v)
            if len(s) > 200 and not k.endswith("url"):
                s = s[:200] + "..."
            parts.append(f"{k}={s}")
    logger.info(f"[IAI-DEBUG] {' '.join(parts)}")


def _norm_100(score) -> Optional[float]:
    """把 0~100 的分数归一化到 0~1；非法值返回 None。"""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    return float(min(max(s / 100.0, 0.0), 1.0))


def key_from_url(url: str) -> Optional[str]:
    """从 COS 公网 URL 解析对象 Key。

    形如 https://{bucket}.cos.{region}.myqcloud.com/path/to/a.jpg?sign=...
    返回 "path/to/a.jpg"（已 urldecode，去掉开头 /）。解析失败返回 None。
    """
    try:
        path = urlparse(url).path
        key = unquote(path).lstrip("/")
        return key or None
    except Exception:
        return None


# ---------- COS 数据万象：图片质量评分 ----------


@lru_cache(maxsize=1)
def _get_cos_client():
    """懒加载 COS 客户端（仅在凭据齐全时）。"""
    if not (settings.COS_SECRET_ID and settings.COS_SECRET_KEY and settings.COS_BUCKET):
        return None
    try:
        from qcloud_cos import CosConfig, CosS3Client

        conf = CosConfig(
            Region=settings.COS_REGION,
            SecretId=settings.COS_SECRET_ID,
            SecretKey=settings.COS_SECRET_KEY,
        )
        return CosS3Client(conf)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[tencent_vision] COS 客户端初始化失败: {e}")
        return None


def assess_quality(key: str) -> Optional[Tuple[float, float, float]]:
    """数据万象图片质量评分。

    返回 (clarity, aesthetic, low_quality) 各 0~1；失败/未开通返回 None。
    - clarity      ← ClarityScore（清晰度综合分：噪声/曝光/模糊/压缩）
    - aesthetic    ← AestheticScore（美观度：构图/色彩）
    - low_quality  ← LowQualityScore（内容质量，越高越差，用于低质淘汰）
    """
    client = _get_cos_client()
    if client is None or not key:
        return None
    try:
        resp = client.ci_image_assess_quality(Bucket=settings.COS_BUCKET, Key=key)
    except Exception as e:
        logger.warning(f"[tencent_vision] 质量评分调用失败 key={key[:60]}: {e}")
        return None

    if not isinstance(resp, dict):
        return None
    clarity = _norm_100(resp.get("ClarityScore"))
    aesthetic = _norm_100(resp.get("AestheticScore"))
    low_quality = _norm_100(resp.get("LowQualityScore"))
    if clarity is None and aesthetic is None and low_quality is None:
        return None
    return (clarity, aesthetic, low_quality)


# ---------- 人脸识别 IAI：人脸检测与分析 ----------


@lru_cache(maxsize=1)
def _get_iai_client():
    """懒加载 IAI 客户端（复用 COS 密钥）。"""
    if not (settings.COS_SECRET_ID and settings.COS_SECRET_KEY):
        return None
    try:
        from tencentcloud.common import credential
        from tencentcloud.iai.v20200303 import iai_client

        cred = credential.Credential(settings.COS_SECRET_ID, settings.COS_SECRET_KEY)
        region = settings.TENCENT_IAI_REGION or "ap-shanghai"
        return iai_client.IaiClient(cred, region)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[tencent_vision] IAI 客户端初始化失败: {e}")
        return None


def _presigned_get_url(url: str, expired: int = 300) -> Optional[str]:
    """为 COS 对象生成预签名 GET URL（私有桶也可匿名读）。

    P1-13 修复：腾讯云 IAI / 人脸比对下载 COS 原图时，若对象 ACL 未公开
    （新上传对象在 set_object_public 生效前有时序窗口），直接 GET 裸 URL 会 403。
    改用 owner 密钥签名的预签名 URL，无论 ACL 是私有还是公开都可读，
    彻底消除「上传后 ACL 设置竞态 → 筛选阶段 403」问题。

    Args:
        url: COS 公网 URL（https://bucket.cos.region.myqcloud.com/key）
        expired: 签名有效期（秒），默认 5 分钟

    Returns:
        预签名 GET URL；非 COS URL 或生成失败时返回 None（调用方回退裸 URL）
    """
    key = key_from_url(url)
    if not key:
        return None
    client = _get_cos_client()
    if client is None:
        return None
    try:
        return client.get_presigned_url(
            Method="GET",
            Bucket=settings.COS_BUCKET,
            Key=key,
            Expired=expired,
        )
    except Exception as e:
        logger.warning(f"[tencent_vision] 生成预签名 GET URL 失败 key={key[:60]}: {e}")
        return None


def _download_and_preprocess_for_tencent(url: str) -> Optional[bytes]:
    """下载原图 → 缩到 2000×2000 → JPEG q=85，返回预处理后的字节。

    关键修复：之前 ``detect_face`` 直接 ``req.Url = image_url``，腾讯 fetch 后
    经常因 5MB / 5000px 限制拒收（FailedOperation.ImageSizeExceed /
    ImageResolutionExceed），导致 face_gender/age 永远 None → 走 fallback
    男人预设 → 精修效果与预期不符。改成本地预处理 + base64 Image 字段
    后可稳定调通，且避免腾讯 fetch 时二次算大小。

    P1-13 修复：下载前先尝试把裸 URL 换成预签名 GET URL，避免私有桶 403。
    预签名失败则回退裸 URL（保持兼容）。

    已经够小（<4.5MB 且 ≤2000px）则直接返回原字节，不做无谓重编码。
    """
    # 优先用预签名 URL（私有桶也能读），失败回退裸 URL
    effective_url = _presigned_get_url(url) or url
    try:
        with httpx.Client(timeout=20) as cli:
            r = cli.get(effective_url)
            r.raise_for_status()
            raw = r.content
        src = Image.open(io.BytesIO(raw))
        src.load()  # 强制解码，拿到真实尺寸
        original_w, original_h = src.size
        original_bytes = len(raw)

        if (max(original_w, original_h) <= _TENCENT_IAI_MAX_SIZE[0]
                and original_bytes <= _TENCENT_IAI_MAX_BYTES):
            _trace("preprocess_skipped",
                   original_bytes=original_bytes,
                   width=original_w, height=original_h)
            return raw

        if src.mode != "RGB":
            src = src.convert("RGB")
        src.thumbnail(_TENCENT_IAI_MAX_SIZE, Resampling.LANCZOS)
        buf = io.BytesIO()
        src.save(buf, format="JPEG", quality=_TENCENT_IAI_JPEG_QUALITY, optimize=True)
        out = buf.getvalue()
        _trace("preprocess_done",
               original_bytes=original_bytes,
               original_size=f"{original_w}x{original_h}",
               output_bytes=len(out),
               output_size=f"{src.size[0]}x{src.size[1]}",
               jpeg_quality=_TENCENT_IAI_JPEG_QUALITY)
        return out
    except Exception as e:
        _trace("preprocess_failed", url=url[:120],
               error_type=type(e).__name__, error=str(e)[:200])
        logger.warning(f"[tencent_vision] 图片预处理失败 url={url[:80]}: {e}")
        return None


def detect_face(
    image_url: Optional[str] = None,
    image_data: Optional[bytes] = None,
) -> Optional[Tuple[int, float, Optional[int], Optional[int]]]:
    """人脸检测与分析（含性别/年龄属性）。

    关键修复：传 ``image_url`` 时先下载 + 缩图，再走 base64 ``Image`` 字段，
    避免腾讯 IAI 5MB/5000px 限制拒收。

    返回 (face_count, face_quality:0~1, gender, age)；
    - gender: int，腾讯 IAI 约定 1=男 / 0=女 / 2=未知（None 表示未返回）
    - age:    int，年龄数值（None 表示未返回）
    无脸返回 (0, 0.0, None, None)；失败返回 None。
    """
    client = _get_iai_client()
    if client is None:
        return None
    try:
        from tencentcloud.iai.v20200303 import models

        # 1. 准备 base64 图片：优先用调用方传入的 bytes；否则下载原图预处理
        b64_image: Optional[str] = None
        used_preprocess = False
        if image_data is not None:
            b64_image = base64.b64encode(image_data).decode("ascii")
        elif image_url:
            processed = _download_and_preprocess_for_tencent(image_url)
            if processed is not None:
                b64_image = base64.b64encode(processed).decode("ascii")
                used_preprocess = True
                _trace("using_preprocessed_image", b64_size_bytes=len(b64_image))
            else:
                # 预处理失败 → 兜底走 URL（保持原行为，避免完全调不通）
                _trace("fallback_to_url", reason="preprocess_failed")
        else:
            return None

        req = models.DetectFaceRequest()
        req.MaxFaceNum = 5
        req.NeedFaceAttributes = 1  # 打开：返回性别/年龄，用于人物类别判定
        req.NeedQualityDetection = 1
        if b64_image is not None:
            req.Image = b64_image
        else:
            req.Url = image_url  # 兜底路径
        resp = client.DetectFace(req)
    except Exception as e:
        src = image_url[:60] if image_url else "bytes"
        err_code = getattr(e, "code", None) or getattr(e, "Code", None)
        err_msg = getattr(e, "message", None) or getattr(e, "Message", None) or str(e)[:200]
        _trace("detect_failed",
               src=src, used_preprocess=used_preprocess,
               error_type=type(e).__name__,
               error_code=err_code, error_msg=err_msg)
        logger.warning(f"[tencent_vision] 人脸检测调用失败 src={src}: {e}")
        return None

    faces = getattr(resp, "FaceInfos", None) or []
    if not faces:
        return 0, 0.0, None, None

    quals: list[float] = []
    genders: list[int] = []
    ages: list[int] = []
    for f in faces:
        q_info = getattr(f, "FaceQualityInfo", None)
        if q_info is not None:
            q = _norm_100(getattr(q_info, "Score", None))
            if q is not None:
                quals.append(q)
        attr = getattr(f, "FaceAttributesInfo", None)
        if attr is not None:
            g = getattr(attr, "Gender", None)
            if g is not None:
                # 兼容两种返回：直接 int（部分版本）或 AttributeItem{Type,Probability}
                if hasattr(g, "Type"):
                    g = g.Type
                g = int(g)
                # 腾讯枚举：0=女 / 1=男；2、99 等代表「无法判定」（官方示例即 99）→ 视为未知
                g = g if g in (0, 1) else None
                if g is not None:
                    genders.append(g)
            a = getattr(attr, "Age", None)
            if a is not None:
                ages.append(int(a))
    face_quality = sum(quals) / len(quals) if quals else 0.7
    # 取首脸的性别/年龄作为代表（合照由 face_count>=2 判为 group）
    gender = genders[0] if genders else None
    age = ages[0] if ages else None
    return len(faces), float(face_quality), gender, age


def compare_face(
    image_url_a: str,
    image_url_b: str,
) -> Optional[float]:
    """人脸比对（同一人判定）：返回相似度 Score 0~100；无脸/失败返回 None。

    与 DetectFace 同密钥、同 COS 生态，零额外转存。先下载+缩图预处理（绕开
    腾讯 5MB/5000px 限制），再走 base64 ImageA/ImageB 字段比对两张图中的最大脸。

    返回值语义：
    - 0~100 的相似度分（≥ CLUSTER_FACE_SAME_THRESHOLD 视为同一人）
    - None 表示「无脸 / 未开通人脸比对 / 调用异常」→ 由调用方回退到文字匹配
    """
    client = _get_iai_client()
    if client is None:
        return None
    try:
        from tencentcloud.iai.v20200303 import models

        img_a = _download_and_preprocess_for_tencent(image_url_a)
        img_b = _download_and_preprocess_for_tencent(image_url_b)
        if img_a is None or img_b is None:
            _trace("compare_face_skipped", reason="preprocess_failed")
            return None

        req = models.CompareFaceRequest()
        req.ImageA = base64.b64encode(img_a).decode("ascii")
        req.ImageB = base64.b64encode(img_b).decode("ascii")
        req.QualityControl = 0  # 0=不控制（避免因姿态/质量直接拒）
        resp = client.CompareFace(req)
        score = getattr(resp, "Score", None)
        if score is None:
            return None
        s = float(score)
        _trace("compare_face_done", score=s)
        return s
    except Exception as e:
        err_code = getattr(e, "code", None) or getattr(e, "Code", None)
        err_msg = getattr(e, "message", None) or getattr(e, "Message", None) or str(e)[:200]
        # 常见：FailedOperation.NoFace（某张无脸）、未开通人脸比对权限
        _trace("compare_face_failed",
               error_type=type(e).__name__,
               error_code=err_code, error_msg=err_msg)
        logger.warning(f"[tencent_vision] 人脸比对失败 a/b: {e}")
        return None
