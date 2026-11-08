#!/usr/bin/env bash
# 启动语音桥（常驻；可被 LaunchAgent / systemd 调用）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if [ -z "${MCP_ENDPOINT:-}" ]; then
  echo "缺少 MCP_ENDPOINT，请先 cp .env.example .env 并填入小智云接入点" >&2
  exit 1
fi

exec python3 -u mcp_pipe.py
