#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${ROOT_DIR}/vendor/ffmpeg"
BASE_URL="${FFMPEG_DOWNLOAD_BASE:-https://github.com/BtbN/FFmpeg-Builds/releases/download/latest}"
TARGET="${1:-auto}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/download-ffmpeg.sh [auto|amd64|arm64|all]

Examples:
  ./scripts/download-ffmpeg.sh          # detect host architecture
  ./scripts/download-ffmpeg.sh amd64    # Linux x86_64
  ./scripts/download-ffmpeg.sh arm64    # Linux ARM64 / Apple Silicon Docker target
  ./scripts/download-ffmpeg.sh all      # download both archives

Optional environment variable:
  FFMPEG_DOWNLOAD_BASE=https://...      # override download base URL
EOF
}

host_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo amd64 ;;
    arm64|aarch64) echo arm64 ;;
    *)
      echo "Unsupported host architecture: $(uname -m)" >&2
      exit 1
      ;;
  esac
}

archive_name() {
  case "$1" in
    amd64) echo "ffmpeg-linux64.tar.xz" ;;
    arm64) echo "ffmpeg-linuxarm64.tar.xz" ;;
    *) return 1 ;;
  esac
}

remote_name() {
  case "$1" in
    amd64) echo "ffmpeg-master-latest-linux64-gpl.tar.xz" ;;
    arm64) echo "ffmpeg-master-latest-linuxarm64-gpl.tar.xz" ;;
    *) return 1 ;;
  esac
}

validate_archive() {
  tar -tJf "$1" >/dev/null 2>&1
}

download_one() {
  local arch="$1"
  local archive remote target tmp
  archive="$(archive_name "$arch")"
  remote="$(remote_name "$arch")"
  target="${DEST_DIR}/${archive}"
  tmp="${target}.part"

  mkdir -p "$DEST_DIR"

  if [[ -f "$target" ]]; then
    if validate_archive "$target"; then
      echo "FFmpeg archive already exists and is valid: ${target}"
      return 0
    fi
    echo "Existing archive is invalid, removing: ${target}" >&2
    rm -f "$target"
  fi

  echo "Downloading FFmpeg for ${arch}:"
  echo "  ${BASE_URL}/${remote}"
  echo "  -> ${target}"

  rm -f "$tmp"
  curl -fL --retry 5 --retry-delay 3 --connect-timeout 15 \
    "${BASE_URL}/${remote}" \
    -o "$tmp"

  if ! validate_archive "$tmp"; then
    rm -f "$tmp"
    echo "Downloaded archive failed validation: ${remote}" >&2
    exit 1
  fi

  mv "$tmp" "$target"
  echo "Saved: ${target}"
}

case "$TARGET" in
  auto)
    download_one "$(host_arch)"
    ;;
  amd64|arm64)
    download_one "$TARGET"
    ;;
  all)
    download_one amd64
    download_one arm64
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown target: ${TARGET}" >&2
    usage >&2
    exit 2
    ;;
esac
