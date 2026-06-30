"""健康检查冒烟测试。"""

from fastapi.testclient import TestClient

from drama_smith.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
