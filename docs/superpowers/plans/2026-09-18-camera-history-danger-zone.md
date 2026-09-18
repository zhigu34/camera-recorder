# Camera History, Disable, and Danger Zone Plan

**Goal:** Finish Phase 5 camera management interactions by adding camera-scoped history navigation, explicit disable/re-enable semantics, and blocker-aware permanent deletion.

**Scope:** Frontend only. Reuse existing `GET /api/cameras/{id}/deletion-impact`, unified `PUT /api/cameras/{id}`, and guarded `DELETE /api/cameras/{id}`.

## Task 1 — Contract tests
- Add source-contract tests for history summary, deep links, disable confirmation, deletion impact, blocker handling, and Danger Zone-only deletion.
- Remove the easy enabled switch from `CameraEditorDialog`.

## Task 2 — Camera-scoped navigation
- Add camera-scoped route builders for recordings, motion activity, system events, health, and uploads.
- Make Event Center consume `camera_id` for activity/system filtering.
- Make Health Center consume `camera_id` and open the matching camera drawer when data is available.
- Make Upload Management consume `camera_id` and filter tasks by their recording camera.

## Task 3 — History summary
- Add a focused `CameraHistoryPanel` component.
- Load deletion-impact counts as the canonical current history summary.
- Link each count to its camera-scoped workspace.
- Refresh when selected Camera ID changes.

## Task 4 — Disable / re-enable
- Remove enabled toggle from the general editor UI.
- Add explicit right-pane Disable Camera action.
- Require confirmation explaining recording, probing/reconnect, motion detection and pre-roll stop while history remains.
- Re-enable directly from the detail pane without destructive confirmation.
- Prevent runtime actions while disabled.

## Task 5 — Deletion impact dialog
- Add `CameraDeletionImpactDialog`.
- Fetch deletion impact before every delete attempt.
- If blockers exist, show counts + deep links + optional Disable; never offer cascade deletion.
- If no blockers exist, require explicit permanent-delete confirmation, then call DELETE.
- Keep delete only in right-pane Danger Zone.

## Task 6 — Integration cleanup
- Integrate history and deletion components into `CamerasView`.
- Preserve split view, editor, batch add, preview, event-detection extension, playback shortcuts and deep-link selection.
- Run CI after implementation, but do not block intermediate development on CI.
