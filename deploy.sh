#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"
BUILD_LOG="$ROOT_DIR/logs/deploy-build.log"
UP_LOG="$ROOT_DIR/logs/deploy-up.log"
CHECK_ONLY=0
NO_FFMPEG_DOWNLOAD=0
NO_BUILD=0

info() { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }

usage() {
  cat <<'EOF'
Camera Recorder 一键部署脚本

用法:
  ./deploy.sh [选项]

选项:
  --check-only          只做环境/配置检查，不构建和启动
  --no-ffmpeg-download  FFmpeg 本地包缺失时不尝试联网下载
  --no-build            跳过镜像构建，直接启动现有镜像
  -h, --help            显示帮助

可选环境变量:
  DEPLOY_AUTO_PULL=0       缺少基础镜像时不自动 docker pull（默认 1）
  DEPLOY_BUILD_VERBOSE=1   显示完整 Docker 构建输出（默认仅失败时显示错误摘要）
  FFMPEG_DOWNLOAD_BASE     覆盖 FFmpeg 下载地址
  GITHUB_PROXY_PROMPT=0    GitHub 下载时不询问代理
  GITHUB_DOWNLOAD_PROXY    直接指定本次 GitHub 下载代理
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check-only) CHECK_ONLY=1 ;;
    --no-ffmpeg-download) NO_FFMPEG_DOWNLOAD=1 ;;
    --no-build) NO_BUILD=1 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "未知参数: $1（使用 --help 查看用法）" ;;
  esac
  shift
done

random_hex() {
  local bytes="${1:-32}"
  if command_exists openssl; then
    openssl rand -hex "$bytes"
  elif [ -r /dev/urandom ] && command_exists od; then
    od -An -N"$bytes" -tx1 /dev/urandom | tr -d ' \n'
    printf '\n'
  else
    fail "无法生成随机密钥：需要 openssl，或 od + /dev/urandom"
  fi
}

env_get() {
  local key="$1"
  awk -v key="$key" 'index($0, key "=") == 1 {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

env_set() {
  local key="$1" value="$2" tmp="${ENV_FILE}.tmp.$$"
  awk -v key="$key" -v value="$value" '
    BEGIN {done=0}
    index($0, key "=") == 1 {print key "=" value; done=1; next}
    {print}
    END {if (!done) print key "=" value}
  ' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}

env_delete() {
  local key="$1" tmp="${ENV_FILE}.tmp.$$"
  awk -v key="$key" 'index($0, key "=") != 1 {print}' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}

ensure_env_key() {
  local key="$1" value="$2"
  grep -q "^${key}=" "$ENV_FILE" || env_set "$key" "$value"
}

normalize_arch() {
  case "$1" in
    x86_64|amd64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *) return 1 ;;
  esac
}

image_arch_ok() {
  local image="$1" expected="$2" actual
  actual="$(docker image inspect "$image" --format '{{.Architecture}}' 2>/dev/null || true)"
  [ -n "$actual" ] || return 1
  actual="$(normalize_arch "$actual" 2>/dev/null || echo "$actual")"
  [ "$actual" = "$expected" ]
}

ensure_image() {
  local image="$1" arch="$2"
  if image_arch_ok "$image" "$arch"; then
    ok "本地基础镜像可用: $image"
    return 0
  fi
  if [ "${DEPLOY_AUTO_PULL:-1}" = "0" ]; then
    fail "缺少可用镜像 $image，请先 docker pull 或 docker load"
  fi
  warn "本地缺少可用镜像: $image"
  info "尝试拉取: $image"
  docker pull "$image" || fail "无法拉取 $image；网络受限时请在其他机器 docker save 后在本机 docker load"
  image_arch_ok "$image" "$arch" || fail "镜像 $image 架构不匹配 $arch"
}

ffmpeg_archive_name() {
  case "$1" in
    amd64) echo ffmpeg-linux64.tar.xz ;;
    arm64) echo ffmpeg-linuxarm64.tar.xz ;;
    *) return 1 ;;
  esac
}

ffmpeg_original_name() {
  case "$1" in
    amd64) echo ffmpeg-master-latest-linux64-gpl.tar.xz ;;
    arm64) echo ffmpeg-master-latest-linuxarm64-gpl.tar.xz ;;
    *) return 1 ;;
  esac
}

validate_archive() {
  [ -s "$1" ] && tar -tJf "$1" >/dev/null 2>&1
}

prepare_ffmpeg() {
  local arch="$1" archive original expected candidate
  archive="$(ffmpeg_archive_name "$arch")"
  original="$(ffmpeg_original_name "$arch")"
  expected="$ROOT_DIR/vendor/ffmpeg/$archive"
  mkdir -p "$ROOT_DIR/vendor/ffmpeg"

  if validate_archive "$expected"; then
    ok "FFmpeg 本地包有效: vendor/ffmpeg/$archive"
    return 0
  fi
  if [ -e "$expected" ]; then
    warn "FFmpeg 包损坏，移动为 ${expected}.invalid"
    mv -f "$expected" "${expected}.invalid"
  fi
  for candidate in "$ROOT_DIR/$original" "$ROOT_DIR/vendor/ffmpeg/$original"; do
    if validate_archive "$candidate"; then
      mv "$candidate" "$expected"
      ok "检测到已下载 FFmpeg 包并自动归位"
      return 0
    fi
  done

  [ "$NO_FFMPEG_DOWNLOAD" = "0" ] || fail "缺少 FFmpeg 本地包: vendor/ffmpeg/$archive"
  [ -f "$ROOT_DIR/scripts/download-ffmpeg.sh" ] || fail "缺少 scripts/download-ffmpeg.sh"
  command_exists curl || fail "需要 curl 下载 FFmpeg，或手工放置 $expected"
  info "FFmpeg 本地包缺失，准备从 GitHub 下载..."
  bash "$ROOT_DIR/scripts/download-ffmpeg.sh" "$arch" || fail "FFmpeg 下载失败"
  validate_archive "$expected" || fail "FFmpeg 包校验失败: $expected"
  ok "FFmpeg 本地包准备完成"
}

project_owns_port() {
  local port="$1" container
  for container in camera-recorder-web camera-recorder-openlist; do
    if docker inspect "$container" >/dev/null 2>&1 && docker port "$container" 2>/dev/null | grep -Eq ":${port}$"; then
      return 0
    fi
  done
  return 1
}

port_in_use() {
  local port="$1"
  if command_exists ss; then
    ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq ":${port}$"; return $?
  elif command_exists lsof; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; return $?
  elif command_exists netstat; then
    netstat -an 2>/dev/null | grep -E 'LISTEN|LISTENING' | grep -Eq "[\.:]${port}[[:space:]]"; return $?
  fi
  return 2
}

check_port() {
  local name="$1" port="$2" rc
  if project_owns_port "$port"; then
    ok "$name 端口 $port 已由本项目使用"
    return 0
  fi
  set +e; port_in_use "$port"; rc=$?; set -e
  case "$rc" in
    0) fail "$name 端口 $port 已被其他进程占用，请修改 .env" ;;
    1) ok "$name 端口可用: $port" ;;
    2) warn "没有 ss/lsof/netstat，跳过端口 $port 检测" ;;
  esac
}

wait_for_health() {
  local container="$1" timeout="${2:-120}" elapsed=0 status
  while [ "$elapsed" -lt "$timeout" ]; do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)"
    case "$status" in
      healthy|running) return 0 ;;
      unhealthy|exited|dead) return 1 ;;
    esac
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

http_ok() {
  local url="$1"
  if command_exists curl; then
    curl -fsS --max-time 4 "$url" >/dev/null 2>&1
  elif command_exists wget; then
    wget -q -T 4 -O /dev/null "$url" >/dev/null 2>&1
  else
    return 2
  fi
}

show_build_errors() {
  local log_file="$1" errors
  errors="$(grep -Ein '(^|[^[:alpha:]])(error|fatal|failed|failure|timeout|timed out|exit code|non-zero|unable to|could not|connection refused|network is unreachable)([^[:alpha:]]|$)' "$log_file" 2>/dev/null | tail -n 80 || true)"
  if [ -n "$errors" ]; then
    warn "构建错误摘要："
    printf '%s\n' "$errors" >&2
  else
    warn "未匹配到标准错误行，显示构建日志最后 60 行："
    tail -n 60 "$log_file" >&2 2>/dev/null || true
  fi
}

show_docker_networks() {
  warn "当前 Docker 网络与子网："
  docker network ls --format '  {{.ID}}  {{.Driver}}  {{.Name}}' >&2 || true
  local ids
  ids="$(docker network ls -q 2>/dev/null || true)"
  if [ -n "$ids" ]; then
    # shellcheck disable=SC2086
    docker network inspect $ids --format '  {{.Name}} -> {{range .IPAM.Config}}{{.Subnet}} {{end}}' >&2 2>/dev/null || true
  fi
}

compose_up_with_network_recovery() {
  local rc
  mkdir -p logs
  : > "$UP_LOG"
  set +e
  "${COMPOSE[@]}" up -d 2>&1 | tee "$UP_LOG"
  rc=${PIPESTATUS[0]}
  set -e
  [ "$rc" -eq 0 ] && return 0

  if grep -q "all predefined address pools have been fully subnetted" "$UP_LOG"; then
    warn "检测到 Docker 默认地址池已耗尽，将清理未使用网络并重试一次。"
    show_docker_networks
    docker network prune -f || fail "docker network prune 执行失败"
    : > "$UP_LOG"
    set +e
    "${COMPOSE[@]}" up -d 2>&1 | tee "$UP_LOG"
    rc=${PIPESTATUS[0]}
    set -e
    [ "$rc" -eq 0 ] && return 0
  fi
  return "$rc"
}

info "Camera Recorder 部署前检查开始"
printf '项目目录: %s\n' "$ROOT_DIR"

command_exists docker || fail "未安装 Docker"
docker version >/dev/null 2>&1 || fail "Docker daemon 不可用"
docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2"
docker buildx version >/dev/null 2>&1 || fail "需要 Docker Buildx"
for cmd in awk grep tar tee; do command_exists "$cmd" || fail "缺少 $cmd"; done

DOCKER_ARCH_RAW="$(docker info --format '{{.Architecture}}' 2>/dev/null || true)"
DOCKER_ARCH="$(normalize_arch "$DOCKER_ARCH_RAW" 2>/dev/null || true)"
[ -n "$DOCKER_ARCH" ] || fail "不支持的 Docker Server 架构: ${DOCKER_ARCH_RAW:-unknown}"
ok "Docker Server 架构: $DOCKER_ARCH"

docker buildx inspect default >/dev/null 2>&1 || fail "未找到 buildx default builder"
docker buildx inspect default --bootstrap >/dev/null 2>&1 || true
export BUILDX_BUILDER=default
ok "构建器: default (docker driver)"

[ -f "$ENV_EXAMPLE" ] || fail "缺少 .env.example"
if [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  info "已从 .env.example 创建 .env"
fi
chmod 600 "$ENV_FILE" 2>/dev/null || true

ensure_env_key CAMREC_WEB_PORT 8080
ensure_env_key OPENLIST_PORT 5244
ensure_env_key TZ Asia/Shanghai
ensure_env_key OPENLIST_UID 0
ensure_env_key OPENLIST_GID 0
if grep -q '^CAMREC_API_PORT=' "$ENV_FILE"; then
  env_delete CAMREC_API_PORT
  ok "已移除废弃的 CAMREC_API_PORT；后端 API 仅在 Docker 内网监听"
fi

SECRET_KEY="$(env_get CAMREC_SECRET_KEY || true)"
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "replace-with-a-long-random-secret" ] || [ "$SECRET_KEY" = "camera-recorder-local-change-me" ]; then
  if [ -s "$ROOT_DIR/data/camera.db" ]; then
    fail "已有 camera.db，但 CAMREC_SECRET_KEY 仍是占位值；为避免旧密文失效，脚本不会自动修改"
  fi
  env_set CAMREC_SECRET_KEY "$(random_hex 32)"
  ok "已生成 CAMREC_SECRET_KEY（不输出明文）"
else
  ok "CAMREC_SECRET_KEY 已配置"
fi

OPENLIST_PASSWORD="$(env_get OPENLIST_ADMIN_PASSWORD || true)"
if [ -z "$OPENLIST_PASSWORD" ] || [ "$OPENLIST_PASSWORD" = "replace-with-a-strong-openlist-password" ] || [ "$OPENLIST_PASSWORD" = "camera-recorder-openlist-change-me" ]; then
  if find "$ROOT_DIR/openlist-data" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
    warn "OpenList 已有数据但管理员密码仍是占位值；脚本不会自动覆盖"
  else
    env_set OPENLIST_ADMIN_PASSWORD "$(random_hex 24)"
    ok "已生成 OPENLIST_ADMIN_PASSWORD（不输出明文）"
  fi
fi

mkdir -p data recordings staging failed logs openlist-data vendor/ffmpeg
for dir in data recordings staging failed logs openlist-data vendor/ffmpeg; do
  [ -w "$dir" ] || fail "目录不可写: $dir"
done

FREE_KB="$(df -Pk "$ROOT_DIR" 2>/dev/null | awk 'NR==2 {print $4}' || true)"
if [ -n "$FREE_KB" ] && [ "$FREE_KB" -lt 20971520 ]; then
  warn "当前文件系统剩余空间不足 20 GiB"
elif [ -n "$FREE_KB" ]; then
  ok "磁盘剩余空间: 约 $((FREE_KB / 1024 / 1024)) GiB"
fi

WEB_PORT="$(env_get CAMREC_WEB_PORT)"
OPENLIST_PORT="$(env_get OPENLIST_PORT)"
for item in "CAMREC_WEB_PORT:$WEB_PORT" "OPENLIST_PORT:$OPENLIST_PORT"; do
  key="${item%%:*}"; value="${item#*:}"
  case "$value" in ''|*[!0-9]*) fail "$key 不是有效端口: $value" ;; esac
  [ "$value" -ge 1 ] && [ "$value" -le 65535 ] || fail "$key 超出端口范围: $value"
done
[ "$WEB_PORT" != "$OPENLIST_PORT" ] || fail "Web 与 OpenList 端口不能重复"
check_port Web "$WEB_PORT"
check_port OpenList "$OPENLIST_PORT"

prepare_ffmpeg "$DOCKER_ARCH"
ensure_image python:3.12-slim "$DOCKER_ARCH"
ensure_image node:22-alpine "$DOCKER_ARCH"
ensure_image nginx:1.27-alpine "$DOCKER_ARCH"
ensure_image openlistteam/openlist:latest "$DOCKER_ARCH"

COMPOSE=(docker compose --env-file "$ENV_FILE")
"${COMPOSE[@]}" config >/dev/null || fail "docker compose 配置校验失败"
ok "docker compose config 校验通过"

if [ "$CHECK_ONLY" = "1" ]; then
  ok "检查完成（--check-only），未构建或启动服务"
  exit 0
fi

if [ "$NO_BUILD" = "0" ]; then
  BUILD_CMD=("${COMPOSE[@]}" build)
  if "${COMPOSE[@]}" build --help 2>/dev/null | grep -q -- '--builder'; then
    BUILD_CMD+=(--builder default)
  fi
  BUILD_CMD+=(backend frontend)
  mkdir -p logs
  : > "$BUILD_LOG"
  info "开始构建 backend/frontend（默认静默，完整日志: $BUILD_LOG）..."
  set +e
  if [ "${DEPLOY_BUILD_VERBOSE:-0}" = "1" ]; then
    "${BUILD_CMD[@]}" 2>&1 | tee "$BUILD_LOG"
    BUILD_RC=${PIPESTATUS[0]}
  else
    "${BUILD_CMD[@]}" >"$BUILD_LOG" 2>&1
    BUILD_RC=$?
  fi
  set -e
  if [ "$BUILD_RC" -ne 0 ]; then
    show_build_errors "$BUILD_LOG"
    fail "镜像构建失败，完整日志: $BUILD_LOG"
  fi
  ok "backend/frontend 镜像构建完成"
else
  warn "已使用 --no-build，跳过镜像构建"
fi

info "启动/更新服务..."
compose_up_with_network_recovery || fail "docker compose up 失败，日志: $UP_LOG"

info "等待 backend 健康..."
if ! wait_for_health camera-recorder-backend 150; then
  "${COMPOSE[@]}" logs --tail=120 backend || true
  fail "backend 未通过健康检查"
fi
ok "backend healthy（仅 Docker 内网可达）"

info "检查 frontend..."
if ! wait_for_health camera-recorder-web 60; then
  "${COMPOSE[@]}" logs --tail=80 frontend || true
  fail "frontend 容器未正常运行"
fi
set +e; http_ok "http://127.0.0.1:${WEB_PORT}/health"; HTTP_RC=$?; set -e
case "$HTTP_RC" in
  0) ok "Web 入口与后端 API 反代正常" ;;
  1) warn "frontend 已运行，但 /health 反代检测暂未通过" ;;
  2) warn "没有 curl/wget，跳过 HTTP 检测" ;;
esac

info "检查 OpenList..."
if ! wait_for_health camera-recorder-openlist 90; then
  "${COMPOSE[@]}" logs --tail=80 openlist || true
  fail "OpenList 容器未正常运行"
fi
ok "OpenList 容器运行正常"

printf '\n'
"${COMPOSE[@]}" ps
printf '\n'
ok "部署完成"
printf 'Camera Recorder Web: http://127.0.0.1:%s\n' "$WEB_PORT"
printf 'Backend API:        internal only (backend:8000, via Web /api and /ws)\n'
printf 'OpenList:           http://127.0.0.1:%s\n' "$OPENLIST_PORT"
printf '\n常用命令:\n'
printf '  查看后端日志: docker compose logs -f backend\n'
printf '  查看全部状态: docker compose ps\n'
printf '  再次部署/升级: ./deploy.sh\n'
