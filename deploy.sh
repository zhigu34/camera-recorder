#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ROOT_DIR}/.env"
ENV_EXAMPLE="${ROOT_DIR}/.env.example"
BUILD_LOG="${ROOT_DIR}/logs/deploy-build.log"
CHECK_ONLY=0
NO_FFMPEG_DOWNLOAD=0
NO_BUILD=0

info() { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Camera Recorder 一键部署脚本

用法:
  bash deploy.sh [选项]

选项:
  --check-only          只做环境/配置检查，不构建和启动
  --no-ffmpeg-download  FFmpeg 本地包缺失时不尝试联网下载
  --no-build            跳过镜像构建，直接启动现有镜像
  -h, --help            显示帮助

可选环境变量:
  DEPLOY_AUTO_PULL=0     缺少基础镜像时不自动 docker pull（默认 1）
  FFMPEG_DOWNLOAD_BASE  覆盖 FFmpeg 预下载脚本的下载地址
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

command_exists() { command -v "$1" >/dev/null 2>&1; }

random_hex() {
  local bytes="${1:-32}"
  if command_exists openssl; then
    openssl rand -hex "$bytes"
  elif [ -r /dev/urandom ] && command_exists od; then
    od -An -N"$bytes" -tx1 /dev/urandom | tr -d ' \n'
    printf '\n'
  else
    fail "无法生成安全随机密钥：需要 openssl，或 od + /dev/urandom"
  fi
}

env_get() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return 1
  awk -v key="$key" 'index($0, key "=") == 1 {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

env_set() {
  local key="$1" value="$2" tmp
  tmp="${ENV_FILE}.tmp.$$"
  awk -v key="$key" -v value="$value" '
    BEGIN {done=0}
    index($0, key "=") == 1 {print key "=" value; done=1; next}
    {print}
    END {if (!done) print key "=" value}
  ' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}

ensure_env_key() {
  local key="$1" default_value="$2"
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    env_set "$key" "$default_value"
  fi
}

normalize_arch() {
  case "$1" in
    x86_64|amd64) echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
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

  if docker image inspect "$image" >/dev/null 2>&1; then
    warn "本地镜像 $image 架构不匹配当前 Docker Server ($arch)"
  else
    warn "本地缺少基础镜像: $image"
  fi

  if [ "${DEPLOY_AUTO_PULL:-1}" = "0" ]; then
    fail "请先手工准备镜像: docker pull $image（或 docker load -i <镜像包>）"
  fi

  info "尝试拉取基础镜像: $image"
  if ! docker pull "$image"; then
    fail "无法拉取 $image。当前网络无法访问镜像仓库时，请在其他机器下载后 docker save，再在本机 docker load。"
  fi

  image_arch_ok "$image" "$arch" || fail "镜像 $image 拉取后仍不是 $arch 架构"
  ok "基础镜像准备完成: $image"
}

ffmpeg_archive_name() {
  case "$1" in
    amd64) echo "ffmpeg-linux64.tar.xz" ;;
    arm64) echo "ffmpeg-linuxarm64.tar.xz" ;;
    *) return 1 ;;
  esac
}

ffmpeg_original_name() {
  case "$1" in
    amd64) echo "ffmpeg-master-latest-linux64-gpl.tar.xz" ;;
    arm64) echo "ffmpeg-master-latest-linuxarm64-gpl.tar.xz" ;;
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
  expected="${ROOT_DIR}/vendor/ffmpeg/${archive}"

  mkdir -p "${ROOT_DIR}/vendor/ffmpeg"

  if validate_archive "$expected"; then
    ok "FFmpeg 本地包有效: vendor/ffmpeg/${archive}"
    return 0
  fi

  if [ -e "$expected" ]; then
    warn "FFmpeg 本地包损坏，保留为: ${expected}.invalid"
    mv -f "$expected" "${expected}.invalid"
  fi

  for candidate in \
    "${ROOT_DIR}/${original}" \
    "${ROOT_DIR}/vendor/ffmpeg/${original}"
  do
    if validate_archive "$candidate"; then
      mv "$candidate" "$expected"
      ok "检测到已下载的 FFmpeg 包并自动归位: vendor/ffmpeg/${archive}"
      return 0
    fi
  done

  if [ "$NO_FFMPEG_DOWNLOAD" = "1" ]; then
    fail "缺少 FFmpeg 本地包: vendor/ffmpeg/${archive}"
  fi

  [ -f "${ROOT_DIR}/scripts/download-ffmpeg.sh" ] || fail "缺少 scripts/download-ffmpeg.sh"
  command_exists curl || fail "FFmpeg 包缺失且宿主机没有 curl。请手工下载 ${original} 到 vendor/ffmpeg/${archive}"

  info "FFmpeg 本地包不存在，尝试预下载（只在缺失时执行）..."
  if ! bash "${ROOT_DIR}/scripts/download-ffmpeg.sh" "$arch"; then
    cat >&2 <<EOF

FFmpeg 自动下载失败。
请在可访问 GitHub 的机器下载：
  https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/${original}

然后放到：
  ${expected}

再重新执行：
  bash deploy.sh
EOF
    exit 1
  fi

  validate_archive "$expected" || fail "FFmpeg 下载完成但压缩包校验失败: $expected"
  ok "FFmpeg 本地包准备完成"
}

project_owns_port() {
  local port="$1" container
  for container in camera-recorder-backend camera-recorder-web camera-recorder-openlist; do
    if docker inspect "$container" >/dev/null 2>&1; then
      if docker port "$container" 2>/dev/null | grep -Eq ":${port}$"; then
        return 0
      fi
    fi
  done
  return 1
}

port_in_use() {
  local port="$1"
  if command_exists ss; then
    ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq ":${port}$"
    return $?
  fi
  if command_exists lsof; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  if command_exists netstat; then
    netstat -an 2>/dev/null | grep -E 'LISTEN|LISTENING' | grep -Eq "[\.:]${port}[[:space:]]"
    return $?
  fi
  return 2
}

check_port() {
  local name="$1" port="$2" rc
  if project_owns_port "$port"; then
    ok "$name 端口 $port 已由本项目容器占用"
    return 0
  fi
  set +e
  port_in_use "$port"
  rc=$?
  set -e
  case "$rc" in
    0) fail "$name 端口 $port 已被其他进程占用，请修改 .env 后重试" ;;
    1) ok "$name 端口可用: $port" ;;
    2) warn "未找到 ss/lsof/netstat，跳过端口 $port 占用检测" ;;
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
    return $?
  fi
  if command_exists wget; then
    wget -q -T 4 -O /dev/null "$url" >/dev/null 2>&1
    return $?
  fi
  return 2
}

info "Camera Recorder 部署前检查开始"
printf '%s\n' "项目目录: $ROOT_DIR"

command_exists docker || fail "未安装 Docker"
docker version >/dev/null 2>&1 || fail "Docker daemon 不可用，请先启动 Docker"
docker compose version >/dev/null 2>&1 || fail "未安装 Docker Compose v2（需要 docker compose）"
docker buildx version >/dev/null 2>&1 || fail "未安装 Docker Buildx"
command_exists awk || fail "缺少 awk"
command_exists grep || fail "缺少 grep"
command_exists tar || fail "缺少 tar"
command_exists tee || fail "缺少 tee"

DOCKER_ARCH_RAW="$(docker info --format '{{.Architecture}}' 2>/dev/null || true)"
DOCKER_ARCH="$(normalize_arch "$DOCKER_ARCH_RAW" 2>/dev/null || true)"
[ -n "$DOCKER_ARCH" ] || fail "不支持的 Docker Server 架构: ${DOCKER_ARCH_RAW:-unknown}（仅支持 amd64/arm64）"
ok "Docker Server 架构: $DOCKER_ARCH"

if docker buildx inspect default >/dev/null 2>&1; then
  docker buildx inspect default --bootstrap >/dev/null 2>&1 || true
  export BUILDX_BUILDER=default
  ok "构建器: default (docker driver)"
else
  fail "未找到 buildx default builder。请先执行: docker buildx ls"
fi

[ -f "$ENV_EXAMPLE" ] || fail "缺少 .env.example"
if [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  info "已从 .env.example 创建 .env"
fi
chmod 600 "$ENV_FILE" 2>/dev/null || true

ensure_env_key "CAMREC_WEB_PORT" "8080"
ensure_env_key "CAMREC_API_PORT" "8000"
ensure_env_key "OPENLIST_PORT" "5244"
ensure_env_key "TZ" "Asia/Shanghai"
ensure_env_key "OPENLIST_UID" "0"
ensure_env_key "OPENLIST_GID" "0"

SECRET_KEY="$(env_get CAMREC_SECRET_KEY || true)"
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "replace-with-a-long-random-secret" ] || [ "$SECRET_KEY" = "camera-recorder-local-change-me" ]; then
  if [ -s "${ROOT_DIR}/data/camera.db" ]; then
    fail "已有 data/camera.db，但 CAMREC_SECRET_KEY 仍是占位值。为避免已有摄像头/SMTP/WebDAV 密码无法解密，脚本不会自动改密钥，请手工确认旧密钥。"
  fi
  env_set "CAMREC_SECRET_KEY" "$(random_hex 32)"
  ok "已生成 CAMREC_SECRET_KEY（仅写入 .env，不输出明文）"
else
  if [ "${#SECRET_KEY}" -lt 32 ]; then
    warn "CAMREC_SECRET_KEY 长度偏短；已有数据时不要直接更换，新部署建议使用至少 32 字符"
  else
    ok "CAMREC_SECRET_KEY 已配置"
  fi
fi

OPENLIST_PASSWORD="$(env_get OPENLIST_ADMIN_PASSWORD || true)"
if [ -z "$OPENLIST_PASSWORD" ] || [ "$OPENLIST_PASSWORD" = "replace-with-a-strong-openlist-password" ] || [ "$OPENLIST_PASSWORD" = "camera-recorder-openlist-change-me" ]; then
  if find "${ROOT_DIR}/openlist-data" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
    warn "OpenList 已有数据但管理员密码仍为占位值；为避免登录凭据变化，脚本不自动覆盖。建议你确认后手工修改 .env。"
  else
    env_set "OPENLIST_ADMIN_PASSWORD" "$(random_hex 24)"
    ok "已生成 OPENLIST_ADMIN_PASSWORD（仅写入 .env，不输出明文）"
  fi
else
  ok "OPENLIST_ADMIN_PASSWORD 已配置"
fi

mkdir -p data recordings staging failed logs openlist-data vendor/ffmpeg
for dir in data recordings staging failed logs openlist-data vendor/ffmpeg; do
  [ -w "$dir" ] || fail "目录不可写: $dir"
done

FREE_KB="$(df -Pk "$ROOT_DIR" 2>/dev/null | awk 'NR==2 {print $4}' || true)"
if [ -n "$FREE_KB" ] && [ "$FREE_KB" -lt 20971520 ]; then
  warn "当前文件系统剩余空间不足 20 GiB；录像系统上线前请确认 recordings 所在磁盘容量"
elif [ -n "$FREE_KB" ]; then
  ok "磁盘剩余空间: 约 $((FREE_KB / 1024 / 1024)) GiB"
fi

WEB_PORT="$(env_get CAMREC_WEB_PORT)"
API_PORT="$(env_get CAMREC_API_PORT)"
OPENLIST_PORT="$(env_get OPENLIST_PORT)"

for item in "CAMREC_WEB_PORT:$WEB_PORT" "CAMREC_API_PORT:$API_PORT" "OPENLIST_PORT:$OPENLIST_PORT"; do
  key="${item%%:*}"
  value="${item#*:}"
  case "$value" in
    ''|*[!0-9]*) fail "$key 不是有效端口: $value" ;;
  esac
  [ "$value" -ge 1 ] && [ "$value" -le 65535 ] || fail "$key 超出端口范围: $value"
done
[ "$WEB_PORT" != "$API_PORT" ] && [ "$WEB_PORT" != "$OPENLIST_PORT" ] && [ "$API_PORT" != "$OPENLIST_PORT" ] \
  || fail "CAMREC_WEB_PORT / CAMREC_API_PORT / OPENLIST_PORT 不能重复"

check_port "Web" "$WEB_PORT"
check_port "API" "$API_PORT"
check_port "OpenList" "$OPENLIST_PORT"

prepare_ffmpeg "$DOCKER_ARCH"

ensure_image "python:3.12-slim" "$DOCKER_ARCH"
ensure_image "node:22-alpine" "$DOCKER_ARCH"
ensure_image "nginx:1.27-alpine" "$DOCKER_ARCH"
ensure_image "openlistteam/openlist:latest" "$DOCKER_ARCH"

COMPOSE=(docker compose --env-file "$ENV_FILE")
"${COMPOSE[@]}" config >/dev/null || fail "docker compose 配置校验失败"
ok "docker compose config 校验通过"

if [ "$CHECK_ONLY" = "1" ]; then
  ok "检查完成（--check-only），未构建或启动服务"
  exit 0
fi

if [ "$NO_BUILD" = "0" ]; then
  mkdir -p logs
  BUILD_CMD=("${COMPOSE[@]}" build)
  if "${COMPOSE[@]}" build --help 2>/dev/null | grep -q -- '--builder'; then
    BUILD_CMD+=(--builder default)
  fi
  BUILD_CMD+=(backend frontend)

  info "开始构建 backend/frontend（APT/PyPI/npm 使用国内源，FFmpeg 使用本地包）..."
  set +e
  "${BUILD_CMD[@]}" 2>&1 | tee "$BUILD_LOG"
  BUILD_RC=${PIPESTATUS[0]}
  set -e

  if [ "$BUILD_RC" -ne 0 ]; then
    if grep -q "auth.docker.io" "$BUILD_LOG" 2>/dev/null; then
      warn "检测到 Docker Hub 鉴权网络错误。确认本地基础镜像存在，并确保本项目使用 default builder。"
    elif grep -Eq "mirrors\.tuna|npmmirror|pypi" "$BUILD_LOG" 2>/dev/null; then
      warn "构建失败发生在依赖源阶段，请查看: $BUILD_LOG"
    fi
    fail "镜像构建失败，完整日志: $BUILD_LOG"
  fi
  ok "backend/frontend 镜像构建完成"
else
  warn "已使用 --no-build，跳过镜像构建"
fi

info "启动/更新服务..."
"${COMPOSE[@]}" up -d || fail "docker compose up 失败"

info "等待 backend 健康..."
if ! wait_for_health "camera-recorder-backend" 150; then
  "${COMPOSE[@]}" logs --tail=120 backend || true
  fail "backend 未通过健康检查"
fi
ok "backend healthy"

info "检查 frontend..."
if ! wait_for_health "camera-recorder-web" 60; then
  "${COMPOSE[@]}" logs --tail=80 frontend || true
  fail "frontend 容器未正常运行"
fi
set +e
http_ok "http://127.0.0.1:${WEB_PORT}/"
HTTP_RC=$?
set -e
case "$HTTP_RC" in
  0) ok "frontend HTTP 可访问" ;;
  1) warn "frontend 容器已运行，但宿主机 HTTP 检测暂未通过，请稍后访问 http://127.0.0.1:${WEB_PORT}/" ;;
  2) warn "宿主机没有 curl/wget，跳过 frontend HTTP 检测" ;;
esac

info "检查 OpenList..."
if ! wait_for_health "camera-recorder-openlist" 90; then
  "${COMPOSE[@]}" logs --tail=80 openlist || true
  fail "OpenList 容器未正常运行"
fi
ok "OpenList 容器运行正常"

printf '\n'
"${COMPOSE[@]}" ps
printf '\n'
ok "部署完成"
printf 'Camera Recorder Web: http://127.0.0.1:%s\n' "$WEB_PORT"
printf 'FastAPI:             http://127.0.0.1:%s\n' "$API_PORT"
printf 'OpenList:            http://127.0.0.1:%s\n' "$OPENLIST_PORT"
printf '\n'
printf '常用命令:\n'
printf '  查看后端日志: docker compose logs -f backend\n'
printf '  查看全部状态: docker compose ps\n'
printf '  再次部署/升级: bash deploy.sh\n'
