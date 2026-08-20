"""认证相关 Schema"""

from pydantic import BaseModel, Field


class DeviceInfo(BaseModel):
    """设备信息（反作弊用）"""

    model: str | None = None
    system: str | None = None
    platform: str | None = None
    sdk_version: str | None = None


class WxLoginReq(BaseModel):
    """微信登录请求"""

    code: str = Field(..., description="wx.login 获取的临时 code")
    device_info: DeviceInfo | None = None


class LoginResultOut(BaseModel):
    """登录成功返回（与前端 LoginResult 对齐）"""

    token: str
    user_id: str
    openid: str
    is_new_user: bool
    member_type: str = "free"
    member_expire_date: str | None = None
    trial_remaining: int = 1
    trial_expire_date: str | None = None
