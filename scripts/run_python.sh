#!/usr/bin/env bash
# Shared launcher: picks the project venv (or python3) and runs a script.
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$TASK_ROOT/.." && pwd)"
CONFIG="$PROJECT_ROOT/config.toml"

[[ -f "$CONFIG" ]] || { echo "找不到配置文件：$CONFIG（可参考 config.example.toml）" >&2; exit 1; }

PYTHON="${DAILY_SUMMARY_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3 || true)"
fi
[[ -n "$PYTHON" ]] || { echo "找不到 Python 3.11+；请安装 Python 并运行 ./setup.sh" >&2; exit 1; }

"$PYTHON" -c 'import tomllib' 2>/dev/null || {
    echo "需要 Python 3.11+（tomllib）；当前：$PYTHON" >&2; exit 1;
}
"$PYTHON" -c 'import httpx' 2>/dev/null || {
    echo "缺少 httpx；请运行 ./setup.sh 安装依赖" >&2; exit 1;
}
exec "$PYTHON" "$TASK_ROOT/$1" "${@:2}"
