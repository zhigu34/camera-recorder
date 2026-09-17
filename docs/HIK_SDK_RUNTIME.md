# Hikvision HCNetSDK runtime

Camera Recorder keeps Hikvision's proprietary HCNetSDK binaries outside this repository. The application code contains only the Python bridge and adapter integration.

## Default behavior

HIK SDK support is disabled by default:

```dotenv
CAMREC_HIK_ENABLED=0
```

With the default setting:

- `hik-bridge` is not created or started;
- backend/frontend/OpenList run normally without proprietary SDK files;
- HIK camera configuration can remain stored, but runtime/probe/media access returns an explicit adapter-unavailable result;
- temporary HIK unavailability is not written back as a device-offline failure;
- `deploy.sh` does not hash, validate, or require the HCNetSDK runtime directory.

The current adapter state is visible through:

```text
GET /api/camera-adapters
```

When disabled, `hik_sdk.available` is false and the response explains that HIK support is disabled by deployment configuration.

## Enabling HIK SDK support

Set both values in `.env`:

```dotenv
CAMREC_HIK_ENABLED=1
HIK_SDK_DIR=./hik-sdk-runtime
```

Then run the normal deployment command:

```bash
./deploy.sh
```

Operators do not need to pass Docker Compose profile flags manually. `deploy.sh` deploys and health-checks the core services first, then handles the optional HIK stage. A HIK startup/runtime failure therefore exits with an actionable HIK error without stopping or rolling back healthy core services.

To disable HIK again:

```dotenv
CAMREC_HIK_ENABLED=0
```

Run `./deploy.sh` once more. Any existing `hik-bridge` container is stopped/removed through the HIK profile while core services remain running.

## Runtime directory

By default the optional HIK profile mounts this host directory read-only into the internal bridge:

```text
./hik-sdk-runtime/
```

Set `HIK_SDK_DIR` if the SDK lives elsewhere.

The selected directory must be the Linux64 HCNetSDK runtime root and contain at least:

```text
libhcnetsdk.so
HCNetSDKCom/
```

Keep the rest of the vendor runtime libraries beside `libhcnetsdk.so` using Hikvision's original directory layout. The bridge receives the runtime root through `HIK_SDK_PATH` and initializes HCNetSDK with its explicit SDK configuration. The vendor runtime is deliberately **not** exported through a process-wide `LD_LIBRARY_PATH`, because doing so can replace Python's OpenSSL libraries and break the bridge process itself.

Example using a private runtime outside the repository:

```dotenv
CAMREC_HIK_ENABLED=1
HIK_SDK_DIR=/opt/private/hikvision/HCNetSDK
```

Do not copy `.so`, `.tar.gz`, credentials, or vendor packages into Git. The repository's `.gitignore` and `.dockerignore` exclude `hik-sdk-runtime` contents by default.

## Runtime behavior

When enabled, `hik-bridge` is internal-only; port 8100 is never published on the host. Backend capability resolution requires both the deployment flag and a bridge health response with `runtime_available: true` before HIK runtime operations are allowed.

HIK cameras use HCNetSDK for login and `NET_DVR_RealPlay_V40`. Recording selects the configured main SDK stream. Preview and local motion detection select the configured sub stream. The backend proxies those bytes over an internal HTTP stream so the existing FFmpeg recording, preview, motion, and event-recording pipelines remain shared.

If the bridge or SDK runtime becomes unavailable while HIK is enabled, HIK runtime/probe/media operations fail explicitly. Manual RTSP and ONVIF cameras continue to work, and capability unavailability alone does not increment HIK camera connectivity failures or rewrite a previously persisted connectivity state to offline.

## Deployment lifecycle

The normal workflow remains:

```bash
git pull && ./deploy.sh
```

`deploy.sh` maintains two logical stages:

```text
Core stage
  backend / frontend / OpenList
  -> build/update
  -> health checks

Optional HIK stage
  CAMREC_HIK_ENABLED=0 -> ensure stale bridge is removed
  CAMREC_HIK_ENABLED=1 -> validate runtime -> start/recreate bridge -> health/runtime check
```

The deployment state records the HIK enable flag and runtime hash so `0 -> 1`, `1 -> 0`, bridge code changes, and private SDK replacements are observable by subsequent incremental deployments.

For manual diagnostics only, Compose profile commands are available:

```bash
docker compose --profile hik config
docker compose --profile hik ps
docker compose --profile hik logs -f hik-bridge
```

These are troubleshooting commands; normal deployment should continue to use `./deploy.sh`.
