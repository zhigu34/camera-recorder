from fastapi.testclient import TestClient

from app.main import app


def test_motion_events_allow_cross_camera_query() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/motion-events",
            params={
                "start": "2026-09-14T00:00:00",
                "end": "2026-09-14T23:59:59.999999",
                "limit": 10,
            },
        )

        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)
