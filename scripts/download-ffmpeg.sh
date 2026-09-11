#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${ROOT_DIR}/vendor/ffmpeg"
BASE_URL="${FFMPEG_DOWNLOAD_BASE:-https://github.com/BtbN/FFmpeg-Builds/releases/download/latest}"
TARGET="${1:-auto}"
DOWNLOAD_PROXY="${GITHUB_DOWNLOAD_PROXY:-}"
PROXY_PROMPT_DONE=0

usage() {
  cat <<'EOF'
Usage:
  ./scripts/download-ffmpeg.sh [auto|amd64|arm64|all]

Examples:
  ./scripts/download-ffmpeg.sh          # detect host architecture
  ./scripts/download-ffmpeg.sh amd64    # Linux x86_64
  ./scripts/download-ffmpeg.sh arm64    # Linux ARM64 / Apple Silicon Docker target
  ./scripts/download-ffmpeg.sh all      # download both archives

Optional environment variables:
  FFMPEG_DOWNLOAD_BASE=https://...      # override download base URL
  GITHUB_DOWNLOAD_PROXY=http://...      # proxy used only for this GitHub download
  GITHUB_PROXY_PROMPT=0                 # disable interactive proxy prompt
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

prompt_github_proxy_if_needed() {
  local answer proxy

  [ "$PROXY_PROMPT_DONE" = "0" ] || return 0
  PROXY_PROMPT_DONE=1

  case "$BASE_URL" in
    *github.com*|*githubusercontent.com*) ;;
    *) return 0 ;;
  esac

  if [ -n "$DOWNLOAD_PROXY" ]; then
    echo "GitHub download proxy is configured for this download only."
    return 0
  fi

  # CI and other non-interactive callers must never block waiting for input.
  [ "${GITHUB_PROXY_PROMPT:-1}" != "0" ] || return 0
  [ -t 0 ] || return 0

  printf '需要从 GitHub 下载文件，是否为本次下载配置代理？ [y/N]: '
  read -r answer
  case "$answer" in
    y|Y|yes|YES|Yes|是)
      printf '请输入代理地址（例如 http://127.0.0.1:7890 或 socks5h://127.0.0.1:7891）: '
      read -r proxy
      if [ -z "$proxy" ]; then
        echo "未输入代理地址，将使用当前网络环境直接下载。"
        return 0
      fi
      case "$proxy" in
        http://*|https://*|socks5://*|socks5h://*)
          DOWNLOAD_PROXY="$proxy"
          echo "已为本次 GitHub 下载启用代理；不会修改 Git、Docker 或系统全局代理。"
          ;;
        *)
          echo "不支持的代理格式：请使用 http://、https://、socks5:// 或 socks5h://" >&2
          exit 2
          ;;
      esac
      ;;
    *)
      echo "本次 GitHub 下载不额外配置代理。"
      ;;
  esac
}

download_one() {
  local arch="$1"
  local archive remote target tmp
  local -a curl_args

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

  prompt_github_proxy_if_needed

  echo "Downloading FFmpeg for ${arch}:"
  echo "  ${BASE_URL}/${remote}"
  echo "  -> ${target}"

  curl_args=(
    -fL
    --retry 5
    --retry-delay 3
    --connect-timeout 15
  )
  if [ -n "$DOWNLOAD_PROXY" ]; then
    curl_args+=(--proxy "$DOWNLOAD_PROXY")
  fi

  rm -f "$tmp"
  curl "${curl_args[@]}" \
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
