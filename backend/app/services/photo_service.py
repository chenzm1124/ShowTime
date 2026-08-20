"""照片业务服务

- STS 临时凭证签发（腾讯云 COS）
- 预签名 PUT URL 生成（前端直传用）
- 上传确认 → Photo 记录入库
- 后端转存到 COS（美图精修结果）
"""

import logging
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.photo import Photo
from app.models.user import User

settings = get_settings()
logger = logging.getLogger(__name__)

# COS 访问域名
_COS_HOST = f"https://{settings.COS_BUCKET}.cos.{settings.COS_REGION}.myqcloud.com" if settings.COS_BUCKET else "https://mock-cos.local"


def _build_cos_url(object_key: str) -> str:
    """根据 object key 拼接 COS 公网访问 URL"""
    return f"{_COS_HOST}/{object_key}"


def _get_cos_client():
    """获取 COSS3Client 单例（懒加载）"""
    from qcloud_cos import CosConfig, CosS3Client

    config = CosConfig(
        Region=settings.COS_REGION,
        SecretId=settings.COS_SECRET_ID,
        SecretKey=settings.COS_SECRET_KEY,
        Scheme="https",
    )
    return CosS3Client(config)


async def get_upload_credential(user: User, file_count: int = 1) -> dict:
    """获取上传凭证信息

    返回 COS bucket/region/host 信息，前端用这些信息配合
    /photos/presign 接口获取每张图的预签名 URL。

    Mock 模式或未配置 COS 密钥时返回假凭证。
    """
    now = int(time.time())

    if not settings.COS_SECRET_ID:
        upload_dir = f"uploads/{user.id}/{now}"
        return {
            "tmp_secret_id": "mock_tmp_secret_id",
            "tmp_secret_key": "mock_tmp_secret_key",
            "session_token": "mock_session_token",
            "expired_time": now + 1800,
            "start_time": now,
            "bucket": "mock-bucket",
            "region": settings.COS_REGION,
            "upload_host": "https://mock-cos.local",
            "upload_dir": upload_dir,
            "file_path": f"{upload_dir}/{{filename}}",
            "url_prefix": "https://mock-cos.local/uploads",
            "presigned_url": "",
            "object_key": "",
        }

    upload_dir = f"uploads/{user.id}/{now}"
    return {
        "tmp_secret_id": settings.COS_SECRET_ID,
        "tmp_secret_key": settings.COS_SECRET_KEY,
        "session_token": "",
        "expired_time": now + settings.COS_STS_DURATION_SECONDS,
        "start_time": now,
        "bucket": settings.COS_BUCKET,
        "region": settings.COS_REGION,
        "upload_host": _COS_HOST,
        "upload_dir": upload_dir,
        "file_path": f"{upload_dir}/{{filename}}",
        "url_prefix": _build_cos_url(upload_dir),
        "presigned_url": "",
        "object_key": "",
    }


def generate_presigned_put_url(user: User, object_key: str) -> str:
    """为指定 object_key 生成预签名 PUT URL

    前端用 wx.uploadFile PUT 文件到此 URL，无需计算签名。
    """
    if not settings.COS_SECRET_ID:
        return ""

    client = _get_cos_client()
    presigned_url = client.get_presigned_url(
        Method="PUT",
        Bucket=settings.COS_BUCKET,
        Key=object_key,
        Expired=settings.COS_STS_DURATION_SECONDS,
        Headers={"Content-Type": "image/jpeg"},
    )
    return presigned_url


def get_presigned_get_url(object_key: str, expired: int = 600) -> str | None:
    """为指定 object_key 生成预签名 GET URL（带 owner 密钥，匿名也可用）。

    用途：后端需要下载原图做 embedding/压缩等处理时，不必依赖对象已设为
    public-read（COS ACL 有最终一致性延迟，并发场景下匿名 GET 仍会 403）。
    用 owner 密钥预签名 GET URL 可稳定取图，且 URL 自带过期时间，安全性更好。

    mock 模式或未配置 COS 密钥时返回 None（调用方回退裸 URL）。
    """
    if not settings.COS_SECRET_ID or not object_key:
        return None
    if not object_key.startswith("http"):
        object_key = extract_object_key(object_key) or object_key

    try:
        client = _get_cos_client()
        return client.get_presigned_url(
            Method="GET",
            Bucket=settings.COS_BUCKET,
            Key=object_key,
            Expired=expired,
        )
    except Exception as e:
        logger.warning(f"[photo_service] 生成预签名 GET URL 失败 key={object_key}: {e}")
        return None


async def confirm_upload(
    db: AsyncSession,
    user: User,
    file_id: str,
    url: str,
    size: int = 0,
    width: int | None = None,
    height: int | None = None,
) -> Photo:
    """上传确认：创建 Photo 记录入库

    url 参数可能是 object key 或完整 URL，统一存为完整公网 URL。
    """
    if url and not url.startswith("http") and not url.startswith("mock://"):
        url = _build_cos_url(url)

    photo = Photo(
        user_id=user.id,
        task_id=None,
        original_url=url,
        original_size=size,
        original_width=width,
        original_height=height,
        status="uploaded",
        order_index=0,
    )
    db.add(photo)
    await db.flush()
    return photo


def normalize_original_url(url: str) -> str | None:
    """规范化 confirm_upload 入库的 original_url。

    返回：
    - 合法公网 COS URL（https://bucket.cos.region.myqcloud.com/key）→ 原样返回
    - 纯 object key（不以 http 开头）→ 拼成完整 URL
    - 非法 URL（如 http://tmp/xxx.jpg 本地临时路径、localhost 等）→ 返回 None，
      调用方应拒绝入库，避免脏数据导致美图下载失败 / 前端放大白屏。

    日志里曾出现 original_url = 'http://tmp/pom6...jpg'（微信临时文件路径被当 URL
    入库），美图拿它当 media_data 下载 → lookup tmp ... no such host 失败；前端放大
    时 <image src="http://tmp/..."> 在开发者工具直接崩页白屏。本函数专门拦截这类情况。
    """
    if not url:
        return None

    # 纯 key：直接拼完整 URL
    if not url.startswith("http://") and not url.startswith("https://"):
        return _build_cos_url(url)

    # 已是 http(s)：校验 host 必须是合法 COS 域名或可解析公网，不能是本地临时路径
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except Exception:
        return None

    if host in ("tmp", "usr", "localhost", "127.0.0.1", "0.0.0.0"):
        return None

    # 允许完整 COS 域名；其它公网 http(s) 也放行（不强制 COS 域名，避免误伤自定义 CDN）
    return url


async def upload_to_cos(
    object_key: str, data: bytes, content_type: str = "image/jpeg"
) -> str:
    """后端直接上传数据到 COS（用于转存美图精修结果）

    上传后自动设为 public-read，否则前端/微信小程序无法匿名访问（COS 默认私有）。

    返回公网访问 URL。
    """
    if not settings.COS_SECRET_ID:
        logger.warning("[photo_service] COS 未配置，跳过真实上传")
        return _build_cos_url(object_key)

    client = _get_cos_client()
    client.put_object(
        Bucket=settings.COS_BUCKET,
        Body=data,
        Key=object_key,
        ContentType=content_type,
        EnableMD5=True,
    )
    logger.info(f"[photo_service] 上传到 COS 成功: {object_key}")

    # 上传后立即设 public-read，否则精修图 URL 会被 COS 拒绝访问（403）
    # 美图回调下载的精修图需要前端匿名访问才能展示
    try:
        client.put_object_acl(
            Bucket=settings.COS_BUCKET,
            Key=object_key,
            ACL="public-read",
        )
        logger.info(f"[photo_service] COS 对象已设为 public-read: {object_key}")
    except Exception as e:
        logger.warning(f"[photo_service] 设置 public-read 失败（图片可能无法匿名访问）: {object_key} {e}")

    return _build_cos_url(object_key)


async def delete_from_cos(object_key: str) -> bool:
    """从 COS 删除对象（用于清理过期原图/原图）"""
    if not settings.COS_SECRET_ID:
        return False

    client = _get_cos_client()
    try:
        client.delete_object(Bucket=settings.COS_BUCKET, Key=object_key)
        logger.info(f"[photo_service] 从 COS 删除: {object_key}")
        return True
    except Exception as e:
        logger.warning(f"[photo_service] COS 删除失败: {e}")
        return False


async def set_object_public(url: str) -> bool:
    """将 COS 对象设为 public-read，确保外网（美图/前端）可直接访问原图

    注意：原图只是临时公开，用户下载精修图后会被 cleanup_original_after_download 删除。
    """
    if not settings.COS_SECRET_ID:
        return False

    object_key = extract_object_key(url)
    if not object_key:
        logger.warning(f"[photo_service] 无法从 URL 提取 object key: {url}")
        return False

    client = _get_cos_client()
    try:
        client.put_object_acl(
            Bucket=settings.COS_BUCKET,
            Key=object_key,
            ACL="public-read",
        )
        logger.info(f"[photo_service] COS 对象已设为 public-read: {object_key}")
        return True
    except Exception as e:
        logger.warning(f"[photo_service] 设置 public-read 失败: {object_key} {e}")
        return False


def object_exists(url: str) -> bool:
    """校验 COS 对象是否真实存在（HEAD object）。

    用于 confirm_upload 入库前防御：前端可能因 devtools bug / 网络异常
    拿到 200 但实际未持久化，导致 DB 里 URL 是死的、后续筛选全 403/404。
    """
    if not settings.COS_SECRET_ID:
        return True  # mock 模式不校验

    object_key = extract_object_key(url)
    if not object_key:
        return False

    client = _get_cos_client()
    try:
        client.head_object(Bucket=settings.COS_BUCKET, Key=object_key)
        return True
    except Exception as e:
        # COS 资源不存在时 CosS3Client 抛 CosServiceError，code=NoSuchKey 或 404
        logger.warning(f"[photo_service] 对象不存在校验失败: {object_key} {e}")
        return False


def is_object_public(url: str, timeout: float = 5.0) -> bool:
    """匿名 HEAD 校验 COS 对象是否已公开可读。

    P1-13 修复：set_object_public 设置 ACL 后，COS 可能存在最终一致性传播
    延迟（几秒~几十秒）。在启动筛选/精修前用「匿名 GET/HEAD」（不带签名）
    校验一次，确保外部服务（腾讯云 IAI / 美图）能拉到图，避免时序竞态 403。

    Args:
        url: COS 公网 URL
        timeout: 单次校验超时（秒）

    Returns:
        True=已公开可匿名读；False=未公开或校验失败
    """
    if not settings.COS_SECRET_ID:
        return True  # mock 模式不校验
    if not url or not url.startswith("http"):
        return False
    try:
        import httpx as _httpx

        with _httpx.Client(timeout=timeout, follow_redirects=True) as cli:
            r = cli.head(url)
            return r.status_code < 400
    except Exception as e:
        logger.warning(f"[photo_service] 匿名 HEAD 校验失败 url={url[:80]}: {e}")
        return False



async def get_photo_by_id(db: AsyncSession, photo_id: int) -> Photo | None:
    """按 id 查询 Photo 记录"""
    from sqlalchemy import select

    result = await db.execute(select(Photo).where(Photo.id == photo_id))
    return result.scalar_one_or_none()


async def update_photo_processed(
    db: AsyncSession,
    photo_id: int,
    task_id: int,
    processed_url: str,
    success: bool,
) -> None:
    """逐张精修完成后即时回写 Photo 表（用于前端「先好先显示」）。

    只更新属于该 task 且 id 匹配的 Photo，避免误改其它任务照片。
    失败时把 processed_url 标记为带 _retouch_failed 标记的原图（由
    pipeline 传入），success=False 让前端据此区分展示。
    注意：复用现有 status 字段（completed/failed）；不新增列以免迁移。
    """
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal

    # P1-14 修复：美图回调并发回写时若复用 pipeline 同一 AsyncSession 会触发
    # "session is provisioning a new connection; concurrent operations are not
    # permitted"。此处开一个独立 session 提交，避免跨协程共享冲突。
    session: AsyncSession = AsyncSessionLocal()
    try:
        photo = (
            await session.execute(
                select(Photo).where(Photo.id == photo_id, Photo.task_id == task_id)
            )
        ).scalar_one_or_none()
        if photo is None:
            return
        photo.processed_url = processed_url
        photo.status = "completed" if success else "failed"
        session.add(photo)
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"[photo_service] 写回 Photo {photo_id} 失败: {e}")
    finally:
        await session.close()


async def cleanup_original_after_download(
    db: AsyncSession, photo_id: int, user_id: int | None = None
) -> bool:
    """用户下载精修图后清理原图

    业务逻辑（对应产品需求）：
    - 精修完成后原图保留，供用户在预览页做「原图/精修图」对比查看；
    - 一旦用户下载（保存）了精修图，立即删除 COS 中的原图并置
      original_deleted=True，避免原图长期占用存储。

    幂等：原图已删除则直接返回 True，不重复删。

    P0-15 修复：增加 user_id 校验
    - 旧逻辑：仅按 photo_id 查 Photo → 任何登录用户都能调
      POST /photos/{任意 photo_id}/download 触发别人原图清理
    - 新逻辑：必须传 user_id；photo.user_id 不匹配则拒绝（返回 False，不抛异常
      以保持接口契约）。mock 模式（无 user_id）跳过校验以保持向后兼容。
    """
    photo = await get_photo_by_id(db, photo_id)
    if not photo:
        logger.warning(f"[photo_service] 未找到 Photo id={photo_id}，跳过原图清理")
        return False

    # P0-15 修复：跨用户访问防护
    if user_id is not None and photo.user_id != user_id:
        logger.warning(
            f"[photo_service] 跨用户清理原图被拒 photo_id={photo_id} "
            f"photo_owner={photo.user_id} requester={user_id}"
        )
        return False

    if photo.original_deleted:
        logger.info(f"[photo_service] Photo id={photo_id} 原图已清理过，跳过")
        return True

    original_url = photo.original_url
    deleted = False
    if original_url:
        original_key = extract_object_key(original_url)
        if original_key:
            deleted = await delete_from_cos(original_key)

    photo.original_deleted = True
    db.add(photo)
    await db.commit()
    logger.info(
        f"[photo_service] 下载后清理原图 photo_id={photo_id} "
        f"key={extract_object_key(original_url) if original_url else None} deleted={deleted}"
    )
    return True


def extract_object_key(url: str) -> str | None:
    """从 COS URL 中提取 object key"""
    if not url or not url.startswith("http"):
        return url
    prefix = f"{_COS_HOST}/"
    if url.startswith(prefix):
        return url[len(prefix):]
    return None


def setup_cos_lifecycle():
    """配置 COS 存储桶生命周期规则

    规则：
    - uploads/           → 3天后自动删除（原图兜底清理；主删除逻辑在用户下载精修图时触发，
                            见 cleanup_original_after_download，以便用户先看原图/精修图对比）

    关于精修图（processed/）：
    - 早期版本曾配置 processed/free/ processed/vip/ processed/vip3/ 三条规则，
      但 meitu_pro 实际写入路径是 processed/{YYYYMMDD}/，前缀对不上导致规则形同虚设。
    - 现已统一改为应用层调度器（app.services.cleanup_scheduler）负责：所有精修图
      保留 3 天，北京 24:00 触发清理，不分 VIP 等级。
    - 见 cleanup_scheduler.run_loop 注释。
    - 老的 7/30/永久 规则保留不再写入，避免误导后来读代码的人。
    """
    if not settings.COS_SECRET_ID:
        logger.info("[photo_service] COS 未配置，跳过生命周期配置")
        return

    from qcloud_cos import CosConfig, CosS3Client

    config = CosConfig(
        Region=settings.COS_REGION,
        SecretId=settings.COS_SECRET_ID,
        SecretKey=settings.COS_SECRET_KEY,
        Scheme="https",
    )
    client = CosS3Client(config)

    lifecycle_config = {
        "Rule": [
            # 原图：3天后兜底删除（主删除在用户下载精修图时触发，保留以供对比查看）
            {
                "ID": "delete-original-after-3days",
                "Filter": {"Prefix": "uploads/"},
                "Status": "Enabled",
                "Expiration": {"Days": 3},
            },
            # processed/* 精修图：不再走 COS lifecycle，由应用层 cleanup_scheduler
            # （app/services/cleanup_scheduler.py）按"3天+北京24:00"统一清理。
        ]
    }

    try:
        client.put_bucket_lifecycle(
            Bucket=settings.COS_BUCKET,
            LifecycleConfiguration=lifecycle_config,
        )
        logger.info("[photo_service] COS 生命周期规则配置成功")
    except Exception as e:
        logger.warning(f"[photo_service] COS 生命周期配置失败（不影响运行）: {e}")
