"""任务管理相关 Schema（与前端 task.ts 接口对齐）"""
from typing import Optional

from pydantic import BaseModel, Field


class TaskCreateOptions(BaseModel):
    """创建任务选项（与前端 TaskCreateOptions 对齐）"""

    retouch_styles: list[str] = Field(default_factory=lambda: ["auto"], description="修图风格")
    location: str | None = None


class TaskCreateReq(BaseModel):
    """创建任务请求（与前端 CreateTaskPayload 对齐）"""

    photo_urls: list[str] = Field(..., description="照片 URL 列表（对象 key 或本地路径）")
    options: TaskCreateOptions = Field(default_factory=TaskCreateOptions)


class PreviewReq(BaseModel):
    """筛选预览请求（先筛选、再确认流程）

    只做智能筛选（分组 + 评分排序），不精修、不扣额度。
    """

    photo_urls: list[str] = Field(..., description="已上传原图 URL 列表", min_length=1, max_length=50)


class PreviewDroppedPhotoOut(BaseModel):
    """被去重（未精选）的照片"""

    photo_id: str
    original_url: str
    order_index: int = 0


class PreviewOut(BaseModel):
    """筛选预览返回"""

    total_photos: int = 0
    total_groups: int = 0
    selected_count: int = 0
    dropped_count: int = 0
    selected_photos: list["SelectedPhotoOut"] = []
    groups: list["PhotoGroupOut"] = []
    dropped_photos: list[PreviewDroppedPhotoOut] = []
    # 业务级可读错误信息（如"图片批量处理筛选失败：无法正常筛选照片。"）。
    # 出现 error 时其它字段为空，前端应直接展示 error 文案，不要进入结果渲染。
    error: str | None = None


class CreateTaskResultOut(BaseModel):
    """创建任务返回"""

    task_id: str
    status: str = "pending"
    estimated_time: int = 5
    quota_used: int = 1
    quota_remaining: int | str = 0


class PhotoStatusItemOut(BaseModel):
    """任务中单张照片的实时状态（用于前端「先好先显示」逐张渲染）"""

    photo_id: str
    original_url: str
    processed_url: str | None = None
    thumbnail_url: str | None = None
    status: str = "processing"  # processing | completed | failed
    order_index: int = 0
    is_retouch_failed: bool = False  # processed_url 是否为降级原图（精修失败）


class TaskStatusOut(BaseModel):
    """任务状态"""

    task_id: str
    status: str
    progress: int
    current_stage: str = Field("uploading", description="uploading|screening|retouching|captioning|completed")
    estimated_remaining_time: int = 0
    processed_photos: int = 0
    total_photos: int = 0
    photos: list[PhotoStatusItemOut] = []  # 逐张状态（按 order_index 排序）


class SelectedPhotoOut(BaseModel):
    """单张筛选+精修后的照片

    P0 修复：历史脏数据（如 Photo 表 quality_score=None、cluster_id=None）
    或旧任务 extra_params 里缺字段曾导致 TaskResultOut 校验 500。这里把
    必填字段全部改成 Optional/带默认，对前端展示也更友好。
    """

    photo_id: str
    original_url: str
    processed_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    quality_score: Optional[float] = 0.0
    face_count: Optional[int] = 0
    # type/category 在 pipeline._to_dict 里对 portrait 有值，但补齐 skipped 时曾写 None；
    # 放宽为可选，避免历史数据再炸。
    type: Optional[str] = "portrait"
    category: Optional[str] = None  # 人物分类：man/woman/child/elderly/group（无人物图为 None）
    retouch_style: Optional[str] = None
    retouch_style_label: Optional[str] = None
    caption: Optional[str] = None
    cluster_group_id: Optional[int] = None
    rank_in_group: Optional[int] = None
    # P1 增强：补齐 skipped 时新增，前端据此显示"未入选"角标；老任务里没这字段也不报错。
    status: Optional[str] = None


class PhotoGroupOut(BaseModel):
    """照片分组"""

    group_id: int
    photos: list[SelectedPhotoOut]
    group_type: str = "portrait"


class TaskResultOut(BaseModel):
    """任务处理结果"""

    task_id: str
    status: str
    total_photos: int
    total_groups: int
    selected_photos: list[SelectedPhotoOut]
    groups: list[PhotoGroupOut]
    created_at: str


class TaskHistoryItemOut(BaseModel):
    """历史记录条目"""

    task_id: str
    status: str
    total_photos: int
    total_groups: int = 0
    created_at: str
    thumbnail_url: str | None = None


class TaskHistoryOut(BaseModel):
    """历史记录列表"""

    total: int
    list: list[TaskHistoryItemOut]