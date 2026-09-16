# Independent Media Adapters and HIK SDK Integration Design

## Goal

Allow each camera to select one of three independent media adapters while keeping recording, preview, detection, snapshots, and event pre-roll on one shared media pipeline:

- `manual_rtsp`: use the manually configured RTSP paths.
- `onvif`: resolve ONVIF profiles and use the ONVIF-provided stream URI.
- `hik_sdk`: obtain media through HCNetSDK `NET_DVR_RealPlay_V40` rather than resolving an RTSP URI.

The existing `connection_type` remains the user-facing adapter selector. Existing manual RTSP and ONVIF cameras must continue to work without reconfiguration.

## Current Problem

`DeviceAdapter` currently mixes two responsibilities:

1. camera/device-specific configuration and capability handling;
2. media transport resolution.

Both current adapters return a `ResolvedStream(uri=...)`, so downstream code implicitly assumes every media source is an RTSP-like URI. That model cannot represent HCNetSDK callbacks cleanly and would force HIK-specific branches into recorder, preview, motion detection, and event recording.

## Architecture

Split media resolution from device management.

```text
Camera.connection_type
        |
        v
MediaAdapterRegistry
   |          |          |
   v          v          v
Manual      ONVIF      HIK SDK
Media       Media      Media
Adapter     Adapter    Adapter
   |          |          |
   +----------+----------+
              |
              v
         MediaSource
              |
              v
       shared FFmpeg/media pipeline
              |
      +-------+---------+---------+
      |                 |         |
   Recorder          Preview   Detection
      |
 Event pre-roll
```

`DeviceAdapter` remains available for device/capability concerns, but media-consuming code depends on `MediaAdapter` and `MediaSource` instead of a raw URI.

## MediaSource Contract

Introduce a transport-neutral source descriptor.

```python
MediaSource(
    adapter="manual_rtsp" | "onvif" | "hik_sdk",
    transport="rtsp" | "hik_bridge",
    role="main" | "sub",
    purpose="recording" | "preview" | "detection",
    uri: str | None,
    bridge_stream_id: str | None,
)
```

The invariant is that exactly one transport payload is active:

- `rtsp` => `uri` is populated.
- `hik_bridge` => `bridge_stream_id` is populated.

The compatibility helper `resolve_stream()` can remain temporarily for code that only accepts URI transports, but new media pipeline code should call `resolve_media_source()`.

## Adapter Behavior

### Manual RTSP

- Reads `rtsp_path` and optional `sub_rtsp_path`.
- Preserves current main/sub inference behavior.
- Builds credentialed RTSP URI at runtime.
- Returns `MediaSource(transport="rtsp")`.

### ONVIF

- Reads persisted ONVIF profile metadata.
- Uses main profile for recording and auxiliary profile for preview/detection when available.
- Injects current encrypted camera credentials only at runtime.
- Returns `MediaSource(transport="rtsp")`.
- ONVIF remains responsible for profile/URI negotiation, not for carrying video bytes itself.

### HIK SDK

- Uses a dedicated `hik-bridge` Python process that loads `libhcnetsdk.so` through `ctypes`.
- The FastAPI backend does not load HCNetSDK into its own process.
- Bridge lifecycle owns `NET_DVR_Init`, login/logout, reconnect configuration, real-play callbacks, and SDK cleanup.
- A stream session maps purpose/preference to HCNetSDK channel and stream type, calls `NET_DVR_RealPlay_V40`, and exposes callback data as a local bridge stream.
- Returns `MediaSource(transport="hik_bridge")`.

This isolates SDK crashes and callback/GIL pressure from the main backend while allowing the first implementation to reuse Hikvision's official Python ctypes definitions.

## HIK Bridge Boundary

The bridge has two surfaces:

1. a low-rate control API for login/session management;
2. a high-rate local media endpoint consumed only inside the Docker network.

Initial control operations:

- health
- probe/login
- create stream session
- stop stream session

Each created session returns a short-lived opaque stream id. Credentials are sent over the internal Docker network and are never embedded in persisted bridge URLs or logs.

The media endpoint emits the HCNetSDK real-play callback byte stream in order. FFmpeg is the consumer and remains responsible for demux/decode/remux. The bridge must use bounded queues and terminate a slow consumer rather than allowing unbounded RAM growth.

## Shared Pipeline Integration

Add a single FFmpeg input builder:

```text
MediaSource
   -> build_media_input(source)
   -> FFmpeg input arguments / managed bridge lease
```

For RTSP sources, behavior remains the current `-rtsp_transport tcp -i <uri>` path.

For HIK bridge sources, the input builder acquires a bridge session, points FFmpeg at the local media endpoint, and releases the session when the consumer exits.

Recorder, preview, motion worker, and event prebuffer must not contain `connection_type == ...` branches. They only consume `MediaSource` / the common input builder.

## Data Model

Extend `Camera.connection_type` validation to:

- `manual_rtsp`
- `onvif`
- `hik_sdk`

Add a one-to-one HIK metadata table rather than overloading ONVIF/manual columns. Initial fields:

- camera id
- SDK port (default 8000)
- channel number
- main stream type
- sub stream type
- optional device serial/model discovered during probe

Camera username/password continue to use the existing encrypted credential fields. No plaintext SDK password is stored in HIK metadata.

## API and UI

Camera workspace exposes three explicit add paths:

- Add RTSP
- Add ONVIF
- Add HIK SDK

The HIK flow asks for host, SDK port, username, password, and optional channel. It probes the bridge before persistence and shows discovered device identity when available.

Camera detail/edit preserves the selected adapter and exposes adapter-specific fields. Switching adapter type is not done through the generic edit form in this phase; cameras are created with one connection type to avoid accidental credential/metadata cross-contamination.

## Failure Handling

- Unsupported adapter: explicit `UnsupportedMediaAdapter`.
- Missing metadata: actionable repair/re-add error.
- HIK bridge unavailable: source resolution fails without falling back silently to RTSP.
- SDK login failure: propagate SDK error code in sanitized form; never include password.
- RealPlay failure/disconnect: terminate the media lease so existing recorder/preview retry behavior can reconnect.
- Slow bridge consumer: bounded buffer closes the session rather than growing memory without limit.

There is no automatic adapter fallback. Independent selection means a camera uses exactly the adapter configured for it.

## Deployment

The project remains deployable with:

```bash
git pull && ./deploy.sh
```

Docker Compose gains a `hik-bridge` service. HCNetSDK runtime binaries are not committed to the public repository. Deployment expects the SDK runtime to be supplied from a local/private path or an ignored archive during image build. If the SDK payload is absent, `manual_rtsp` and `onvif` continue to work; HIK SDK camera creation reports that the bridge/runtime is unavailable.

## Testing

### Backend unit tests

- registry selects each adapter strictly by `connection_type`;
- no silent fallback between adapters;
- manual RTSP source matches previous URI/stream-role behavior;
- ONVIF source matches previous profile behavior;
- HIK source creates/releases bridge leases and never exposes credentials in returned source metadata;
- recorder/preview/detection paths consume the common media input builder rather than branch on camera type.

### Bridge tests

HCNetSDK itself is wrapped behind a narrow Python protocol so tests use a fake SDK:

- init/login/logout lifecycle;
- main/sub RealPlay settings;
- callback byte ordering;
- bounded queue behavior;
- stop/disconnect cleanup;
- sanitized SDK error propagation.

### Frontend tests

- camera workspace exposes all three add paths;
- selecting HIK opens the HIK-specific form;
- successful probe/create refreshes the camera list;
- existing manual and ONVIF flows remain unchanged.

### CI / smoke

- normal CI runs without proprietary SDK binaries using bridge fake/no-runtime mode;
- Docker compose config includes the bridge;
- existing backend/frontend smoke remains green;
- optional HIK runtime smoke can run only where the private SDK payload is available.

## Scope for This Delivery

Included:

- MediaAdapter/MediaSource abstraction.
- Migration of existing manual RTSP and ONVIF consumers to the shared media input boundary.
- `hik_sdk` connection type, metadata, API, and frontend selection/add flow.
- Python `hik-bridge` service with HCNetSDK wrapper boundary and RealPlay stream-session plumbing.
- Docker/deploy integration that does not break installations without the proprietary SDK payload.

Not included yet:

- HIK alarm/event subscription integration.
- HIK PTZ/configuration UI.
- NVR playback/download.
- C++ media bridge optimization.
- automatic adapter fallback or automatic vendor detection.
