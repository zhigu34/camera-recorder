from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path


# Approximate file-level durations from CI #1163. The values are only used to
# balance independent runners; correctness never depends on them. New test files
# automatically participate with DEFAULT_WEIGHT_SECONDS until a useful duration
# is known.
DEFAULT_WEIGHT_SECONDS = 1.0
TEST_FILE_WEIGHTS_SECONDS: dict[str, float] = {
    "test_camera_batch.py": 8.2,
    "test_camera_connection_migration.py": 2.7,
    "test_camera_connection_phase1_upgrade.py": 2.8,
    "test_camera_deletion.py": 19.9,
    "test_camera_history_fk.py": 2.4,
    "test_camera_identity.py": 9.2,
    "test_email_notification_profile.py": 3.4,
    "test_event_detection_api.py": 23.7,
    "test_health.py": 5.5,
    "test_health_realtime_v3.py": 15.7,
    "test_health_reliability_v3.py": 10.2,
    "test_health_status.py": 35.8,
    "test_hik_camera_api.py": 15.8,
    "test_motion_activity_api.py": 10.2,
    "test_motion_api.py": 17.7,
    "test_notification_settings.py": 14.4,
    "test_onvif_camera_api.py": 14.5,
    "test_operations_foundation.py": 1.9,
    "test_recording_browser.py": 50.2,
    "test_recording_export_api.py": 76.3,
    "test_recording_export_history.py": 16.3,
    "test_recording_export_worker.py": 24.7,
    "test_recording_management.py": 16.3,
    "test_recording_navigation.py": 16.4,
    "test_recording_schedule.py": 28.0,
    "test_system_settings.py": 8.3,
    "test_upload_websocket.py": 8.9,
}


def partition_test_files(
    test_files: Sequence[str],
    *,
    shard_count: int,
    weights: Mapping[str, float] | None = None,
) -> list[list[str]]:
    if shard_count <= 0:
        raise ValueError("shard_count must be greater than zero")
    if len(set(test_files)) != len(test_files):
        raise ValueError("test_files must not contain duplicates")

    effective_weights = dict(TEST_FILE_WEIGHTS_SECONDS)
    if weights is not None:
        effective_weights.update(weights)

    ordered = sorted(
        test_files,
        key=lambda path: (-effective_weights.get(path, DEFAULT_WEIGHT_SECONDS), path),
    )
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    loads = [0.0 for _ in range(shard_count)]

    for path in ordered:
        shard_index = min(range(shard_count), key=lambda index: (loads[index], index))
        shards[shard_index].append(path)
        loads[shard_index] += effective_weights.get(path, DEFAULT_WEIGHT_SECONDS)

    for shard in shards:
        shard.sort()
    return shards


def pytest_paths_for_shard(
    test_files: Sequence[str],
    *,
    shard_count: int,
    shard_index: int,
) -> list[str]:
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be between zero and shard_count - 1")
    shards = partition_test_files(test_files, shard_count=shard_count)
    return [f"tests/{path}" for path in shards[shard_index]]


def _discover_test_files(tests_dir: Path) -> list[str]:
    return sorted(path.name for path in tests_dir.glob("test_*.py") if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="Select one balanced backend pytest shard")
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument(
        "--tests-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "tests",
    )
    args = parser.parse_args()

    test_files = _discover_test_files(args.tests_dir)
    paths = pytest_paths_for_shard(
        test_files,
        shard_count=args.shards,
        shard_index=args.index,
    )
    if not paths:
        parser.error(f"shard {args.index} is empty")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
