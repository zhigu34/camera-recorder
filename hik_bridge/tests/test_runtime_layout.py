from pathlib import Path

from hik_bridge.sdk import _component_directory, _find_runtime_library


def test_component_directory_points_at_hcnetsdkcom(tmp_path: Path) -> None:
    component_dir = tmp_path / "HCNetSDKCom"
    component_dir.mkdir()
    assert _component_directory(tmp_path) == component_dir


def test_runtime_library_discovery_accepts_vendor_openssl_versions(tmp_path: Path) -> None:
    component_dir = tmp_path / "HCNetSDKCom"
    component_dir.mkdir()
    crypto = component_dir / "libcrypto.so.1.1"
    ssl = tmp_path / "libssl.so.3"
    crypto.write_bytes(b"crypto")
    ssl.write_bytes(b"ssl")

    assert _find_runtime_library(tmp_path, "libcrypto.so") == crypto
    assert _find_runtime_library(tmp_path, "libssl.so") == ssl
