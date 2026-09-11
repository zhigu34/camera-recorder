from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

_MAX_SAMPLES = 500
_LATENCY_EVENTS = {"decode_ready", "first_frame"}
_FINAL_EVENTS = {"first_frame", "startup_error"}


class PlaybackClientMetrics:
    """Keep a bounded in-memory view of real browser playback outcomes.

    Client events are intentionally ephemeral: no user agent string, IP address,
    token, or media URL is persisted. Only coarse browser/platform labels and
    playback dimensions are kept for compatibility and startup-latency tuning.
    """

    def __init__(self) -> None:
        self._samples: deque[dict[str, Any]] = deque(maxlen=_MAX_SAMPLES)

    def record(self, sample: dict[str, Any]) -> None:
        self._samples.append(dict(sample))

    @staticmethod
    def _latency_summary(values: list[float]) -> dict[str, float | int | None]:
        if not values:
            return {"samples": 0, "avg_ms": None, "p95_ms": None, "max_ms": None}
        ordered = sorted(values)
        p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
        return {
            "samples": len(ordered),
            "avg_ms": round(sum(ordered) / len(ordered), 2),
            "p95_ms": round(ordered[p95_index], 2),
            "max_ms": round(ordered[-1], 2),
        }

    def snapshot(self) -> dict[str, Any]:
        samples = list(self._samples)
        events: dict[str, dict[str, Any]] = {}
        for event in ("decode_ready", "first_frame", "startup_error", "playback_error"):
            event_samples = [sample for sample in samples if sample.get("event") == event]
            payload: dict[str, Any] = {"count": len(event_samples)}
            if event in _LATENCY_EVENTS:
                payload.update(
                    self._latency_summary(
                        [
                            float(sample["duration_ms"])
                            for sample in event_samples
                            if isinstance(sample.get("duration_ms"), (int, float))
                        ]
                    )
                )
            events[event] = payload

        grouped: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "successful_starts": 0,
                "startup_errors": 0,
                "first_frame_ms": [],
                "frame_signals": defaultdict(int),
                "hevc_hints": defaultdict(int),
            }
        )
        for sample in samples:
            event = str(sample.get("event") or "")
            if event not in _FINAL_EVENTS:
                continue
            key = (
                str(sample.get("browser") or "unknown"),
                str(sample.get("browser_version") or "unknown"),
                str(sample.get("platform") or "unknown"),
                str(sample.get("codec") or "unknown"),
                str(sample.get("playback_mode") or "unknown"),
                str(sample.get("source_kind") or "unknown"),
            )
            item = grouped[key]
            if event == "first_frame":
                item["successful_starts"] += 1
                if isinstance(sample.get("duration_ms"), (int, float)):
                    item["first_frame_ms"].append(float(sample["duration_ms"]))
                item["frame_signals"][str(sample.get("signal") or "unknown")] += 1
                item["hevc_hints"][str(sample.get("hevc_hint") or "unknown")] += 1
            elif event == "startup_error":
                item["startup_errors"] += 1
                item["hevc_hints"][str(sample.get("hevc_hint") or "unknown")] += 1

        compatibility = []
        for key, item in grouped.items():
            successes = int(item["successful_starts"])
            failures = int(item["startup_errors"])
            attempts = successes + failures
            compatibility.append(
                {
                    "browser": key[0],
                    "browser_version": key[1],
                    "platform": key[2],
                    "codec": key[3],
                    "playback_mode": key[4],
                    "source_kind": key[5],
                    "attempts": attempts,
                    "successful_starts": successes,
                    "startup_errors": failures,
                    "success_rate": round(successes / attempts * 100, 2) if attempts else None,
                    "first_frame": self._latency_summary(item["first_frame_ms"]),
                    "frame_signals": dict(item["frame_signals"]),
                    "hevc_hints": dict(item["hevc_hints"]),
                }
            )
        compatibility.sort(
            key=lambda item: (
                -item["attempts"],
                item["browser"],
                item["browser_version"],
                item["codec"],
            )
        )

        return {
            "sample_count": len(samples),
            "sample_limit": _MAX_SAMPLES,
            "events": events,
            "compatibility": compatibility,
        }

    def reset_for_tests(self) -> None:
        self._samples.clear()


playback_client_metrics = PlaybackClientMetrics()
