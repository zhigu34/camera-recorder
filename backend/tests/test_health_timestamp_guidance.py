from app.api.health import _timestamp_guidance


def test_timestamp_guidance_stays_quiet_below_threshold():
    assert _timestamp_guidance("native", 4) is None


def test_timestamp_guidance_moves_native_to_wallclock():
    guidance = _timestamp_guidance("native", 5)
    assert guidance is not None
    assert guidance["suggested_mode"] == "wallclock"


def test_timestamp_guidance_moves_wallclock_to_reconstruct():
    guidance = _timestamp_guidance("wallclock", 8)
    assert guidance is not None
    assert guidance["suggested_mode"] == "reconstruct"


def test_timestamp_guidance_does_not_auto_escalate_reconstruct():
    guidance = _timestamp_guidance("reconstruct", 12)
    assert guidance is not None
    assert guidance["suggested_mode"] is None
