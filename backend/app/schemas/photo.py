"""照片上传相关 Schema"""

from pydantic import BaseModel, Field


class StsCredentialOut(BaseModel):
    """STS 临时上传凭证（与前端 StsCredential 对齐）"""

    tmp_secret_id: str
    tmp_secret_key: str
    session_token: str
    expired_time: int = Field(..., description="过期时间戳（秒）")
    start_time: int = Field(..., description="起始时间戳（秒）")
    bucket: str
    region: str
    upload_host: str
    upload_dir: str
    file_path: str = Field(..., description="本次上传的完整对象 key 前缀")
    url_prefix: str = Field(..., description="拼接访问 URL 的前缀")
    # 预签名 URL：前端直接 PUT 文件到此 URL，无需计算签名
    presigned_url: str = Field("", description="COS 预签名 PUT URL")
    object_key: str = Field("", description="本次上传的 COS object key")


class PhotoConfirmReq(BaseModel):
    """上传确认请求"""

    file_id: str = Field(..., description="前端生成的文件唯一 ID")
    url: str = Field(..., description="上传后的对象 key 或完整 URL")
    size: int = Field(0, description="文件大小（字节）")
    width: int | None = None
    height: int | None = None


class UploadedPhotoOut(BaseModel):
    """上传确认返回（与前端 UploadedPhoto 对齐）"""

    file_id: str
    url: str
    thumbnail_url: str
    size: int
    width: int = 0
    height: int = 0
    photo_id: str = Field("", description="后端 Photo 记录 ID")
