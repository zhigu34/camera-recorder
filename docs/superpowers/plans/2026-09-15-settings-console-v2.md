# Settings Console V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `/settings` as a UniFi/NAS-style settings console with an independent OpenList section, shared runtime-settings draft state, and a consistent unsaved-change workflow.

**Architecture:** `SystemSettingsWorkspace.vue` owns navigation and one shared runtime-settings editor state for General, Recording, Storage, and OpenList. Small section components receive the draft and mutate it directly, while a focused utility module handles snapshot/diff counting, payload normalization, RTSP seconds↔microseconds conversion, validation, and archive-route compatibility. Existing notification and operations views keep their APIs and save lifecycles.

**Tech Stack:** Vue 3, TypeScript, Vue Router, Element Plus, Axios, Vitest, existing FastAPI `/api/settings` schema.

**Spec:** `docs/superpowers/specs/2026-09-15-settings-console-v2-design.md`

## Global Constraints

- Keep `/settings` as the route and preserve `?section=archive` compatibility by mapping it to OpenList.
- Reuse the existing `/api/settings` GET/PUT contract; do not change SQLite persistence or backend schemas.
- OpenList/WebDAV controls must live only in the OpenList section.
- Preserve WebDAV password-set, replacement, and clear-password semantics.
- Display RTSP timeout in seconds while sending integer microseconds to the backend.
- Preserve unsaved changes while switching among runtime-settings sections.
- Prompt before leaving `/settings` or unloading the page while runtime settings are dirty.
- Keep notification and operations backend/API behavior unchanged.
- Backend validation remains authoritative; client validation must also block critical storage threshold `<=` warning threshold.
- No fake OpenList connection test button.
- Before handoff, frontend lint/tests/build and repository Docker smoke CI must be green.

---

### Task 1: Add runtime-settings model utilities and RED tests

**Files:**
- Create: `frontend/src/utils/runtimeSettings.ts`
- Create: `frontend/src/settingsConsoleV2.test.ts`
- Modify: `frontend/src/adminRouteIntegration.test.ts`

**Interfaces:**
- Produces: `RuntimeSettings`, `RuntimeSettingsDraft`, `normalizeSettingsSection(raw)`, `createRuntimeDraft(data)`, `serializeRuntimePayload(draft)`, `countRuntimeChanges(saved, draft)`, `validateRuntimeDraft(draft)`, `rtspUsToSeconds(value)`, `rtspSecondsToUs(value)`.

- [ ] **Step 1: Write failing tests for section normalization and OpenList separation**

```ts
import { describe, expect, it } from 'vitest'
import workspaceSource from './SystemSettingsWorkspace.vue?raw'
import openListSource from './settings/SettingsOpenListPanel.vue?raw'
import generalSource from './settings/SettingsGeneralPanel.vue?raw'
import recordingSource from './settings/SettingsRecordingPanel.vue?raw'
import storageSource from './settings/SettingsStoragePanel.vue?raw'
import {
  countRuntimeChanges,
  createRuntimeDraft,
  normalizeSettingsSection,
  rtspSecondsToUs,
  rtspUsToSeconds,
  serializeRuntimePayload,
  validateRuntimeDraft,
} from './utils/runtimeSettings'

describe('settings console v2', () => {
  it('maps legacy archive links to openlist and exposes all console sections', () => {
    expect(normalizeSettingsSection('archive')).toBe('openlist')
    expect(normalizeSettingsSection('alerts')).toBe('alerts')
    expect(normalizeSettingsSection('operations')).toBe('operations')
    expect(normalizeSettingsSection('unknown')).toBe('general')
    for (const label of ['常规', '录像', '存储', 'OpenList', '通知与告警', '运维', '高级']) {
      expect(workspaceSource).toContain(label)
    }
  })

  it('keeps OpenList fields out of general recording and storage panels', () => {
    expect(openListSource).toContain('webdav_url')
    expect(openListSource).toContain('webdav_password')
    expect(generalSource).not.toContain('webdav_')
    expect(recordingSource).not.toContain('webdav_')
    expect(storageSource).not.toContain('webdav_')
  })

  it('round-trips RTSP seconds and microseconds', () => {
    expect(rtspUsToSeconds(5_000_000)).toBe(5)
    expect(rtspSecondsToUs(5.5)).toBe(5_500_000)
  })
})
```

- [ ] **Step 2: Add failing tests for dirty counting, payload compatibility, password semantics, and storage validation**

```ts
const loaded = {
  app_name: 'Camera Recorder', segment_duration_seconds: 600, remux_concurrency: 2,
  rtsp_timeout_us: 5_000_000, auto_start_enabled: true, align_segments_to_clock: true,
  storage_warning_percent: 80, storage_critical_percent: 90, upload_enabled: false,
  upload_concurrency: 2, upload_retry_max: 8, webdav_url: 'http://openlist:5244/dav',
  webdav_root: '监控录像', webdav_username: 'admin', webdav_password_set: true,
  local_retention_hours: 48, openlist_management_port: 5244,
}

it('counts changed logical fields and serializes the existing API shape', () => {
  const saved = createRuntimeDraft(loaded)
  const draft = createRuntimeDraft(loaded)
  draft.app_name = 'NVR'
  draft.rtsp_timeout_seconds = 6
  expect(countRuntimeChanges(saved, draft)).toBe(2)
  expect(serializeRuntimePayload(draft)).toMatchObject({
    app_name: 'NVR', rtsp_timeout_us: 6_000_000, webdav_password: null,
    clear_webdav_password: false,
  })
})

it('preserves replacement and clear password semantics', () => {
  const draft = createRuntimeDraft(loaded)
  draft.webdav_password = 'new-secret'
  expect(serializeRuntimePayload(draft).webdav_password).toBe('new-secret')
  draft.webdav_password = ''
  draft.clear_webdav_password = true
  expect(serializeRuntimePayload(draft).clear_webdav_password).toBe(true)
})

it('blocks invalid storage threshold combinations', () => {
  const draft = createRuntimeDraft(loaded)
  draft.storage_warning_percent = 90
  draft.storage_critical_percent = 90
  expect(validateRuntimeDraft(draft)).toContain('严重告警阈值')
})
```

- [ ] **Step 3: Update the existing admin-route test to assert legacy archive mapping rather than DOM scrolling**

```ts
it('maps the legacy archive settings route to the OpenList section', () => {
  expect(workspaceRouteSource).toContain("@open-settings=\"go('/settings?section=archive')\"")
  expect(settingsWorkspaceSource).toContain("normalizeSettingsSection")
  expect(settingsWorkspaceSource).toContain("'openlist'")
})
```

- [ ] **Step 4: Run focused tests and verify RED**

Run: `cd frontend && npm test -- settingsConsoleV2.test.ts adminRouteIntegration.test.ts`

Expected: FAIL because runtime utility exports and new section components do not exist yet.

- [ ] **Step 5: Implement the utility module minimally**

`runtimeSettings.ts` must define the current backend read fields plus frontend-only `rtsp_timeout_seconds`, `webdav_password`, and `clear_webdav_password`; create drafts from GET responses; remove `openlist_management_port` from PUT payload; convert seconds to microseconds; count changes by logical editable field; and return a Chinese validation message when `critical <= warning`.

- [ ] **Step 6: Re-run focused tests that only exercise utility functions**

Run: `cd frontend && npm test -- settingsConsoleV2.test.ts`

Expected: utility assertions PASS; raw-component assertions remain RED until Task 2.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/utils/runtimeSettings.ts frontend/src/settingsConsoleV2.test.ts frontend/src/adminRouteIntegration.test.ts
git commit -m "test: define settings console v2 behavior"
```

---

### Task 2: Build the settings console shell and focused runtime panels

**Files:**
- Create: `frontend/src/settings/SettingsGeneralPanel.vue`
- Create: `frontend/src/settings/SettingsRecordingPanel.vue`
- Create: `frontend/src/settings/SettingsStoragePanel.vue`
- Create: `frontend/src/settings/SettingsOpenListPanel.vue`
- Create: `frontend/src/settings/SettingsAdvancedPanel.vue`
- Rewrite: `frontend/src/SystemSettingsWorkspace.vue`
- Remove runtime-form responsibility from: `frontend/src/SystemSettingsView.vue` (either reduce to a compatibility wrapper or stop importing it)

**Interfaces:**
- Consumes: `RuntimeSettingsDraft` and utilities from Task 1.
- Produces: one shared draft across General/Recording/Storage/OpenList and URL-driven section selection.

- [ ] **Step 1: Implement General panel**

Use `defineModel<RuntimeSettingsDraft>({ required: true })` and render compact row-based controls for `app_name` and `auto_start_enabled`. Include activation text for startup recovery.

- [ ] **Step 2: Implement Recording panel**

Render segment-duration presets, aligned-segment switch, RTSP timeout as an `el-input-number` bound to `rtsp_timeout_seconds` with seconds label, and Remux concurrency. Include activation hints: new/restarted Recorder session, next connection, future processing task.

- [ ] **Step 3: Implement Storage panel**

Render warning threshold, critical threshold, threshold rail/legend, and `local_retention_hours`. Explain `-1 = 永久保留`. Do not render any WebDAV field.

- [ ] **Step 4: Implement OpenList panel**

Render:

```text
服务入口
  打开 OpenList
WebDAV 连接
  webdav_url
  webdav_root
  webdav_username
  webdav_password / password_set / clear
上传策略
  upload_enabled
  upload_concurrency
  upload_retry_max
```

Reuse the current host/management-port URL resolution logic. Do not include local retention here.

- [ ] **Step 5: Implement Advanced panel**

Render an informational page that explains deployment parameters and secrets remain in `.env` / deployment configuration and are intentionally not exposed as SQLite runtime settings.

- [ ] **Step 6: Rewrite `SystemSettingsWorkspace.vue` around a shared runtime draft**

The workspace must:

```ts
const activeSection = ref<SettingsSection>('general')
const runtimeDraft = ref<RuntimeSettingsDraft | null>(null)
const savedDraft = ref<RuntimeSettingsDraft | null>(null)
const dirtyCount = computed(() => savedDraft.value && runtimeDraft.value
  ? countRuntimeChanges(savedDraft.value, runtimeDraft.value)
  : 0)
```

Load `/api/settings` once, keep draft state while navigating sections, save through `serializeRuntimePayload`, and discard by deep-cloning `savedDraft` rather than re-fetching. Use `normalizeSettingsSection()` so `archive -> openlist`. Keep `onBeforeRouteLeave` plus `beforeunload` at workspace level.

- [ ] **Step 7: Add client validation before PUT**

Before save:

```ts
const validationError = validateRuntimeDraft(runtimeDraft.value)
if (validationError) {
  ElMessage.error(validationError)
  return
}
```

A failed PUT must leave the current draft and dirty count unchanged.

- [ ] **Step 8: Run focused tests**

Run: `cd frontend && npm test -- settingsConsoleV2.test.ts adminRouteIntegration.test.ts`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/SystemSettingsWorkspace.vue frontend/src/SystemSettingsView.vue frontend/src/settings frontend/src/utils/runtimeSettings.ts frontend/src/settingsConsoleV2.test.ts frontend/src/adminRouteIntegration.test.ts
git commit -m "feat: rebuild system settings as console"
```

---

### Task 3: Converge styling and embed existing Notifications/Operations cleanly

**Files:**
- Rewrite: `frontend/src/styles/system-settings.css`
- Modify only if required: `frontend/src/AlertSettingsView.vue`
- Modify only if required: `frontend/src/OperationsView.vue`

**Interfaces:**
- Consumes: markup/classes produced by Task 2.
- Produces: approved visual direction without changing notification/operations business logic.

- [ ] **Step 1: Replace card-grid settings CSS with console layout**

Desktop target:

```css
.settings-console { display:grid; grid-template-columns:220px minmax(0,1fr); }
.settings-console-nav { position:sticky; top:0; align-self:start; }
.settings-console-content { min-width:0; }
.settings-group { border:1px solid var(--nvr-border); border-radius:10px; }
.setting-row { display:grid; grid-template-columns:minmax(0,1fr) minmax(220px,320px); align-items:center; }
```

Use existing theme variables only. Avoid a second global dark sidebar; this is an inner settings rail.

- [ ] **Step 2: Style active navigation and compact helper descriptions**

The active item uses the existing blue accent and subtle surface background. Each nav entry shows icon/title/helper text similar to the approved mockup.

- [ ] **Step 3: Add responsive behavior**

At narrow widths, turn the rail into an overflowable horizontal selector and make every setting row one column. Sticky save actions must remain reachable.

- [ ] **Step 4: Keep existing Notifications and Operations logic intact**

Only adjust wrapper spacing/max-width classes if their current outer shells fight the new console content column. Do not move their API calls or rewrite their save logic.

- [ ] **Step 5: Run frontend lint/tests/build**

Run:

```bash
cd frontend
npm run lint
npm test
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/styles/system-settings.css frontend/src/AlertSettingsView.vue frontend/src/OperationsView.vue
git commit -m "style: converge settings console layout"
```

---

### Task 4: Integration verification and deployment confidence

**Files:**
- Modify tests only if a real compatibility gap is found.
- No feature expansion.

**Interfaces:**
- Consumes: completed V2 console.
- Produces: CI evidence that the branch is deployable.

- [ ] **Step 1: Review diff for accidental API/backend changes**

Run: `git diff main...HEAD -- frontend backend`

Expected: settings-console frontend changes only; backend remains untouched unless a documented compatibility fix became strictly necessary.

- [ ] **Step 2: Run the complete frontend verification again from a clean dependency state where practical**

```bash
cd frontend
npm install --prefer-offline --no-audit --no-fund
npm run lint
npm test
npm run build
```

- [ ] **Step 3: Open/update PR and let repository CI run**

CI must include the existing `frontend`, `backend`, and `docker-smoke` jobs. The prior main baseline used `npm run lint`, `npm test`, `npm run build`, backend compile/pytest, Docker Compose build/start/health/proxy/WebSocket smoke checks.

- [ ] **Step 4: Inspect any failed CI job logs and fix the cause, not the symptom**

Do not mark complete with skipped or unresolved failures.

- [ ] **Step 5: Final verification commit if fixes were required**

```bash
git add <fixed-files>
git commit -m "fix: finalize settings console v2"
```

- [ ] **Step 6: Handoff only after green CI**

Report the branch/PR, key UX changes, exact test/build evidence, and the normal deployment command:

```bash
git pull && ./deploy.sh && docker image prune -f
```
