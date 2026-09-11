from __future__ import annotations

import argparse
import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Camera Recorder stability acceptance check")
    parser.add_argument("--hours", type=int, default=24, choices=range(1, 169), metavar="1-168")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="running backend base URL")
    parser.add_argument("--json", action="store_true", help="print raw JSON only")
    return parser


def _percent(value: object) -> str:
    return "-" if value is None else f"{float(value):.2f}%"


def _seconds(value: object) -> str:
    try:
        seconds = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remain = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remain:.0f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m"


def _fetch(base_url: str, hours: int) -> dict:
    url = f"{base_url.rstrip('/')}/api/health/stability?hours={hours}"
    with urlopen(url, timeout=15) as response:  # noqa: S310 - operator-controlled local URL
        return json.load(response)


def _print_report(report: dict) -> int:
    overall = report.get("overall", {})
    verdict = str(overall.get("verdict") or "collecting")
    verdict_label = {
        "pass": "PASS",
        "fail": "FAIL",
        "collecting": "COLLECTING",
    }.get(verdict, verdict.upper())

    print(f"Camera Recorder 稳定性验收：{report.get('hours', '-')}h  {verdict_label}")
    print("=" * 68)
    print(
        "监控摄像头: {monitored}  通过: {passed}  失败: {failed}  采集中: {collecting}".format(
            monitored=overall.get("monitored_cameras", 0),
            passed=overall.get("passed_cameras", 0),
            failed=overall.get("failed_cameras", 0),
            collecting=overall.get("collecting_cameras", 0),
        )
    )
    print(
        f"录像可用率: {_percent(overall.get('online_rate'))}  "
        f"录像完整率: {_percent(overall.get('recording_completeness'))}"
    )
    print(
        f"FFmpeg失败: {overall.get('ffmpeg_failures', 0)}  "
        f"连续失败: {overall.get('failure_streaks', 0)}  "
        f"断流: {overall.get('outage_count', 0)} 次  "
        f"最长: {_seconds(overall.get('longest_offline_seconds'))}"
    )

    rows = report.get("cameras") or []
    actionable = [row for row in rows if row.get("verdict") in {"fail", "collecting"}]
    if actionable:
        print("\n需要关注：")
        for row in actionable:
            reasons = ", ".join(row.get("reasons") or []) or "数据仍在采集"
            print(
                f"- [{str(row.get('verdict')).upper()}] {row.get('name')} ({row.get('ip')})  "
                f"覆盖率 {_percent(row.get('sample_coverage'))}  "
                f"录像可用率 {_percent(row.get('online_rate'))}  "
                f"完整率 {_percent(row.get('recording_completeness'))}  "
                f"最长断流 {_seconds(row.get('longest_offline_seconds'))}  "
                f"原因: {reasons}"
            )

    criteria = report.get("criteria") or {}
    print("\n验收线：")
    print(
        f"采样覆盖率 ≥ {criteria.get('min_sample_coverage', '-')}% · "
        f"录像可用率 ≥ {criteria.get('min_online_rate', '-')}% · "
        f"录像完整率 ≥ {criteria.get('min_recording_completeness', '-')}% · "
        f"最长断流 ≤ {criteria.get('max_longest_outage_seconds', '-')}s · "
        f"连续失败 ≤ {criteria.get('max_failure_streaks', '-')} · "
        f"FFmpeg失败 ≤ {criteria.get('max_ffmpeg_failures', '-')}"
    )

    if verdict == "pass":
        return 0
    if verdict == "fail":
        return 1
    return 2


def main() -> int:
    args = _parser().parse_args()
    try:
        report = _fetch(args.url, args.hours)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        print(f"无法读取稳定性报告: {exc}", file=sys.stderr)
        return 3

    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
        verdict = str((report.get("overall") or {}).get("verdict") or "collecting")
        return 0 if verdict == "pass" else 1 if verdict == "fail" else 2
    return _print_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
