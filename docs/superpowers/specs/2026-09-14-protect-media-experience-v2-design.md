# Protect Media Experience V2 Design

Date: 2026-09-14

## Goal

Unify Playback, playback-event feed, and Live Monitoring into a more UniFi Protect-like media experience while preserving the project's existing media safety rules and minimizing CI time for future frontend-only work.

This iteration intentionally combines the related frontend work into one branch and one PR so the media surfaces share the same visual language instead of evolving independently.

## Non-negotiable constraints

- Navigation or deep links must never auto-start Live or Playback media.
- Playback may start only after an explicit user action such as play, timeline seek, event click, transport action, or another deliberate playback command.
- Live Monitoring must start per camera tile only after an explicit user action.
- A single Live tile's start/pause/retry action must never start, pause, reconnect, or otherwise disturb another tile.
- The center of each Live tile contains only the primary media action. Fullscreen, settings, stream selection, remove, and similar actions must live elsewhere to reduce accidental clicks.
- Existing recording, export, compatibility-transcode, and timeline semantics are not changed by this visual/interaction pass.
- Deployment entry remains `git pull && ./deploy.sh`.

## Scope

This design covers four coordinated areas:

1. Playback player controls V2.
2. Playback detection-event feed V2.
3. Live Monitoring V2 with per-tile media lifecycle.
4. Path-aware CI so frontend-only pull requests do not run unnecessary backend and Docker jobs.

Backend preview-wall protocol is intentionally left unchanged in this iteration. The existing websocket endpoint already accepts a list of slots, so the frontend can open one websocket per active tile and submit exactly one slot per connection.

## Shared Protect-style media UI direction

The three media surfaces should share these rules:

- restrained chrome and minimal borders;
- dark media surfaces with content taking visual priority;
- controls appear contextually rather than permanently filling the page;
- icon-first controls with clear hover/focus states;
- consistent 30–34px control sizing, compact radii, and low-contrast inactive states;
- state colors are informative but not dominant;
- no generic admin-form look for primary media controls;
- no Unicode arrow characters used as media icons;
- keyboard focus remains visible even when hover chrome is visually subdued.

## Playback controls V2

### Current problem

`PlaybackPlayer.vue` still uses native browser `<video controls>` while custom transport controls live separately below the player. This creates two competing control systems and makes the page look inconsistent with Protect.

### Design

Remove native video controls and provide one custom control layer inside the 16:9 player.

The control layer contains:

- play / pause;
- skip backward by the configured interval;
- skip forward by the configured interval;
- mute / unmute and volume;
- playback speed;
- fullscreen;
- current playback state feedback where useful.

The existing skip interval remains selectable from the supported values `5 / 10 / 15 / 20 / 25 / 30` seconds. Playback rate remains `0.5x / 1x / 1.5x / 2x / 4x`.

The bottom control layer is low-profile and fades when there is no pointer/focus activity. It must reappear on pointer movement, keyboard focus, or state-changing interaction.

### Behavior preservation

- Selecting a recording does not start playback.
- The placeholder remains the explicit first-play action when a recording has been selected but no source has started.
- Existing compatibility-source selection and live proxy fallback remain unchanged.
- Playback rate continues to be re-applied when the underlying video source changes.
- Existing wall-clock seek behavior remains authoritative for cross-recording skip operations.
- Gaps continue to show the current "no playable recording" feedback rather than silently snapping.

### Component boundary

`PlaybackPlayer.vue` remains responsible for source lifecycle, compatibility fallback, and the real `<video>` element.

A focused control component should receive media state and emit intent such as play, pause, seek delta, rate, volume, mute, and fullscreen. The Workspace remains responsible for wall-clock cross-segment navigation.

This keeps playback source complexity out of presentation code.

## Playback event feed V2

### Goal

Make the detection feed feel like a compact Protect event rail rather than a stack of admin cards.

### Design

Retain the existing event data, snapshot loading, zone labels, duration calculation, active-event detection, and event-to-seek behavior.

Visual changes:

- reduce border/card emphasis;
- increase thumbnail prominence relative to chrome;
- compact time, duration, and zone metadata;
- use a small purpose-built motion glyph/state marker;
- make the active event obvious without a heavy selected-card border;
- keep internal scrolling within the right event rail;
- remove decorative text that does not help scan or playback decisions.

Clicking an event remains an explicit playback action and continues to seek to the existing pre-roll target.

No fake person/vehicle functionality is introduced. Disabled future filters may remain visually subdued or be removed if they add clutter.

## Live Monitoring V2

### Current problem

The current `PreviewView.vue` uses one global websocket and one global started/paused state. A single start action therefore starts every configured tile, and the user has no independent pause control per tile.

### Per-tile state model

Each `WallSlot` owns its own preview lifecycle state. The conceptual states are:

- `idle` — camera assigned but not started;
- `connecting` — websocket/preview source starting;
- `playing` — frames are being received;
- `paused` — user explicitly paused the tile;
- `retrying` — reconnecting after a recoverable transport failure;
- `error` — tile needs explicit retry or configuration attention.

Runtime connection handles are not persisted to localStorage. Only layout, assigned camera, and stream policy remain persistent.

Reloading or revisiting the page must return all tiles to a non-playing state.

### Connection architecture

Use one websocket connection per actively playing tile.

Each tile connects to the existing `/ws/preview-wall` endpoint and sends a start payload containing exactly one slot. The slot index still identifies where returned JPEG frames belong.

Benefits:

- starting tile A does not start B/C/D;
- pausing tile A closes only A's websocket and preview source;
- changing A's stream policy reconnects only A;
- removing A stops only A;
- hidden tiles after layout reduction can be stopped independently;
- no backend websocket protocol change is required.

The maximum 9-grid layout therefore means at most 9 preview websocket connections.

### Central action rule

The center of a tile contains exactly one primary media action:

- idle: Start;
- playing: Pause;
- paused: Resume;
- error: Retry.

No fullscreen, settings, stream selector, remove action, or secondary action is allowed in the center overlay.

Clicking the video surface itself performs no media action. The primary button must be an intentional target.

When a tile is playing, the center pause button may fade when the pointer is inactive and reappear on hover/focus. It remains the only central control.

### Peripheral tile chrome

- top-left: camera name and recording/runtime status such as REC;
- top-right: active/policy stream indicator such as AUTO, SUB, or MAIN;
- lower-right or edge-aligned hover toolbar: fullscreen, camera settings, stream policy, remove;
- mobile: secondary controls collapse into a `...` menu so the center remains reserved for the primary media action.

### Optional bulk control

A page-level "Start all" / "Pause all" action may remain as a low-emphasis convenience control, but it must be visually and semantically separate from per-tile controls. It must never replace per-tile independent state.

### Layout behavior

- Changing from 9/4 tiles to fewer tiles stops any tiles that become hidden.
- Auto-fill assigns cameras but does not start them.
- Dragging or assigning a camera updates configuration but does not start preview automatically.
- Stream-policy changes on a stopped tile do not start it.
- Stream-policy changes on a playing tile restart only that tile.
- Visibility changes may suspend active connections for resource safety; returning to the page must not start tiles that the user had never explicitly started. If active tiles are temporarily suspended because the document is hidden, only those previously user-started tiles may resume.

## CI path gating

### Goal

Avoid spending most of PR time on backend and Docker verification when a change is frontend-only.

### Pull request behavior

Introduce a lightweight change-detection job or equivalent path-based conditions.

- `frontend/**` only: run frontend tests/build; skip backend and Docker smoke.
- `backend/**`: run backend; also run Docker smoke when integration/runtime packaging can be affected.
- Dockerfiles, `docker-compose.yml`, `deploy.sh`, `scripts/**`, `.env.example`, reverse-proxy/runtime infrastructure, or other explicitly listed deployment paths: run Docker smoke.
- mixed frontend/backend/infrastructure PRs: run every applicable job.
- workflow changes should conservatively run relevant verification so CI edits do not bypass their own checks.

The current `push` trigger on `main` remains available for repository health, but the development workflow does not wait for a second post-merge `main` run by default.

### Check stability

Skipped jobs must be represented consistently so branch protection does not become unpredictable. Prefer a single always-present change-detection job plus conditional jobs over dynamically changing workflow names.

## Testing strategy

This iteration follows the repository's risk-based testing rules.

Do not add visual snapshot tests or helper-by-helper tests merely to freeze implementation details.

Protect these user-visible behaviors:

- Playback page still does not auto-start media on navigation/selection alone.
- Custom play/pause invokes the correct player action.
- Playback speed and skip actions retain existing semantics.
- Event click emits/seeks to the correct event target.
- Live page does not open preview connections on mount.
- Starting one Live tile creates/starts only that tile's connection.
- Pausing one Live tile closes only that tile's connection.
- Starting/pausing one tile does not mutate another tile's media state.
- Reducing the layout stops hidden active tiles.
- Central tile overlay contains only the primary action; secondary controls stay in peripheral toolbar/menu.
- CI path classification correctly identifies frontend-only versus backend/infrastructure changes.

## Expected files / areas

Likely frontend areas:

- `frontend/src/PlaybackPlayer.vue`
- `frontend/src/PlaybackTransportControls.vue` or its replacement
- a new focused playback media-controls component if useful
- `frontend/src/PlaybackWorkspace.vue`
- `frontend/src/PlaybackEventFeed.vue`
- `frontend/src/PreviewView.vue`
- shared media-control styles/components only where they reduce duplication without creating a large generic design system
- targeted frontend regression tests

CI:

- `.github/workflows/ci.yml`

No recording pipeline, remux/export implementation, database migration, or media API change is planned.

## Delivery workflow

- One implementation branch: `ui/protect-media-experience-v2`.
- One PR for the entire approved iteration.
- Necessary targeted tests only.
- One PR CI run after implementation; rerun only if CI naturally fails and requires a fix.
- Self-review the final diff.
- Merge directly when PR CI is green and no blocking review issue remains.
- Do not wait for a second `main` CI run unless the merged state differs materially from the verified PR state.

Deployment remains:

```bash
git pull && ./deploy.sh
```

Because the implementation will include `.github/workflows/ci.yml`, this particular PR is expected to exercise the broader CI path once. After merge, future frontend-only PRs should complete much faster.
