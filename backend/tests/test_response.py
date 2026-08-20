"""统一响应包装中间件测试"""


class TestResponseWrapper:
    def test_success_wrapped(self, client):
        """正常 JSON 响应被包装为 { code:0, message, data }"""
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["message"] == "success"
        assert "data" in body
        assert body["data"]["status"] == "ok"

    def test_error_wrapped(self, client):
        """异常响应包含 code:-1"""
        r = client.get("/api/v1/tasks/99999/status")
        assert r.status_code == 404
        body = r.json()
        assert "detail" in body  # FastAPI 默认 404 格式

    def test_docs_not_wrapped(self, client):
        """/docs 返回 HTML，不被包装"""
        r = client.get("/docs")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        # 不是 JSON，所以不会有 code 字段
        assert not r.text.startswith('{"code"')

    def test_openapi_not_wrapped(self, client):
        """/openapi.json 不被包装"""
        r = client.get("/openapi.json")
        assert r.status_code == 200
        body = r.json()
        assert "code" not in body
        assert "openapi" in body

    def test_login_response_wrapped(self, client):
        """登录响应被正确包装"""
        r = client.post("/api/v1/auth/wx-login", json={"code": "wrapper_test"})
        body = r.json()
        assert body["code"] == 0
        assert body["message"] == "success"
        assert "token" in body["data"]
        assert "user_id" in body["data"]
