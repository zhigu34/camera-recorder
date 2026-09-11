# Local FFmpeg build artifacts

Docker builds do **not** download FFmpeg from GitHub. Put the pre-downloaded BtbN archive in this directory before building.

Expected filenames:

- amd64: `ffmpeg-linux64.tar.xz`
- arm64: `ffmpeg-linuxarm64.tar.xz`

Recommended:

```bash
./scripts/download-ffmpeg.sh auto
```

Or download both architectures:

```bash
./scripts/download-ffmpeg.sh all
```

The large `.tar.xz` files are intentionally ignored by Git but remain part of the Docker build context when present locally.
