"""Mock 智能精修 Provider

开发期默认实现：直接返回原图 URL（不调用美图 API）。
真实实现 RetoucherMeituProvider 接口已定义在 base.py 中。
"""

from app.ai.base import RetouchResult, RetoucherProvider, SelectedPhoto


class MockRetoucher(RetoucherProvider):
    """Mock 精修

    开发期未配置美图密钥时使用。为了能让「原图/精修图」对比 UI 正常切换、
    并让结果页拿到与原图不同的 processed_url，这里给 URL 追加一个 mock 标记。
    注意：实际图像内容仍是原图，真实精修效果需配置美图云修 Pro。
    """

    async def retouch(self, photo: SelectedPhoto) -> RetouchResult:
        base_url = photo.processed_url or photo.original_url
        # 保持与原图 URL 可区分，便于前端切换对比；COS 会忽略未知 query 参数
        separator = "&" if "?" in base_url else "?"
        processed_url = f"{base_url}{separator}mock_retouch=1"
        return RetouchResult(
            photo_id=photo.photo_id,
            processed_url=processed_url,
            success=True,
        )
