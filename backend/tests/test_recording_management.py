from fastapi.testclient import TestClient

from app.main import app


def test_recording_management_returns_paginated_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/api/recording-management", params={"limit": 1, "offset": 0})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "offset", "limit", "stats"}
    assert isinstance(body["items"], list)
    assert len(body["items"]) <= 1
    assert body["offset"] == 0
    assert body["limit"] == 1
    assert body["total"] >= len(body["items"])
    assert set(body["stats"]) == {
        "total",
        "total_size",
        "archived",
        "pending_archive",
        "abnormal",
    }


def test_recording_management_validates_page_size() -> None:
    with TestClient(app) as client:
        response = client.get("/api/recording-management", params={"limit": 0})

    assert response.status_code == 422
