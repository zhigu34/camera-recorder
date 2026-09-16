from __future__ import annotations

import importlib.util
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SHARD_SCRIPT = BACKEND_ROOT / "ci_test_shards.py"


def _load_shard_module():
    assert SHARD_SCRIPT.exists(), "backend/ci_test_shards.py must provide CI test partitioning"
    spec = importlib.util.spec_from_file_location("ci_test_shards", SHARD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_partition_is_deterministic_disjoint_and_complete() -> None:
    shard_module = _load_shard_module()
    test_files = sorted(path.name for path in (BACKEND_ROOT / "tests").glob("test_*.py"))

    first = shard_module.partition_test_files(test_files, shard_count=4)
    second = shard_module.partition_test_files(test_files, shard_count=4)

    assert first == second
    flattened = [path for shard in first for path in shard]
    assert sorted(flattened) == test_files
    assert len(flattened) == len(set(flattened))
    assert all(shard for shard in first)


def test_partition_balances_known_slow_files_by_weight() -> None:
    shard_module = _load_shard_module()
    test_files = [
        "test_recording_export_api.py",
        "test_recording_browser.py",
        "test_health_status.py",
        "test_recording_schedule.py",
        "test_event_detection_api.py",
        "test_camera_deletion.py",
        "test_fast_a.py",
        "test_fast_b.py",
        "test_fast_c.py",
        "test_fast_d.py",
    ]
    weights = {
        "test_recording_export_api.py": 76.0,
        "test_recording_browser.py": 50.0,
        "test_health_status.py": 36.0,
        "test_recording_schedule.py": 28.0,
        "test_event_detection_api.py": 24.0,
        "test_camera_deletion.py": 20.0,
    }

    shards = shard_module.partition_test_files(test_files, shard_count=4, weights=weights)
    loads = [sum(weights.get(path, 1.0) for path in shard) for shard in shards]

    assert max(loads) - min(loads) <= 25.0


def test_shard_paths_are_pytest_ready() -> None:
    shard_module = _load_shard_module()

    paths = shard_module.pytest_paths_for_shard(
        ["test_beta.py", "test_alpha.py", "test_gamma.py"],
        shard_count=2,
        shard_index=0,
    )

    assert paths
    assert all(path.startswith("tests/") for path in paths)
