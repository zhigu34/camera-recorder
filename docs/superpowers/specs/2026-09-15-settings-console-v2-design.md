# Settings Console V2 Design

Date: 2026-09-15
Status: Approved direction, pending written-spec review

## Goal

Refactor the current system settings experience into a UniFi/NAS-style settings console without changing the existing persistence model. OpenList becomes an independent first-level settings section instead of being embedded in the general system settings page.

## Scope

This iteration is primarily a frontend information-architecture and interaction refactor. Reuse existing settings, notifications, operations, and status APIs unless an implementation-only compatibility endpoint is strictly necessary.

In scope:

- Replace the current top local tabs with a persistent settings navigation rail.
- Split settings into first-level sections: General, Recording, Storage, OpenList, Notifications & Alerts, Operations, Advanced.
- Move all OpenList/WebDAV controls out of the generic system settings page into an independent OpenList settings page.
- Keep existing notification and operations functionality, but render them inside the new settings shell.
- Preserve existing dirty-state protection, before-unload protection, save/reload behavior, encrypted password semantics, and backend validation.
- Replace raw RTSP microseconds editing with a seconds-based UI while continuing to send microseconds to the backend.
- Add a consistent unsaved-change action bar for system/OpenList settings.
- Clearly label setting activation behavior where useful: immediate, new Recorder session, or service restart.

Out of scope:

- New authentication or role management.
- Replacing SQLite settings storage.
- Reworking notification or operations backend APIs.
- Adding new OpenList server-side capabilities such as browsing remote directories.
- Changing deployment-time secrets or `.env` semantics.

## Information Architecture

The `/settings` workspace becomes a two-column console shell:

### Left navigation

1. **常规** — system identity and startup behavior.
2. **录像** — recording segmentation and media processing.
3. **存储** — local storage thresholds and retention behavior.
4. **OpenList** — WebDAV archive service and upload policy.
5. **通知与告警** — existing alert configuration.
6. **运维** — existing logs, backups, status, and operational tools.
7. **高级** — low-frequency or dangerous lower-level settings. In V2 this is an informational placeholder unless a current setting clearly belongs here.

Each item includes a compact title and helper description. The active section is represented by URL query state so deep links remain possible.

### Right content area

Each section uses a consistent structure:

- Page title and one-line description.
- One or more compact setting groups.
- Setting rows with description on the left and the control on the right.
- Optional contextual guidance rail on wide screens.
- Sticky unsaved-change bar when the section owns editable system settings.

On narrow screens the left navigation becomes a horizontal/scrollable section selector and the content becomes single-column.

## Section Design

### General

Contains:

- System name.
- Start/recover recording automatically after service startup.

The page should stay deliberately sparse.

### Recording

Contains:

- Segment duration presets.
- Clock-aligned segmentation.
- RTSP timeout edited in seconds, converted to/from `rtsp_timeout_us` at the view-model boundary.
- Remux concurrency.

Activation guidance:

- Segment duration: new/restarted Recorder session.
- Clock alignment: new/restarted Recorder session.
- RTSP timeout: next connection/session.
- Remux concurrency: immediate for future processing tasks.

### Storage

Contains:

- Warning threshold.
- Critical threshold.
- Local retention hours.

The warning/critical threshold relationship remains backend validated, and the UI also provides immediate client guidance. Retention semantics remain `-1 = keep forever`.

The existing retention value currently sits next to OpenList settings but represents local retention behavior, so it moves to Storage.

### OpenList

OpenList becomes a standalone first-level section.

Header state communicates one of:

- 自动归档已启用 / configured.
- 已关闭.
- 未保存 WebDAV 凭据 or incomplete configuration.

Groups:

1. **服务入口**
   - Open OpenList management UI using the existing host/port resolution behavior.

2. **WebDAV connection**
   - WebDAV URL.
   - Remote archive root.
   - Username.
   - Password, preserving `webdav_password_set`, replacement, and clear-password behavior.

3. **Upload policy**
   - Enable automatic upload.
   - Upload concurrency.
   - Maximum retry count.

Local retention is not duplicated here; OpenList may link the user to Storage instead.

No fake “connection test” button is added until a real backend operation exists.

### Notifications & Alerts

Reuse `AlertSettingsView.vue` behavior and APIs. Adapt its outer layout only as needed so it visually belongs inside the new settings shell. Do not reimplement its form logic in this iteration.

### Operations

Reuse `OperationsView.vue` behavior and APIs. Adapt its outer layout only as needed.

### Advanced

Present an intentionally minimal page explaining that deployment parameters and secrets remain controlled by `.env` / deployment configuration. Do not expose deployment secrets in SQLite-backed runtime settings.

## State and Save Model

The existing `/api/settings` remains the source of truth for General, Recording, Storage, and OpenList.

To avoid each settings page fetching and overwriting the full object independently, the frontend should introduce a shared settings editor state owned by `SystemSettingsWorkspace.vue` or a focused composable/store. It must:

- Fetch `/api/settings` once for runtime-settings sections.
- Hold the editable draft and the last saved snapshot.
- Expose per-section dirty counts and total dirty count.
- Save the complete existing backend payload through one `PUT /api/settings` request.
- Reset the draft from the saved snapshot when changes are discarded.
- Preserve unsaved changes when switching between General, Recording, Storage, and OpenList.
- Prompt before leaving the settings workspace when runtime settings are dirty.
- Keep WebDAV password replacement/clear semantics safe across section changes.

Notification settings retain their existing independent save lifecycle.

## Unsaved Change Bar

For runtime settings, show the action bar only when changes exist.

Example:

`已修改 3 项（尚未保存）        放弃修改   保存更改`

The count is derived from changed logical fields, not from serialized string length or DOM controls.

Saving updates the saved snapshot and removes the bar. Discarding restores the saved runtime settings without a full page reload.

## Validation and Error Handling

- Keep backend validation authoritative.
- Add client-side guard that critical storage threshold must be greater than warning threshold before submitting.
- Normalize RTSP seconds to integer microseconds before sending.
- Preserve the current error-message behavior from Axios responses.
- A failed load leaves an explicit retry action rather than displaying a misleading editable default as if it were saved state.
- A failed save leaves the draft intact and the dirty bar visible.

## Files / Component Boundaries

Expected frontend changes:

- `frontend/src/SystemSettingsWorkspace.vue` — settings console shell, route section state, shared runtime-settings state ownership.
- `frontend/src/SystemSettingsView.vue` — refactor away from one giant page; either become focused section renderer(s) or be replaced by small section components.
- New focused components such as:
  - `SettingsGeneralPanel.vue`
  - `SettingsRecordingPanel.vue`
  - `SettingsStoragePanel.vue`
  - `SettingsOpenListPanel.vue`
  - `SettingsAdvancedPanel.vue`
- `frontend/src/styles/system-settings.css` — console navigation, setting rows, responsive behavior, sticky save bar.
- Existing `AlertSettingsView.vue` and `OperationsView.vue` — only wrapper/layout convergence if needed.
- Add focused tests for navigation, OpenList separation, seconds/microseconds conversion, dirty count, save/discard behavior, and deep-link compatibility.

Avoid creating one new oversized settings component. Shared runtime state and save behavior should be isolated from visual section components.

## Routing Compatibility

Keep `/settings` as the route.

Use query sections, including compatibility with existing links:

- `/settings` or `?section=general` -> General.
- `?section=recording` -> Recording.
- `?section=storage` -> Storage.
- `?section=openlist` -> OpenList.
- Existing `?section=archive` -> redirect/map to OpenList for backward compatibility.
- Existing `?section=alerts` -> Notifications & Alerts.
- Existing `?section=operations` -> Operations.
- `?section=advanced` -> Advanced.

## Visual Direction

Match the approved mockup direction:

- Persistent, calm settings navigation rather than card-heavy dashboard treatment.
- High information clarity with lower visual density.
- Compact bordered setting groups and row-based controls.
- Existing product theme variables remain the source of color and surface styling.
- Avoid adding a second global dark sidebar; the settings rail lives inside the existing application shell.

## Testing and Completion Criteria

Frontend tests must verify:

- All seven settings sections are reachable.
- OpenList controls are absent from General/Recording/Storage and present in OpenList.
- `section=archive` resolves to OpenList.
- Runtime draft survives navigation between runtime-settings sections.
- Leaving the workspace with dirty runtime settings requires confirmation.
- Save sends a payload compatible with the existing `/api/settings` schema.
- RTSP timeout shown in seconds round-trips to microseconds correctly.
- Password-set / replace / clear behavior is preserved.
- Storage threshold invalid combinations cannot be submitted.

Before handoff, run frontend lint/tests/build plus the repository Docker smoke workflow or equivalent existing CI checks. No deployment-ready claim is made until those checks are green.
