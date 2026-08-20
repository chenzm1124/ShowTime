"""额度相关 Schema（QuotaInfo 输出）

合并了 VIP / 试用 / 广告 / 次数包四个维度的快照。
"""

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.pack import UserPackBrief


class CurrentQuotaBlock(BaseModel):
    """当前生效的额度块（前端展示用）"""

    photos_per_task: int
    photos_per_task_label: str
    # 补充：当前来源标签，便于前端在多源场景下直接渲染文案
    source: str = Field(..., description="vip | pack | trial | ad | none")


class QuotaInfoOut(BaseModel):
    """用户额度快照"""

    member_type: str
    trial_remaining: int
    trial_first_used_date: date | None
    ad_unlock_remaining_today: int
    ad_unlock_watched_today: int
    ad_unlock_date: date
    vip_expire_date: date | None
    vip_daily_used: int
    vip_daily_date: date
    current_quota: CurrentQuotaBlock
    monthly_used: int
    # 新增：用户持有的所有次数包（含 ACTIVE / EXHAUSTED / EXPIRED）
    user_packs: list[UserPackBrief] = []
