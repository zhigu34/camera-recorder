from fastapi.testclient import TestClient

from app.main import app


def test_recording_browser_empty_day_shape(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    with TestClient(app) as client:
        response = client.get(
            "/api/recordings/browser",
            params={"camera_id": 99999999, "date": "2026-09-11"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["camera_id"] == 99999999
    assert body["date"] == "2026-09-11"
    assert body["timezone"] == "Asia/Shanghai"
    assert body["count"] == 0
    assert body["items"] == []


def test_recording_browser_rejects_invalid_date():
    with TestClient(app) as client:
        response = client.get(
            "/api/recordings/browser",
            params={"camera_id": 1, "date": "not-a-date"},
        )

    assert response.status_code == 422


def test_missing_recording_playback_is_404():
    with TestClient(app) as client:
        response = client.get("/api/recordings/99999999/playback")

    assert response.status_code == 404
