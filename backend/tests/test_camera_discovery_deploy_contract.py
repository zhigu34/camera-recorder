from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _compose_config() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _deploy_script() -> str:
    return (ROOT / "deploy.sh").read_text(encoding="utf-8")


def _ci_workflow() -> str:
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_discovery_helper_uses_host_network_without_published_ports() -> None:
    service = _compose_config()["services"]["onvif-discovery"]

    assert service["network_mode"] == "host"
    assert not service.get("ports")
    assert service["container_name"] == "camera-recorder-onvif-discovery"
    assert "camera-discovery-runtime:/run/camera-recorder" in service["volumes"]


def test_backend_remains_bridge_networked_and_shares_only_discovery_runtime() -> None:
    compose = _compose_config()
    backend = compose["services"]["backend"]

    assert backend.get("network_mode") != "host"
    assert "onvif-discovery" not in backend.get("depends_on", {})
    assert (
        backend["environment"]["CAMREC_ONVIF_DISCOVERY_SOCKET"]
        == "/run/camera-recorder/onvif-discovery.sock"
    )
    assert "camera-discovery-runtime:/run/camera-recorder" in backend["volumes"]


def test_discovery_runtime_is_a_named_volume() -> None:
    compose = _compose_config()

    assert "camera-discovery-runtime" in compose["volumes"]


def test_discovery_helper_command_uses_uds_and_unlinks_stale_socket() -> None:
    service = _compose_config()["services"]["onvif-discovery"]
    rendered = " ".join(str(part) for part in service["command"])

    assert "rm -f /run/camera-recorder/onvif-discovery.sock" in rendered
    assert "app.discovery_helper:app" in rendered
    assert "--uds /run/camera-recorder/onvif-discovery.sock" in rendered


def test_deploy_tracks_discovery_as_best_effort_post_core_stage() -> None:
    script = _deploy_script()

    assert "UPDATE_DISCOVERY" in script
    assert "camera-recorder-onvif-discovery" in script
    assert "DISCOVERY_UPDATE_SERVICES" in script
    assert "局域网发现服务启动失败" in script

    core_start = script.index("CORE_UPDATE_SERVICES=()")
    discovery_stage = script.index("DISCOVERY_UPDATE_SERVICES=()", core_start)
    core_section = script[core_start:discovery_stage]

    assert "onvif-discovery" not in core_section
    assert "核心 docker compose up" in core_section


def test_deploy_classifies_backend_runtime_changes_for_discovery_helper() -> None:
    script = _deploy_script()

    assert "mark_discovery" in script
    assert "backend/Dockerfile|backend/pyproject.toml|backend/uv.lock" in script
    assert "backend/app/discovery_helper.py" in script
    assert "backend/app/services/camera_discovery.py" in script


def test_ci_validates_discovery_topology_and_uds_health_without_lan_scan() -> None:
    workflow = _ci_workflow()

    assert "Verify discovery helper topology" in workflow
    assert "camera-recorder-onvif-discovery" in workflow
    assert "/run/camera-recorder/onvif-discovery.sock" in workflow
    assert "/scan/onvif" not in workflow
    assert "/scan/rtsp" not in workflow


def test_deploy_classifies_discovery_only_code_without_restarting_backend() -> None:
    script = _deploy_script()

    helper_rule = (
        "backend/app/discovery_helper.py|backend/app/services/camera_discovery.py) "
        "BUILD_BACKEND=1; mark_discovery ;;"
    )
    shared_rule = (
        "backend/app/schemas/camera_discovery.py|backend/app/services/onvif_client.py) "
        "BUILD_BACKEND=1; UPDATE_BACKEND=1; mark_discovery ;;"
    )

    assert helper_rule in script
    assert shared_rule in script
