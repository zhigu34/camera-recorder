import importlib
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _exports():
    name = "app.services.recording_export"
    assert importlib.util.find_spec(name) is not None, "recording export analysis is not implemented"
    return importlib.import_module(name)


def dt(minute: int, second: int = 0):
    return datetime(2026, 9, 14, 10, minute, second, tzinfo=timezone.utc)


def source(module, recording_id: int, start, end, *, available=True):
    return module.ExportSourceSlice(
        recording_id=recording_id,
        started_at=start,
        ended_at=end,
        path=Path(f"/recordings/{recording_id}.mp4"),
        available=available,
    )


def test_contiguous_sources_form_one_group_with_one_second_tolerance():
    module = _exports()
    request_start = dt(0)
    request_end = dt(15)
    slices = [
        source(module, 1, dt(0), dt(5)),
        source(module, 2, dt(5, 1), dt(10)),
        source(module, 3, dt(10), dt(15)),
    ]

    analysis = module.analyze_source_slices(slices, request_start, request_end)

    assert len(analysis.groups) == 1
    assert analysis.groups[0].recording_ids == [1, 2, 3]
    assert analysis.gaps == []
    assert analysis.covered_duration == 15 * 60


def test_real_gap_splits_groups_and_reports_exact_interval():
    module = _exports()
    slices = [
        source(module, 1, dt(0), dt(5)),
        source(module, 2, dt(5, 3), dt(10)),
    ]

    analysis = module.analyze_source_slices(slices, dt(0), dt(10))

    assert len(analysis.groups) == 2
    assert [(gap.start_at, gap.end_at) for gap in analysis.gaps] == [(dt(5), dt(5, 3))]
    assert analysis.covered_duration == (5 * 60) + (4 * 60 + 57)


def test_leading_and_trailing_uncovered_time_are_gaps():
    module = _exports()
    slices = [source(module, 1, dt(2), dt(8))]

    analysis = module.analyze_source_slices(slices, dt(0), dt(10))

    assert [(gap.start_at, gap.end_at) for gap in analysis.gaps] == [
        (dt(0), dt(2)),
        (dt(8), dt(10)),
    ]
    assert analysis.requested_duration == 10 * 60
    assert analysis.covered_duration == 6 * 60


def test_overlapping_sources_do_not_double_count_coverage():
    module = _exports()
    slices = [
        source(module, 1, dt(0), dt(6)),
        source(module, 2, dt(5), dt(10)),
    ]

    analysis = module.analyze_source_slices(slices, dt(0), dt(10))

    assert len(analysis.groups) == 1
    assert analysis.covered_duration == 10 * 60
    assert analysis.gaps == []


def test_missing_local_source_is_unavailable_and_does_not_bridge_groups():
    module = _exports()
    slices = [
        source(module, 1, dt(0), dt(5)),
        source(module, 2, dt(5), dt(10), available=False),
        source(module, 3, dt(10), dt(15)),
    ]

    analysis = module.analyze_source_slices(slices, dt(0), dt(15))

    assert analysis.unavailable_count == 1
    assert [(item.start_at, item.end_at) for item in analysis.unavailable_intervals] == [
        (dt(5), dt(10))
    ]
    assert [(gap.start_at, gap.end_at) for gap in analysis.gaps] == [(dt(5), dt(10))]
    assert [group.recording_ids for group in analysis.groups] == [[1], [3]]
    assert analysis.covered_duration == 10 * 60


def test_clips_sources_to_requested_bounds():
    module = _exports()
    slices = [
        source(module, 1, dt(0), dt(10)),
    ]
    start = dt(2)
    end = dt(8)

    analysis = module.analyze_source_slices(slices, start, end)

    assert analysis.groups[0].start_at == start
    assert analysis.groups[0].end_at == end
    assert analysis.covered_duration == 6 * 60
    assert analysis.gaps == []
