"""AI 服务层 + 文案生成模块测试

覆盖：
- AI pipeline 完整流程（筛选+精修+文案）
- Mock Screener 分组逻辑
- Mock Retoucher 精修
- Mock CaptionProvider 文案生成
- /api/v1/captions/styles 端点
- /api/v1/captions/generate 端点
"""

import asyncio
import warnings

warnings.filterwarnings("ignore")

from app.ai import PhotoInfo, ai_pipeline
from app.ai.base import CaptionStyle
from app.ai.screener import MockScreener
from app.ai.retoucher import MockRetoucher
from app.ai.caption_gen import MockCaptionProvider


class TestAIPipeline:
    """AI pipeline 完整流程测试"""

    def test_process_basic(self):
        photos = [
            PhotoInfo(photo_id="p1", original_url="http://img/a.jpg", order_index=0),
            PhotoInfo(photo_id="p2", original_url="http://img/b.jpg", order_index=1),
            PhotoInfo(photo_id="p3", original_url="http://img/c.jpg", order_index=2),
        ]
        result = asyncio.run(
            ai_pipeline.process(photos, retouch_styles=["auto"], location="杭州")
        )
        assert result["total_photos"] == 3
        assert result["total_groups"] >= 1
        assert len(result["selected_photos"]) == 3
        assert len(result["groups"]) >= 1

    def test_process_photo_fields(self):
        photos = [PhotoInfo(photo_id="p1", original_url="http://img/a.jpg")]
        result = asyncio.run(ai_pipeline.process(photos, ["fresh"]))
        photo = result["selected_photos"][0]
        assert photo["photo_id"] == "p1"
        assert photo["original_url"] == "http://img/a.jpg"
        assert photo["processed_url"]
        assert 0 <= photo["quality_score"] <= 1
        assert photo["type"] in ("portrait", "landscape")
        assert photo["retouch_style"] in ("auto", "hk", "cyber", "soft", "film", "fresh")
        assert photo["retouch_style_label"]

    def test_process_caption_generated(self):
        """每组至少有一张照片带文案"""
        photos = [
            PhotoInfo(photo_id=f"p{i}", original_url=f"http://img/{i}.jpg", order_index=i)
            for i in range(5)
        ]
        result = asyncio.run(ai_pipeline.process(photos, ["auto"], "西湖"))
        captions = [p["caption"] for p in result["selected_photos"] if p["caption"]]
        assert len(captions) >= 1

    def test_process_empty_photos(self):
        result = asyncio.run(ai_pipeline.process([], ["auto"]))
        assert result["total_photos"] == 0
        assert result["selected_photos"] == []

    def test_generate_captions_only(self):
        result = asyncio.run(
            ai_pipeline.generate_captions_only(
                ["http://img/a.jpg"], "西湖", "literary", count=3
            )
        )
        assert len(result.captions) == 3
        assert result.style == "literary"
        assert result.location == "西湖"


class TestMockScreener:
    """智能筛选 Mock 测试"""

    def test_screen_groups(self):
        screener = MockScreener()
        photos = [
            PhotoInfo(photo_id=f"p{i}", original_url=f"http://img/{i}.jpg")
            for i in range(6)
        ]
        result = asyncio.run(screener.screen(photos))
        assert result.total_photos == 6
        assert result.total_groups >= 2  # 6 张至少分 2 组
        assert len(result.selected) == 6

    def test_screen_quality_score_range(self):
        screener = MockScreener()
        photos = [PhotoInfo(photo_id="p1", original_url="http://img/a.jpg")]
        result = asyncio.run(screener.screen(photos))
        score = result.selected[0].quality_score
        assert 0.0 <= score <= 1.0


class TestMockRetoucher:
    """智能精修 Mock 测试"""

    def test_retouch_returns_url(self):
        from app.ai.base import SelectedPhoto

        photo = SelectedPhoto(
            photo_id="p1",
            original_url="http://img/a.jpg",
            processed_url="http://img/a.jpg",
            thumbnail_url="http://img/a.jpg",
            quality_score=0.85,
            face_count=1,
            type="portrait",
            retouch_style="auto",
            retouch_style_label="智能配风格",
            cluster_group_id=0,
            rank_in_group=0,
        )
        retoucher = MockRetoucher()
        result = asyncio.run(retoucher.retouch(photo))
        assert result.success is True
        assert result.processed_url == "http://img/a.jpg"


class TestMockCaptionProvider:
    """文案生成 Mock 测试"""

    def test_generate_literary(self):
        provider = MockCaptionProvider()
        result = asyncio.run(
            provider.generate(["http://img/a.jpg"], None, "literary", count=3)
        )
        assert len(result.captions) == 3
        assert all(isinstance(c, str) and len(c) > 0 for c in result.captions)

    def test_generate_all_styles(self):
        provider = MockCaptionProvider()
        for style in ("literary", "humor", "minimal", "emotional", "checkin"):
            result = asyncio.run(
                provider.generate(["http://img/a.jpg"], None, style, count=2)
            )
            assert len(result.captions) == 2

    def test_generate_with_location(self):
        provider = MockCaptionProvider()
        result = asyncio.run(
            provider.generate(["http://img/a.jpg"], "西湖", "checkin", count=2)
        )
        assert len(result.captions) == 2


class TestCaptionsAPI:
    """文案生成 API 端点测试"""

    def test_get_styles(self, client, auth_headers):
        r = client.get("/api/v1/captions/styles", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 5
        codes = [s["code"] for s in data]
        assert "literary" in codes
        assert "humor" in codes
        for s in data:
            assert s["code"]
            assert s["name"]
            assert s["emoji"]

    def test_generate_captions(self, client, auth_headers):
        r = client.post(
            "/api/v1/captions/generate",
            json={
                "photo_urls": ["http://img/a.jpg", "http://img/b.jpg"],
                "location": "杭州西湖",
                "style": "literary",
                "count": 3,
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 3
        for item in data:
            assert item["id"]
            assert item["text"]
            assert item["style"] == "literary"
            assert item["style_label"]
            assert item["emoji"]

    def test_generate_default_count(self, client, auth_headers):
        r = client.post(
            "/api/v1/captions/generate",
            json={"photo_urls": ["http://img/a.jpg"], "style": "humor"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 3  # 默认 count=3

    def test_generate_checkin_style_with_location(self, client, auth_headers):
        r = client.post(
            "/api/v1/captions/generate",
            json={
                "photo_urls": ["http://img/a.jpg"],
                "location": "日本京都",
                "style": "checkin",
                "count": 2,
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 2
        assert all(item["style"] == "checkin" for item in data)

    def test_generate_no_auth_mock_mode_fallback(self, client):
        """Mock 模式下未登录会 fallback 到测试用户或返回 404（空库）"""
        r = client.post(
            "/api/v1/captions/generate",
            json={"photo_urls": ["http://img/a.jpg"], "style": "literary"},
        )
        # Mock 模式：无 token 时 fallback 到第一个用户，或空库返回 404
        assert r.status_code in (200, 404)

    def test_generate_empty_photos(self, client, auth_headers):
        """空照片列表不报 422（Pydantic list[str] 默认允许空列表）"""
        r = client.post(
            "/api/v1/captions/generate",
            json={"photo_urls": [], "style": "literary"},
            headers=auth_headers,
        )
        # 空列表走流程，返回空文案
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
