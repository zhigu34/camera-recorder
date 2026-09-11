from app.cli.stability_check import _effective_verdict


def _report(verdict: str, hours: int = 24) -> dict:
    return {"hours": hours, "overall": {"verdict": verdict}}


def test_acceptance_requires_current_process_uptime() -> None:
    assert _effective_verdict(_report("pass"), 23 * 3600, False) == "collecting"
    assert _effective_verdict(_report("pass"), 24 * 3600, False) == "pass"


def test_known_failure_is_not_hidden_by_short_uptime() -> None:
    assert _effective_verdict(_report("fail"), 60, False) == "fail"
    assert _effective_verdict(_report("pass"), 60, True) == "pass"
