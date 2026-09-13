import importlib
import importlib.util
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError


def _load_contracts():
    schema_name = "app.schemas.recording_export"
    model_name = "app.models.recording_export"
    assert importlib.util.find_spec(schema_name) is not None, "recording export schemas are not implemented"
    assert importlib.util.find_spec(model_name) is not None, "recording export models are not implemented"
    return importlib.import_module(schema_name), importlib.import_module(model_name)


def test_export_create_defaults_and_validates_options():
    schemas, _ = _load_contracts()
    start = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    payload = schemas.ExportCreateRequest(
        camera_id=7,
        start_at=start,
        end_at=start + timedelta(minutes=15),
    )

    assert payload.export_mode == "fast"
    assert payload.gap_policy == "merge"
    assert payload.package_mode == "individual"

    with pytest.raises(ValidationError):
        schemas.ExportCreateRequest(
            camera_id=7,
            start_at=start,
            end_at=start + timedelta(minutes=15),
            gap_policy="merge",
            package_mode="zip",
        )


def test_export_range_requires_timezone_order_and_24_hour_limit():
    schemas, _ = _load_contracts()
    aware = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

    for start_at, end_at in [
        (aware.replace(tzinfo=None), aware + timedelta(minutes=1)),
        (aware, aware),
        (aware, aware - timedelta(seconds=1)),
        (aware, aware + timedelta(hours=24, seconds=1)),
    ]:
        with pytest.raises(ValidationError):
            schemas.ExportRangeRequest(camera_id=3, start_at=start_at, end_at=end_at)

    valid = schemas.ExportRangeRequest(
        camera_id=3,
        start_at=aware,
        end_at=aware + timedelta(hours=24),
    )
    assert valid.camera_id == 3


def test_export_models_expose_expected_persistence_shape():
    _, models = _load_contracts()
    job_columns = models.ExportJob.__table__.columns
    artifact_columns = models.ExportArtifact.__table__.columns

    assert {
        "id",
        "camera_id",
        "requested_start_at",
        "requested_end_at",
        "export_mode",
        "gap_policy",
        "package_mode",
        "status",
        "progress",
        "gap_count",
        "requested_duration",
        "covered_duration",
        "error_message",
        "created_at",
        "started_at",
        "completed_at",
        "expires_at",
    }.issubset(job_columns.keys())
    assert {
        "id",
        "export_job_id",
        "kind",
        "segment_index",
        "start_at",
        "end_at",
        "path",
        "file_size",
        "created_at",
    }.issubset(artifact_columns.keys())

    assert models.ExportJob.__mapper__.relationships["artifacts"].cascade.delete_orphan
