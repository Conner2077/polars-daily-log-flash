#!/usr/bin/env bash
# Shared launcher: reads config.toml, prepares the pdl environment, runs a script.
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$TASK_ROOT/.." && pwd)"
CONFIG="$PROJECT_ROOT/config.toml"

[[ -f "$CONFIG" ]] || { echo "找不到配置文件：$CONFIG（可参考 config.example.toml）" >&2; exit 1; }
/usr/bin/env python3 -c 'import tomllib' 2>/dev/null || {
    echo "需要 Python 3.11+（tomllib）；请检查 PATH 中的 python3" >&2; exit 1;
}

eval "$(/usr/bin/env python3 - "$CONFIG" <<'PY'
import os, shlex, sys, tomllib
with open(sys.argv[1], 'rb') as stream:
    config = tomllib.load(stream)
paths = config.get('paths', {})
pdl_root = os.path.expanduser(os.path.expandvars(str(paths.get('pdl_root') or '')))
if not pdl_root:
    raise SystemExit('config.toml 必须设置 paths.pdl_root')
pdl_python = os.path.expanduser(os.path.expandvars(str(
    paths.get('pdl_python') or os.path.join(pdl_root, '.venv/bin/python'))))
pdl_server_config = os.path.expanduser(os.path.expandvars(str(
    paths.get('pdl_server_config') or '~/.polars-daily-log/config.yaml')))
print('PDL_ROOT=' + shlex.quote(pdl_root))
print('PDL_PYTHON=' + shlex.quote(pdl_python))
print('PDL_SERVER_CONFIG_DEFAULT=' + shlex.quote(pdl_server_config))
PY
)"

export PDL_SERVER_CONFIG="${PDL_SERVER_CONFIG:-$PDL_SERVER_CONFIG_DEFAULT}"
export PYTHONPATH="$PDL_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$PDL_PYTHON" "$TASK_ROOT/$1" "${@:2}"
