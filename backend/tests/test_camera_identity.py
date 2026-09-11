from fastapi.testclient import TestClient

from app.main import app


def test_camera_identity_metadata_round_trip_and_clear() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/cameras",
            json={
                "name": "pytest-camera-identity",
                "manufacturer": "Reolink",
                "model": "RLC-810A",
                "form_factor": "bullet",
                "ip": "192.0.2.120",
                "username": "admin",
                "password": "test-secret",
                "rtsp_path": "/ch1/main",
                "timestamp_mode": "native",
            },
        )
        assert created.status_code == 201
        body = created.json()
        camera_id = body["id"]
        assert body["manufacturer"] == "Reolink"
        assert body["model"] == "RLC-810A"
        assert body["form_factor"] == "bullet"

        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={
                "manufacturer": "  ",
                "model": None,
                "form_factor": "turret",
            },
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["manufacturer"] is None
        assert body["model"] is None
        assert body["form_factor"] == "turret"

        fetched = client.get(f"/api/cameras/{camera_id}")
        assert fetched.status_code == 200
        assert fetched.json()["manufacturer"] is None
        assert fetched.json()["model"] is None
        assert fetched.json()["form_factor"] == "turret"

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204
