# Recording Range Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users export a selected playback wall-clock range into one MP4, multiple MP4s, or an optional uncompressed ZIP while preserving gaps as explicit metadata and keeping original recordings untouched.

**Architecture:** Add a dedicated export persistence layer (`ExportJob` / `ExportArtifact`), a pure range-analysis layer, and an application-local asynchronous export manager. Export work is built from local finalized `Recording.mp4_path` files only. Each continuous wall-clock group is trimmed independently, then `merge` optionally concatenates those group outputs so gap offsets never corrupt boundary calculations. Export files live under `settings.data_dir / "exports"`; original recordings and the emergency recording cleanup service remain isolated.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite, asyncio subprocess, FFmpeg/ffprobe, Python `zipfile`, Vue 3, TypeScript, Axios, Element Plus, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-14-range-export-design.md`

## Global Constraints

- Existing recording capture/finalization stays unchanged: finalized source assets remain MP4 rows in `recordings`.
- Export never writes, renames, deletes, or mutates original `Recording.mp4_path` files.
- V1 exports local finalized MP4s only. A recording whose database row exists but whose local MP4 has already been cleaned is unavailable for export; cloud-direct merge/download is out of scope.
- Missing local source coverage must be surfaced as an unavailable/gap interval, never silently treated as covered.
- Gap tolerance defaults to 1 second to absorb container timestamp noise.
- `gap_policy=merge` always produces one MP4 and requires `package_mode=individual`.
- `gap_policy=split` produces one MP4 per continuous group; `package_mode=zip` is optional and uses `ZIP_STORED`.
- `fast` uses stream copy and may land near keyframes. It must never silently fall back to full transcode.
- `exact` may re-encode to produce stable boundaries and must be clearly higher CPU cost.
- Export duration is limited to 24 hours per request.
- Export outputs expire after 24 hours in V1; expiry cleanup is owned by the export manager, not `storage_cleanup_manager`.
- All output paths are server-generated and containment-checked below the export root.
- Export APIs and range-selection UI must not auto-start playback.

---

### Task 1: Export persistence and schema contracts

**Files:**
- Create: `backend/app/models/recording_export.py`
- Create: `backend/app/schemas/recording_export.py`
- Create: `backend/migrations/versions/20260914_0014_recording_exports.py`
- Create: `backend/tests/test_recording_export_models.py`
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- `ExportJob` fields: camera FK, requested start/end, export mode, gap policy, package mode, status, progress, gap count, requested/covered duration, error, lifecycle timestamps, expiry.
- `ExportArtifact` fields: job FK, kind (`mp4|zip|manifest`), segment index, optional real start/end, path, size, created timestamp.
- Pydantic request/response types for range analysis, job creation, job status, gaps/groups, and artifacts.

- [ ] Write failing tests asserting request validation: timezone-aware datetimes, `end > start`, maximum 24 hours, enum values, and `merge + zip` rejection.
- [ ] Write failing tests for SQLAlchemy defaults/relationships and cascade behavior.
- [ ] Verify the new tests are RED because export models/schemas do not exist.
- [ ] Implement the two models, relationships, enums-as-strings, and Pydantic contracts.
- [ ] Export the models from `app.models` so Alembic metadata discovers them.
- [ ] Add migration `20260914_0014` with `down_revision="20260913_0013"`, indexes on `camera_id`, `status`, `expires_at`, and `export_job_id`.
- [ ] Run focused backend tests and verify GREEN.

### Task 2: Pure range analysis and gap grouping

**Files:**
- Create: `backend/app/services/recording_export.py`
- Create: `backend/tests/test_recording_export_analysis.py`

**Interfaces:**
- `analyze_recording_range(session, camera_id, start_at, end_at, gap_tolerance_seconds=1.0)`.
- Internal immutable structures representing source slices, continuous groups, gaps, and unavailable intervals.
- Analysis response includes `recording_count`, `continuous_groups`, `gaps`, `unavailable_count`, `requested_duration`, and `covered_duration`.

**Behavior:**
- Query rows where `started_at < requested_end` and `ended_at > requested_start`, ordered by start/id.
- Clip each row to the requested bounds.
- A row only contributes playable export coverage if `Path(recording.mp4_path)` exists and is a regular non-empty file.
- Missing-local rows are reported as unavailable and do not bridge two continuous groups.
- Overlaps are merged; adjacent clips separated by at most 1 second remain one group.
- Leading/trailing uncovered time inside the requested range is also reported as a gap.

- [ ] Write failing tests for no rows, one row, overlapping rows, exact adjacency, <=1s tolerance, >1s gaps, leading/trailing gaps, multiple gaps, and missing-local rows.
- [ ] Verify RED before implementing analysis.
- [ ] Implement only pure grouping/query logic; do not invoke FFmpeg in this task.
- [ ] Verify all focused analysis tests GREEN.

### Task 3: Safe group export command construction

**Files:**
- Modify: `backend/app/services/recording_export.py`
- Create: `backend/tests/test_recording_export_ffmpeg.py`

**Interfaces:**
- `build_concat_file(...)` with safe FFmpeg concat escaping.
- `build_fast_group_command(...)` producing a trimmed stream-copy MP4 for one continuous group.
- `build_exact_group_command(...)` producing an exact-boundary compatibility MP4 for one continuous group.
- `build_merge_groups_command(...)` concatenating already-trimmed group MP4 outputs.

**Key rule:** Never concatenate all raw source slices first and then apply one wall-clock offset across a gap. Each continuous group is independently trimmed relative to that group's first source timestamp; only completed group files are concatenated for `gap_policy=merge`.

- [ ] Write failing command tests for first-slice offset, last-slice end trim, HEVC stream-copy preservation, paths containing spaces/quotes, and group-merge concat.
- [ ] Verify RED.
- [ ] Implement fast commands with `-c copy`, generated timestamps/negative-ts protection where needed, and atomic `.part.mp4` targets.
- [ ] Implement exact commands with deterministic video/audio output suitable for browser download; keep this mode explicitly separate from fast mode.
- [ ] Ensure subprocess errors include a bounded stderr tail and delete incomplete `.part` files.
- [ ] Verify command tests GREEN.

### Task 4: Export worker, artifacts, split/merge and ZIP

**Files:**
- Modify: `backend/app/services/recording_export.py`
- Create: `backend/tests/test_recording_export_worker.py`

**Interfaces:**
- `RecordingExportManager.start()`, `.stop()`, `.enqueue(job_id)`, `.status()`.
- `recording_export_manager` singleton.
- Job directory: `settings.data_dir / "exports" / f"camera-{camera_id}" / YYYY-MM-DD / f"export-{job_id}"`.

**Execution:**
1. Re-analyze the request immediately before processing so deleted/missing source files cannot be hidden by stale analysis.
2. Mark `processing`; persist gap/coverage metadata.
3. Render one MP4 per continuous group into a job-local work area.
4. For `merge`, concatenate group outputs into one final MP4 without inserting black frames.
5. For `split + individual`, keep group MP4s as downloadable artifacts.
6. For `split + zip`, generate `export-info.json`, create a `ZIP_STORED` archive, and expose the ZIP as the primary download artifact. Group MP4 artifacts may remain internal or be marked consistently so API output is unambiguous.
7. Commit artifacts only after successful atomic rename, then mark job `ready`.
8. On error, mark `failed`, persist a bounded error string, and remove temporary files.

- [ ] Write failing worker tests using mocked subprocess execution for status transitions, merge, split, ZIP store mode, manifest content, and cleanup after failure.
- [ ] Verify RED.
- [ ] Implement one-worker-at-a-time concurrency for V1 to avoid unbounded disk/CPU pressure.
- [ ] On startup, convert stale `processing` jobs from a prior process into `failed` with a restart explanation; enqueue still-valid `pending` jobs.
- [ ] Add expiry scanning: delete only paths contained under export root, then mark jobs `expired`; never inspect/delete original recording files.
- [ ] Verify worker tests GREEN.

### Task 5: Export API and download isolation

**Files:**
- Create: `backend/app/api/exports.py`
- Create: `backend/tests/test_recording_export_api.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- `POST /api/exports/analyze`
- `POST /api/exports`
- `GET /api/exports/{job_id}`
- `GET /api/exports/{job_id}/artifacts`
- `GET /api/exports/{job_id}/artifacts/{artifact_id}/download`

**Lifecycle integration:**
- Ensure `settings.data_dir / "exports"` exists during startup.
- Start export manager after database initialization/background recorder primitives are safe.
- Stop export manager during shutdown before database close.
- Register `exports_router` in FastAPI.

- [ ] Write failing API tests for analyze shape, nonexistent camera, no local coverage, timezone validation, max duration, `merge+zip` rejection, successful job creation/enqueue, status retrieval, artifact ownership, expired artifact, and path-containment denial.
- [ ] Verify RED.
- [ ] Implement endpoints with database ownership checks and `FileResponse` downloads.
- [ ] Return a clear `409` when analysis contains zero locally exportable coverage.
- [ ] Do not accept any filesystem path from the client.
- [ ] Verify API tests GREEN.

### Task 6: Frontend export contracts and confirmation workflow

**Files:**
- Create: `frontend/src/types/exports.ts`
- Create: `frontend/src/utils/playbackExport.ts`
- Create: `frontend/src/playbackExport.test.ts`
- Modify: `frontend/src/PlaybackWorkspace.vue`

**Dependencies:** Playback timeline range-selection contract from `2026-09-14-playback-timeline-interaction.md`.

**Interfaces:**
- `ExportRange` in wall-clock seconds for the selected date.
- Utilities convert selected date + wall-clock seconds into timezone-compatible local ISO values without inventing UTC shifts.
- UI state: `rangeSelectEnabled`, `exportRange`, `analysis`, `exportMode`, `gapPolicy`, `packageMode`, `activeExportJob`.

- [ ] Write failing utility tests for default range creation, day-boundary clamping, request payload construction, and option visibility (`zip` only for split with gaps).
- [ ] Verify RED.
- [ ] Add “导出片段” next to playback actions; clicking it enters range mode only and does not call `PlaybackPlayer.open/play`.
- [ ] Default range starts at current wall-clock cursor and ends at `+5min` clamped to day end; if no active time, use the first recording start when available.
- [ ] “继续/分析” calls `/api/exports/analyze`; present count, coverage, and each gap/unavailable interval.
- [ ] Defaults: `fast`, `merge`; if split selected, default `individual`; show `zip` only under split.
- [ ] Create the ExportJob only after explicit confirmation.
- [ ] Verify frontend focused tests GREEN.

### Task 7: Export progress, artifacts and expiry UI

**Files:**
- Modify: `frontend/src/PlaybackWorkspace.vue`
- Create: `frontend/src/playbackExportUiSemantics.test.ts`

**Interfaces:**
- Poll `GET /api/exports/{id}` only while status is `pending|processing`.
- On `ready`, fetch artifacts and show one or more download actions.
- Single/merge: one MP4 action.
- Split individual: one action per MP4 with real start/end.
- Split ZIP: one ZIP action.

- [ ] Write failing semantic tests proving no polling when idle/ready, no auto-play side effect, and correct download shape for each package mode.
- [ ] Implement compact job progress UI in playback workspace; no separate history page in V1.
- [ ] Stop timers on completion, failure, expiry, camera/date change, and unmount.
- [ ] Show failed/expired states clearly without mutating the selected playback context.
- [ ] Verify frontend tests/build GREEN.

### Task 8: Full verification and integration review

**Files:**
- Modify only if verification exposes a defect.

- [ ] Run backend compileall and full pytest.
- [ ] Run frontend full Vitest suite and `npm run build`.
- [ ] Run Docker smoke through the existing CI workflow.
- [ ] Verify startup migration from revision `20260913_0013` to the new head.
- [ ] Verify `/health` remains healthy with no export jobs.
- [ ] Verify source MP4 files are byte-for-byte untouched after successful and failed exports.
- [ ] Verify 24h expiry removes only export artifacts.
- [ ] Review PR diff for accidental playback auto-start, recording-storage changes, or deployment changes.
- [ ] Merge only after all PR CI jobs are green; then verify main CI.
