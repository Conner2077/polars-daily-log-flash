#!/usr/bin/env bash
# launchd entry point: run today's pipeline, log, and alert on failure.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/data/logs"
mkdir -p "$LOG_DIR"
umask 077

if ! DAY="$("$ROOT/scripts/run_python.sh" today.py 2>>"$LOG_DIR/bootstrap.err")"; then
    echo "无法计算当天日期，详见 $LOG_DIR/bootstrap.err" >&2
    exit 1
fi
LOG="$LOG_DIR/$DAY.log"
exec >> "$LOG" 2>&1

echo "=== $(date '+%F %T') scheduled run start (date=$DAY) ==="

set +e
if [[ "${SCHEDULED_NO_SUBMIT:-0}" == "1" ]]; then
    "$ROOT/scripts/run_daily.sh" --date "$DAY" --no-submit
else
    "$ROOT/scripts/run_daily.sh" --date "$DAY"
fi
code=$?
set -e

if (( code != 0 )); then
    echo "=== $(date '+%F %T') FAILED exit=$code ==="
    echo "每日总结失败：${DAY}，exit=${code}，日志：${LOG}" > "$LOG_DIR/last-failure.txt"
    "$ROOT/scripts/run_python.sh" notify_failure.py \
        --date "$DAY" --code "$code" --log "$LOG" || true
    exit "$code"
fi

echo "=== $(date '+%F %T') success ==="
rm -f "$LOG_DIR/last-failure.txt"
exit 0
