# Recordings Workspace Split Design

## Status and precedence

This design is the structural continuation of `2026-09-13-playback-v3-design.md`.

It **supersedes** the earlier design where Playback V3 was teleported into the existing recording-management layout and where the right-side recording catalog remained part of the Playback surface. Timeline math, wall-clock semantics, motion-event behavior, and existing playback compatibility requirements from the earlier design remain valid.

## Goal

Finish the Playback V3 information architecture by separating **continuous playback** from **recording file management** while keeping both under one top-level “录像” module.

The current implementation still renders the legacy `RecordingManagementView.vue` and teleports the V3 timeline and motion event feed into it. As a result, the Playback surface still contains the legacy calendar/catalog and recording segment table. This design replaces that hybrid layout with two explicit top tabs:

- **回放** — camera/date-first continuous playback.
- **录像管理** — segment/file administration.

No recording, cloud archive, compatibility proxy, deletion, health, or upload-management capability is removed.

## Navigation and routes

The left sidebar has one top-level entry named **录像** with description **“连续回放与录像管理”**. Its target is `/recordings/playback`.

Routes:

- `/recordings/playback` — Playback V3.
- `/recordings/manage` — recording management.
- `/recordings/browser` — compatibility redirect to `/recordings/playback`, preserving query and hash.

Both primary routes use `navKey: 'recordings'`. Their route meta also sets `recordingMode: 'playback'` or `recordingMode: 'manage'`.

A new `RecordingsWorkspace.vue` owns the top tabs and renders the selected child surface. Tab changes preserve `camera_id`, `date`, and `recording_id` when present.

The top tabs sit immediately below the global product top bar. They are not additional sidebar entries.

## Playback tab

Playback becomes the default recordings experience. It does not render the recording segment table or management catalog.

The desktop hierarchy is fixed:

1. Compact camera selector and date picker.
2. Main row with dominant video player on the left and detection event feed on the right.
3. Full-width continuous Playback V3 timeline below that row.
4. Compact playback/source status attached to the player when needed.

On narrow screens, the event feed stacks below the player and the timeline remains below both.

The legacy recording table, storage/health/upload filters, batch selection, delete controls, expanded calendar catalog, and file-management actions do not render in Playback.

Playback still consumes the day’s recording segments internally. Segments remain implementation data used to resolve wall-clock seeks, source changes, gaps, cloud/local source choice, compatibility proxy behavior, and event-to-video jumps. Users navigate by wall-clock time and events rather than segment rows.

### Playback selection controls

Playback has exactly two primary selectors:

- Camera selector.
- Compact date picker.

The date picker selects a day; it does not expand into the management calendar/table inside the Playback surface.

If route query state is incomplete, Playback uses the existing recent-recording behavior to select an initial camera/date/recording. Deep links with `camera_id`, `date`, and `recording_id` continue to work.

### Playback engine

The existing playback engine is currently embedded in `RecordingManagementView.vue`. It owns direct playback, HEVC handling, H.264 compatibility proxy/live proxy, cloud/OpenList playback, proxy progress, auto-advance, adjacent recording transitions, and error/fallback logic.

This behavior is extracted into one reusable playback layer with two concrete pieces:

- `useRecordingPlayback.ts` — source selection, compatibility/cloud state, proxy progress, fallback, adjacent transitions, and playback state.
- `PlaybackPlayer.vue` — player UI around a native `<video ref>`, exposing an explicit seek/play API to its parent.

Playback behavior must not be copied into a second implementation.

`PlaybackWorkspace.vue` owns camera/date/recording route state, day-recording loading, active wall-clock state, `PlaybackPlayer`, `PlaybackEventFeed`, and `PlaybackTimelineV3`.

The timeline integrates with `PlaybackPlayer` through component refs/events. The final Playback architecture does not use document-wide `querySelector`, `MutationObserver`, or Teleport to discover or seek the video.

## Recording management tab

`/recordings/manage` remains the segment-first administrative surface.

It preserves the existing capabilities:

- Camera/date filtering.
- Calendar/day summaries.
- Recording segment table.
- Local/cloud source status.
- Upload/archive state.
- Recording health and warning counts.
- Batch selection.
- Delete/cleanup actions.
- Compatibility/proxy operations.
- Recording metadata used for diagnosis.

During this restructuring, Management **keeps its existing selected-recording player/preview and operational controls**. We do not visually simplify or remove that preview in this task. What is removed from Management is only the V3 Teleport injection: the continuous V3 timeline and Playback event feed belong exclusively to the Playback tab.

A later, separate design may simplify the Management preview, but that is not part of this migration.

## Cross-navigation

Playback and Management deep-link to each other.

From Playback:

- **管理当前录像** opens `/recordings/manage` with current `camera_id`, `date`, and active `recording_id`.
- If playback is currently in a gap and no recording is active, it passes only camera/date context.

From Management:

- Double-clicking a recording opens `/recordings/playback` with that recording’s `camera_id`, local date, and `recording_id`.
- The row action label becomes **回放** and opens the same Playback route.
- Playback starts at the selected segment start for this migration.

Other product links use the route matching their intent:

- Event Center “查看录像” / motion-event viewing -> `/recordings/playback`.
- Live Monitoring “录像回放” -> `/recordings/playback`.
- Upload/archive administration -> `/recordings/manage`.
- Health compatibility/proxy operational links -> `/recordings/manage`.

## State and query contract

The route query is the durable cross-workspace state contract:

- `camera_id`: selected camera.
- `date`: selected local recording date (`YYYY-MM-DD`).
- `recording_id`: active/selected segment when known.

Playback maintains transient wall-clock position in component state. This restructuring does not add a required `time` query parameter.

Switching top tabs preserves the current query. Each surface ignores query fields it does not need rather than clearing them.

All wall-clock timeline semantics continue to use the project’s offset-ignoring local recording clock helpers, preserving the previously fixed timezone behavior.

If a deep-linked `recording_id` does not belong to the selected camera/date, the surface discards that recording selection and falls back to valid camera/date context. It must never select an unrelated segment.

## Migration strategy

### Stage 1 — workspace shell and routing

Create `RecordingsWorkspace.vue`, add `/recordings/playback`, keep `/recordings/manage`, redirect `/recordings/browser` to Playback, and change the sidebar entry from “录像管理” to “录像”.

At the end of this stage, both tabs are navigable and preserve query context, but the old Playback implementation may still be temporarily used behind the Playback tab until Stage 3.

### Stage 2 — isolate the playback engine

Extract playback state/behavior from `RecordingManagementView.vue` into `useRecordingPlayback.ts` and `PlaybackPlayer.vue` without changing direct/proxy/cloud behavior.

Add an explicit player API for seek/play. Regression-test same-recording seek, cross-recording source switches, pending seeks after metadata, compatibility fallback, and cloud fallback.

Management consumes the same extracted player layer for its existing selected-recording preview so there is still one playback implementation.

### Stage 3 — native Playback V3 page

Create `PlaybackWorkspace.vue` with the compact camera/date controls, `PlaybackPlayer`, `PlaybackEventFeed`, and `PlaybackTimelineV3`.

Remove Playback’s Teleport and document-level MutationObserver/querySelector integration. The Playback route renders no segment table, management filters, batch actions, or management calendar.

### Stage 4 — deep-link cleanup

Add **管理当前录像** in Playback and **回放** actions in Management. Update Event Center, Live Monitoring, Uploads, Health, and other current route consumers to point to Playback or Management according to intent.

Remove the obsolete `RecordingManagementWorkspace.vue` compatibility injection once no route depends on it.

### Stage 5 — Playback interaction polish

After the structural split is verified, continue Playback V3 with previous/next event, ±10 seconds, playback speed, screenshot, and export-range UX. These controls do not block the workspace split.

## Error handling

A failure to load the Playback event feed or timeline does not prevent video playback.

Seeking to a wall-clock time with no recording leaves the current source unchanged and reports that no recording exists at that time.

A failed source switch preserves the existing direct/proxy/cloud fallback semantics.

Switching tabs never deletes, stops, uploads, retries, or otherwise mutates recordings. Management mutations remain explicit and confirmation-protected.

A stale/invalid route `recording_id` is ignored rather than mapped to another recording.

## Testing

Frontend tests cover at least:

- `/recordings/browser` redirects to Playback while preserving query/hash.
- Playback and Management share the same `navKey` and sidebar entry.
- Top tab switching preserves `camera_id`, `date`, and `recording_id`.
- Playback does not render the segment table, management filters, batch actions, or management calendar.
- Management still renders segment administration, selection, delete, status, and compatibility controls.
- Management -> Playback deep link carries recording context.
- Playback -> Management deep link carries current context.
- Same-recording timeline/event seeks do not remount the Playback workspace.
- Cross-recording seeks switch source and apply the correct offset.
- Direct, compatibility proxy/live proxy, and cloud/OpenList playback regressions remain covered.
- Timeline/player integration uses an explicit component API and no document-level DOM discovery.

Final verification remains:

- `npm test`
- `npm run build`
- backend `pytest`
- docker-smoke CI

## Non-goals

This restructuring does not add person/vehicle analytics, change recording storage format, redesign OpenList upload behavior, add authentication/permissions, implement export-range/video clipping, or visually redesign the Management preview.

It does not remove recording segment management. It puts segment management in the **录像管理** tab while making **回放** genuinely continuous-time-first.