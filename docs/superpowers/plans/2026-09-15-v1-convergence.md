# Camera Recorder V1 Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the four agreed V1.0 convergence batches: frontend visual/quality freeze, frontend routing/state cleanup, connectivity monitor hardening, and operations foundations.

**Architecture:** Keep every batch independently mergeable. Frontend work must preserve the explicit-media-start contract; backend monitor work extends the existing lightweight connectivity monitor instead of replacing Recorder ownership; operations work uses bounded APIs and existing event/audit patterns rather than introducing an external platform dependency.

**Tech Stack:** Vue 3 + TypeScript + Pinia + Vue Router + Element Plus + Vite/Vitest; FastAPI + SQLAlchemy + SQLite/Alembic + asyncio; Docker Compose; GitHub Actions.

**Spec:** User-approved four-batch scope in the project conversation on 2026-09-15.

## Global Constraints

- Entering Live, Playback, Recording Management, or camera detail must never start media automatically.
- Video remains uncropped (`object-fit: contain`) and playback keeps the established strict 16:9 contract.
- Use `git pull && ./deploy.sh` as the deployment workflow.
- Each batch is a bounded PR with fresh CI and final diff review before merge.
- Pure UI work must not add brittle CSS-internal tests or deliberate RED CI.
- Backend behavior changes use RED -> GREEN tests.

---

### Task 1: Frontend visual and quality freeze

**Files:**
- Modify: `frontend/src/main.ts`, `frontend/src/router.ts`, selected workspace styles/views, `frontend/package.json`, `.github/workflows/ci.yml`, `docs/ROADMAP.md`
- Create as needed: shared final visual layer / quality config files

**Interfaces:**
- Consumes: existing `--nvr-*` tokens and Protect workspace rules.
- Produces: one documented style ownership order, lazy-loaded route/workspace modules, frontend lint script, synchronized roadmap.

- [ ] Inventory current global CSS imports and remove rules/files that are provably superseded without changing visible behavior.
- [ ] Apply the same compact Protect control/surface language to Uploads, Health, Recording Schedule, and Settings.
- [ ] Add shared reduced-motion/loading/empty/error treatment and narrow-screen finish without touching media sizing.
- [ ] Add ESLint for Vue/TypeScript and wire `npm run lint` into frontend CI.
- [ ] Lazy-load route/workspace views so the main JS chunk is materially smaller.
- [ ] Update ROADMAP items that are already implemented and document the remaining V1.0 gates.
- [ ] Run `npm test`, `npm run lint`, and `npm run build`; expect all tests pass and production build succeeds.

### Task 2: Frontend routing and state convergence

**Files:**
- Modify: `frontend/src/UploadManagementView.vue`, `frontend/src/SystemSettingsWorkspace.vue`, `frontend/src/router.ts`, relevant stores/playback components/tests.
- Create: shared frontend API types / navigation helpers only where they remove actual duplication.

**Interfaces:**
- Produces: `/uploads?task_id=<id>`, `/settings?section=archive`, exact entity navigation, shared types/state paths, explicit store/prop channels replacing global playback CustomEvents where feasible.

- [ ] Write behavior tests for upload task deep link and archive settings deep link; verify RED.
- [ ] Implement route-query synchronization without triggering media.
- [ ] Reuse camera/runtime stores in pages that redundantly fetch shared camera/runtime state when behavior is equivalent.
- [ ] Extract shared API types used by multiple pages.
- [ ] Replace remaining playback window/document CustomEvent state transport with explicit component/store communication where bounded by this PR.
- [ ] Add settings dirty-state route-leave protection for unsaved editable sections.
- [ ] Run focused tests, full `npm test`, lint, and build; expect GREEN.

### Task 3: Connectivity monitor hardening

**Files:**
- Modify: existing connectivity monitor/service, camera probe API/service, app startup lifecycle, system event helpers, models/migrations only if persistence is required, backend tests.

**Interfaces:**
- Preserve: Recorder process as one positive source and lightweight RTSP probe as the non-recorder source.
- Add: immediate first cycle, persisted failure streak, manual-probe reconciliation, monitor-error events, compatibility fallback for RTSP servers that close OPTIONS, optional Recorder liveness freshness/watchdog signal derived from existing runtime evidence rather than video decoding.

- [ ] Write failing tests for immediate first cycle, failure-streak persistence/recovery, manual probe reconciliation, and monitor exception event emission.
- [ ] Implement minimal persistence and lifecycle changes.
- [ ] Add RTSP OPTIONS compatibility logic without treating arbitrary TCP connect alone as fully online.
- [ ] Add bounded stale-recorder/watchdog handling using existing process/runtime timestamps; do not decode media in the monitor.
- [ ] Run targeted pytest and full backend pytest; expect GREEN.

### Task 4: Operations foundations

**Files:**
- Create/modify: operations API/service modules, settings/audit models + Alembic migration if required, frontend operations/settings surfaces, Prometheus endpoint support, docs and tests.

**Interfaces:**
- Produce: bounded log listing/download, log rotation policy visibility, redacted configuration export/import, operation audit records, Prometheus-format metrics endpoint, release/upgrade documentation.

- [ ] Write backend failing tests for safe log path handling, redacted config export/import validation, audit creation, and metrics endpoint.
- [ ] Implement log inventory/download restricted to configured application/FFmpeg logs and reject path traversal.
- [ ] Implement versioned configuration export/import with secrets excluded or represented only by `*_set` markers; import must never silently overwrite secrets with blanks.
- [ ] Add operation audit persistence and record high-value administrative mutations.
- [ ] Add `/metrics` in Prometheus text format using existing runtime/health/upload/connectivity counters without requiring an external Prometheus server.
- [ ] Add a compact Operations/maintenance UI entry under Settings for logs, config backup/restore, audit visibility, and metrics discoverability.
- [ ] Document backup, migration, upgrade, rollback, and V1.0 release checklist.
- [ ] Run full backend/frontend tests, lint/build, and Docker smoke; expect GREEN.

## Self-review

- Spec coverage: all four user-approved batches are represented.
- Media-start contract is explicitly preserved in every frontend task.
- Real 24h/72h camera stability and browser hardware matrix remain external acceptance work, not falsely claimed by these code PRs.
- ONVIF/person-detection/event-recording are intentionally excluded from V1.0 convergence.
