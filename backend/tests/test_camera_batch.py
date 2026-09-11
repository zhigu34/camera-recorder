from fastapi.testclient import TestClient

from app.main import app


def test_batch_camera_create_and_skip_existing() -> None:
    payload = {
        "skip_existing": True,
        "cameras": [
            {
                "name": "pytest-batch-camera-a",
                "ip": "192.0.2.10",
                "username": "admin",
                "password": "test-secret-a",
                "rtsp_path": "/ch1/main",
                "sub_rtsp_path": "/ch1/sub",
                "timestamp_mode": "reconstruct",
            },
            {
                "name": "pytest-batch-camera-b",
                "ip": "192.0.2.11",
                "username": "admin",
                "password": "test-secret-b",
                "rtsp_path": "/ch1/main",
                "timestamp_mode": "native",
            },
        ],
    }

    with TestClient(app) as client:
        first = client.post("/api/cameras/batch", json=payload)
        assert first.status_code == 201
        first_body = first.json()
        assert first_body["created"] == 2
        assert first_body["skipped"] == 0

        created_camera = client.get(f"/api/cameras/{first_body['created_ids'][0]}")
        assert created_camera.status_code == 200
        assert created_camera.json()["sub_rtsp_path"] == "/ch1/sub"

        second = client.post("/api/cameras/batch", json=payload)
        assert second.status_code == 201
        second_body = second.json()
        assert second_body["created"] == 0
        assert second_body["skipped"] == 2
        assert second_body["skipped_names"] == [
            "pytest-batch-camera-a",
            "pytest-batch-camera-b",
        ]

        for camera_id in first_body["created_ids"]:
            response = client.delete(f"/api/cameras/{camera_id}")
            assert response.status_code == 204


def test_batch_camera_rejects_duplicate_names_in_same_request() -> None:
    payload = {
        "skip_existing": True,
        "cameras": [
            {
                "name": "pytest-duplicate-camera",
                "ip": "192.0.2.20",
                "password": "test-secret-a",
            },
            {
                "name": "pytest-duplicate-camera",
                "ip": "192.0.2.21",
                "password": "test-secret-b",
            },
        ],
    }

    with TestClient(app) as client:
        response = client.post("/api/cameras/batch", json=payload)

    assert response.status_code == 422
    assert "重复名称" in response.json()["detail"]
