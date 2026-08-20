"""照片上传模块测试

覆盖：
- STS 凭证获取（含认证、参数）
- 上传确认（Photo 入库、字段验证）
- Mock 模式凭证内容验证
"""

import warnings

warnings.filterwarnings("ignore")


class TestGetSts:
    """STS 凭证获取"""

    def test_get_sts_with_auth(self, client, auth_headers):
        """带认证获取 STS"""
        r = client.get("/api/v1/photos/sts?file_count=3", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        data = body["data"]

        # Mock 模式凭证字段验证
        assert data["tmp_secret_id"] == "mock_tmp_secret_id"
        assert data["tmp_secret_key"] == "mock_tmp_secret_key"
        assert data["session_token"] == "mock_session_token"
        # bucket/region 随配置变化，只验证存在性
        assert data["bucket"]
        assert data["region"]
        assert "uploads/" in data["upload_dir"]
        assert "{filename}" in data["file_path"]
        assert data["expired_time"] > data["start_time"]

    def test_get_sts_default_file_count(self, client, auth_headers):
        """不传 file_count 默认为 1"""
        r = client.get("/api/v1/photos/sts", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["code"] == 0

    def test_get_sts_invalid_file_count(self, client, auth_headers):
        """file_count 超出范围返回 422"""
        r = client.get("/api/v1/photos/sts?file_count=0", headers=auth_headers)
        assert r.status_code == 422

        r2 = client.get("/api/v1/photos/sts?file_count=501", headers=auth_headers)
        assert r2.status_code == 422

    def test_get_sts_upload_dir_contains_user_id(self, client, auth_headers):
        """upload_dir 包含用户 ID"""
        r = client.get("/api/v1/photos/sts", headers=auth_headers)
        data = r.json()["data"]
        # Mock 模式下 upload_dir 格式：uploads/{user_id}/{timestamp}
        parts = data["upload_dir"].split("/")
        assert len(parts) == 3
        assert parts[0] == "uploads"
        assert parts[1].isdigit()  # user_id


class TestConfirmUpload:
    """上传确认"""

    def test_confirm_basic(self, client, auth_headers):
        """基本上传确认"""
        r = client.post(
            "/api/v1/photos/confirm",
            json={
                "file_id": "test_file_001",
                "url": "mock://photo_001.jpg",
                "size": 1024000,
                "width": 1080,
                "height": 1920,
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        data = body["data"]

        assert data["file_id"] == "test_file_001"
        assert data["url"] == "mock://photo_001.jpg"
        assert data["size"] == 1024000
        assert data["width"] == 1080
        assert data["height"] == 1920
        assert data["photo_id"]  # 后端生成的 Photo ID
        assert data["thumbnail_url"] == data["url"]

    def test_confirm_without_dimensions(self, client, auth_headers):
        """不传宽高也能确认"""
        r = client.post(
            "/api/v1/photos/confirm",
            json={"file_id": "test_file_002", "url": "mock://photo_002.jpg", "size": 512000},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["width"] == 0
        assert data["height"] == 0

    def test_confirm_missing_file_id_returns_422(self, client, auth_headers):
        """缺少 file_id 返回 422"""
        r = client.post(
            "/api/v1/photos/confirm",
            json={"url": "mock://photo.jpg", "size": 1000},
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_confirm_missing_url_returns_422(self, client, auth_headers):
        """缺少 url 返回 422"""
        r = client.post(
            "/api/v1/photos/confirm",
            json={"file_id": "test_file", "size": 1000},
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_confirm_multiple_photos(self, client, auth_headers):
        """连续确认多张照片，每张返回不同 photo_id"""
        ids = []
        for i in range(5):
            r = client.post(
                "/api/v1/photos/confirm",
                json={"file_id": f"file_{i}", "url": f"mock://photo_{i}.jpg", "size": 1000},
                headers=auth_headers,
            )
            assert r.status_code == 200
            ids.append(r.json()["data"]["photo_id"])

        # 5 个不同的 photo_id
        assert len(set(ids)) == 5
