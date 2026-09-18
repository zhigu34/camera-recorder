# ONVIF WS-Discovery Design

Status: **Approved in chat — implementation-ready**

Date: 2026-09-18

## Goal

Add explicit, user-triggered LAN discovery for ONVIF devices without changing the current Camera identity model or creating a second ONVIF camera workflow.

Discovery produces temporary device candidates only. A user selects a candidate to prefill the existing `CameraEditorDialog`, then enters credentials, runs the existing ONVIF Probe if desired, and saves through the unified Camera API.

This is the first Post-V1 ONVIF capability slice.

## Non-goals

This phase does **not** implement:

- automatic background LAN scanning;
- automatic Camera creation;
- credential probing during WS-Discovery;
- persistence of discovery results;
- ONVIF PullPoint / Events subscriptions;
- PTZ control;
- native smart-event ingestion;
- a separate ONVIF add page;
- changes to stable Camera IDs/history semantics;
- destructive Camera architecture Contract cleanup.

Events/PTZ remain separate follow-up slices.

## Confirmed Product Flow

The existing unified editor remains the only camera add/edit surface.

### Manual RTSP

The editor shows Manual RTSP connection fields only. No discovery action is shown.

### ONVIF

When `adapter=onvif`, the editor shows the normal ONVIF connection fields plus:

`扫描局域网 ONVIF 设备`

The flow is:

```text
Select ONVIF
  -> optionally scan LAN
  -> review temporary candidates
  -> select one candidate
  -> prefill host / ONVIF service port and safe discovery metadata
  -> enter username/password
  -> optionally run existing connection Probe
  -> Probe enriches device information / Media Profiles / RTSP URIs
  -> save through the existing unified /api/cameras mutation
```

Scanning is always optional. Users who already know the camera address may continue entering it manually.

### HIK SDK

The editor shows HIK SDK connection fields only. ONVIF discovery is not shown.

## Discovery Semantics

A scan is explicitly triggered by the user. Camera Recorder MUST NOT run WS-Discovery continuously or at backend startup.

A scan:

- sends a WS-Discovery Probe over UDP multicast;
- listens for ProbeMatches for a bounded interval;
- normalizes and deduplicates responses;
- returns temporary candidates;
- writes nothing to SQLite;
- does not create or update Camera/CameraConnection rows;
- does not request or receive device usernames/passwords.

Default scan duration: **3 seconds**.

Backend API requests have a hard overall discovery timeout of **5 seconds** so a broken helper or multicast stack cannot hold an HTTP request indefinitely.

## Candidate Model

Each candidate contains only non-secret discovery information:

```json
{
  "endpoint_reference": "urn:uuid:...",
  "xaddrs": [
    "http://192.168.1.50/onvif/device_service"
  ],
  "scopes": [
    "onvif://www.onvif.org/type/video_encoder",
    "onvif://www.onvif.org/name/front-door"
  ],
  "device_service_url": "http://192.168.1.50/onvif/device_service",
  "host": "192.168.1.50",
  "port": 80,
  "selectable": true,
  "unavailable_reason": null
}
```

### Selectability

All discovered responses remain visible for diagnostics.

A candidate is selectable only when Camera Recorder can derive a safe ONVIF Device Service URL from the returned XAddr list.

Selectable XAddr requirements:

- scheme is `http` or `https`;
- hostname is present;
- URL contains no embedded username/password;
- port is valid when present;
- URL passes the same service-URL safety rules used by the existing ONVIF client.

If a device advertises UUID/scopes but no usable XAddr:

```text
selectable=false
unavailable_reason="设备已响应 WS-Discovery，但未提供可用的 ONVIF Device Service 地址"
```

The candidate still appears in the discovery result UI but cannot be selected.

## Candidate Deduplication

Deduplicate in this order:

1. normalized endpoint reference / UUID when present;
2. otherwise normalized safe Device Service URL;
3. otherwise response source + normalized scope set.

When duplicate responses contain multiple XAddrs/scopes, merge unique values.

For each merged candidate choose the preferred Device Service URL using:

1. HTTP/HTTPS XAddr whose hostname is an IP address;
2. otherwise any valid HTTP/HTTPS XAddr;
3. preserve all valid XAddrs in `xaddrs` for diagnostics.

Do not perform DNS resolution or probe candidate XAddrs during discovery.

## Network Architecture

The existing backend remains on the normal Compose bridge network.

Do **not** change the backend to `network_mode: host`.

Introduce a minimal internal helper service:

```text
onvif-discovery
```

with:

```yaml
network_mode: host
```

The helper exists only to obtain host/LAN multicast network visibility required by WS-Discovery.

### Backend/helper transport

Backend and helper communicate through a shared Unix Domain Socket, not a TCP port.

Example runtime socket:

```text
/run/camera-recorder/onvif-discovery.sock
```

Both containers mount the same small Compose named volume at `/run/camera-recorder`.

Use a named volume rather than a host bind mount so deployment does not depend on host-directory ownership, SELinux labels, or stale socket files from an earlier container instance.

The helper must unlink any stale `onvif-discovery.sock` before binding and must remove it on clean shutdown.

The helper listens on the Unix socket and exposes only an internal scan operation.

Benefits:

- no helper TCP port is exposed on the host;
- no Docker bridge multicast assumptions;
- backend remains isolated from host networking;
- helper does not need database/storage mounts;
- helper remains a narrow LAN-discovery capability.

## Helper Security Boundary

The helper MUST NOT receive or access:

- Camera passwords;
- encrypted credentials;
- Camera database;
- recordings;
- staging/upload data;
- OpenList configuration;
- HIK runtime.

The helper receives only a bounded discovery request such as:

```json
{
  "timeout_seconds": 3.0
}
```

and returns normalized discovery candidates.

It does not persist state between requests.

## Backend API

Add:

```text
POST /api/onvif-discovery/scan
```

No credentials are accepted.

Suggested response:

```json
{
  "devices": [...],
  "scan_duration_ms": 3012,
  "warnings": []
}
```

### Failure semantics

If the helper is unavailable:

- return HTTP 503;
- detail explains that ONVIF LAN discovery is unavailable;
- manual ONVIF address entry remains usable.

If discovery times out normally:

- return HTTP 200 with an empty `devices` list.

Malformed individual ProbeMatches are ignored and surfaced as a sanitized warning count/message; one malformed device MUST NOT fail the entire scan.

The API MUST NOT expose raw XML packets.

## WS-Discovery Implementation

Implement the minimal ONVIF discovery subset directly rather than adding a large ONVIF framework dependency.

Discovery uses:

```text
UDP multicast: 239.255.255.250:3702
WS-Discovery Probe
ONVIF NetworkVideoTransmitter type
```

The implementation should:

- generate a fresh WS-Addressing message UUID per scan;
- bind an IPv4 UDP socket suitable for receiving multicast responses;
- send a standards-compatible Probe;
- receive until the monotonic deadline;
- tolerate duplicate/multi-packet ProbeMatches;
- parse XML defensively;
- cap packet size / candidate count;
- normalize XAddrs/scopes;
- close the socket deterministically.

Initial limits:

- scan duration: 3 seconds;
- hard HTTP/helper deadline: 5 seconds;
- maximum UDP payload processed: 64 KiB per datagram;
- maximum normalized candidates returned: 256.

IPv4 discovery is the required first slice. IPv6 WS-Discovery is deferred.

The first supported deployment target for LAN discovery is Linux Docker Engine. If host networking is unavailable on the current container platform, the helper must fail its own readiness cleanly and the backend must expose discovery as unavailable without affecting manual ONVIF configuration or recording core health.

## Deployment

Add `onvif-discovery` to `docker-compose.yml`.

It reuses the existing Camera Recorder backend image/runtime rather than introducing another language/runtime.

The helper:

- uses `network_mode: host` on Linux deployments;
- has no published ports;
- mounts only the shared named runtime-socket volume;
- starts a small dedicated helper entrypoint;
- has a healthcheck that validates process/socket readiness without performing LAN scans.

Backend mounts the same runtime-socket path and receives:

```text
CAMREC_ONVIF_DISCOVERY_SOCKET=/run/camera-recorder/onvif-discovery.sock
```

The discovery helper is an optional-adjunct stage of the normal deployment because it contains no proprietary dependency but is not required for reliable recording.

Deployment order is:

1. bring the normal recording core (`backend`, `frontend`, `openlist`) to its requested healthy state;
2. then start/recreate `onvif-discovery`.

A discovery-helper startup/health failure MUST:

- leave healthy core services running;
- print an actionable warning;
- record discovery as unavailable for that deployment;
- still return a successful overall deployment exit status when the recording core succeeded.

This differs intentionally from explicitly enabled HIK capability, where a requested HIK failure returns non-zero. LAN discovery is convenience functionality and must never turn a healthy recording deployment into a failed deployment.

The backend capability behavior is graceful: when the helper is unavailable, only LAN discovery is unavailable; manually configured ONVIF cameras and the existing ONVIF Probe continue to work.

## Deploy Script Behavior

The deployment classifier must understand the helper explicitly.

Expected behavior:

- frontend-only changes: do not restart discovery helper;
- WS-Discovery/helper backend code changes: rebuild backend image and recreate helper;
- shared backend runtime/dependency changes: recreate backend and helper;
- Compose changes: validate/update helper as part of the core deployment plan;
- helper startup failure: warn, leave the healthy recorder backend/frontend stack untouched, and keep the overall deploy exit status successful;
- a later backend/helper code change should retry helper recreation automatically.

## Frontend UX

Discovery appears inside `CameraEditorDialog` only when:

```text
form.adapter === 'onvif'
```

Place the action next to the ONVIF device-address field:

```text
设备地址   [ 192.168.1.50 ] [扫描局域网]
```

Clicking it opens a discovery dialog/panel containing:

- scan status;
- candidate count;
- endpoint/host;
- safe Device Service address;
- useful decoded scope labels when available;
- selectable/unselectable state;
- reason for an unselectable device;
- Rescan action.

Selecting a valid candidate:

- sets ONVIF `host`;
- derives and sets ONVIF `port`;
- retains the selected `device_service_url` in the editor draft for the subsequent Probe;
- does not set username/password;
- does not automatically Probe;
- does not automatically save;
- closes the discovery chooser.

For an existing Camera, selecting a candidate changes only the draft. The actual current connection remains unchanged until the user presses Save.

## Existing Probe Reuse

Do not duplicate existing ONVIF interrogation.

The existing Probe path already obtains:

- manufacturer;
- model;
- firmware;
- serial/hardware information;
- ONVIF service capabilities;
- Media Profiles;
- selected recording/preview/detection profile tokens;
- credential-free RTSP URIs;
- codec/resolution/fps media information.

After discovery fills the address, the current `POST /api/camera-connections/probe` remains responsible for authenticated device interrogation.

## Draft Model Change

The ONVIF editor draft should support an optional explicit:

```text
device_service_url
```

When manually entering host/port and no discovery URL is selected, derive:

```text
http://<host>:<port>/onvif/device_service
```

using the existing backend/client convention.

When a discovery candidate provides a different valid path or HTTPS URL, preserve that exact safe Device Service URL for Probe/save rather than discarding it and rebuilding a default path.

Changing host or port manually after candidate selection clears the discovered explicit URL unless it still matches the edited authority.

## Testing

### Parser/unit tests

Cover:

- Probe XML generation;
- ProbeMatch parsing;
- multiple XAddrs;
- no XAddr;
- unsafe credential-bearing XAddr rejection;
- IPv4/hostname/IPv6-literal URL normalization even though multicast scan itself is IPv4;
- duplicate EPR merge;
- duplicate XAddr merge;
- malformed XML isolation;
- candidate cap.

### Helper tests

Use mocked UDP socket/input rather than real multicast in CI.

Verify:

- bounded deadline;
- socket cleanup;
- candidate normalization;
- helper UDS endpoint;
- no credential fields in request/response schemas.

### Backend API tests

Verify:

- successful candidate list;
- empty discovery result;
- helper unavailable -> 503;
- malformed helper response -> safe 502/503 behavior;
- manual ONVIF Probe remains independent of discovery availability.

### Frontend tests

Verify:

- scan action appears only for ONVIF;
- discovery does not appear for Manual RTSP/HIK;
- unselectable candidates are visible but disabled;
- selecting a candidate only changes editor draft;
- username/password remain untouched;
- discovered non-default Device Service URL is preserved;
- no automatic Probe/save;
- Rescan works.

### Deployment tests

Verify Compose contract:

- backend remains bridge-networked;
- helper uses host networking;
- helper publishes no ports;
- helper/backend share only the expected runtime socket mount;
- core backend does not `depends_on` helper in a way that prevents recorder startup when discovery is unhealthy.

## Acceptance Criteria

The slice is complete when:

1. selecting ONVIF exposes a Scan LAN action in the unified editor;
2. manual ONVIF entry still works unchanged;
3. scan executes only after explicit user action;
4. Docker deployment can discover LAN ONVIF ProbeMatches through the host-network helper;
5. candidates with incomplete discovery data remain visible;
6. only candidates with safe usable ONVIF XAddr are selectable;
7. selecting a candidate only fills the editor draft;
8. credentials are entered only in the existing editor;
9. existing authenticated Probe performs device/profile/URI interrogation;
10. Save still uses the unified Camera API and preserves Camera ID/history on edits;
11. helper failure does not stop recording core or break manually configured ONVIF cameras;
12. CI tests do not require real multicast cameras.

## Follow-up Slices

After this slice:

1. ONVIF persisted capability/detail presentation in Camera Device Center.
2. ONVIF PullPoint/Events as a native event source.
3. PTZ capability detection and optional controls.
4. Optional IPv6 WS-Discovery if field deployments require it.
