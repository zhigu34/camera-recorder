# Frontend Timezone Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every visible complete date+time in the frontend render in the deployment timezone from `.env TZ`, using exactly `YYYY-MM-DD HH:mm:ss`, without changing pure-date, pure-time, relative-time, playback arithmetic, sorting, filtering, or storage semantics.

**Architecture:** Keep timestamps as data and timezone as presentation policy. The backend centralizes `TZ` validation and exposes the effective timezone through `/api/settings/runtime`; the frontend configures one shared formatter before Vue mounts, then all complete datetime presentation flows through that formatter. Existing business-time helpers such as playback wall-clock parsing remain separate and are not rewritten to use the presentation formatter.

**Tech Stack:** FastAPI, Pydantic, Python `zoneinfo`, Vue 3, TypeScript, Axios, Vitest, Vite, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-15-frontend-timezone-display-design.md`

## Global Constraints

- `.env` `TZ` is the only deployment-level timezone source of truth.
- Missing or blank `TZ` resolves to `Asia/Shanghai`.
- Invalid IANA timezone resolves to `UTC` on the backend.
- Frontend bootstrap failure or invalid timezone falls back to `Asia/Shanghai` and must not block mounting.
- Complete datetime display format is exactly `YYYY-MM-DD HH:mm:ss`.
- Pure dates such as `2026-09-15` remain unchanged.
- Pure clock values such as `01:01:01` remain unchanged.
- Relative labels such as `今天`, `昨天`, `刚刚`, `5分钟前` remain unchanged.
- Duration, timeline arithmetic, playback seek math, date filtering, sorting, database storage, and API query semantics remain unchanged.
- Existing backend values already shaped as `YYYY-MM-DD HH:mm:ss` are treated as presentation-ready and must not be shifted twice.
- No database migration is required.
- No new runtime dependency is required.

---

### Task 1: Centralize backend timezone resolution and expose it in runtime settings

**Files:**
- Create: `backend/app/core/timezone.py`
- Modify: `backend/app/schemas/event.py`
- Modify: `backend/app/api/settings.py`
- Test: `backend/tests/test_event_timezone.py`
- Test: `backend/tests/test_system_settings.py`

**Interfaces:**
- Produces: `configured_timezone_name() -> str`
- Produces: `configured_timezone() -> tzinfo`
- Produces: `GET /api/settings/runtime` field `timezone: str`
- Consumed later by: frontend bootstrap and the existing `EventRead.created_at` serializer.

- [ ] **Step 1: Write failing backend timezone helper tests**

Add tests that define the contract before implementation:

```python
from app.core.timezone import configured_timezone_name


def test_configured_timezone_defaults_to_shanghai(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    assert configured_timezone_name() == "Asia/Shanghai"


def test_configured_timezone_uses_valid_iana_name(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    assert configured_timezone_name() == "Asia/Shanghai"


def test_configured_timezone_invalid_falls_back_to_utc(monkeypatch):
    monkeypatch.setenv("TZ", "Invalid/Timezone")
    assert configured_timezone_name() == "UTC"
```

- [ ] **Step 2: Extend runtime-settings and EventRead tests before implementation**

Add a test that calls the runtime endpoint with `TZ=Asia/Shanghai` and asserts:

```python
assert response.json()["timezone"] == "Asia/Shanghai"
```

Keep the existing event serialization test asserting:

```python
assert event.model_dump(mode="json")["created_at"] == "2026-09-11 16:00:00"
```

and update its imports only after the shared helper exists.

- [ ] **Step 3: Run focused backend tests and verify RED**

Run:

```bash
cd backend
uv run pytest tests/test_event_timezone.py tests/test_system_settings.py -q
```

Expected: FAIL because `app.core.timezone` and the runtime `timezone` field do not exist yet.

- [ ] **Step 4: Implement the centralized helper**

Create `backend/app/core/timezone.py` with the exact behavior:

```python
import os
from datetime import timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Shanghai"


def configured_timezone_name() -> str:
    name = os.getenv("TZ", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return "UTC"
    return name


def configured_timezone() -> tzinfo:
    name = configured_timezone_name()
    return timezone.utc if name == "UTC" else ZoneInfo(name)
```

Refactor `backend/app/schemas/event.py` to import `configured_timezone` and remove its private timezone lookup. Preserve the current rule that naive SQLite timestamps are interpreted as UTC before conversion.

- [ ] **Step 5: Expose the timezone from `/api/settings/runtime`**

Modify `backend/app/api/settings.py`:

```python
from app.core.timezone import configured_timezone_name
```

and add:

```python
"timezone": configured_timezone_name(),
```

to the existing runtime response. Do not add timezone to editable SQLite system settings because it is deployment configuration, not a UI-editable runtime setting.

- [ ] **Step 6: Run focused backend tests and verify GREEN**

Run:

```bash
cd backend
uv run pytest tests/test_event_timezone.py tests/test_system_settings.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add backend/app/core/timezone.py backend/app/schemas/event.py backend/app/api/settings.py backend/tests/test_event_timezone.py backend/tests/test_system_settings.py
git commit -m "feat: expose deployment timezone"
```

---

### Task 2: Add the frontend application-timezone formatter

**Files:**
- Create: `frontend/src/utils/dateTime.ts`
- Create: `frontend/src/dateTime.test.ts`

**Interfaces:**
- Produces: `DEFAULT_APPLICATION_TIME_ZONE = 'Asia/Shanghai'`
- Produces: `configureApplicationTimeZone(timeZone: string): string`
- Produces: `applicationTimeZone(): string`
- Produces: `formatDateTime(value?: string | Date | null): string`
- Consumed later by: all complete datetime UI presentation and bootstrap.

- [ ] **Step 1: Write formatter tests first**

Create `frontend/src/dateTime.test.ts` with at least these cases:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import {
  applicationTimeZone,
  configureApplicationTimeZone,
  formatDateTime,
} from './utils/dateTime'

beforeEach(() => configureApplicationTimeZone('Asia/Shanghai'))

describe('application datetime presentation', () => {
  it('renders a UTC instant in Asia/Shanghai', () => {
    expect(formatDateTime('2026-09-14T17:01:01Z')).toBe('2026-09-15 01:01:01')
  })

  it('renders an offset-aware instant without double shifting', () => {
    expect(formatDateTime('2026-09-15T01:01:01+08:00')).toBe('2026-09-15 01:01:01')
  })

  it('passes through an existing backend display datetime unchanged', () => {
    expect(formatDateTime('2026-09-15 01:01:01')).toBe('2026-09-15 01:01:01')
  })

  it('treats a naive ISO API datetime as UTC for presentation', () => {
    expect(formatDateTime('2026-09-14T17:01:01')).toBe('2026-09-15 01:01:01')
  })

  it('returns dash for empty values and original text for invalid non-empty values', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
  })

  it('rejects invalid frontend timezone configuration with Shanghai fallback', () => {
    expect(configureApplicationTimeZone('Invalid/Timezone')).toBe('Asia/Shanghai')
    expect(applicationTimeZone()).toBe('Asia/Shanghai')
  })
})
```

- [ ] **Step 2: Run the formatter test and verify RED**

Run:

```bash
cd frontend
npm test -- --run src/dateTime.test.ts
```

Expected: FAIL because `utils/dateTime.ts` does not exist.

- [ ] **Step 3: Implement deterministic formatter behavior**

Implement `frontend/src/utils/dateTime.ts` using one module-level application timezone and `Intl.DateTimeFormat(...).formatToParts()`.

Required parsing order:

```ts
const DISPLAY_DATETIME = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/
const NAIVE_ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/
```

Rules:

```ts
if (!value) return '-'
if (typeof value === 'string' && DISPLAY_DATETIME.test(value)) return value
if (typeof value === 'string' && NAIVE_ISO.test(value)) parsed = new Date(`${value}Z`)
else parsed = value instanceof Date ? value : new Date(value)
if (Number.isNaN(parsed.getTime())) return typeof value === 'string' ? value : '-'
```

Use an explicit `timeZone` plus numeric year/month/day/hour/minute/second and assemble the final string from `formatToParts`; do not rely on locale punctuation or order.

- [ ] **Step 4: Run formatter tests and verify GREEN**

Run:

```bash
cd frontend
npm test -- --run src/dateTime.test.ts
```

Expected: PASS regardless of the machine/test-process timezone.

- [ ] **Step 5: Commit Task 2**

```bash
git add frontend/src/utils/dateTime.ts frontend/src/dateTime.test.ts
git commit -m "feat: add application datetime formatter"
```

---

### Task 3: Bootstrap frontend timezone before Vue mount

**Files:**
- Create: `frontend/src/utils/applicationBootstrap.ts`
- Create: `frontend/src/timezoneBootstrap.test.ts`
- Modify: `frontend/src/main.ts`

**Interfaces:**
- Consumes: `configureApplicationTimeZone()` from Task 2.
- Produces: `bootstrapApplicationTimeZone(): Promise<string>`.
- Contract: request `/api/settings/runtime` with a bounded timeout, configure timezone, and always resolve to a usable timezone.

- [ ] **Step 1: Write bootstrap tests first**

Create `frontend/src/timezoneBootstrap.test.ts` that mocks Axios and asserts:

```ts
it('uses the runtime timezone returned by backend', async () => {
  mockedAxios.get.mockResolvedValue({ data: { timezone: 'Asia/Shanghai' } })
  await expect(bootstrapApplicationTimeZone()).resolves.toBe('Asia/Shanghai')
  expect(applicationTimeZone()).toBe('Asia/Shanghai')
})

it('falls back to Shanghai when runtime settings cannot be loaded', async () => {
  mockedAxios.get.mockRejectedValue(new Error('offline'))
  await expect(bootstrapApplicationTimeZone()).resolves.toBe('Asia/Shanghai')
})
```

Also assert the request is made to `/api/settings/runtime` with a finite timeout.

- [ ] **Step 2: Run bootstrap tests and verify RED**

Run:

```bash
cd frontend
npm test -- --run src/timezoneBootstrap.test.ts
```

Expected: FAIL because `applicationBootstrap.ts` does not exist.

- [ ] **Step 3: Implement bounded timezone bootstrap**

Create `frontend/src/utils/applicationBootstrap.ts`:

```ts
import axios from 'axios'
import {
  DEFAULT_APPLICATION_TIME_ZONE,
  configureApplicationTimeZone,
} from './dateTime'

interface RuntimeBootstrapSettings { timezone?: string }

export async function bootstrapApplicationTimeZone() {
  try {
    const { data } = await axios.get<RuntimeBootstrapSettings>('/api/settings/runtime', { timeout: 1500 })
    return configureApplicationTimeZone(data.timezone || DEFAULT_APPLICATION_TIME_ZONE)
  } catch {
    return configureApplicationTimeZone(DEFAULT_APPLICATION_TIME_ZONE)
  }
}
```

- [ ] **Step 4: Mount Vue only after timezone configuration completes**

Refactor `frontend/src/main.ts` so the existing theme setup remains synchronous, then use:

```ts
import { bootstrapApplicationTimeZone } from './utils/applicationBootstrap'

async function bootstrap() {
  await bootstrapApplicationTimeZone()
  const app = createApp(Root)
  const pinia = createPinia()
  app.use(pinia)
  app.use(router)
  app.use(ElementPlus)
  app.mount('#app')
}

void bootstrap()
```

There must be no path that mounts Vue before `bootstrapApplicationTimeZone()` resolves.

- [ ] **Step 5: Add a source contract for mount ordering**

In `timezoneBootstrap.test.ts`, import `main.ts` as raw text using Vite `?raw` and assert the source contains `await bootstrapApplicationTimeZone()` before `app.mount('#app')`. This avoids needing a DOM-heavy application bootstrap test.

- [ ] **Step 6: Run focused frontend tests and build**

Run:

```bash
cd frontend
npm test -- --run src/dateTime.test.ts src/timezoneBootstrap.test.ts
npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add frontend/src/utils/applicationBootstrap.ts frontend/src/timezoneBootstrap.test.ts frontend/src/main.ts
git commit -m "feat: bootstrap frontend timezone"
```

---

### Task 4: Add an exhaustive regression scanner for datetime presentation

**Files:**
- Create: `frontend/src/dateTimePresentationContract.test.ts`

**Interfaces:**
- Produces: a source-level guard over all production `.ts` and `.vue` files under `frontend/src`.
- Consumed by: Task 5 migration and future CI.

- [ ] **Step 1: Write the source-contract test before migration**

Use Vite raw globbing so the test automatically sees new production files:

```ts
const sources = import.meta.glob('./**/*.{ts,vue}', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>
```

Exclude:

```ts
path.endsWith('.test.ts')
path.endsWith('/utils/dateTime.ts')
```

The test must collect and print every production source path containing browser-local complete datetime formatting. At minimum flag:

```ts
'.toLocaleString('
```

Also flag direct formatter names that currently duplicate complete datetime presentation when their implementation parses a `Date` and returns a date+time string, including source-local `formatTime()` implementations in `CamerasView.vue`, `OperationsView.vue`, `UploadManagementView.vue`, and `AlertSettingsView.vue` until they are migrated.

The failure message must list all offending paths so Task 5 is mechanically exhaustive rather than dependent on a remembered page list.

- [ ] **Step 2: Add preservation assertions for out-of-scope time logic**

The same test should assert representative pure-time/business helpers still exist and are not replaced with `formatDateTime()`:

```ts
expect(playbackEventFeedSource).toContain('function clockLabel')
expect(recordingManagementSource).toContain('function localSeconds')
expect(eventCenterSource).toContain('function activityDayLabel')
```

This protects the agreed scope: display-only complete datetimes, not playback/date-grouping arithmetic.

- [ ] **Step 3: Run the contract test and verify RED**

Run:

```bash
cd frontend
npm test -- --run src/dateTimePresentationContract.test.ts
```

Expected: FAIL and print current offenders, including at least `utils/healthDisplay.ts`, `CamerasView.vue`, `OperationsView.vue`, `UploadManagementView.vue`, and `AlertSettingsView.vue`.

- [ ] **Step 4: Commit the RED guard test**

```bash
git add frontend/src/dateTimePresentationContract.test.ts
git commit -m "test: guard datetime presentation policy"
```

---

### Task 5: Migrate every complete datetime display to the shared formatter

**Files:**
- Modify: `frontend/src/utils/healthDisplay.ts`
- Modify: `frontend/src/CamerasView.vue`
- Modify: `frontend/src/OperationsView.vue`
- Modify: `frontend/src/UploadManagementView.vue`
- Modify: `frontend/src/AlertSettingsView.vue`
- Modify: `frontend/src/RecordingExportHistoryDrawer.vue` where a complete date+time is shown
- Modify: any additional production `.ts`/`.vue` path reported by `dateTimePresentationContract.test.ts`
- Test: `frontend/src/dateTimePresentationContract.test.ts`
- Test: existing feature tests that cover affected views.

**Interfaces:**
- Consumes: `formatDateTime()` from Task 2.
- Does not consume `formatDateTime()` for pure-date, pure-clock, relative labels, duration, wall-clock seconds, seek math, or date filtering.

- [ ] **Step 1: Migrate health presentation helper**

Change `frontend/src/utils/healthDisplay.ts` so its existing `formatTime()` becomes a compatibility wrapper:

```ts
import { formatDateTime } from './dateTime'

export function formatTime(value?: string | null) {
  return formatDateTime(value)
}
```

This automatically fixes `CameraHealthDrawer.vue` and any other health component already using `formatTime()` without changing component APIs.

- [ ] **Step 2: Migrate camera complete datetime presentation**

In `frontend/src/CamerasView.vue`, import `formatDateTime` and replace the local browser-time formatter. Preserve every use of `Date.now()` related to preview cache busting; only the visible `last_probe_at`, `last_online_at`, or equivalent complete datetime output changes.

- [ ] **Step 3: Migrate operations complete datetime presentation**

In `frontend/src/OperationsView.vue`, replace local `formatTime()` with `formatDateTime()` for:

- connectivity monitor `last_cycle_at`;
- log `modified_at`;
- audit event `created_at`.

Do not change the pure-date backup filename logic `new Date().toISOString().slice(0, 10)` in this task because it is not a visible complete datetime field.

- [ ] **Step 4: Migrate upload and alert complete datetime presentation**

In `frontend/src/UploadManagementView.vue`, replace the local `formatTime()` with `formatDateTime()` for task timestamps such as `started_at`, `completed_at`, `next_retry_at`, `created_at`, and `updated_at` wherever displayed.

In `frontend/src/AlertSettingsView.vue`, replace `lastCheckText()` date parsing with:

```ts
return formatDateTime(status.value?.alerts?.monitor?.last_check_at)
```

while preserving `'-'` behavior through the shared formatter.

- [ ] **Step 5: Normalize complete datetime ranges without changing pure clock logic**

In `frontend/src/RecordingExportHistoryDrawer.vue`, distinguish between the user-visible full timestamp and pure clock range pieces:

- If a field is presented as a standalone complete date+time, use `formatDateTime()`.
- Keep `localClock()` for time-only values inside same-day ranges such as `HH:mm:ss – HH:mm:ss`.
- Keep `localDate()` for a pure-date label if it remains date-only.

Do not feed export range math or API request values through `formatDateTime()`.

- [ ] **Step 6: Resolve every additional path printed by the exhaustive scanner**

Run:

```bash
cd frontend
npm test -- --run src/dateTimePresentationContract.test.ts
```

For every production path listed in the failure output, apply the same rule:

- visible date+time -> `formatDateTime()`;
- pure date -> keep existing pure-date renderer;
- pure clock -> keep existing clock renderer;
- relative label -> keep existing relative renderer;
- arithmetic/filter/sort -> keep raw timestamp parsing.

Repeat until the contract test passes with no production browser-local complete datetime formatter remaining.

- [ ] **Step 7: Add representative rendering assertions**

Extend or add focused tests for at least health and one admin view so they prove the shared formatter import is present and local `toLocaleString()` is absent. The utility behavior itself remains covered by `dateTime.test.ts`; these tests only prove wiring.

- [ ] **Step 8: Run all frontend tests, lint, and build**

Run:

```bash
cd frontend
npm run lint
npm test
npm run build
```

Expected: PASS. Existing tests for pure clocks, playback timelines, event grouping, and navigation must remain green without expectation rewrites that change behavior.

- [ ] **Step 9: Commit Task 5**

```bash
git add frontend/src
git commit -m "feat: standardize frontend datetime display"
```

---

### Task 6: End-to-end verification, Docker smoke, and PR readiness

**Files:**
- Modify only if required by test failure: `.github/workflows/ci.yml`
- No database migration files.

**Interfaces:**
- Verifies the complete path `.env TZ -> backend runtime endpoint -> frontend bootstrap -> shared formatter -> UI`.

- [ ] **Step 1: Run full backend verification**

Run:

```bash
cd backend
uv run python -m compileall app
uv run python -m pytest
```

Expected: PASS.

- [ ] **Step 2: Run full frontend verification**

Run:

```bash
cd frontend
npm run lint
npm test
npm run build
```

Expected: PASS.

- [ ] **Step 3: Run whitespace and scope verification**

Run:

```bash
git diff --check main...HEAD
git diff --name-only main...HEAD
```

Verify there are no migration files and no unrelated backend business-time rewrites.

- [ ] **Step 4: Open a Draft PR to trigger the repository CI matrix**

The PR description must explicitly state:

- deployment timezone source is `.env TZ`;
- frontend format is `YYYY-MM-DD HH:mm:ss`;
- pure date/time/relative labels are unchanged;
- playback/date grouping arithmetic is unchanged;
- no database migration.

- [ ] **Step 5: Verify Docker runtime timezone contract**

In Docker smoke, with default Compose `TZ=Asia/Shanghai`, verify:

```bash
curl -fsS http://127.0.0.1:8080/api/settings/runtime
```

contains:

```json
"timezone":"Asia/Shanghai"
```

Do not add `TZ` to the static frontend Nginx container as a supposed browser-time fix; the runtime API is the intended bridge.

- [ ] **Step 6: Verify representative frontend routes load after bootstrap**

Smoke at least:

```bash
curl -fsS http://127.0.0.1:8080/ >/dev/null
curl -fsS http://127.0.0.1:8080/cameras >/dev/null
curl -fsS http://127.0.0.1:8080/events >/dev/null
curl -fsS http://127.0.0.1:8080/settings?section=operations >/dev/null
curl -fsS http://127.0.0.1:8080/uploads >/dev/null
```

The frontend must still mount even if the runtime timezone request is unavailable because Task 3 has a Shanghai fallback.

- [ ] **Step 7: Review CI evidence**

Require all changed-path jobs to be green:

- changes / `git diff --check`;
- frontend lint + full Vitest + `vue-tsc` + Vite build;
- backend compileall + full pytest;
- Docker smoke.

- [ ] **Step 8: Commit any final verification-only change**

Only if CI required a workflow smoke assertion, commit it separately:

```bash
git add .github/workflows/ci.yml
git commit -m "test: verify runtime timezone in docker smoke"
```

Otherwise no extra commit is required.

## Self-review results

- **Spec coverage:** All spec requirements map to Tasks 1-6: deployment timezone source, backend validation, runtime API, pre-mount frontend bootstrap, deterministic formatter, legacy preformatted-value compatibility, global migration, regression guard, and final CI/Docker verification.
- **Scope protection:** `EventCenterView.vue` date grouping and `todayString()`, `DashboardView.vue` relative activity labels, `PlaybackEventFeed.vue` pure clock labels, and `RecordingManagementView.vue` wall-clock arithmetic remain explicitly outside formatter migration unless they display a complete datetime.
- **Type consistency:** `configured_timezone_name()`, `configured_timezone()`, `configureApplicationTimeZone()`, `applicationTimeZone()`, `formatDateTime()`, and `bootstrapApplicationTimeZone()` are defined once and consumed consistently by later tasks.
- **Placeholder scan:** No TODO/TBD/implementation-later placeholders remain; every task has a RED command, concrete implementation contract, GREEN command, and commit boundary.
