# Camera LAN Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit LAN discovery to the unified camera editor: ONVIF via WS-Discovery and Manual RTSP via bounded TCP-554 scanning, without automatic Camera creation or credential use.

**Architecture:** A minimal host-network `onvif-discovery` helper runs from the existing backend image and exposes credential-free scan operations over a shared Unix Domain Socket. The bridge-networked backend proxies those operations through `/api/camera-discovery/onvif` and `/api/camera-discovery/rtsp`; the existing `CameraEditorDialog` consumes the temporary candidates and continues using the existing Probe/save paths.

**Tech Stack:** Python 3.12, FastAPI, httpx UDS transport, asyncio/socket/XML stdlib, psutil, Docker Compose, Vue 3 + TypeScript + Element Plus, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-18-onvif-ws-discovery-design.md`

## Global Constraints

- Scanning is explicit user action only; never background/startup scanning.
- Discovery never receives usernames/passwords and never creates/updates Camera rows.
- ONVIF scan default duration is 3 seconds with a 5-second backend/helper hard deadline.
- ONVIF candidates without a safe HTTP/HTTPS XAddr remain visible but unselectable.
- Manual RTSP scan targets only TCP 554 on the default-route IPv4 /24, max 254 hosts, max 64 concurrent connects, 300 ms per host, 3-second overall deadline.
- RTSP discovery sends no application bytes and never guesses stream paths.
- Backend remains on Compose bridge networking; only the helper uses host networking.
- Backend/helper share a named UDS runtime volume; no helper TCP port is published.
- Helper failure must not stop recording core or make deploy.sh return failure when core services are healthy.
- Manual ONVIF/RTSP entry and existing authenticated Probe/save flows remain available.
- HIK SDK has no LAN scan action in this slice.
- No database migration and no destructive Camera Contract cleanup.

---

### Task 1: Discovery schemas and pure ONVIF/RTSP discovery core

**Files:**
- Create: `backend/app/schemas/camera_discovery.py`
- Create: `backend/app/services/camera_discovery.py`
- Modify: `backend/app/services/onvif_client.py`
- Test: `backend/tests/test_camera_discovery.py`

**Interfaces:**
- Produces `OnvifDiscoveryCandidate`, `OnvifDiscoveryResponse`, `RtspDiscoveryCandidate`, `RtspDiscoveryResponse`.
- Produces `parse_probe_matches(xml, source_host)`, `merge_onvif_candidates(...)`, `scan_onvif(timeout_seconds=3.0)`, `default_route_ipv4_network()`, `scan_rtsp_port_554()`.
- Exposes public `validate_service_url(url: str) -> str` from the existing ONVIF client safety rule.

- [ ] **Step 1: Write failing parser/normalization tests**

```python
def test_probe_match_without_xaddr_remains_visible_but_unselectable():
    candidates, warnings = parse_probe_matches(PROBE_MATCH_WITHOUT_XADDR, "192.168.1.20")
    assert warnings == []
    assert candidates[0].endpoint_reference == "urn:uuid:camera-1"
    assert candidates[0].selectable is False
    assert candidates[0].device_service_url is None

def test_credential_bearing_xaddr_is_not_selectable():
    candidates, _ = parse_probe_matches(PROBE_MATCH_WITH_CREDENTIAL_XADDR, "192.168.1.21")
    assert candidates[0].xaddrs == []
    assert candidates[0].selectable is False

def test_duplicate_epr_merges_unique_scopes_and_xaddrs():
    merged = merge_onvif_candidates([FIRST_MATCH, SECOND_MATCH])
    assert len(merged) == 1
    assert merged[0].xaddrs == [
        "http://192.168.1.50/onvif/device_service",
        "http://camera.local/onvif/device_service",
    ]
```

Run: `cd backend && uv run pytest tests/test_camera_discovery.py -q`
Expected: FAIL because the module/functions do not exist.

- [ ] **Step 2: Implement WS-Discovery XML generation/parsing and safe candidate merge**

Implement a fresh WS-Addressing UUID Probe for `dn:NetworkVideoTransmitter`, defensive ProbeMatch parsing, safe HTTP/HTTPS XAddr validation, IP-host preference, sanitized warnings, EPR/XAddr fallback deduplication, and a 256-candidate cap.

- [ ] **Step 3: Write failing RTSP network/scan tests**

```python
async def test_rtsp_scanner_connects_only_to_554_and_writes_nothing(monkeypatch):
    calls = []
    async def fake_open(host, port):
        calls.append((host, port))
        return FakeReader(), FakeWriter()
    result = await scan_rtsp_port_554(
        network=ipaddress.ip_network("192.168.10.0/24"),
        self_ip=ipaddress.ip_address("192.168.10.10"),
        open_connection=fake_open,
    )
    assert all(port == 554 for _, port in calls)
    assert all(writer.writes == [] for writer in CREATED_WRITERS)
```

Run: same pytest command.
Expected: FAIL because RTSP scanner functions do not exist.

- [ ] **Step 4: Implement bounded RTSP TCP-554 scanner**

Parse Linux default route, resolve its interface IPv4 through psutil, derive strict /24, exclude network/broadcast/self, use semaphore 64, 300 ms connect timeout and 3-second overall timeout, close writers without writing data, and numerically sort successful IPv4 candidates.

- [ ] **Step 5: Implement bounded UDP WS-Discovery scanner**

Use IPv4 UDP multicast `239.255.255.250:3702`, receive until monotonic deadline, ignore oversized/malformed datagrams safely, close socket deterministically, merge repeated ProbeMatches and return scan duration/warnings.

- [ ] **Step 6: Run discovery unit tests**

Run: `cd backend && uv run pytest tests/test_camera_discovery.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

`git commit -m "feat: add camera LAN discovery core"`

### Task 2: Host-network UDS helper and backend discovery API

**Files:**
- Create: `backend/app/discovery_helper.py`
- Create: `backend/app/services/camera_discovery_client.py`
- Create: `backend/app/api/camera_discovery.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_camera_discovery_helper.py`
- Test: `backend/tests/test_camera_discovery_api.py`

**Interfaces:**
- Helper: `GET /health`, `POST /scan/onvif`, `POST /scan/rtsp`.
- Backend: `POST /api/camera-discovery/onvif`, `POST /api/camera-discovery/rtsp`.
- Client: `CameraDiscoveryClient.scan_onvif()`, `CameraDiscoveryClient.scan_rtsp()` over httpx `AsyncHTTPTransport(uds=...)`.
- Setting: `settings.onvif_discovery_socket: Path`.

- [ ] **Step 1: Write failing helper tests**

```python
def test_helper_scan_contract_has_no_credentials(client, monkeypatch):
    response = client.post("/scan/rtsp", json={})
    assert response.status_code == 200
    assert "username" not in response.text
    assert "password" not in response.text
```

Run: `cd backend && uv run pytest tests/test_camera_discovery_helper.py -q`
Expected: FAIL because helper app does not exist.

- [ ] **Step 2: Implement helper FastAPI app**

Expose only health and the two scan operations. Use fixed server-side limits; reject extra request fields. No DB imports, no credential schemas, no persistence.

- [ ] **Step 3: Write failing backend API tests**

```python
def test_onvif_discovery_api_proxies_candidates(monkeypatch):
    async def fake_scan():
        return OnvifDiscoveryResponse(devices=[CANDIDATE], scan_duration_ms=10, warnings=[])
    monkeypatch.setattr(camera_discovery_api.discovery_client, "scan_onvif", fake_scan)
    with TestClient(app) as client:
        response = client.post("/api/camera-discovery/onvif")
    assert response.status_code == 200
    assert response.json()["devices"][0]["host"] == "192.168.1.50"

def test_helper_unavailable_returns_503(monkeypatch):
    async def unavailable():
        raise CameraDiscoveryUnavailable("socket missing")
    ...
    assert response.status_code == 503
```

Run: API test file.
Expected: FAIL because route/client do not exist.

- [ ] **Step 4: Implement UDS client and backend proxy router**

Use a 5-second overall httpx timeout, typed Pydantic validation, sanitized 503 for missing/refused socket and safe 502 for malformed helper responses. Register router in `app.main`.

- [ ] **Step 5: Run helper/API tests**

Run: `cd backend && uv run pytest tests/test_camera_discovery_helper.py tests/test_camera_discovery_api.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

`git commit -m "feat: expose camera discovery helper API"`

### Task 3: Preserve discovered ONVIF Device Service URLs through Probe/save

**Files:**
- Modify: `backend/app/schemas/camera_connection.py`
- Modify: `backend/app/services/camera_adapter_probe.py`
- Modify: `backend/app/services/camera_mutation.py`
- Modify: `frontend/src/camera-editor/types.ts`
- Modify: `frontend/src/camera-editor/model.ts`
- Test: `backend/tests/test_camera_adapter_api.py` or nearest unified adapter API test file
- Test: `frontend/src/cameraEditorModel.test.ts`

**Interfaces:**
- `OnvifConnectionCreate/Update.device_service_url: str | None`.
- `OnvifEditorDraft.device_service_url: string`.
- Manual host/port entry with empty explicit URL continues deriving `http://<host>:<port>/onvif/device_service`.

- [ ] **Step 1: Write failing backend tests for non-default HTTPS/path URL**

```python
def test_onvif_probe_preserves_explicit_device_service_url(monkeypatch):
    payload = {
        "connection": {
            "adapter": "onvif",
            "host": "camera.local",
            "port": 8443,
            "device_service_url": "https://camera.local:8443/custom/device",
            ...
        }
    }
    ...
    assert captured_url == "https://camera.local:8443/custom/device"
```

Expected: FAIL because current schema forbids `device_service_url`.

- [ ] **Step 2: Add safe optional URL to ONVIF create/update schemas and service paths**

Validate with `validate_service_url`; require URL hostname to match the declared `host` after normalized bracket handling, derive default when omitted, use the explicit URL for Probe and canonical ONVIF config persistence.

- [ ] **Step 3: Write failing frontend model tests**

Verify draft restoration includes existing `config.device_service_url`, discovered URL participates in connection fingerprint/payload, and manually changing authority can clear it in the editor layer.

- [ ] **Step 4: Update editor model types/payload generation**

Add `device_service_url` only to ONVIF draft/payload; preserve existing default behavior when blank.

- [ ] **Step 5: Run backend + frontend model tests**

Run:
- `cd backend && uv run pytest <unified-camera-test-file> -q`
- `cd frontend && npm test -- cameraEditorModel.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

`git commit -m "feat: preserve discovered ONVIF service URLs"`

### Task 4: Compose/deploy integration for the discovery helper

**Files:**
- Modify: `docker-compose.yml`
- Modify: `deploy.sh`
- Modify: `.env.example` only if an operator-visible socket override is intentionally exposed; otherwise leave unchanged.
- Create: `backend/tests/test_camera_discovery_deploy_contract.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Named volume: `camera-discovery-runtime`.
- Helper container: `camera-recorder-onvif-discovery`.
- Socket: `/run/camera-recorder/onvif-discovery.sock`.
- Backend env: `CAMREC_ONVIF_DISCOVERY_SOCKET=/run/camera-recorder/onvif-discovery.sock`.

- [ ] **Step 1: Write failing Compose/deploy contract tests**

```python
def test_discovery_helper_uses_host_network_and_no_ports():
    service = _compose_config()["services"]["onvif-discovery"]
    assert service["network_mode"] == "host"
    assert not service.get("ports")
    assert "camera-discovery-runtime:/run/camera-recorder" in service["volumes"]

def test_backend_does_not_depend_on_discovery_helper():
    backend = _compose_config()["services"]["backend"]
    assert "onvif-discovery" not in backend.get("depends_on", {})
```

Expected: FAIL before Compose changes.

- [ ] **Step 2: Add helper service and named volume**

Reuse `camera-recorder-core:local`; command unlinks stale socket then runs:
`uvicorn app.discovery_helper:app --uds /run/camera-recorder/onvif-discovery.sock`.
Healthcheck performs a Unix-socket connect/readiness check without scanning.

- [ ] **Step 3: Update deploy classification/stage**

Add `UPDATE_DISCOVERY`; backend/shared runtime changes recreate helper, frontend-only changes do not. After core health checks, start/recreate helper as a best-effort stage. Failure logs a warning and leaves final core deployment success intact.

- [ ] **Step 4: Update docker-smoke workflow**

Validate helper Compose topology, start helper after backend, wait for helper health, verify the backend container can call helper `GET /health` over the shared UDS, but never invoke actual LAN scans in CI.

- [ ] **Step 5: Run deploy-contract tests**

Run: `cd backend && uv run pytest tests/test_camera_discovery_deploy_contract.py tests/test_hik_deploy_contract.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

`git commit -m "feat: deploy LAN discovery helper"`

### Task 5: Unified discovery chooser in CameraEditorDialog

**Files:**
- Create: `frontend/src/CameraDiscoveryDialog.vue`
- Create: `frontend/src/camera-discovery/types.ts`
- Modify: `frontend/src/CameraEditorDialog.vue`
- Modify: `frontend/src/styles/camera-editor-dialog.css`
- Create: `frontend/src/cameraDiscoveryDialog.test.ts`
- Modify: `frontend/src/cameraEditorDialog.test.ts`

**Interfaces:**
- Props: `modelValue: boolean`, `adapter: 'manual_rtsp' | 'onvif'`.
- Emits: `selected` with a typed RTSP or ONVIF candidate.
- Endpoints: `POST /api/camera-discovery/rtsp`, `POST /api/camera-discovery/onvif`.

- [ ] **Step 1: Write failing frontend source/model contract tests**

```ts
it('shows discovery only for Manual RTSP and ONVIF', () => {
  expect(editorSource).toContain('<CameraDiscoveryDialog')
  expect(editorSource).toContain("form.adapter === 'manual_rtsp'")
  expect(editorSource).toContain("form.adapter === 'onvif'")
  expect(editorSource).not.toContain("form.adapter === 'hik_sdk' && discovery")
})
```

Expected: FAIL because component does not exist.

- [ ] **Step 2: Implement typed discovery dialog**

Show loading/count/network, Rescan, candidates, unselectable ONVIF reasons. RTSP rows show `host:554`; ONVIF rows show host/device service URL/scopes. Never display or request credentials.

- [ ] **Step 3: Integrate beside the address field**

Use one “扫描局域网” action for Manual RTSP/ONVIF. HIK renders no scan action.

Selecting RTSP candidate changes only host/port.

Selecting ONVIF candidate changes host/port/device_service_url only.

Do not auto-Probe, auto-Save, clear username/password, or change identity/runtime fields.

- [ ] **Step 4: Handle discovered ONVIF URL invalidation**

When a user manually edits host/port after selection, clear the explicit discovered URL unless its normalized authority still matches. A new selected candidate replaces it.

- [ ] **Step 5: Run frontend tests/lint/build**

Run:
- `cd frontend && npm test -- cameraDiscoveryDialog.test.ts cameraEditorDialog.test.ts cameraEditorModel.test.ts`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

`git commit -m "feat: add LAN scan to camera editor"`

### Task 6: Full regression verification and status documentation

**Files:**
- Modify: `docs/V1_STATUS.md`
- Modify: `docs/ROADMAP.md` only where current-state checkboxes can be truthfully closed by this slice.
- Modify: PR description after verification.

**Interfaces:**
- No new runtime interfaces.

- [ ] **Step 1: Run focused backend discovery suite**

`cd backend && uv run pytest tests/test_camera_discovery.py tests/test_camera_discovery_helper.py tests/test_camera_discovery_api.py tests/test_camera_discovery_deploy_contract.py -q`

- [ ] **Step 2: Run existing ONVIF/unified adapter regressions**

`cd backend && uv run pytest tests/test_onvif_client.py tests/test_onvif_camera_api.py tests/test_camera_adapter_api.py -q` using the actual unified test filename present in the repository.

- [ ] **Step 3: Run full frontend validation**

`cd frontend && npm run lint && npm test && npm run build`

- [ ] **Step 4: Run backend quality/full CI through GitHub**

Require compileall/Ruff, all backend shards, frontend, and docker-smoke on the exact PR head.

- [ ] **Step 5: Update status docs**

Record LAN discovery as implemented code while keeping real-LAN camera validation as field acceptance. Do not mark ONVIF Events/PTZ complete.

- [ ] **Step 6: Review changed-file scope**

Confirm no DB migration, no legacy Contract removal, no credential persistence in discovery, no auto Camera creation, and no backend host-network change.

- [ ] **Step 7: Mark Ready and merge only after exact-head green**

Use expected-head SHA protection for merge.
