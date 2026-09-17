from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _compose_config() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _deploy_script() -> str:
    return (ROOT / "deploy.sh").read_text(encoding="utf-8")


def _env_example() -> str:
    return (ROOT / ".env.example").read_text(encoding="utf-8")


def test_deploy_tracks_hik_bridge_and_private_runtime_changes() -> None:
    script = _deploy_script()

    assert "UPDATE_HIK" in script
    assert "hik_sdk_hash=" in script
    assert "UPDATE_SERVICES+=(hik-bridge)" in script
    assert "camera-recorder-hik-bridge" in script
    assert "libhcnetsdk.so" in script
    assert "HCNetSDKCom" in script
    assert "--force-recreate" in script


def test_deploy_classifies_hik_runtime_paths_without_full_deploy() -> None:
    script = _deploy_script()

    assert "hik-sdk-runtime/.gitkeep) ;;" in script
    assert "hik-sdk-runtime/*) UPDATE_HIK=1 ;;" in script


def test_hik_bridge_is_profile_scoped_and_runtime_mount_is_preserved() -> None:
    compose = _compose_config()
    service = compose["services"]["hik-bridge"]
    environment = service.get("environment", {})

    assert service["profiles"] == ["hik"]
    assert environment["HIK_SDK_PATH"] == "/opt/hikvision/runtime"
    assert "LD_LIBRARY_PATH" not in environment
    assert "${HIK_SDK_DIR:-./hik-sdk-runtime}:/opt/hikvision/runtime:ro" in service["volumes"]


def test_backend_is_independent_from_hik_bridge_and_defaults_hik_off() -> None:
    compose = _compose_config()
    backend = compose["services"]["backend"]
    dependencies = backend.get("depends_on", {})

    assert "hik-bridge" not in dependencies
    assert backend["environment"]["CAMREC_HIK_ENABLED"] == "${CAMREC_HIK_ENABLED:-0}"
    assert backend["environment"]["CAMREC_HIK_BRIDGE_URL"] == "http://hik-bridge:8100"


def test_env_example_defaults_hik_support_off() -> None:
    env_example = _env_example()

    assert "CAMREC_HIK_ENABLED=0\nHIK_SDK_DIR=./hik-sdk-runtime" in env_example
