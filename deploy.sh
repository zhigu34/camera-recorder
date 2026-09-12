#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"
BUILD_LOG="$ROOT_DIR/logs/deploy-build.log"
UP_LOG="$ROOT_DIR/logs/deploy-up.log"
STATE_FILE="$ROOT_DIR/logs/deploy-state"
CHECK_ONLY=0
NO_FFMPEG_DOWNLOAD=0
NO_BUILD=0
FORCE_FULL=0

info() { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }

usage() {
  cat <<'USAGE'
Camera Recorder 智能增量部署脚本

用法:
  ./deploy.sh [选项]

默认行为:
  自动比较“上次成功部署 -> 当前代码”的文件变化，只重建/更新受影响服务。
  纯 frontend 变化只重建 frontend，并使用 --no-deps，backend 录像不会中断。

选项:
  --check-only          只做检查并显示部署计划，不构建和启动
  --no-ffmpeg-download  FFmpeg 本地包缺失时不尝试联网下载
  --no-build            跳过需要的镜像构建，仅执行容器更新（不会记录新的部署基线）
  --full                强制完整重建 backend/frontend，并更新全部服务
  -h, --help            显示帮助

可选环境变量:
  DEPLOY_AUTO_PULL=0       缺少基础镜像时不自动 docker pull（默认 1）
  DEPLOY_BUILD_VERBOSE=1   显示完整 Docker 构建输出（默认仅失败时显示错误摘要）
  FFMPEG_DOWNLOAD_BASE     覆盖 FFmpeg 下载地址
  GITHUB_PROXY_PROMPT=0    GitHub 下载时不询问代理
  GITHUB_DOWNLOAD_PROXY    直接指定本次 GitHub 下载代理
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check-only) CHECK_ONLY=1 ;;
    --no-ffmpeg-download) NO_FFMPEG_DOWNLOAD=1 ;;
    --no-build) NO_BUILD=1 ;;
    --full) FORCE_FULL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "未知参数: $1（使用 --help 查看用法）" ;;
  esac
  shift
done

random_hex() {
  local bytes="${1:-32}"
  if command_exists openssl; then openssl rand -hex "$bytes"
  elif [ -r /dev/urandom ] && command_exists od; then od -An -N"$bytes" -tx1 /dev/urandom | tr -d ' \n'; printf '\n'
  else fail "无法生成随机密钥：需要 openssl，或 od + /dev/urandom"; fi
}

env_get() { awk -v key="$1" 'index($0, key "=") == 1 {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"; }
env_set() {
  local key="$1" value="$2" tmp="${ENV_FILE}.tmp.$$"
  awk -v key="$key" -v value="$value" 'BEGIN{done=0} index($0,key "=")==1{print key "=" value;done=1;next}{print} END{if(!done) print key "=" value}' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}
env_delete() { local key="$1" tmp="${ENV_FILE}.tmp.$$"; awk -v key="$key" 'index($0,key "=")!=1{print}' "$ENV_FILE" > "$tmp"; mv "$tmp" "$ENV_FILE"; }
ensure_env_key() { grep -q "^${1}=" "$ENV_FILE" || env_set "$1" "$2"; }

normalize_arch() { case "$1" in x86_64|amd64) echo amd64 ;; aarch64|arm64) echo arm64 ;; *) return 1 ;; esac; }
image_arch_ok() {
  local image="$1" expected="$2" actual
  actual="$(docker image inspect "$image" --format '{{.Architecture}}' 2>/dev/null || true)"
  [ -n "$actual" ] || return 1
  actual="$(normalize_arch "$actual" 2>/dev/null || echo "$actual")"
  [ "$actual" = "$expected" ]
}
ensure_image() {
  local image="$1" arch="$2"
  image_arch_ok "$image" "$arch" && { ok "本地基础镜像可用: $image"; return 0; }
  [ "${DEPLOY_AUTO_PULL:-1}" != "0" ] || fail "缺少可用镜像 $image，请先 docker pull 或 docker load"
  warn "本地缺少可用镜像: $image"
  info "尝试拉取: $image"
  docker pull "$image" || fail "无法拉取 $image；网络受限时请在其他机器 docker save 后在本机 docker load"
  image_arch_ok "$image" "$arch" || fail "镜像 $image 架构不匹配 $arch"
}

ffmpeg_archive_name() { case "$1" in amd64) echo ffmpeg-linux64.tar.xz ;; arm64) echo ffmpeg-linuxarm64.tar.xz ;; *) return 1 ;; esac; }
ffmpeg_original_name() { case "$1" in amd64) echo ffmpeg-master-latest-linux64-gpl.tar.xz ;; arm64) echo ffmpeg-master-latest-linuxarm64-gpl.tar.xz ;; *) return 1 ;; esac; }
validate_archive() { [ -s "$1" ] && tar -tJf "$1" >/dev/null 2>&1; }
prepare_ffmpeg() {
  local arch="$1" archive original expected candidate
  archive="$(ffmpeg_archive_name "$arch")"; original="$(ffmpeg_original_name "$arch")"; expected="$ROOT_DIR/vendor/ffmpeg/$archive"
  mkdir -p "$ROOT_DIR/vendor/ffmpeg"
  validate_archive "$expected" && { ok "FFmpeg 本地包有效: vendor/ffmpeg/$archive"; return 0; }
  if [ -e "$expected" ]; then warn "FFmpeg 包损坏，移动为 ${expected}.invalid"; mv -f "$expected" "${expected}.invalid"; fi
  for candidate in "$ROOT_DIR/$original" "$ROOT_DIR/vendor/ffmpeg/$original"; do
    if validate_archive "$candidate"; then mv "$candidate" "$expected"; ok "检测到已下载 FFmpeg 包并自动归位"; return 0; fi
  done
  [ "$NO_FFMPEG_DOWNLOAD" = "0" ] || fail "缺少 FFmpeg 本地包: vendor/ffmpeg/$archive"
  [ -f "$ROOT_DIR/scripts/download-ffmpeg.sh" ] || fail "缺少 scripts/download-ffmpeg.sh"
  command_exists curl || fail "需要 curl 下载 FFmpeg，或手工放置 $expected"
  info "FFmpeg 本地包缺失，准备从 GitHub 下载..."
  bash "$ROOT_DIR/scripts/download-ffmpeg.sh" "$arch" || fail "FFmpeg 下载失败"
  validate_archive "$expected" || fail "FFmpeg 包校验失败: $expected"
  ok "FFmpeg 本地包准备完成"
}

hash_stream() {
  if command_exists sha256sum; then sha256sum | awk '{print $1}'
  elif command_exists shasum; then shasum -a 256 | awk '{print $1}'
  else cksum | awk '{print $1 ":" $2}'; fi
}
file_hash() { [ -f "$1" ] && hash_stream < "$1" || printf '%s\n' missing; }
state_get() { [ -f "$STATE_FILE" ] || return 0; awk -F= -v key="$1" '$1==key{sub(/^[^=]*=/,"");print;exit}' "$STATE_FILE"; }
git_ready() { command_exists git && git rev-parse --is-inside-work-tree >/dev/null 2>&1; }
git_worktree_hash() { git status --porcelain=v1 --untracked-files=all 2>/dev/null | hash_stream; }
container_exists() { docker inspect "$1" >/dev/null 2>&1; }
container_running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = true ]; }

project_owns_port() {
  local port="$1" container
  for container in camera-recorder-web camera-recorder-openlist; do
    if docker inspect "$container" >/dev/null 2>&1 && docker port "$container" 2>/dev/null | grep -Eq ":${port}$"; then return 0; fi
  done
  return 1
}
port_in_use() {
  local port="$1"
  if command_exists ss; then ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq ":${port}$"; return $?
  elif command_exists lsof; then lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; return $?
  elif command_exists netstat; then netstat -an 2>/dev/null | grep -E 'LISTEN|LISTENING' | grep -Eq "[\.:]${port}[[:space:]]"; return $?
  fi
  return 2
}
check_port() {
  local name="$1" port="$2" rc
  if project_owns_port "$port"; then ok "$name 端口 $port 已由本项目使用"; return 0; fi
  set +e; port_in_use "$port"; rc=$?; set -e
  case "$rc" in 0) fail "$name 端口 $port 已被其他进程占用，请修改 .env" ;; 1) ok "$name 端口可用: $port" ;; 2) warn "没有 ss/lsof/netstat，跳过端口 $port 检测" ;; esac
}

wait_for_health() {
  local container="$1" timeout="${2:-120}" elapsed=0 status
  while [ "$elapsed" -lt "$timeout" ]; do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)"
    case "$status" in healthy|running) return 0 ;; unhealthy|exited|dead) return 1 ;; esac
    sleep 2; elapsed=$((elapsed + 2))
  done
  return 1
}
http_ok() {
  local url="$1"
  if command_exists curl; then curl -fsS --max-time 4 "$url" >/dev/null 2>&1
  elif command_exists wget; then wget -q -T 4 -O /dev/null "$url" >/dev/null 2>&1
  else return 2; fi
}
show_build_errors() {
  local log_file="$1" errors
  errors="$(grep -Ein '(^|[^[:alpha:]])(error|fatal|failed|failure|timeout|timed out|exit code|non-zero|unable to|could not|connection refused|network is unreachable)([^[:alpha:]]|$)' "$log_file" 2>/dev/null | tail -n 80 || true)"
  if [ -n "$errors" ]; then warn "构建错误摘要："; printf '%s\n' "$errors" >&2
  else warn "未匹配到标准错误行，显示构建日志最后 60 行："; tail -n 60 "$log_file" >&2 2>/dev/null || true; fi
}
show_docker_networks() {
  warn "当前 Docker 网络与子网："
  docker network ls --format '  {{.ID}}  {{.Driver}}  {{.Name}}' >&2 || true
  local ids; ids="$(docker network ls -q 2>/dev/null || true)"
  if [ -n "$ids" ]; then
    # shellcheck disable=SC2086
    docker network inspect $ids --format '  {{.Name}} -> {{range .IPAM.Config}}{{.Subnet}} {{end}}' >&2 2>/dev/null || true
  fi
}
compose_up_with_network_recovery() {
  local rc; local args=("$@")
  mkdir -p logs; : > "$UP_LOG"
  set +e; "${COMPOSE[@]}" up -d "${args[@]}" 2>&1 | tee "$UP_LOG"; rc=${PIPESTATUS[0]}; set -e
  [ "$rc" -eq 0 ] && return 0
  if grep -q "all predefined address pools have been fully subnetted" "$UP_LOG"; then
    warn "检测到 Docker 默认地址池已耗尽，将清理未使用网络并重试一次。"
    show_docker_networks; docker network prune -f || fail "docker network prune 执行失败"
    : > "$UP_LOG"; set +e; "${COMPOSE[@]}" up -d "${args[@]}" 2>&1 | tee "$UP_LOG"; rc=${PIPESTATUS[0]}; set -e
  fi
  return "$rc"
}

BUILD_BACKEND=0
BUILD_FRONTEND=0
UPDATE_BACKEND=0
UPDATE_FRONTEND=0
UPDATE_OPENLIST=0
CONFIG_ALL=0
PLAN_SOURCE=""
CHANGED_FILES=""
CURRENT_COMMIT=""
CURRENT_WORKTREE_HASH=""
CURRENT_ENV_HASH=""

mark_full() {
  BUILD_BACKEND=1; BUILD_FRONTEND=1
  UPDATE_BACKEND=1; UPDATE_FRONTEND=1; UPDATE_OPENLIST=1
  CONFIG_ALL=1
}
classify_path() {
  local path="$1"
  case "$path" in
    frontend/*) BUILD_FRONTEND=1; UPDATE_FRONTEND=1 ;;
    backend/*|vendor/ffmpeg/*) BUILD_BACKEND=1; UPDATE_BACKEND=1 ;;
    .dockerignore) BUILD_BACKEND=1; BUILD_FRONTEND=1; UPDATE_BACKEND=1; UPDATE_FRONTEND=1 ;;
    docker-compose.yml) mark_full ;;
    .env.example) CONFIG_ALL=1; UPDATE_BACKEND=1; UPDATE_FRONTEND=1; UPDATE_OPENLIST=1 ;;
    deploy.sh|README.md|docs/*|.github/*|.gitignore|Makefile|scripts/*) ;;
    '') ;;
    *) warn "无法精确归类变更: $path，按完整部署处理"; mark_full ;;
  esac
}
collect_changed_files() {
  local previous_commit="" previous_worktree="" base="" files=""
  if ! git_ready; then PLAN_SOURCE="非 Git 环境"; mark_full; return; fi

  CURRENT_COMMIT="$(git rev-parse HEAD)"
  CURRENT_WORKTREE_HASH="$(git_worktree_hash)"
  previous_commit="$(state_get commit || true)"
  previous_worktree="$(state_get worktree_hash || true)"

  if [ "$FORCE_FULL" = "1" ]; then PLAN_SOURCE="--full"; mark_full; return; fi

  if [ -n "$previous_commit" ] && git cat-file -e "${previous_commit}^{commit}" 2>/dev/null && git merge-base --is-ancestor "$previous_commit" "$CURRENT_COMMIT" 2>/dev/null; then
    base="$previous_commit"; PLAN_SOURCE="上次成功部署 ${previous_commit:0:8}"
  elif container_exists camera-recorder-backend || container_exists camera-recorder-web || container_exists camera-recorder-openlist; then
    if git rev-parse --verify ORIG_HEAD >/dev/null 2>&1 && git merge-base --is-ancestor ORIG_HEAD "$CURRENT_COMMIT" 2>/dev/null; then
      base="$(git rev-parse ORIG_HEAD)"; PLAN_SOURCE="首次智能部署，使用 pull 前 ${base:0:8} 作为基线"
    else
      PLAN_SOURCE="未找到可靠部署基线"; warn "已有运行容器但没有可用部署基线，将执行完整部署一次"; mark_full; return
    fi
  else
    PLAN_SOURCE="首次部署"; mark_full; return
  fi

  if [ "$base" != "$CURRENT_COMMIT" ]; then files="$(git diff --name-only "$base..$CURRENT_COMMIT" 2>/dev/null || true)"; fi
  if [ -z "$previous_worktree" ] || [ "$previous_worktree" != "$CURRENT_WORKTREE_HASH" ] || [ "$previous_commit" != "$CURRENT_COMMIT" ]; then
    files="$(printf '%s\n' "$files"; git diff --name-only HEAD 2>/dev/null || true; git diff --cached --name-only 2>/dev/null || true; git ls-files --others --exclude-standard 2>/dev/null || true)"
  fi
  CHANGED_FILES="$(printf '%s\n' "$files" | awk 'NF && !seen[$0]++')"
  while IFS= read -r path; do [ -n "$path" ] && classify_path "$path"; done <<< "$CHANGED_FILES"
}

save_deploy_state() {
  git_ready || return 0
  mkdir -p "$(dirname "$STATE_FILE")"
  CURRENT_COMMIT="$(git rev-parse HEAD)"
  CURRENT_WORKTREE_HASH="$(git_worktree_hash)"
  CURRENT_ENV_HASH="$(file_hash "$ENV_FILE")"
  cat > "$STATE_FILE" <<STATE
commit=$CURRENT_COMMIT
worktree_hash=$CURRENT_WORKTREE_HASH
env_hash=$CURRENT_ENV_HASH
STATE
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
if [ ! -f "$ENV_FILE" ]; then cp "$ENV_EXAMPLE" "$ENV_FILE"; info "已从 .env.example 创建 .env"; fi
chmod 600 "$ENV_FILE" 2>/dev/null || true
ensure_env_key CAMREC_WEB_PORT 8080
ensure_env_key OPENLIST_PORT 5244
ensure_env_key TZ Asia/Shanghai
ensure_env_key OPENLIST_UID 0
ensure_env_key OPENLIST_GID 0
if grep -q '^CAMREC_API_PORT=' "$ENV_FILE"; then env_delete CAMREC_API_PORT; ok "已移除废弃的 CAMREC_API_PORT；后端 API 仅在 Docker 内网监听"; fi

SECRET_KEY="$(env_get CAMREC_SECRET_KEY || true)"
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "replace-with-a-long-random-secret" ] || [ "$SECRET_KEY" = "camera-recorder-local-change-me" ]; then
  if [ -s "$ROOT_DIR/data/camera.db" ]; then fail "已有 camera.db，但 CAMREC_SECRET_KEY 仍是占位值；为避免旧密文失效，脚本不会自动修改"; fi
  env_set CAMREC_SECRET_KEY "$(random_hex 32)"; ok "已生成 CAMREC_SECRET_KEY（不输出明文）"
else ok "CAMREC_SECRET_KEY 已配置"; fi

OPENLIST_PASSWORD="$(env_get OPENLIST_ADMIN_PASSWORD || true)"
if [ -z "$OPENLIST_PASSWORD" ] || [ "$OPENLIST_PASSWORD" = "replace-with-a-strong-openlist-password" ] || [ "$OPENLIST_PASSWORD" = "camera-recorder-openlist-change-me" ]; then
  if find "$ROOT_DIR/openlist-data" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then warn "OpenList 已有数据但管理员密码仍是占位值；脚本不会自动覆盖"
  else env_set OPENLIST_ADMIN_PASSWORD "$(random_hex 24)"; ok "已生成 OPENLIST_ADMIN_PASSWORD（不输出明文）"; fi
fi

mkdir -p data recordings staging failed logs openlist-data vendor/ffmpeg
for dir in data recordings staging failed logs openlist-data vendor/ffmpeg; do [ -w "$dir" ] || fail "目录不可写: $dir"; done
FREE_KB="$(df -Pk "$ROOT_DIR" 2>/dev/null | awk 'NR==2 {print $4}' || true)"
if [ -n "$FREE_KB" ] && [ "$FREE_KB" -lt 20971520 ]; then warn "当前文件系统剩余空间不足 20 GiB"
elif [ -n "$FREE_KB" ]; then ok "磁盘剩余空间: 约 $((FREE_KB / 1024 / 1024)) GiB"; fi

WEB_PORT="$(env_get CAMREC_WEB_PORT)"; OPENLIST_PORT="$(env_get OPENLIST_PORT)"
for item in "CAMREC_WEB_PORT:$WEB_PORT" "OPENLIST_PORT:$OPENLIST_PORT"; do
  key="${item%%:*}"; value="${item#*:}"
  case "$value" in ''|*[!0-9]*) fail "$key 不是有效端口: $value" ;; esac
  [ "$value" -ge 1 ] && [ "$value" -le 65535 ] || fail "$key 超出端口范围: $value"
done
[ "$WEB_PORT" != "$OPENLIST_PORT" ] || fail "Web 与 OpenList 端口不能重复"
check_port Web "$WEB_PORT"; check_port OpenList "$OPENLIST_PORT"

COMPOSE=(docker compose --env-file "$ENV_FILE")
"${COMPOSE[@]}" config >/dev/null || fail "docker compose 配置校验失败"
ok "docker compose config 校验通过"

collect_changed_files
CURRENT_ENV_HASH="$(file_hash "$ENV_FILE")"
PREVIOUS_ENV_HASH="$(state_get env_hash || true)"
if [ -n "$PREVIOUS_ENV_HASH" ] && [ "$PREVIOUS_ENV_HASH" != "$CURRENT_ENV_HASH" ]; then
  warn ".env 自上次成功部署后发生变化，将重新协调全部服务"
  CONFIG_ALL=1; UPDATE_BACKEND=1; UPDATE_FRONTEND=1; UPDATE_OPENLIST=1
fi

container_running camera-recorder-backend || UPDATE_BACKEND=1
container_running camera-recorder-web || UPDATE_FRONTEND=1
container_running camera-recorder-openlist || UPDATE_OPENLIST=1

if [ "$UPDATE_BACKEND" = "1" ] && [ -z "$("${COMPOSE[@]}" images -q backend 2>/dev/null || true)" ]; then BUILD_BACKEND=1; fi
if [ "$UPDATE_FRONTEND" = "1" ] && [ -z "$("${COMPOSE[@]}" images -q frontend 2>/dev/null || true)" ]; then BUILD_FRONTEND=1; fi

printf '\n'
info "自动部署分析: ${PLAN_SOURCE:-当前状态}"
if [ -n "$CHANGED_FILES" ]; then
  printf '检测到变更文件:\n'
  printf '%s\n' "$CHANGED_FILES" | awk 'NR<=20{print "  - " $0}'
  CHANGED_COUNT="$(printf '%s\n' "$CHANGED_FILES" | awk 'NF{n++}END{print n+0}')"
  [ "$CHANGED_COUNT" -le 20 ] || printf '  ... 另有 %s 个文件\n' "$((CHANGED_COUNT - 20))"
else
  printf '检测到变更文件: 无运行时相关变化\n'
fi

BUILD_LABELS=""; UPDATE_LABELS=""
[ "$BUILD_BACKEND" = "1" ] && BUILD_LABELS="${BUILD_LABELS} backend"
[ "$BUILD_FRONTEND" = "1" ] && BUILD_LABELS="${BUILD_LABELS} frontend"
[ "$UPDATE_BACKEND" = "1" ] && UPDATE_LABELS="${UPDATE_LABELS} backend"
[ "$UPDATE_FRONTEND" = "1" ] && UPDATE_LABELS="${UPDATE_LABELS} frontend"
[ "$UPDATE_OPENLIST" = "1" ] && UPDATE_LABELS="${UPDATE_LABELS} openlist"
printf '需要构建:%s\n' "${BUILD_LABELS:- 无}"
printf '需要更新:%s\n' "${UPDATE_LABELS:- 无}"
if [ "$UPDATE_BACKEND" = "0" ]; then ok "backend 保持运行，当前录像不会因本次部署中断"
else warn "本次需要更新 backend；backend 容器重建/重启时，正在录像会短暂中断"; fi
printf '\n'

if [ "$CHECK_ONLY" = "1" ]; then ok "检查完成（--check-only），未构建或启动服务"; exit 0; fi

if [ "$BUILD_BACKEND" = "1" ] && [ "$NO_BUILD" = "0" ]; then prepare_ffmpeg "$DOCKER_ARCH"; ensure_image python:3.12-slim "$DOCKER_ARCH"; fi
if [ "$BUILD_FRONTEND" = "1" ] && [ "$NO_BUILD" = "0" ]; then ensure_image node:22-alpine "$DOCKER_ARCH"; ensure_image nginx:1.27-alpine "$DOCKER_ARCH"; fi
if [ "$UPDATE_OPENLIST" = "1" ]; then ensure_image openlistteam/openlist:latest "$DOCKER_ARCH"; fi

BUILD_SERVICES=()
[ "$BUILD_BACKEND" = "1" ] && BUILD_SERVICES+=(backend)
[ "$BUILD_FRONTEND" = "1" ] && BUILD_SERVICES+=(frontend)
if [ "${#BUILD_SERVICES[@]}" -gt 0 ]; then
  if [ "$NO_BUILD" = "1" ]; then
    warn "已使用 --no-build，跳过所需镜像构建:${BUILD_LABELS}"
  else
    BUILD_CMD=("${COMPOSE[@]}" build)
    if "${COMPOSE[@]}" build --help 2>/dev/null | grep -q -- '--builder'; then BUILD_CMD+=(--builder default); fi
    BUILD_CMD+=("${BUILD_SERVICES[@]}")
    mkdir -p logs; : > "$BUILD_LOG"
    info "开始构建:${BUILD_LABELS}（默认静默，完整日志: $BUILD_LOG）..."
    set +e
    if [ "${DEPLOY_BUILD_VERBOSE:-0}" = "1" ]; then "${BUILD_CMD[@]}" 2>&1 | tee "$BUILD_LOG"; BUILD_RC=${PIPESTATUS[0]}
    else "${BUILD_CMD[@]}" >"$BUILD_LOG" 2>&1; BUILD_RC=$?; fi
    set -e
    if [ "$BUILD_RC" -ne 0 ]; then show_build_errors "$BUILD_LOG"; fail "镜像构建失败，完整日志: $BUILD_LOG"; fi
    ok "镜像构建完成:${BUILD_LABELS}"
  fi
fi

UPDATE_SERVICES=()
[ "$UPDATE_BACKEND" = "1" ] && UPDATE_SERVICES+=(backend)
[ "$UPDATE_FRONTEND" = "1" ] && UPDATE_SERVICES+=(frontend)
[ "$UPDATE_OPENLIST" = "1" ] && UPDATE_SERVICES+=(openlist)

if [ "${#UPDATE_SERVICES[@]}" -gt 0 ]; then
  info "启动/更新服务:${UPDATE_LABELS}"
  if [ "$CONFIG_ALL" = "1" ]; then
    compose_up_with_network_recovery || fail "docker compose up 失败，日志: $UP_LOG"
  else
    compose_up_with_network_recovery --no-deps "${UPDATE_SERVICES[@]}" || fail "docker compose up 失败，日志: $UP_LOG"
  fi
else
  ok "代码与服务状态均无需更新，跳过容器重建"
fi

if [ "$UPDATE_BACKEND" = "1" ] || container_exists camera-recorder-backend; then
  info "等待 backend 健康..."
  if ! wait_for_health camera-recorder-backend 150; then "${COMPOSE[@]}" logs --tail=120 backend || true; fail "backend 未通过健康检查"; fi
  ok "backend healthy（仅 Docker 内网可达）"
fi
if [ "$UPDATE_FRONTEND" = "1" ] || container_exists camera-recorder-web; then
  info "检查 frontend..."
  if ! wait_for_health camera-recorder-web 60; then "${COMPOSE[@]}" logs --tail=80 frontend || true; fail "frontend 容器未正常运行"; fi
  set +e; http_ok "http://127.0.0.1:${WEB_PORT}/health"; HTTP_RC=$?; set -e
  case "$HTTP_RC" in 0) ok "Web 入口与后端 API 反代正常" ;; 1) warn "frontend 已运行，但 /health 反代检测暂未通过" ;; 2) warn "没有 curl/wget，跳过 HTTP 检测" ;; esac
fi
if [ "$UPDATE_OPENLIST" = "1" ] || container_exists camera-recorder-openlist; then
  info "检查 OpenList..."
  if ! wait_for_health camera-recorder-openlist 90; then "${COMPOSE[@]}" logs --tail=80 openlist || true; fail "OpenList 容器未正常运行"; fi
  ok "OpenList 容器运行正常"
fi

if [ "$NO_BUILD" = "1" ] && [ "${#BUILD_SERVICES[@]}" -gt 0 ]; then
  warn "由于跳过了必要构建，本次不更新智能部署基线；下次仍会检测到这些源码变化"
else
  save_deploy_state
  ok "已记录本次成功部署基线"
fi

printf '\n'; "${COMPOSE[@]}" ps; printf '\n'
ok "部署完成"
printf 'Camera Recorder Web: http://127.0.0.1:%s\n' "$WEB_PORT"
printf 'Backend API:        internal only (backend:8000, via Web /api and /ws)\n'
printf 'OpenList:           http://127.0.0.1:%s\n' "$OPENLIST_PORT"
printf '\n常用命令:\n'
printf '  智能增量部署: git pull && ./deploy.sh\n'
printf '  预览部署计划: ./deploy.sh --check-only\n'
printf '  强制完整部署: ./deploy.sh --full\n'
printf '  查看后端日志: docker compose logs -f backend\n'
printf '  查看全部状态: docker compose ps\n'
