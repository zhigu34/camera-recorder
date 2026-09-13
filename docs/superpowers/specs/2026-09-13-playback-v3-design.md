# Playback V3 Design

## Goal

Replace the current segment-first playback navigation with a UniFi Protect-inspired continuous timeline while preserving the existing recording storage, HEVC/direct playback, H.264 compatibility proxy, OpenList cloud playback, and recording management behavior.

## Interaction model

Playback becomes camera/date-first rather than segment-first. The video player remains the primary surface. A continuous timeline sits directly below it with a fixed center playhead and precise wall-clock label. Users drag the timeline beneath the playhead or click a time to navigate. The timeline supports 24h, 6h, 1h, and 15m zoom levels; wheel zoom keeps the wall-clock time under the pointer stable as much as possible.

The recording lane renders actual coverage from the day's recording segments. Gaps remain visually empty and are not auto-bridged. A motion lane renders real Motion Detection V1 events. Person and vehicle lanes may be shown only as disabled placeholders when useful for hierarchy; no fake event data is created.

The existing 24-hour heat map becomes a compact overview/minimap below the detailed timeline. It is used for day-level context and fast repositioning rather than primary playback navigation.

## Playback selection

A timeline seek resolves wall-clock seconds to the recording segment whose range contains that point. If no segment contains the point, playback does not change and the UI reports that no recording exists at that time. If a segment exists, the existing `play()` path is reused so direct HEVC/H.264, cloud playback, and compatibility fallback behavior remain unchanged. Once video metadata is available, the player seeks to the requested offset within the segment.

Motion event selection uses the same seek path with a 2-second lead-in. The event's persisted `recording_id` is preferred; wall-clock containment is the fallback.

## Component boundaries

`PlaybackTimelineV3.vue` owns timeline presentation and pointer/drag/wheel interactions. It consumes recording ranges, selected camera/date, motion events, active wall-clock position, and zoom state; it emits wall-clock seek requests.

`utils/playbackTimelineV3.ts` owns pure math: zoom spans, viewport clamping, pointer-to-time mapping, range-to-percentage mapping, recording lookup, and zoom-around-anchor behavior. These functions are covered by Vitest before component implementation.

`RecordingManagementView.vue` owns actual playback. It gets a real `<video ref>` and a pending seek state so timeline navigation no longer depends on `querySelector`, MutationObserver, or Teleport hacks.

`RecordingManagementWorkspace.vue` becomes a thin compatibility wrapper or is removed once Motion is rendered natively by the new timeline.

## Visual direction

The visual hierarchy follows Protect rather than a dashboard/card layout: video dominates; controls are compact; the timeline is dense, flat, and technical; labels and separators use restrained contrast; active state uses the existing NVR blue. The timeline is full-width under the player and right-side catalog remains secondary.

## Error handling

Timeline loading failure does not break video playback. Motion API failure leaves the motion lane empty with a small status hint. Seeking into a gap does not change the current source. If a compatibility proxy replaces the video source, the pending timeline seek is re-applied after metadata is available.

## Testing

Pure timeline math is tested with Vitest. Recording resolution and seek offset behavior is tested independently from Vue rendering. Final verification requires `npm test`, `npm run build`, backend pytest, and docker-smoke CI to pass.