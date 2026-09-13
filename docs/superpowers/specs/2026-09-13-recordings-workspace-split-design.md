# Recordings Workspace Split Design

## Goal

Finish the Playback V3 information architecture by separating **continuous playback** from **recording file management** while keeping both under one top-level “录像” module.

The current implementation still renders the legacy `RecordingManagementView.vue` and teleports the V3 timeline and motion event feed into it. As a result, the Playback surface still contains the legacy calendar/catalog and recording segment table. This design replaces that hybrid layout with two explicit top tabs:

- **回放** — camera/date-first continuous playback.
- **录像管理** — segment/file administration.

No recording, cloud archive, compatibility proxy, deletion, or health capability is removed.

## Navigation and routes

The left sidebar has one top-level entry named **录像** with a description such as “连续回放与录像管理”. Its target is the playback route.

Routes:

- `/recordings/playback` — Playback V3.
- `/recordings/manage` — recording management.
- `/recordings/browser` — compatibility redirect to `/recordings/playback`, preserving query and hash.

Both routes use the same `navKey: 'recordings'`, so the shell keeps one active sidebar entry. A route meta value such as `recordingMode: 'playback' | 'manage'` selects the inner workspace.

A shared `RecordingsWorkspace.vue` renders the top tabs and the selected child surface. Tab changes preserve meaningful query state (`camera_id`, `date`, `recording_id`) so switching views does not lose context.

The top tabs are part of the recordings workspace, immediately below the global product top bar. They are not additional sidebar entries.

## Playback tab

Playback becomes the default recordings experience. It must not expose the recording segment list as a primary navigation surface.

The hierarchy is:

1. Compact camera/date controls.
2. Dominant video player.
3. Right-side detection event feed on desktop; stacked below the player on narrow screens.
4. Full-width continuous Playback V3 timeline below the player/event row.
5. Compact playback/status details only when they directly help playback.

The legacy recording table, storage/health/upload filters, batch selection, delete controls, expanded calendar catalog, and file-management actions do not render in this tab.

Playback still consumes the day’s recording segments internally. Segments remain implementation data used to resolve wall-clock seeks, source changes, gaps, cloud/local source choice, compatibility proxy behavior, and event-to-video jumps. Users navigate by wall-clock time and events rather than by segment rows.

### Playback selection controls

Camera and date remain directly selectable in Playback. Date selection should be compact; a full management-style calendar is not required in the primary Playback surface. A lightweight date picker may show which days have recordings, but it must not recreate the old catalog/table layout.

If route query state is incomplete, Playback resolves an initial camera/date/recording using the existing recent-recording behavior. Deep links with `camera_id`, `date`, and `recording_id` must continue to work.

### Playback engine

The current playback engine is embedded in `RecordingManagementView.vue`. It owns direct playback, HEVC handling, H.264 compatibility proxy/live proxy, cloud/OpenList playback, proxy progress, auto-advance, adjacent recording navigation, and error/fallback logic.

That engine must be extracted into a playback-focused component/composable instead of duplicated. The new Playback tab uses the extracted engine directly.

The V3 timeline must integrate through an explicit player API/ref. The final architecture must not depend on document-wide `querySelector`, `MutationObserver`, or Teleport lifecycle tricks to seek the video.

Expected boundary:

- `PlaybackPlayer.vue` (or equivalent) — video/source/fallback UI and explicit seek API.
- `useRecordingPlayback.ts` (if extraction benefits clarity) — source selection, proxy/cloud state, adjacent source transitions.
- `PlaybackWorkspace.vue` — camera/date state, player, event feed, timeline, deep-link state.
- `PlaybackTimelineV3.vue` — timeline presentation/interactions.
- `PlaybackEventFeed.vue` — real motion event feed.

The exact split may be adjusted during implementation if the existing player logic can be isolated cleanly with fewer files, but playback behavior must have one source of truth.

## Recording management tab

The Management tab preserves the administrative capabilities users already have:

- Camera/date filtering.
- Calendar/day summaries.
- Recording segment table.
- Local/cloud source status.
- Upload/archive state.
- Recording health and warning counts.
- Batch selection.
- Delete/cleanup actions.
- Compatibility/proxy actions that are operationally relevant.
- Existing metadata needed to diagnose a recording.

The management surface is segment-first by design because a segment/file is the object being administered.

Management does not need to duplicate the full continuous Playback V3 timeline. A selected segment may retain a compact preview or existing player during the first migration if that is the lowest-risk way to preserve current operational behavior. The long-term navigation action is explicit: **在回放中打开**.

This staged rule is important: splitting the workspaces must not accidentally remove file-management or compatibility capabilities just to make the Playback tab visually clean.

## Cross-navigation

Playback and Management must deep-link to each other.

From Playback:

- “管理当前录像” opens `/recordings/manage` with the current `camera_id`, `date`, and active `recording_id`.
- If playback is currently in a gap and no recording is active, Management still receives camera/date context without inventing a recording ID.

From Management:

- Double-clicking a recording, or an explicit “回放” action, opens `/recordings/playback` with that recording’s camera/date/id.
- Playback starts at the segment start unless a wall-clock target is also supplied by a future feature.

Other product links should use the route that matches intent:

- Event center “查看录像” / motion-event actions -> Playback.
- Live monitoring “录像回放” -> Playback.
- Upload/archive administration -> Management.
- Health/compatibility operational links -> Management when they refer to a segment/proxy operation; Playback when they only request viewing.

## State and query contract

The route query is the durable cross-workspace state contract:

- `camera_id`: selected camera.
- `date`: selected local recording date (`YYYY-MM-DD`).
- `recording_id`: active/selected segment when known.

Playback also maintains transient wall-clock state in memory for timeline movement. We do not add a required `time` query parameter in this restructuring; that can be introduced later if shareable second-level playback links are desired.

Switching top tabs preserves the current query. Each surface ignores query fields it does not need rather than clearing them.

All wall-clock timeline semantics continue to use the project’s offset-ignoring local recording clock helpers, avoiding the previously fixed timezone shift regression.

## Migration strategy

The migration is staged to protect playback and management behavior.

### Stage 1 — workspace shell and routing

Introduce the shared recordings workspace with top tabs and explicit `/recordings/playback` route. Keep `/recordings/manage` working. Update the sidebar label/target and compatibility redirect.

### Stage 2 — isolate the playback engine

Extract the existing player/source/fallback logic from `RecordingManagementView.vue` without changing behavior. Add an explicit video ref/seek API. Regression-test same-recording seek, cross-recording source switches, pending seeks after metadata, and compatibility/cloud fallback state.

### Stage 3 — native Playback V3 page

Build `PlaybackWorkspace.vue` using the isolated player, `PlaybackTimelineV3`, and `PlaybackEventFeed`. Remove Teleport and document-level MutationObserver/querySelector integration. The Playback route contains no segment table or management catalog.

### Stage 4 — management cleanup and deep links

Keep or simplify the management-side preview as appropriate, preserve all segment administration actions, and add explicit “在回放中打开” / “管理当前录像” navigation. Update Event Center, Live Monitoring, Uploads, Health, and other route consumers to use the correct destination.

### Stage 5 — Playback interaction polish

Only after the structural split is stable, add the remaining Playback controls such as previous/next event, ±10 seconds, playback speed, screenshot, and export-range UX. These controls belong to Playback and should not block the workspace split.

## Error handling

A failure to load the Playback event feed or timeline must not prevent direct video playback.

A failure to resolve a wall-clock target to a recording leaves the current source unchanged and reports that no recording exists at that time.

A failed source switch preserves the existing direct/proxy/cloud fallback semantics.

Switching tabs must not delete, stop, re-upload, or otherwise mutate recordings. Management actions remain explicit and confirmation-protected as they are today.

If a deep-linked `recording_id` is stale or does not belong to the selected camera/date, the destination surface falls back to camera/date context rather than selecting an unrelated segment.

## Testing

Frontend tests must cover at least:

- Route compatibility: `/recordings/browser` redirects to Playback while preserving query/hash.
- Both Playback and Management share the same sidebar/nav key.
- Top tab switching preserves `camera_id`, `date`, and `recording_id`.
- Playback does not render the segment management table/catalog.
- Management still renders segment administration and delete/select controls.
- Management -> Playback deep link carries recording context.
- Playback -> Management deep link carries current context.
- Same-recording timeline/event seeks do not remount the Playback workspace.
- Cross-recording seeks switch the player source and apply the correct offset.
- Timeline/player integration uses an explicit component API rather than document-level DOM discovery.

Final verification remains:

- `npm test`
- `npm run build`
- backend `pytest`
- docker-smoke CI

## Non-goals for this restructuring

This change does not add person/vehicle analytics, change recording storage format, redesign OpenList upload behavior, add authentication/permissions, or implement export-range/video clipping yet.

It also does not remove recording segment management. The purpose is to put segment management in the correct tab while making Playback genuinely continuous-time-first.