from app.services.recording_schedule_manager import RecordingScheduleManager


def test_recording_owner_reports_manual_and_schedule_ownership() -> None:
    manager = RecordingScheduleManager()

    assert manager.recording_owner(1) is None

    manager._manual_running.add(1)
    assert manager.recording_owner(1) == "manual"

    manager._manual_running.clear()
    manager._managed.add(1)
    assert manager.recording_owner(1) == "schedule"


def test_detach_for_runtime_reload_only_detaches_target_schedule_runtime_state() -> None:
    manager = RecordingScheduleManager()
    manager._managed.add(1)
    manager._manual_running.add(2)
    manager._manual_paused.add(3)
    manager._camera_status[1] = {"camera_id": 1, "mode": "automatic"}
    manager._camera_status[2] = {"camera_id": 2, "mode": "manual"}

    manager.detach_for_runtime_reload(1)

    assert 1 not in manager._managed
    assert 1 not in manager._camera_status
    assert 2 in manager._manual_running
    assert 2 in manager._camera_status
    assert 3 in manager._manual_paused
