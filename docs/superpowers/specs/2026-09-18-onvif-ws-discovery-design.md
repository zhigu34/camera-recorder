# Camera LAN Discovery Design

Status: **Approved in chat — implementation-ready**

Date: 2026-09-18

## Goal

Add explicit, user-triggered LAN discovery for ONVIF and Manual RTSP cameras without changing the current Camera identity model or creating parallel camera-management workflows.

Discovery produces temporary candidates only. ONVIF uses WS-Discovery; Manual RTSP performs only bounded TCP port-554 discovery on the host LAN `/24`. A user selects a candidate to prefill the existing `CameraEditorDialog`, then completes the existing adapter-specific fields/Probe flow and saves through the unified Camera API.

This is the first Post-V1 LAN discovery slice.

## Non-goals

This phase does **not** implement:

- automatic background LAN scanning;
- automatic Camera creation;
- credential probing during discovery;
- RTSP path guessing;
- RTSP OPTIONS/DESCRIBE requests during discovery;
- scanning RTSP ports other than TCP 554;
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

When `adapter=manual_rtsp`, the editor shows the normal RTSP fields plus:

`扫描局域网 RTSP 设备`

The scan performs only TCP-connect discovery against port `554` on the selected host LAN `/24`.

It does not:

- guess a main/sub stream path;
- send RTSP OPTIONS/DESCRIBE;
- use or request credentials;
- classify a successful TCP listener as a specific camera brand/model.

Selecting a result fills only:

- `host`;
- `port=554`.

The user still supplies main/sub RTSP paths and uses the existing Probe flow before saving.

Manual entry remains fully supported and scanning is optional.

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

The editor shows HIK SDK connection fields only. LAN discovery actions are not shown in this phase.


## RTSP Port-554 Discovery

RTSP discovery intentionally means only "which hosts on the local /24 accept TCP connections on port 554".

### Network selection

The helper identifies the IPv4 address of the interface used by the host default route.

If that address is, for example:

```text
192.168.1.10
```

the scan target is:

```text
192.168.1.1 - 192.168.1.254
TCP 554
```

The helper excludes:

- network address;
- broadcast address;
- its own interface address.

Supported default-route address ranges for automatic scanning:

- RFC1918 private IPv4;
- IPv4 link-local if used by the deployment.

If no suitable non-loopback IPv4 default-route interface can be determined, RTSP LAN scan returns discovery-unavailable rather than guessing an interface.

The first slice does not expose arbitrary CIDR input in the UI.

### Probe behavior

Each host receives only a TCP connect attempt to port `554`.

A successful TCP connection means:

```text
host:554 is reachable
```

and nothing more.

No application bytes are written to the socket.

Initial bounds:

- target count: maximum 254 hosts;
- concurrency: maximum 64 in-flight connection attempts;
- per-host connect timeout: 300 ms;
- overall RTSP scan hard deadline: 3 seconds;
- result cap: 254.

Sockets are closed immediately after connect success/failure.

### RTSP candidate shape

```json
{
  "host": "192.168.1.50",
  "port": 554,
  "selectable": true
}
```

Results are sorted numerically by IPv4 address.

No manufacturer/model/name/path is inferred from an open port.

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

The helper accepts only bounded, credential-free discovery operations.

Conceptually:

```text
scan_onvif(timeout_seconds=3.0)
scan_rtsp_port_554()
```

The backend does not send user-selected CIDRs, credentials, or arbitrary target ports to the helper in this phase.

and returns normalized discovery candidates.

It does not persist state between requests.

## Backend API

Add two explicit backend operations:

```text
POST /api/camera-discovery/onvif
POST /api/camera-discovery/rtsp
```

Neither accepts credentials.

The ONVIF operation invokes WS-Discovery.

The RTSP operation invokes the bounded local-/24 TCP-554 scan.

Keeping separate endpoints makes adapter semantics explicit and avoids a loosely typed "scan mode" payload.

Suggested ONVIF response:

```json
{
  "devices": [...],
  "scan_duration_ms": 3012,
  "warnings": []
}
```

Suggested RTSP response:

```json
{
  "network": "192.168.1.0/24",
  "devices": [
    {"host": "192.168.1.50", "port": 554, "selectable": true}
  ],
  "scan_duration_ms": 842,
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

## ONVIF WS-Discovery Implementation

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

## Manual RTSP Frontend UX

RTSP scanning appears inside `CameraEditorDialog` only when:

```text
form.adapter === 'manual_rtsp'
```

Place the action beside the device-address field:

```text
设备地址   [ 192.168.1.50 ] [扫描局域网]
```

The result chooser shows:

- scanned `/24` network;
- discovered `host:554` candidates;
- scan status/count;
- Rescan action.

Selecting a candidate sets only:

```text
host=<candidate host>
port=554
```

It does not modify:

- username/password;
- main_path;
- sub_path;
- device identity metadata;
- runtime/recording policy.

It does not automatically Probe or Save.

## ONVIF Frontend UX

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

### ONVIF parser/unit tests

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

### RTSP scanner tests

Use mocked/default-route interface discovery and mocked TCP connection attempts.

Verify:

- default-route IPv4 selection;
- private `/24` derivation;
- network/broadcast/self exclusion;
- TCP 554 only;
- no bytes are written;
- 64-concurrency bound;
- per-host and overall deadlines;
- numeric IP sorting;
- empty result;
- no suitable interface -> discovery unavailable.

### Helper tests

Use mocked UDP/socket/network inputs rather than real LAN discovery in CI.

Verify:

- bounded deadline;
- socket cleanup;
- candidate normalization;
- helper UDS endpoint;
- no credential fields in request/response schemas.

### Backend API tests

Verify:

- successful ONVIF candidate list;
- successful RTSP `host:554` candidate list;
- RTSP response includes derived scanned `/24`;
- empty discovery result;
- helper unavailable -> 503;
- malformed helper response -> safe 502/503 behavior;
- manual ONVIF Probe remains independent of discovery availability.

### Frontend tests

Verify:

- ONVIF scan action appears only for ONVIF;
- RTSP scan action appears only for Manual RTSP;
- discovery does not appear for HIK;
- unselectable candidates are visible but disabled;
- selecting an ONVIF candidate only changes the ONVIF editor draft;
- selecting an RTSP candidate changes only host and port=554;
- RTSP paths remain untouched;
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
2. selecting Manual RTSP exposes a Scan LAN action that probes only TCP 554 on the default LAN /24;
3. HIK SDK exposes no discovery action in this phase;
4. manual ONVIF and RTSP entry still work unchanged;
5. scans execute only after explicit user action;
6. Docker deployment can discover LAN ONVIF ProbeMatches through the host-network helper;
7. RTSP discovery returns only reachable host:554 candidates and does not guess paths;
8. ONVIF candidates with incomplete discovery data remain visible;
9. only candidates with safe usable ONVIF XAddr are selectable;
10. selecting any candidate only fills the relevant editor draft fields;
11. credentials are entered only in the existing editor;
12. existing authenticated Probe performs device/profile/URI interrogation;
13. Save still uses the unified Camera API and preserves Camera ID/history on edits;
14. helper failure does not stop recording core or break manually configured cameras;
15. CI tests do not require real multicast cameras or a real LAN /24.

## Follow-up Slices

After this slice:

1. ONVIF persisted capability/detail presentation in Camera Device Center.
2. ONVIF PullPoint/Events as a native event source.
3. PTZ capability detection and optional controls.
4. Optional IPv6 WS-Discovery if field deployments require it.
