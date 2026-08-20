"""阿里云视觉智能开放平台 RPC 封装（IQA + 人脸检测）

能力：
- 图像清晰度评分   AssessSharpness   （图像分析处理 / imageenhan）
- 图像曝光度评分   AssessExposure    （图像分析处理 / imageenhan）
- 图像构图美学评分 AssessComposition （图像分析处理 / imageenhan）
- 人脸检测         DetectFace        （人脸人体 / facebody）

调用方式：阿里云 OpenAPI RPC 签名（aliyun-python-sdk-core AcsClient）。
需要 RAM AccessKey（IQA_ACCESS_KEY_ID / IQA_ACCESS_KEY_SECRET），且仅支持 cn-shanghai。

未安装 SDK / 未配置凭据 / 调用异常时，由调用方（RealScreener）降级为本地 CV 值。
"""

import base64
import json
import logging
from functools import lru_cache
from typing import Optional, Tuple

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# 各能力端点与版本（视觉智能开放平台，仅 cn-shanghai）
_IMAGENHAN_ENDPOINT = "imageenhan.cn-shanghai.aliyuncs.com"
_IMAGENHAN_VERSION = "2019-09-30"
_FACEBODY_ENDPOINT = "facebody.cn-shanghai.aliyuncs.com"
_FACEBODY_VERSION = "2019-12-30"


def _norm_score(score) -> Optional[float]:
    """把不同量纲的分数归一化到 0~1。

    视觉平台返回可能是 0-1 / 0-10 / 0-100 不等；按范围自适应缩放。
    """
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    if s < 0:
        return 0.0
    if s <= 1.0:
        return s
    if s <= 10.0:
        return s / 10.0
    if s <= 100.0:
        return s / 100.0
    return 1.0


@lru_cache(maxsize=1)
def _get_client():
    """懒加载 AcsClient（仅在凭据齐全时）。"""
    if not (settings.IQA_ACCESS_KEY_ID and settings.IQA_ACCESS_KEY_SECRET):
        return None
    try:
        from aliyunsdkcore.client import AcsClient
        from aliyunsdkcore.request import RpcRequest

        class _VisualRequest(RpcRequest):
            def __init__(self, action: str, version: str, endpoint: str):
                # RpcRequest 第一个位置参数是 product（取 endpoint 子域名前缀），
                # 真实域名用 set_domain 单独指定
                product = endpoint.split(".")[0]
                super().__init__(product, version, action)
                self.set_endpoint(endpoint)
                self.set_method("POST")
                self.set_accept_format("JSON")

        client = AcsClient(
            settings.IQA_ACCESS_KEY_ID,
            settings.IQA_ACCESS_KEY_SECRET,
            settings.IQA_REGION or "cn-shanghai",
        )
        return client, _VisualRequest
    except Exception as e:  # pragma: no cover
        logger.warning(f"[aliyun_vision] AcsClient 初始化失败，降级本地 CV: {e}")
        return None


def _rpc(
    action: str,
    endpoint: str,
    version: str,
    image_url: Optional[str] = None,
    image_data: Optional[bytes] = None,
) -> Optional[dict]:
    """同步发起一次 RPC 调用，返回解析后的 JSON dict；任何失败返回 None。

    image_url:   公网图片地址（需阿里云可访问，如上海 OSS 标准域名）
    image_data:  原始图片字节，自动 base64 后走 ImageData 参数，
                 绕开「非上海 OSS 链接」限制，适合图片在腾讯云 COS 的场景。
    """
    loaded = _get_client()
    if loaded is None:
        return None
    client, ReqCls = loaded
    try:
        req = ReqCls(action, version, endpoint)
        if image_data is not None:
            req.add_query_param("ImageData", base64.b64encode(image_data).decode("ascii"))
        elif image_url:
            req.add_query_param("ImageURL", image_url)
        else:
            return None
        resp_bytes = client.do_action_with_exception(req)
        resp = json.loads(resp_bytes)
        # 调试用：记录返回结构，便于核对字段名（Score / Faces 等）
        logger.debug(
            f"[aliyun_vision] {action} 返回 keys={list(resp.keys())} "
            f"data_keys={list(resp.get('Data', {}).keys()) if isinstance(resp.get('Data'), dict) else None}"
        )
        return resp
    except Exception as e:
        logger.warning(
            f"[aliyun_vision] {action} 调用失败: {e} "
            f"(src={'bytes' if image_data is not None else image_url[:60] if image_url else 'none'})"
        )
        return None


def assess_iqa(
    image_url: Optional[str] = None,
    image_data: Optional[bytes] = None,
) -> Optional[Tuple[float, float, float]]:
    """返回 (clarity, exposure, composition) 各 0~1；失败返回 None。"""
    sharp = _rpc("AssessSharpness", _IMAGENHAN_ENDPOINT, _IMAGENHAN_VERSION, image_url, image_data)
    expo = _rpc("AssessExposure", _IMAGENHAN_ENDPOINT, _IMAGENHAN_VERSION, image_url, image_data)
    comp = _rpc("AssessComposition", _IMAGENHAN_ENDPOINT, _IMAGENHAN_VERSION, image_url, image_data)

    def _score(resp, key="Score"):
        if not resp:
            return None
        # 兼容 Data.Score 与顶层 Score
        data = resp.get("Data", resp)
        return _norm_score(data.get(key)) if isinstance(data, dict) else None

    c = _score(sharp)
    e = _score(expo)
    m = _score(comp)
    if c is None and e is None and m is None:
        return None
    # 缺失项保留 None，由 RealScreener 用本地 CV 值顶替（不填中性）
    return (c, e, m)


def detect_face(
    image_url: Optional[str] = None,
    image_data: Optional[bytes] = None,
) -> Optional[Tuple[int, float]]:
    """返回 (face_count, face_quality:0~1)；失败或无脸返回 None。"""
    resp = _rpc("DetectFace", _FACEBODY_ENDPOINT, _FACEBODY_VERSION, image_url, image_data)
    if not resp:
        return None
    data = resp.get("Data", resp)
    if not isinstance(data, dict):
        return None

    faces = data.get("Faces") or []
    if not faces:
        # 有返回但无人脸
        return 0, 0.0

    # 脸质量：兼容 Quality / FaceQuality / Beautify / Score 等字段，取均值
    quals = []
    for f in faces:
        if not isinstance(f, dict):
            continue
        for k in ("Quality", "FaceQuality", "Score", "Beauty"):
            if k in f and f[k] is not None:
                q = _norm_score(f[k])
                if q is not None:
                    quals.append(q)
                break
    face_quality = sum(quals) / len(quals) if quals else 0.7
    return len(faces), float(face_quality)
