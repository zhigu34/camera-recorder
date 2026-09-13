from fastapi.testclient import TestClient

from app.main import app


def _create_camera(client: TestClient, name: str) -> int:
    response = client.post(
        "/api/cameras",
        json={
            "name": name,
            "ip": "192.0.2.41",
            "rtsp_port": 554,
            "username": "admin",
            "password": "secret",
            "rtsp_path": "/ch1/main",
            "sub_rtsp_path": "/ch1/sub",
            "enabled": True,
            "auto_record": False,
            "recording_schedule_enabled": False,
            "recording_schedule": [],
            "timestamp_mode": "reconstruct",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_motion_settings_and_zone_crud_are_camera_scoped() -> None:
    with TestClient(app) as client:
        camera_id = _create_camera(client, "motion-api-camera-a")
        other_camera_id = _create_camera(client, "motion-api-camera-b")

        response = client.get(f"/api/cameras/{camera_id}/motion-detection")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["sensitivity"] == "medium"
        assert body["analysis_fps"] == 5
        assert body["analysis_width"] == 640
        assert body["zones"] == []
        assert body["runtime"]["state"] == "disabled"

        response = client.put(
            f"/api/cameras/{camera_id}/motion-detection",
            json={
                "enabled": True,
                "sensitivity": "high",
                "analysis_fps": 4,
                "analysis_width": 640,
                "min_duration_ms": 900,
                "merge_gap_ms": 2500,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["enabled"] is True
        assert response.json()["sensitivity"] == "high"

        polygon = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
        response = client.post(
            f"/api/cameras/{camera_id}/motion-zones",
            json={"name": "仓库入口", "enabled": True, "polygon": polygon},
        )
        assert response.status_code == 201, response.text
        zone = response.json()
        zone_id = int(zone["id"])
        assert zone["camera_id"] == camera_id
        assert zone["polygon"] == polygon

        response = client.get(f"/api/cameras/{camera_id}/motion-detection")
        assert [item["id"] for item in response.json()["zones"]] == [zone_id]

        response = client.get(f"/api/cameras/{other_camera_id}/motion-detection")
        assert response.status_code == 200
        assert response.json()["zones"] == []

        response = client.put(
            f"/api/cameras/{camera_id}/motion-zones/{zone_id}",
            json={"name": "装卸入口", "enabled": False},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "装卸入口"
        assert response.json()["enabled"] is False

        response = client.delete(f"/api/cameras/{camera_id}/motion-zones/{zone_id}")
        assert response.status_code == 204
        assert client.get(f"/api/cameras/{camera_id}/motion-detection").json()["zones"] == []


def test_motion_zone_rejects_foreign_camera_scope() -> None:
    with TestClient(app) as client:
        camera_id = _create_camera(client, "motion-api-camera-owner")
        other_camera_id = _create_camera(client, "motion-api-camera-other")
        response = client.post(
            f"/api/cameras/{camera_id}/motion-zones",
            json={
                "name": "入口",
                "polygon": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
            },
        )
        zone_id = int(response.json()["id"])

        response = client.put(
            f"/api/cameras/{other_camera_id}/motion-zones/{zone_id}",
            json={"name": "不应成功"},
        )
        assert response.status_code == 404

        response = client.delete(f"/api/cameras/{other_camera_id}/motion-zones/{zone_id}")
        assert response.status_code == 404
