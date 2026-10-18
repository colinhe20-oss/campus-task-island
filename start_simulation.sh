#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo '请先按 README.md 建立 .venv 并安装 Python 依赖。' >&2
  exit 1
fi
if [[ ! -d web/node_modules ]]; then
  npm --prefix web ci
fi
npm --prefix web run build
exec .venv/bin/python -m examples.simulation_server "$@"
