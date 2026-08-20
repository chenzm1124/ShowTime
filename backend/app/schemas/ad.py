"""广告解锁 Schema"""

from pydantic import BaseModel, Field


class AdUnlockReq(BaseModel):
    """广告解锁请求"""

    ad_type: str = Field("rewarded_video", description="广告类型")
    ad_platform: str = Field("wechat", description="广告平台: wechat/tencent/pangolin")
    watch_duration_seconds: int = Field(0, ge=0, description="观看时长（秒）")
    ad_callback_data: dict | None = Field(None, description="广告回调数据（反作弊用）")


class AdUnlockResultOut(BaseModel):
    """广告解锁结果（与前端 AdUnlockResult 对齐）"""

    unlocked_count: int = Field(..., description="今日已观看广告次数")
    ad_unlock_remaining_today: int = Field(..., description="当日广告解锁剩余处理次数")
    ad_unlock_daily_limit: int = Field(2, description="每日广告观看上限")
