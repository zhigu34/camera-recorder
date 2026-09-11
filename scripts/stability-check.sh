#!/usr/bin/env bash
set -euo pipefail

HOURS="${1:-24}"

if ! [[ "$HOURS" =~ ^[0-9]+$ ]] || [ "$HOURS" -lt 1 ] || [ "$HOURS" -gt 168 ]; then
  echo "用法: $0 [1-168]" >&2
  echo "示例: $0 24    # 24 小时验收" >&2
  echo "      $0 72    # 72 小时验收" >&2
  exit 64
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "未找到 docker compose / docker-compose" >&2
  exit 69
fi

if ! "${COMPOSE[@]}" ps --status running backend 2>/dev/null | grep -q backend; then
  echo "backend 容器未运行，请先执行 ./deploy.sh" >&2
  exit 69
fi

exec "${COMPOSE[@]}" exec -T backend \
  python -m app.cli.stability_check --hours "$HOURS"
