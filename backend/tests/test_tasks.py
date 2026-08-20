"""任务管理模块测试"""
import time
import warnings

warnings.filterwarnings("ignore")


def _create_task(client, headers) -> str:
    r = client.post(
        "/api/v1/tasks",
        json={
            "photo_urls": ["mock://a.jpg", "mock://b.jpg", "mock://c.jpg"],
            "options": {"retouch_styles": ["auto"], "location": "杭州"},
        },
        headers=headers,
    )
    assert r.status_code == 200
    return r.json()["data"]["task_id"]


class TestCreateTask:
    def test_create_basic(self, client, auth_headers):
        r = client.post(
            "/api/v1/tasks",
            json={"photo_urls": ["mock://a.jpg", "mock://b.jpg"], "options": {"retouch_styles": ["auto"]}},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["task_id"]
        assert data["status"] == "pending"
        assert data["estimated_time"] > 0

    def test_create_default_options(self, client, auth_headers):
        r = client.post("/api/v1/tasks", json={"photo_urls": ["mock://a.jpg"]}, headers=auth_headers)
        assert r.status_code == 200

    def test_create_empty_photos_returns_400(self, client, auth_headers):
        r = client.post("/api/v1/tasks", json={"photo_urls": []}, headers=auth_headers)
        assert r.status_code == 400

    def test_create_missing_photos_returns_422(self, client, auth_headers):
        r = client.post("/api/v1/tasks", json={"options": {}}, headers=auth_headers)
        assert r.status_code == 422

    def test_create_multiple_styles(self, client, auth_headers):
        r = client.post(
            "/api/v1/tasks",
            json={"photo_urls": ["mock://a.jpg"], "options": {"retouch_styles": ["auto", "hk", "cyber"]}},
            headers=auth_headers,
        )
        assert r.status_code == 200


class TestTaskStatus:
    def test_status_immediate(self, client, auth_headers):
        tid = _create_task(client, auth_headers)
        r = client.get(f"/api/v1/tasks/{tid}/status", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["task_id"] == tid
        assert data["status"] in ("pending", "processing")
        assert data["total_photos"] == 3

    def test_status_completed_after_delay(self, client, auth_headers):
        tid = _create_task(client, auth_headers)
        time.sleep(6.5)
        r = client.get(f"/api/v1/tasks/{tid}/status", headers=auth_headers)
        data = r.json()["data"]
        assert data["status"] == "completed"
        assert data["progress"] == 100
        assert data["current_stage"] == "completed"

    def test_status_not_found(self, client, auth_headers):
        r = client.get("/api/v1/tasks/99999/status", headers=auth_headers)
        assert r.status_code == 404


class TestTaskResult:
    def test_result_structure(self, client, auth_headers):
        tid = _create_task(client, auth_headers)
        time.sleep(6.5)
        r = client.get(f"/api/v1/tasks/{tid}/result", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["task_id"] == tid
        assert data["status"] == "completed"
        assert data["total_photos"] == 3
        assert len(data["selected_photos"]) == 3
        assert len(data["groups"]) >= 1

    def test_result_photo_fields(self, client, auth_headers):
        tid = _create_task(client, auth_headers)
        time.sleep(6.5)
        r = client.get(f"/api/v1/tasks/{tid}/result", headers=auth_headers)
        for p in r.json()["data"]["selected_photos"]:
            assert p["photo_id"]
            assert p["original_url"]
            assert p["processed_url"]
            assert 0 <= p["quality_score"] <= 1
            assert p["type"] in ("portrait", "landscape")

    def test_result_not_found(self, client, auth_headers):
        r = client.get("/api/v1/tasks/99999/result", headers=auth_headers)
        assert r.status_code == 404


class TestTaskHistory:
    def test_history_empty(self, client, auth_headers):
        r = client.get("/api/v1/tasks", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 0
        assert data["list"] == []

    def test_history_after_create(self, client, auth_headers):
        _create_task(client, auth_headers)
        r = client.get("/api/v1/tasks", headers=auth_headers)
        data = r.json()["data"]
        assert data["total"] >= 1
        assert len(data["list"]) >= 1
        item = data["list"][0]
        assert item["task_id"]
        assert item["status"]
        assert item["created_at"]

    def test_history_pagination(self, client, auth_headers):
        for _ in range(3):
            _create_task(client, auth_headers)
        r = client.get("/api/v1/tasks?page=1&page_size=2", headers=auth_headers)
        data = r.json()["data"]
        assert data["total"] >= 3
        assert len(data["list"]) == 2
