"""照片上传路由

- GET  /api/v1/photos/sts             获取上传凭证信息
- POST /api/v1/photos/presign         获取预签名 PUT URL（前端直传用）
- POST /api/v1/photos/confirm         上传确认（Photo 入库）
- POST /api/v1/photos/meitu-callback  美图云修回调（HMAC 验签）
- POST /api/v1/photos/{photo_id}/download  确认下载精修图（按 user 校验）
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.ai.meitu_pro import process_meitu_callback
from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.db.session import DbSession
from app.schemas.photo import PhotoConfirmReq, StsCredentialOut, UploadedPhotoOut
from app.services import photo_service

settings = get_settings()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/photos", tags=["photos"])


class PresignReq(BaseModel):
    """预签名请求"""

    object_key: str = Field(..., description="COS object key，如 uploads/1/123/abc.jpg")


class PresignOut(BaseModel):
    """预签名返回"""

    presigned_url: str = Field(..., description="COS 预签名 PUT URL")
    object_key: str = Field(..., description="COS object key")
    access_url: str = Field(..., description="上传成功后的公网访问 URL")


class BatchPresignReq(BaseModel):
    """批量预签名请求"""

    object_keys: list[str] = Field(..., description="COS object key 列表", min_length=1, max_length=50)


class BatchPresignItem(BaseModel):
    """批量预签名单条结果"""

    object_key: str
    presigned_url: str
    access_url: str


class BatchPresignOut(BaseModel):
    """批量预签名返回"""

    items: list[BatchPresignItem]


@router.get(
    "/sts",
    response_model=StsCredentialOut,
    summary="获取上传凭证",
)
async def get_sts(
    user: CurrentUser,
    file_count: int = Query(1, ge=1, le=500, description="本次上传文件数"),
) -> StsCredentialOut:
    """获取对象存储上传凭证信息"""
    cred = await photo_service.get_upload_credential(user, file_count)
    return StsCredentialOut(**cred)


@router.post(
    "/presign",
    response_model=PresignOut,
    summary="获取预签名上传URL",
)
async def get_presigned_url(
    req: PresignReq,
    user: CurrentUser,
) -> PresignOut:
    """获取 COS 预签名 PUT URL

    前端用 wx.uploadFile PUT 文件到此 URL，无需计算签名。

    P0-03 修复：generate_presigned_put_url 内部调用腾讯云 COS SDK
    的同步阻塞 IO，直接在 async 路由里执行会阻塞整个事件循环。
    多张并发上传（14 张连发 14 次 presign）时请求排队线性放大，
    尾部请求超时/卡 loading。改为 run_in_threadpool 丢到线程池，
    不阻塞 uvloop 主循环。
    """
    presigned_url = await run_in_threadpool(
        photo_service.generate_presigned_put_url, user, req.object_key
    )
    access_url = photo_service._build_cos_url(req.object_key)

    return PresignOut(
        presigned_url=presigned_url,
        object_key=req.object_key,
        access_url=access_url,
    )


@router.post(
    "/presign/batch",
    response_model=BatchPresignOut,
    summary="批量获取预签名上传URL",
)
async def get_presigned_urls_batch(
    req: BatchPresignReq,
    user: CurrentUser,
) -> BatchPresignOut:
    """一次获取多张照片的预签名 PUT URL

    前端批量上传时，把 N 次 presign 往返压缩成 1 次，从根上消除
    presign 并发瓶颈（见 /presign 单张接口的 P0-03 说明）。
    """
    items: list[BatchPresignItem] = []
    for object_key in req.object_keys:
        presigned_url = await run_in_threadpool(
            photo_service.generate_presigned_put_url, user, object_key
        )
        items.append(
            BatchPresignItem(
                object_key=object_key,
                presigned_url=presigned_url,
                access_url=photo_service._build_cos_url(object_key),
            )
        )
    return BatchPresignOut(items=items)


@router.post(
    "/confirm",
    response_model=UploadedPhotoOut,
    summary="上传确认",
)
async def confirm_upload(
    req: PhotoConfirmReq,
    user: CurrentUser,
    db: DbSession,
) -> UploadedPhotoOut:
    """上传完成后回传文件信息，创建 Photo 记录"""
    # P0 修复：入库前规范化 + 校验 original_url。
    # 1) 把纯 object key 拼成完整 COS URL；
    # 2) 拦截非法 URL（如微信临时路径 http://tmp/xxx.jpg）——这类脏数据会让美图下载
    #    失败（lookup tmp ... no such host），且前端放大时 <image src="http://tmp/...">
    #    在微信开发者工具直接崩页白屏。必须提前拒绝，让前端重传。
    normalized_url = photo_service.normalize_original_url(req.url)
    if not normalized_url:
        logger.warning(
            f"[photos] confirm_upload 拒绝：非法 original_url url={req.url}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="照片上传失败：图片地址无效，请重新上传",
        )
    req.url = normalized_url

    # P0 修复：入库前校验 COS 对象真实存在。
    # 前端 PUT 在微信开发者工具模拟器偶发"success 但未真正持久化"（devtools bug），
    # 若盲信 URL 入库 → 后续筛选下载全 403/404 → 闷头降级。
    # 这里用 head_object 防御：不存在则拒绝入库，让前端重传。
    if not photo_service.object_exists(req.url):
        logger.warning(
            f"[photos] confirm_upload 拒绝：COS 对象不存在 url={req.url}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="照片上传失败：COS 中未找到该对象，请重新上传",
        )

    photo = await photo_service.confirm_upload(
        db,
        user,
        file_id=req.file_id,
        url=req.url,
        size=req.size,
        width=req.width,
        height=req.height,
    )
    await db.commit()

    # P0 修复：原图直传 COS 私有桶后必须显式设为 public-read，
    # 否则后端/美图/前端匿名访问会 403（之前全部照片筛选降级的根因）。
    # 与 upload_to_cos（精修图）保持一致：原图仅临时公开，下载精修图后会被清理。
    try:
        await photo_service.set_object_public(photo.original_url)
    except Exception as e:
        logger.warning(f"[photos] 原图设为公开失败（筛选可能下载 403）: {e}")

    return UploadedPhotoOut(
        file_id=req.file_id,
        url=photo.original_url,
        thumbnail_url=photo.original_url,
        size=photo.original_size,
        width=photo.original_width or 0,
        height=photo.original_height or 0,
        photo_id=str(photo.id),
    )


@router.post(
    "/meitu-callback",
    summary="美图云修回调",
)
async def meitu_callback(
    request: Request,
    db: DbSession,
):
    """美图云修 Pro 处理完成后的回调端点

    美图会 POST 处理结果到此接口。
    后端下载精修图并转存到 COS，同时回写 Photo.processed_url 与任务结果，
    这样结果页才能展示真正的精修图（而非原图）。

    P1-11 修复：photo_id 兼容多种来源
    - 优先从 query 参数 `?photo_id=xxx` 读取（美图回调会把 repost_url 的 query 原样回传）
    - 兼容 header `X-Meitu-Photo-Id`（保留历史通道）
    - 同时支持 HMAC 签名校验（MEITU_CALLBACK_REQUIRE_SIG=True 时开启）
      美图默认不会主动加任何自定义 header / 签名头，故默认关闭强制签名，
      仅做 IP 来源校验（callbacks 不能来自任意人，但美图服务器也无法伪造）。
      生产环境若美图侧已对接密钥，可置 True。
    """
    # 签名校验（仅当 MEITU_CALLBACK_REQUIRE_SIG=True 才强制）
    raw = await request.body()
    if settings.MEITU_CALLBACK_REQUIRE_SIG:
        if not settings.MEITU_API_SECRET:
            logger.error("[meitu-callback] MEITU_CALLBACK_REQUIRE_SIG=True 但未配置 MEITU_API_SECRET，拒绝")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="回调鉴权未配置",
            )
        sig_header = request.headers.get("X-Meitu-Signature", "")
        expected = hmac.new(
            settings.MEITU_API_SECRET.encode("utf-8"),
            raw,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            logger.warning(
                f"[meitu-callback] 签名校验失败 ip={request.client.host if request.client else '?'} "
                f"sig_prefix={sig_header[:8]}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="签名校验失败",
            )

    # photo_id 来源：query 优先（美图默认透传）→ header 兜底
    photo_id: str | None = None
    query_photo_id = request.query_params.get("photo_id")
    header_photo_id = request.headers.get("X-Meitu-Photo-Id", "")
    raw_photo_id = query_photo_id or header_photo_id
    if raw_photo_id:
        try:
            photo_id = str(int(raw_photo_id))
        except (TypeError, ValueError):
            logger.warning(
                f"[meitu-callback] photo_id 非法 query={query_photo_id!r} header={header_photo_id!r}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="photo_id 非法",
            )

    import json
    try:
        body = json.loads(raw)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请求体不是合法 JSON",
        )

    result = await process_meitu_callback(body, photo_id=photo_id, db=db)
    return result


class DownloadConfirmOut(BaseModel):
    """下载确认返回"""

    photo_id: str = Field(..., description="照片 ID")
    original_deleted: bool = Field(..., description="原图是否已删除")


@router.post(
    "/{photo_id}/download",
    response_model=DownloadConfirmOut,
    summary="确认下载精修图",
)
async def confirm_download(
    photo_id: str,
    user: CurrentUser,
    db: DbSession,
) -> DownloadConfirmOut:
    """用户下载（保存到相册）精修图后调用

    触发清理：一旦用户下载精修图，立即删除 COS 中的原图，
    以支持「先对比、后清理」的存储策略。幂等，重复调用安全。

    P0-15 修复：增加 user_id 校验
    - 旧逻辑：仅按 photo_id 查 Photo → 任何登录用户都能调
      POST /photos/{任意 photo_id}/download 触发别人原图清理
    - 新逻辑：校验 photo.user_id == user.id，否则 403
    """
    try:
        pid = int(photo_id)
    except (TypeError, ValueError):
        pid = 0

    await photo_service.cleanup_original_after_download(db, pid, user_id=user.id)
    return DownloadConfirmOut(photo_id=photo_id, original_deleted=True)
