# Camera Split View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the desktop camera detail drawer with a permanent split-view workspace while preserving deep links, current camera operations, and responsive narrow-screen navigation.

**Architecture:** Keep the existing `CamerasView.vue` data loading, Pinia camera store, preview flow, runtime actions, and backend API contracts. Reshape presentation into an independently scrollable left device list and a persistent right detail pane, add deterministic camera selection, and retarget `CamerasWorkspace.vue` portal content from the drawer DOM to a stable split-view detail mount. Add a focused split-view stylesheet and source-contract Vitest coverage so later Phase 5 work can replace the editor without reopening layout semantics.

**Tech Stack:** Vue 3, TypeScript, Vue Router, Pinia, Element Plus, Vitest, CSS.

**Spec:** `docs/superpowers/specs/2026-09-16-camera-architecture-refactor-design.md`

## Global Constraints

- Do not change backend APIs, database models, migrations, or runtime service behavior in this PR.
- Preserve `/cameras?camera_id=<id>` deep links and valid selection restoration after refresh.
- Desktop camera management must use a permanent left-list/right-detail split view, not an overlay drawer.
- With cameras present and no valid `camera_id`, select the first visible camera when appropriate and normalize the URL using replace semantics rather than adding browser-history noise.
- Add Disabled as a separate summary/filter state; disabled cameras must not be counted as connection issues.
- Keep existing preview, probe, start/stop recording, edit, batch-add, HIK/ONVIF add entry points, event-detection shortcut, playback shortcut, recordings shortcut, and delete behavior intact for this PR.
- Narrow layouts may collapse to list/detail navigation, but desktop remains split view.
- Do not implement the unified `CameraEditorDialog`, adapter selector, history summary API, deletion-impact dialog, or contract cleanup in this PR.

---

### Task 1: Lock the split-view contract with tests

**Files:**
- Create: `frontend/src/cameraSplitView.test.ts`
- Modify: `frontend/src/cameraDetailDrawerV2.test.ts`

**Interfaces:**
- Consumes: raw source of `CamerasView.vue`, `CamerasWorkspace.vue`, `main.ts`, and the new split-view stylesheet.
- Produces: source-level contract checks for permanent split layout, Disabled filtering, deep-link/default-selection semantics, stable portal mount targets, responsive fallback, and style load order.

- [ ] **Step 1: Write failing split-view source-contract tests**

Create `frontend/src/cameraSplitView.test.ts` with assertions that require:

```ts
import { describe, expect, it } from 'vitest'

import cameraSource from './CamerasView.vue?raw'
import workspaceSource from './CamerasWorkspace.vue?raw'
import mainSource from './main.ts?raw'
import splitStyleSource from './styles/camera-split-view.css?raw'

describe('camera split view', () => {
  it('uses a permanent desktop list/detail workspace instead of the legacy camera drawer', () => {
    expect(cameraSource).toContain('class="camera-split-layout"')
    expect(cameraSource).toContain('class="camera-list-pane"')
    expect(cameraSource).toContain('class="camera-detail-pane"')
    expect(cameraSource).not.toContain('<el-drawer')
  })

  it('keeps camera deep links and selects the first visible camera when no camera id is present', () => {
    expect(cameraSource).toContain('nextQuery.camera_id = String(cameraId)')
    expect(cameraSource).toContain("writeCameraDeepLink(firstCamera.id, 'replace')")
  })

  it('treats disabled devices as a separate filter state', () => {
    expect(cameraSource).toContain("'disabled'")
    expect(cameraSource).toContain('disabled: cameras.value.filter')
    expect(cameraSource).toContain("filter.value === 'disabled'")
  })

  it('provides stable workspace portal targets in the persistent detail pane', () => {
    expect(cameraSource).toContain('class="camera-detail-extension-slot"')
    expect(workspaceSource).toContain('.camera-detail-pane .camera-detail-extension-slot')
  })

  it('loads the split-view refinement and includes a narrow-screen list/detail fallback', () => {
    expect(mainSource).toContain("./styles/camera-split-view.css")
    expect(splitStyleSource).toContain('.camera-split-layout')
    expect(splitStyleSource).toContain('@media (max-width:')
    expect(splitStyleSource).toContain('.camera-detail-back')
  })
})
```

Update `cameraDetailDrawerV2.test.ts` so its shortcut/event-detection assertions target the stable split-view detail slot rather than `.camera-detail-drawer .drawer-body-v2`, and stop requiring the old drawer refinement layer as the active page layout.

- [ ] **Step 2: Run the targeted tests and verify RED**

Run:

```bash
cd frontend
npm test -- cameraSplitView.test.ts cameraDetailDrawerV2.test.ts
```

Expected: `cameraSplitView.test.ts` fails because the split markup/style/default-selection/Disabled filter do not exist yet.

- [ ] **Step 3: Commit the RED contract tests**

```bash
git add frontend/src/cameraSplitView.test.ts frontend/src/cameraDetailDrawerV2.test.ts
git commit -m "test: define camera split view contract"
```

### Task 2: Add deterministic selection and Disabled filtering

**Files:**
- Modify: `frontend/src/CamerasView.vue`
- Test: `frontend/src/cameraSplitView.test.ts`

**Interfaces:**
- Consumes: existing Vue Router query semantics and current camera list/filter computation.
- Produces: `FilterKey` including `disabled`, summary count `disabled`, and selection synchronization that resolves a missing query to the first visible camera with router `replace`.

- [ ] **Step 1: Extend filter and summary semantics**

Change the filter type and valid filters to include `disabled`:

```ts
type FilterKey = 'all' | 'online' | 'issue' | 'recording' | 'disabled'
const validFilters = new Set<FilterKey>(['all', 'online', 'issue', 'recording', 'disabled'])
```

Extend summary computation:

```ts
disabled: cameras.value.filter((camera) => health(camera) === 'disabled').length,
```

Extend `filteredCameras`:

```ts
if (filter.value === 'disabled') return health(camera) === 'disabled'
```

Keep `issue` restricted to enabled `offline`/`unknown` devices.

- [ ] **Step 2: Replace drawer-location synchronization with persistent selection synchronization**

Refactor the location synchronizer so a valid `camera_id` selects that camera without requiring a drawer boolean. For a missing `camera_id`, after filtered cameras are available choose the first visible camera and call:

```ts
const firstCamera = filteredCameras.value[0]
if (firstCamera) {
  selectedCamera.value = firstCamera
  preparePreview(firstCamera)
  writeCameraDeepLink(firstCamera.id, 'replace')
}
```

Invalid camera IDs still warn only on explicit initial load, then normalize to the first visible camera (or remove `camera_id` when the list is empty).

- [ ] **Step 3: Keep selection stable across refresh/filter changes**

When data refreshes, rebind `selectedCamera` from the store by ID. If the selected device disappears, choose the first current visible camera. If filters change and the current selected camera is still valid globally, keep it in the detail pane rather than destroying selection.

- [ ] **Step 4: Run targeted tests**

```bash
cd frontend
npm test -- cameraSplitView.test.ts
```

Expected: Disabled/deep-link assertions pass; layout assertions remain RED until Task 3.

- [ ] **Step 5: Commit selection/filter behavior**

```bash
git add frontend/src/CamerasView.vue
git commit -m "feat: add camera split selection semantics"
```

### Task 3: Replace desktop drawer with permanent split-view markup

**Files:**
- Modify: `frontend/src/CamerasView.vue`
- Modify: `frontend/src/CamerasWorkspace.vue`
- Test: `frontend/src/cameraSplitView.test.ts`
- Test: `frontend/src/cameraDetailDrawerV2.test.ts`

**Interfaces:**
- Consumes: Task 2 persistent `selectedCamera`, existing preview/actions/detail content, and workspace shortcuts/event-detection portal content.
- Produces: `.camera-split-layout`, `.camera-list-pane`, `.camera-detail-pane`, `.camera-detail-body`, and `.camera-detail-extension-slot` stable structural mounts.

- [ ] **Step 1: Wrap list controls/cards in the left pane**

Keep heading/actions at page level. Move the summary/filter toolbar and device cards into:

```html
<div class="camera-split-layout" :class="{ 'detail-active': Boolean(selectedCamera) }">
  <aside class="camera-list-pane">
    <!-- summary, search/sort, cards -->
  </aside>
  <section class="camera-detail-pane" aria-label="摄像头详情">
    <!-- persistent detail -->
  </section>
</div>
```

- [ ] **Step 2: Render current drawer body permanently in the right pane**

Remove `<el-drawer>`. Preserve the current title states, previous/next navigation, device overview, on-demand preview, device operations, connection/video/runtime sections, and Danger Zone inside `.camera-detail-body`.

Add a narrow-layout back control at the top:

```html
<button type="button" class="camera-detail-back" @click="showCameraList">返回设备列表</button>
```

For an empty camera collection, render the right-pane Add Camera CTA instead of an empty drawer.

- [ ] **Step 3: Provide a stable portal extension slot**

Place:

```html
<div v-if="selectedCamera" class="camera-detail-extension-slot"></div>
```

inside the right-pane detail body after the main preview/identity area, so Phase 5 PR1 keeps current playback/recording/event-detection shortcuts without relying on drawer internals.

- [ ] **Step 4: Retarget CamerasWorkspace portal discovery**

Replace `.camera-detail-drawer .drawer-body-v2` probing/Teleport targets with:

```ts
'.camera-detail-pane .camera-detail-extension-slot'
```

Keep HIK/ONVIF heading-action Teleports unchanged in this PR.

- [ ] **Step 5: Run targeted tests**

```bash
cd frontend
npm test -- cameraSplitView.test.ts cameraDetailDrawerV2.test.ts cameraMotionPortal.test.ts
```

Expected: all pass.

- [ ] **Step 6: Commit structural migration**

```bash
git add frontend/src/CamerasView.vue frontend/src/CamerasWorkspace.vue frontend/src/cameraSplitView.test.ts frontend/src/cameraDetailDrawerV2.test.ts
git commit -m "feat: render camera management as split view"
```

### Task 4: Add responsive split-view styling and full frontend verification

**Files:**
- Create: `frontend/src/styles/camera-split-view.css`
- Modify: `frontend/src/main.ts`
- Test: `frontend/src/cameraSplitView.test.ts`

**Interfaces:**
- Consumes: split-view class names from Task 3 and existing `--nvr-*` design tokens.
- Produces: desktop 320–380px-ish list pane, flexible detail pane, independent scrolling, and narrow-screen list/detail fallback.

- [ ] **Step 1: Add desktop split layout styles**

Create `camera-split-view.css` using existing tokens. Required core rules:

```css
.camera-split-layout {
  display: grid;
  grid-template-columns: minmax(320px, 360px) minmax(0, 1fr);
  min-height: 0;
  gap: 16px;
}

.camera-list-pane,
.camera-detail-pane {
  min-width: 0;
  min-height: 0;
}

.camera-list-pane {
  overflow: auto;
}

.camera-detail-pane {
  overflow: auto;
  border: 1px solid var(--nvr-border);
  border-radius: 12px;
  background: var(--nvr-surface);
}

.camera-detail-back {
  display: none;
}
```

Adapt current drawer selectors where needed by scoping equivalent detail rules to `.camera-detail-pane` without copying unrelated overlay/chrome styles.

- [ ] **Step 2: Add narrow-screen list/detail fallback**

At a breakpoint compatible with the current shell (use `max-width: 900px` unless existing camera responsive rules require a narrower value):

```css
@media (max-width: 900px) {
  .camera-split-layout {
    display: block;
  }
  .camera-split-layout.detail-active .camera-list-pane {
    display: none;
  }
  .camera-split-layout:not(.detail-active) .camera-detail-pane {
    display: none;
  }
  .camera-detail-back {
    display: inline-flex;
  }
}
```

`showCameraList` must clear only the narrow-layout detail presentation/query state needed for navigation; it must not delete or mutate the Camera.

- [ ] **Step 3: Load the split-view refinement after existing camera detail styles**

Add to `main.ts` after the current camera drawer/detail style imports:

```ts
import './styles/camera-split-view.css'
```

This keeps legacy detail styling reusable during PR1 while making the permanent split layout authoritative.

- [ ] **Step 4: Run full frontend verification**

```bash
cd frontend
npm test
npm run lint
npm run build
```

Expected: all tests, lint, and production build pass.

- [ ] **Step 5: Review scope and diff**

Verify no backend files changed and no unified editor/history/deletion-impact work leaked into PR1. Confirm `CamerasWorkspace.vue` no longer depends on `.camera-detail-drawer` for its selected-camera portal.

- [ ] **Step 6: Commit styling and integration**

```bash
git add frontend/src/styles/camera-split-view.css frontend/src/main.ts frontend/src/CamerasView.vue frontend/src/CamerasWorkspace.vue frontend/src/*.test.ts
git commit -m "style: finish responsive camera split view"
```

### Task 5: PR verification gate

**Files:**
- No product-file changes unless CI finds a regression.

**Interfaces:**
- Consumes: completed branch.
- Produces: reviewable PR with exact-head CI evidence.

- [ ] **Step 1: Open a draft PR**

Open `feat/camera-split-view` -> `main` with a Phase 5 PR1 scope summary and explicitly state that unified editor/history/deletion-impact are deferred.

- [ ] **Step 2: Wait for exact-head CI and inspect every failing job**

Required gates:

```text
frontend lint/tests/build: success
backend jobs: success or correctly skipped by path classification
docker smoke: success or correctly skipped by path classification
```

Do not dismiss a frontend source-contract regression as test-only without checking whether it represents a preserved user flow.

- [ ] **Step 3: Final diff review**

Confirm:

```text
Desktop: permanent split view
Deep link: camera_id preserved/restored
Default selection: first visible camera with replace semantics
Disabled: separate summary/filter
Preview/runtime/edit flows: preserved
Workspace shortcuts/event detection: preserved through stable slot
Narrow: list/detail fallback
Backend/API/DB: unchanged
```

- [ ] **Step 4: Mark PR ready only after exact-head CI is green**

Merge remains a separate closeout action after the verified PR is review-ready.
