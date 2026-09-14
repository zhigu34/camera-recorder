from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_operations_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/operations/logs" in paths
    assert "/api/operations/backup" in paths
    assert "/api/operations/restore" in paths
    assert "/api/operations/audit" in paths
    assert "/metrics" in paths


def test_log_listing_is_scoped_to_configured_logs_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "logs_dir", tmp_path)
    (tmp_path / "camera-1.log").write_text("hello\nworld\n", encoding="utf-8")
    (tmp_path / "worker.log").write_text("worker\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "hidden.log").write_text("hidden\n", encoding="utf-8")

    client = TestClient(app)
    response = client.get("/api/operations/logs")

    assert response.status_code == 200
    payload = response.json()
    assert [item["name"] for item in payload] == ["camera-1.log", "worker.log"]
    assert all(item["size_bytes"] > 0 for item in payload)
