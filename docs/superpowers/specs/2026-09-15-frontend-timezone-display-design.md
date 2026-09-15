# Frontend Timezone Display Design

Date: 2026-09-15
Status: Approved for specification review
Scope: Global frontend date+time rendering only

## 1. Goal

Make every frontend field that visibly renders a complete date and time use the deployment timezone configured by `.env` `TZ`, with a single deterministic format:

```text
YYYY-MM-DD HH:mm:ss
```

For the current deployment default:

```env
TZ=Asia/Shanghai
```

an instant such as `2026-09-14T17:01:01Z` must render as:

```text
2026-09-15 01:01:01
```

The result must be identical even when the browser/device itself is in another timezone such as America/Los_Angeles.

## 2. Non-goals

This change does not redefine all time behavior in the application.

The following remain as they are unless they currently render a complete date+time string:

- pure dates such as `2026-09-15`;
- pure clock values such as `01:01:01`;
- relative labels such as `今天`, `昨天`, `刚刚`, `5分钟前`;
- duration values such as `3分 20秒`;
- timeline arithmetic, playback seek math, event sorting, and duration calculations;
- database timestamp storage;
- recording/event table migrations;
- API query semantics for start/end filters.

This phase is a presentation standardization, not a rewrite of temporal business logic.

## 3. Why `.env TZ` does not currently guarantee frontend display

`TZ` currently reaches the backend and OpenList containers through Docker Compose, but Vue code runs in the user's browser. Browser APIs such as:

```ts
new Date(value).toLocaleString()
```

use the browser/device timezone unless an explicit `timeZone` is supplied.

There is a second complication: SQLite `CURRENT_TIMESTAMP` is UTC regardless of the container's `TZ`. The backend already accounts for this in `EventRead`, where a SQLite naive timestamp is treated as UTC and converted using the configured deployment timezone before serialization.

Therefore the system must explicitly separate:

1. the instant stored/transmitted by backend data;
2. the deployment timezone used for human presentation;
3. the browser's own local timezone, which must not control product display.

## 4. Source of truth for application timezone

`.env` `TZ` remains the deployment-level source of truth.

The backend will expose the validated effective timezone to the frontend through the existing runtime-settings endpoint:

```http
GET /api/settings/runtime
```

The response gains:

```json
{
  "timezone": "Asia/Shanghai"
}
```

No separate frontend-only timezone setting is introduced.

### 4.1 Backend timezone helper

Timezone lookup/validation will be centralized in a small backend helper rather than repeated in schemas.

Conceptual API:

```py
configured_timezone_name() -> str
configured_timezone() -> tzinfo
```

Rules:

- missing/blank `TZ` -> `Asia/Shanghai`;
- valid IANA timezone -> use that timezone;
- invalid IANA timezone -> fall back to `UTC` rather than crashing the API;
- the existing `EventRead` serializer will use the same helper, preserving current behavior while removing duplicate timezone resolution logic.

This keeps `.env TZ` as the only deployment source while making it available consistently to both backend serializers and frontend bootstrap.

## 5. Frontend bootstrap

The frontend must know the application timezone before the first application render so timestamps do not initially flash in the browser timezone and then change.

`frontend/src/main.ts` will perform a bounded bootstrap request to:

```http
GET /api/settings/runtime
```

before mounting Vue.

The bootstrap only needs the timezone field for this feature. If the request fails, times out, or returns an invalid timezone, the frontend uses:

```text
Asia/Shanghai
```

as its safe product fallback and continues mounting. A runtime-settings outage must not prevent the UI from loading.

Changing `.env TZ` is a deployment configuration change and is expected to take effect after service restart/redeploy and browser reload; live timezone mutation while a page is already open is out of scope.

## 6. Frontend date-time utility

Add a single module:

```text
frontend/src/utils/dateTime.ts
```

It owns all complete date+time presentation.

Conceptual interface:

```ts
configureApplicationTimeZone(timeZone: string): void
applicationTimeZone(): string
formatDateTime(value?: string | Date | null): string
```

`formatDateTime` returns exactly:

```text
YYYY-MM-DD HH:mm:ss
```

It uses `Intl.DateTimeFormat` with an explicit `timeZone` and `formatToParts`, not locale-dependent `toLocaleString()`, so punctuation/order cannot vary by browser locale.

### 6.1 Input compatibility rules

The existing backend currently has more than one timestamp representation, so the formatter must avoid double conversion.

#### Explicit instant

Input carrying `Z` or a numeric offset is an absolute instant:

```text
2026-09-14T17:01:01Z
2026-09-15T01:01:01+08:00
```

Parse it as an instant and render it in the configured application timezone.

#### Existing human-facing backend value

The event API currently serializes `EventRead.created_at` as an already-converted display value:

```text
2026-09-15 01:01:01
```

A value matching the exact `YYYY-MM-DD HH:mm:ss` shape is already in deployment-local presentation form. The formatter returns it unchanged. This prevents the frontend from treating it as browser-local and shifting it a second time.

#### Naive ISO API datetime

A timezone-less ISO API value such as:

```text
2026-09-14T17:01:01
```

is treated as UTC for presentation purposes. This matches the project's SQLite/UTC storage convention and prevents the browser's local timezone from silently becoming part of the interpretation.

This compatibility behavior belongs only in the presentation formatter. Existing timeline/query code is not rewritten to use it for arithmetic.

#### Invalid/empty value

- null/undefined/empty -> `-`;
- unparseable non-empty string -> return the original text rather than inventing a timestamp.

## 7. Rendering scope

The implementation will audit all of `frontend/src`, not just the page that exposed the issue.

Every visible complete date+time field must route through `formatDateTime()`.

Expected areas include, but are not limited to:

- dashboard/realtime health timestamps;
- health center;
- camera details and connectivity/probe timestamps;
- recording management/list/detail timestamps;
- playback event/detail timestamps when they include both date and time;
- event center system event timestamps;
- event-detection event timestamps;
- upload management timestamps;
- operations/audit/maintenance timestamps;
- alert/notification timestamps;
- settings/status panels that show last-run/updated-at timestamps.

The audit must also catch helper functions such as the existing health `formatTime()` that call browser-local `toLocaleString()`.

Pure-date and pure-clock renderers are deliberately excluded unless a component currently combines them into a complete date+time display.

## 8. Guardrails against regression

After migration, product code must not introduce new browser-local complete datetime formatting.

Tests will enforce that direct complete-datetime formatters do not spread again. In particular:

- `Date#toLocaleString()` for product datetime rendering is forbidden outside the shared utility;
- direct `Intl.DateTimeFormat` instances for complete datetime display are forbidden outside the shared utility;
- page-local `formatDateTime`/`formatTime` implementations that duplicate the shared formatter should be removed or reduced to wrappers only when required for compatibility.

The rule does not ban `Date` usage for arithmetic, sorting, duration calculations, date pickers, or relative labels.

## 9. Backend/API compatibility

No timestamp database migration is required.

No existing event/recording tables are renamed or rewritten.

Existing API timestamp fields remain compatible. The only additive API contract is:

```json
GET /api/settings/runtime
{
  "timezone": "Asia/Shanghai"
}
```

The existing human-facing `EventRead.created_at` format remains accepted and must not be double-shifted by the frontend.

Future backend work may normalize all API timestamps to offset-aware ISO 8601, but that is explicitly outside this phase because it would touch playback/query contracts and is not required to fix frontend presentation.

## 10. Error handling

Timezone configuration must fail safe.

Backend:

- invalid `TZ` -> effective timezone `UTC`;
- runtime endpoint still returns successfully with `timezone: "UTC"`.

Frontend:

- runtime-settings request failure -> use `Asia/Shanghai` fallback;
- invalid timezone returned by server -> use `Asia/Shanghai` fallback;
- invalid timestamp value -> preserve original visible text, or `-` for empty values;
- formatting failures must not crash a page.

## 11. Testing strategy

### Backend

Add/extend tests for:

- runtime settings exposes `Asia/Shanghai` when configured;
- missing `TZ` resolves to `Asia/Shanghai`;
- invalid `TZ` resolves to `UTC`;
- `EventRead` continues using the same centralized timezone helper and retains its current expected Shanghai conversion.

### Frontend utility

Tests must cover at least:

```text
configured timezone: Asia/Shanghai
input:  2026-09-14T17:01:01Z
output: 2026-09-15 01:01:01
```

and:

```text
input:  2026-09-15T01:01:01+08:00
output: 2026-09-15 01:01:01
```

and the existing human-facing compatibility input:

```text
input:  2026-09-15 01:01:01
output: 2026-09-15 01:01:01
```

and a naive UTC API value:

```text
input:  2026-09-14T17:01:01
output: 2026-09-15 01:01:01
```

Tests must remain correct even when the test process/browser timezone is not Asia/Shanghai.

### Frontend integration

Add focused tests/source-contract checks to prove:

- application bootstrap configures timezone before mount;
- representative health/event/recording/operations timestamps use the shared formatter;
- no migrated page falls back to browser-local `toLocaleString()`;
- pure date/time and relative-label behavior is not intentionally changed by this work.

### Final verification

Run:

- frontend lint;
- full frontend tests;
- `vue-tsc`/production build;
- backend full pytest;
- backend compileall;
- Docker Compose smoke;
- browser/deep-link smoke for representative pages after containers start.

## 12. Acceptance criteria

This feature is complete when all of the following are true:

1. `.env TZ=Asia/Shanghai` is the effective deployment timezone source.
2. The frontend receives the effective timezone from the backend at bootstrap.
3. A complete date+time is always rendered as `YYYY-MM-DD HH:mm:ss`.
4. Rendering does not change when the client machine/browser timezone changes.
5. Existing preformatted event timestamps are not shifted twice.
6. Pure date, pure time, relative labels, durations, timeline arithmetic, and query semantics remain outside the scope of this display migration.
7. Direct browser-local complete datetime formatting is removed from migrated product UI and protected by regression tests.
8. Full frontend/backend/Docker CI is green before merge/deployment.
