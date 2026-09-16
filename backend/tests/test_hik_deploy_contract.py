from pathlib import Path


def test_deploy_tracks_hik_bridge_and_private_runtime_changes() -> None:
    script = (Path(__file__).resolve().parents[2] / "deploy.sh").read_text(encoding="utf-8")

    assert "UPDATE_HIK" in script
    assert "hik_sdk_hash=" in script
    assert "UPDATE_SERVICES+=(hik-bridge)" in script
    assert "camera-recorder-hik-bridge" in script
    assert "libhcnetsdk.so" in script
    assert "HCNetSDKCom" in script
    assert "--force-recreate" in script


def test_deploy_classifies_hik_runtime_paths_without_full_deploy() -> None:
    script = (Path(__file__).resolve().parents[2] / "deploy.sh").read_text(encoding="utf-8")

    assert "hik-sdk-runtime/.gitkeep) ;;" in script
    assert "hik-sdk-runtime/*) UPDATE_HIK=1 ;;" in script
