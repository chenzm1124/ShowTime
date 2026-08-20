"""广告解锁 + 额度扣减测试"""
import warnings

warnings.filterwarnings("ignore")


class TestAdUnlock:
    """广告解锁 API"""

    def test_ad_unlock_first(self, client, auth_headers):
        """首次观看广告"""
        r = client.post(
            "/api/v1/quota/ad-unlock",
            json={"ad_type": "rewarded_video", "ad_platform": "wechat", "watch_duration_seconds": 30},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["unlocked_count"] == 1
        assert data["ad_unlock_remaining_today"] == 3  # 初始2 + 广告1
        assert data["ad_unlock_daily_limit"] == 2

    def test_ad_unlock_second(self, client, auth_headers):
        """第二次观看广告"""
        client.post("/api/v1/quota/ad-unlock", json={}, headers=auth_headers)
        r = client.post("/api/v1/quota/ad-unlock", json={}, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["unlocked_count"] == 2
        assert data["ad_unlock_remaining_today"] == 4  # 初始2 + 广告2

    def test_ad_unlock_exceeds_daily_limit(self, client, auth_headers):
        """第三次观看广告超出每日上限"""
        client.post("/api/v1/quota/ad-unlock", json={}, headers=auth_headers)
        client.post("/api/v1/quota/ad-unlock", json={}, headers=auth_headers)
        r = client.post("/api/v1/quota/ad-unlock", json={}, headers=auth_headers)
        assert r.status_code == 400
        assert "上限" in r.json()["detail"]

    def test_ad_unlock_increases_quota(self, client, auth_headers):
        """观看广告后额度快照中 ad_unlock_remaining_today 增加"""
        # 观看前
        r1 = client.get("/api/v1/user/quota", headers=auth_headers)
        before = r1.json()["data"]["ad_unlock_remaining_today"]

        # 观看广告
        client.post("/api/v1/quota/ad-unlock", json={}, headers=auth_headers)

        # 观看后
        r2 = client.get("/api/v1/user/quota", headers=auth_headers)
        after = r2.json()["data"]["ad_unlock_remaining_today"]
        assert after == before + 1


class TestQuotaConsumption:
    """任务创建时的额度扣减"""

    def test_first_task_uses_trial(self, client, auth_headers):
        """首次任务扣减试用额度"""
        # 创建任务前
        r1 = client.get("/api/v1/user/quota", headers=auth_headers)
        assert r1.json()["data"]["trial_remaining"] == 1

        # 创建任务
        client.post(
            "/api/v1/tasks",
            json={"photo_urls": ["mock://a.jpg"], "options": {"retouch_styles": ["auto"]}},
            headers=auth_headers,
        )

        # 创建任务后
        r2 = client.get("/api/v1/user/quota", headers=auth_headers)
        assert r2.json()["data"]["trial_remaining"] == 0

    def test_second_task_uses_ad(self, client, auth_headers):
        """试用用完后，第二次任务扣减广告额度"""
        # 第一次任务（消耗试用）
        client.post(
            "/api/v1/tasks",
            json={"photo_urls": ["mock://a.jpg"]},
            headers=auth_headers,
        )

        # 查看额度
        r1 = client.get("/api/v1/user/quota", headers=auth_headers)
        assert r1.json()["data"]["trial_remaining"] == 0
        ad_before = r1.json()["data"]["ad_unlock_remaining_today"]

        # 第二次任务（消耗广告）
        client.post(
            "/api/v1/tasks",
            json={"photo_urls": ["mock://b.jpg"]},
            headers=auth_headers,
        )

        # 广告额度减少
        r2 = client.get("/api/v1/user/quota", headers=auth_headers)
        assert r2.json()["data"]["ad_unlock_remaining_today"] == ad_before - 1

    def test_three_tasks_consumes_all_quota(self, client, auth_headers):
        """创建3个任务后，试用+广告额度全部消耗"""
        for i in range(3):
            r = client.post(
                "/api/v1/tasks",
                json={"photo_urls": [f"mock://photo_{i}.jpg"]},
                headers=auth_headers,
            )
            assert r.status_code == 200

        # 额度应该为 0
        r = client.get("/api/v1/user/quota", headers=auth_headers)
        data = r.json()["data"]
        assert data["trial_remaining"] == 0
        assert data["ad_unlock_remaining_today"] == 0
