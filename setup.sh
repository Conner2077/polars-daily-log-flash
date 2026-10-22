#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

python3 - <<'PY' || { echo "需要 Python 3.11+（tomllib）" >&2; exit 1; }
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

python3 -m venv "$ROOT/.venv"
if ! "$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"; then
    echo "默认 pip 源失败，改用官方 PyPI 重试..."
    "$ROOT/.venv/bin/python" -m pip install --index-url https://pypi.org/simple \
        -r "$ROOT/requirements.txt"
fi
echo "依赖安装完成：$ROOT/.venv"
echo "下一步：cp config.example.toml config.toml && ./scripts/jira_login.sh"
