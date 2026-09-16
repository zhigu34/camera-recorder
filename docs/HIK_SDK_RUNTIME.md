# Hikvision HCNetSDK runtime

Camera Recorder keeps Hikvision's proprietary HCNetSDK binaries outside this repository.
The application code contains only the Python bridge and adapter integration.

## Runtime directory

By default Docker Compose mounts this host directory read-only into the internal HIK bridge:

```text
./hik-sdk-runtime/
```

Set `HIK_SDK_DIR` in `.env` if the SDK lives elsewhere.

The selected directory must be the Linux64 HCNetSDK runtime root and contain at least:

```text
libhcnetsdk.so
HCNetSDKCom/
```

Keep the rest of the vendor runtime libraries beside `libhcnetsdk.so` using Hikvision's
original directory layout. The bridge sets `HIK_SDK_PATH` and `LD_LIBRARY_PATH` for that
mounted directory.

Example `.env`:

```dotenv
HIK_SDK_DIR=/opt/private/hikvision/HCNetSDK
```

Do not copy `.so`, `.tar.gz`, credentials, or vendor packages into Git. The repository's
`.gitignore` and `.dockerignore` exclude `hik-sdk-runtime` contents by default.

## Runtime behavior

The `hik-bridge` container is internal-only; port 8100 is not published on the host.
If no HCNetSDK runtime is mounted, the bridge still starts and reports
`runtime_available: false`. Manual RTSP and ONVIF cameras continue to work, while HIK SDK
probe/create operations fail explicitly until the runtime is supplied.

When the SDK is present, HIK cameras use HCNetSDK for login and `NET_DVR_RealPlay_V40`.
Recording selects the configured main SDK stream. Preview and local motion detection select
the configured sub stream. The backend proxies those bytes over an internal HTTP stream so
the existing FFmpeg recording, preview, motion, and event-recording pipelines remain shared.

## Deployment

The normal deployment workflow does not change:

```bash
git pull && ./deploy.sh
```

Changing `HIK_SDK_DIR` or replacing the private runtime only requires recreating the relevant
containers; the application does not bake proprietary SDK files into its image.
