from datetime import datetime, timedelta, timezone

from app.models.camera import Camera


def test_recording_runtime_is_immediate_online_signal() -> None:
    from app.services.camera_connectivity_monitor import resolve_connectivity_observation

    result = resolve_connectivity_observation(
        previous_status="offline",
        recorder_state="RECORDING",
        recorder_pid=1234,
        probe_ok=None,
        previous_failures=2,
    )

    assert result.status == "online"
    assert result.consecutive_failures == 0
    assert result.source == "recorder"


def test_rtsp_failures_need_three_consecutive_misses() -> None:
    from app.services.camera_connectivity_monitor import resolve_connectivity_observation

    first = resolve_connectivity_observation(
        previous_status="online",
        recorder_state="STOPPED",
        recorder_pid=None,
        probe_ok=False,
        previous_failures=0,
    )
    second = resolve_connectivity_observation(
        previous_status=first.status,
        recorder_state="STOPPED",
        recorder_pid=None,
        probe_ok=False,
        previous_failures=first.consecutive_failures,
    )
    third = resolve_connectivity_observation(
        previous_status=second.status,
        recorder_state="STOPPED",
        recorder_pid=None,
        probe_ok=False,
        previous_failures=second.consecutive_failures,
    )

    assert first.status == "online"
    assert second.status == "online"
    assert third.status == "offline"
    assert third.consecutive_failures == 3
    assert third.source == "rtsp"


def test_single_rtsp_success_recovers_offline_camera() -> None:
    from app.services.camera_connectivity_monitor import resolve_connectivity_observation

    result = resolve_connectivity_observation(
        previous_status="offline",
        recorder_state="STOPPED",
        recorder_pid=None,
        probe_ok=True,
        previous_failures=3,
    )

    assert result.status == "online"
    assert result.consecutive_failures == 0
    assert result.source == "rtsp"


def test_stale_persisted_online_state_becomes_unknown() -> None:
    stale = datetime.now(timezone.utc) - timedelta(seconds=90)
    camera = Camera(
        name="stale-connectivity",
        ip="192.0.2.10",
        password_encrypted="unused",
        status="online",
        last_probe_at=stale,
        last_online_at=stale,
    )

    assert camera.connectivity_status == "unknown"
