# Camera Recorder V1.0 Current Status

> This file is the current-state source of truth for V1.0 convergence. `ROADMAP.md` keeps historical planning context and may contain checkboxes that were completed by later PRs.

## Already completed in code

- Vue Router is the canonical frontend router.
- Pinia camera/runtime stores exist and are used by core workspaces.
- Camera deep links support `/cameras?camera_id=<id>` and open the exact device drawer without auto-starting preview.
- Activity -> Playback exact-event navigation exists with one-shot explicit-action autoplay semantics.
- Live / Playback / Recording Management do not start media on page entry.
- Home / Live / Activity / Playback / Cameras use the shared Protect visual system.
- Camera connectivity is separated from Recorder and Schedule state and is published through `/ws/status`.
- Motion Detection V2, realtime activity, event-bounded playback and event export are implemented.
- Alembic is initialized and the repository contains a real migration chain under `backend/migrations/versions`.
- Operations provides bounded log access, 20 MiB camera-log rotation with five backups, redacted configuration backup/restore, administrative audit records and `/metrics` Prometheus output.
- Upgrade, migration, backup and rollback guidance is documented in `docs/RELEASE.md`.

## V1.0 code-convergence work

The implementation plan is `docs/superpowers/plans/2026-09-15-v1-convergence.md`. All four code-convergence batches are implemented:

1. **Complete** — Frontend visual/quality freeze: Admin workspace convergence, reduced motion, lint gate, route/view code splitting.
2. **Complete** — Frontend routing/state convergence: upload/settings deep links, shared state/types, explicit playback communication, unsaved-settings protection.
3. **Complete** — Connectivity hardening: immediate first probe, persisted failure streak, manual-probe reconciliation, monitor observability and stale-recorder handling.
4. **Complete** — Operations foundations: safe logs and visible rotation policy, configuration backup/restore, high-value administrative audit trail, Prometheus metrics and release/upgrade documentation.

Code convergence being complete does **not** mean V1.0 has passed field acceptance or should automatically be tagged as a final release. The release checklist is in `docs/RELEASE.md`.

## External V1.0 acceptance gates

These require real cameras/browsers/storage and cannot be truthfully closed by CI alone:

- 10-camera 24h continuous recording test.
- 10-camera 72h continuous recording test.
- Network loss, camera reboot, RTSP jitter and FFmpeg-kill recovery tests.
- OpenList/WebDAV outage while local recording continues, followed by upload recovery.
- Disk critical protection test on a real recording volume.
- Chrome / Edge / Safari matrix for local/cloud H.264 and HEVC playback, seeking, cross-segment and cross-day continuation.

## Post-V1.0 feature track

- ONVIF discovery/device metadata/media profiles/events/PTZ capability.
- Event-only recording policy and trigger state machine.
- Low-FPS substream person detection when native smart events are unavailable.
- Configurable pre-record ring buffer and additional event types.
- Additional notification transports and optional inference acceleration.
