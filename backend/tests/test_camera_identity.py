from fastapi.testclient import TestClient

from app.main import app
from app.services.camera_identity import infer_camera_form_factor


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


def test_camera_form_factor_catalog_is_conservative() -> None:
    assert infer_camera_form_factor("Hikvision", "DS-2CD2347G2-LU").form_factor == "turret"
    assert infer_camera_form_factor(None, "DS-2CD2347G2-LU").form_factor == "turret"
    assert infer_camera_form_factor("Unknown", "DS-2CD2T47G2-L").form_factor == "bullet"
    assert infer_camera_form_factor("Dahua", "IPC-HFW3849T1-AS-PV").form_factor == "bullet"
    assert infer_camera_form_factor(None, "IPC-HDW3849H-AS-PV").form_factor == "turret"
    assert infer_camera_form_factor("Reolink", "RLC-810A").form_factor == "bullet"
    assert infer_camera_form_factor(None, "RLC-833A").form_factor == "turret"
    assert infer_camera_form_factor("Ubiquiti", "G4 Doorbell Pro").form_factor == "doorbell"
    assert infer_camera_form_factor("Unknown", "ABC-123") is None


def test_ezviz_cs_families_are_inferred_from_model() -> None:
    assert infer_camera_form_factor("Hikvision", "CS-C6c-V101-8G8WF").form_factor == "ptz"
    assert infer_camera_form_factor("Hikvision", "CS-C6C-3H3WFRV").form_factor == "ptz"
    assert infer_camera_form_factor("Hikvision", "CS-C60p-V100-8G55WFL").form_factor == "ptz"
    assert infer_camera_form_factor("Hikvision", "CS-C8c-V100-8H8WKFL").form_factor == "ptz"
    assert infer_camera_form_factor("Hikvision", "CS-E4p-V100-8C6WKF").form_factor == "dome"
    assert infer_camera_form_factor(None, "CS-C6c-V101-8G8WF").form_factor == "ptz"
    assert infer_camera_form_factor("EZVIZ", "CS-E4p-V100-8C6WKF").form_factor == "dome"


def test_camera_form_factor_is_inferred_when_unspecified_and_manual_choice_wins() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/cameras",
            json={
                "name": "pytest-camera-auto-form-factor",
                "manufacturer": "Hikvision",
                "model": "DS-2CD2347G2-LU",
                "form_factor": "unknown",
                "ip": "192.0.2.121",
                "username": "admin",
                "password": "test-secret",
                "rtsp_path": "/ch1/main",
                "timestamp_mode": "native",
            },
        )
        assert created.status_code == 201
        body = created.json()
        camera_id = body["id"]
        assert body["form_factor"] == "turret"

        updated = client.put(
            f"/api/cameras/{camera_id}",
            json={
                "manufacturer": "Reolink",
                "model": "RLC-810A",
                "form_factor": "dome",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["form_factor"] == "dome"

        renamed = client.put(
            f"/api/cameras/{camera_id}",
            json={"manufacturer": "Dahua", "model": "IPC-HFW3849T1-AS-PV"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["form_factor"] == "dome"

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204


def test_camera_form_factor_is_inferred_from_model_without_manufacturer() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/cameras",
            json={
                "name": "pytest-camera-model-only-form-factor",
                "model": "DS-2CD2347G2-LU",
                "form_factor": "unknown",
                "ip": "192.0.2.122",
                "username": "admin",
                "password": "test-secret",
                "rtsp_path": "/ch1/main",
                "timestamp_mode": "native",
            },
        )
        assert created.status_code == 201
        body = created.json()
        camera_id = body["id"]
        assert body["form_factor"] == "turret"

        deleted = client.delete(f"/api/cameras/{camera_id}")
        assert deleted.status_code == 204
