from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _compose_config() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _deploy_script() -> str:
    return (ROOT / "deploy.sh").read_text(encoding="utf-8")


def _env_example() -> str:
    return (ROOT / ".env.example").read_text(encoding="utf-8")


def test_deploy_tracks_optional_hik_runtime_and_profile_stage() -> None:
    script = _deploy_script()

    assert "UPDATE_HIK" in script
    assert "hik_sdk_hash=" in script
    assert 'HIK_COMPOSE=(docker compose --env-file "$ENV_FILE" --profile hik)' in script
    assert '"${HIK_COMPOSE[@]}" up -d --no-deps --force-recreate hik-bridge' in script
    assert '"${HIK_COMPOSE[@]}" rm -sf hik-bridge' in script
    assert "camera-recorder-hik-bridge" in script
    assert "libhcnetsdk.so" in script
    assert "HCNetSDKCom" in script


def test_deploy_defaults_and_validates_hik_enable_flag() -> None:
    script = _deploy_script()

    assert "ensure_env_key CAMREC_HIK_ENABLED 0" in script
    assert 'case "$HIK_ENABLED" in' in script
    assert "0|1) ;;" in script
    assert "CAMREC_HIK_ENABLED 仅支持 0 或 1" in script
    assert 'CURRENT_HIK_SDK_HASH="disabled"' in script
    assert "hik_enabled=$HIK_ENABLED" in script


def test_deploy_classifies_hik_runtime_only_when_enabled() -> None:
    script = _deploy_script()

    assert "hik-sdk-runtime/.gitkeep) ;;" in script
    assert "hik-sdk-runtime/*) mark_hik_if_enabled ;;" in script
    assert "backend/Dockerfile|backend/pyproject.toml|backend/uv.lock" in script
    assert "hik_bridge/*) BUILD_BACKEND=1; mark_hik_if_enabled ;;" in script


def test_deploy_keeps_hik_out_of_core_update_stage() -> None:
    script = _deploy_script()
    core_start = script.index("CORE_UPDATE_SERVICES=()")
    hik_stage = script.index('if [ "$HIK_ENABLED" = "0" ]; then', core_start)
    core_section = script[core_start:hik_stage]

    assert "CORE_UPDATE_SERVICES+=(backend)" in core_section
    assert "CORE_UPDATE_SERVICES+=(frontend)" in core_section
    assert "CORE_UPDATE_SERVICES+=(openlist)" in core_section
    assert "hik-bridge" not in core_section
    assert "核心 docker compose up" in core_section


def test_disabled_hik_path_does_not_hash_sdk_runtime() -> None:
    script = _deploy_script()
    disabled_branch = script.index('if [ "$HIK_ENABLED" = "1" ]; then\n    CURRENT_HIK_SDK_HASH="$(hik_sdk_hash')
    disabled_assignment = script.index('CURRENT_HIK_SDK_HASH="disabled"', disabled_branch)

    assert disabled_assignment > disabled_branch
    assert 'HIK SDK 支持已关闭（CAMREC_HIK_ENABLED=0），跳过 SDK runtime 检查' in script


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
