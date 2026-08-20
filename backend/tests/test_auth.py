"""认证模块测试

覆盖：
- 健康检查
- 微信登录（新用户创建、重复登录、参数校验）
- JWT token 有效性
- 退出登录
"""

import warnings

warnings.filterwarnings("ignore")


class TestHealth:
    """健康检查"""

    def test_health_returns_ok(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "ok"

    def test_health_db(self, client):
        r = client.get("/api/v1/health/db")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0


class TestWxLogin:
    """微信登录"""

    def test_login_creates_new_user(self, client):
        """首次登录应创建新用户"""
        r = client.post(
            "/api/v1/auth/wx-login",
            json={"code": "new_user_code_001"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        data = body["data"]

        assert "token" in data
        assert len(data["token"]) > 0
        assert data["user_id"]
        assert data["openid"].startswith("mock_openid_")
        assert data["is_new_user"] is True
        assert data["member_type"] == "free"
        assert data["trial_remaining"] == 1
        assert data["member_expire_date"] is None

    def test_login_same_code_returns_existing_user(self, client):
        """同一 code 再次登录，返回同一用户，is_new_user=False"""
        # 第一次登录
        r1 = client.post("/api/v1/auth/wx-login", json={"code": "repeat_code_002"})
        assert r1.status_code == 200
        user1 = r1.json()["data"]

        # 第二次登录（同一 code）
        r2 = client.post("/api/v1/auth/wx-login", json={"code": "repeat_code_002"})
        assert r2.status_code == 200
        user2 = r2.json()["data"]

        assert user1["openid"] == user2["openid"]
        assert user1["user_id"] == user2["user_id"]
        assert user2["is_new_user"] is False

    def test_login_different_code_creates_different_user(self, client):
        """不同 code 产生不同 openid"""
        r1 = client.post("/api/v1/auth/wx-login", json={"code": "code_a"})
        r2 = client.post("/api/v1/auth/wx-login", json={"code": "code_b"})
        assert r1.json()["data"]["openid"] != r2.json()["data"]["openid"]

    def test_login_with_device_info(self, client):
        """携带设备信息登录"""
        r = client.post(
            "/api/v1/auth/wx-login",
            json={
                "code": "device_code_003",
                "device_info": {
                    "model": "iPhone 15 Pro",
                    "system": "iOS 17",
                    "platform": "ios",
                    "sdk_version": "3.0",
                },
            },
        )
        assert r.status_code == 200
        assert r.json()["data"]["is_new_user"] is True

    def test_login_missing_code_returns_422(self, client):
        """缺少 code 参数返回 422"""
        r = client.post("/api/v1/auth/wx-login", json={})
        assert r.status_code == 422

    def test_login_token_is_valid_jwt(self, client):
        """登录返回的 token 可以用于后续请求"""
        r = client.post("/api/v1/auth/wx-login", json={"code": "jwt_test_code"})
        token = r.json()["data"]["token"]

        # 用 token 请求需要认证的接口
        r2 = client.get("/api/v1/photos/sts", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json()["code"] == 0


class TestLogout:
    """退出登录"""

    def test_logout_returns_ok(self, client):
        r = client.post("/api/v1/auth/logout")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["ok"] is True
