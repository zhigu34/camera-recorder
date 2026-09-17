from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("relative_path", "forbidden_writers"),
    [
        (
            "app/api/onvif_cameras.py",
            ("upsert_onvif_connection", "switch_to_onvif_connection"),
        ),
        (
            "app/api/hik_cameras.py",
            ("upsert_hik_connection", "switch_to_hik_connection"),
        ),
    ],
)
def test_legacy_adapter_routes_delegate_persistence_to_unified_mutation(
    relative_path: str,
    forbidden_writers: tuple[str, ...],
) -> None:
    source = (Path(__file__).parents[1] / relative_path).read_text(encoding="utf-8")

    assert "create_unified_camera" in source
    assert "update_unified_camera" in source
    for writer in forbidden_writers:
        assert writer not in source

    assert "await db.commit()" not in source
    assert ".stop_all(" not in source
    assert ".restore(" not in source
