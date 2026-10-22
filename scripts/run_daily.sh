#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

DAY=""
COLLECT=1
REFRESH=1
SUBMIT=1
DRY_RUN=0
GENERATE_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --date)
            [[ $# -ge 2 ]] || { echo "缺少 --date 的值" >&2; exit 2; }
            DAY="$2"; GENERATE_ARGS+=("$1" "$2"); shift 2 ;;
        --no-collect) COLLECT=0; shift ;;
        --no-refresh) REFRESH=0; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --no-submit) SUBMIT=0; shift ;;
        -h|--help)
            cat <<'EOF'
用法：./scripts/run_daily.sh [--date YYYY-MM-DD] [--no-collect] [--no-refresh] [--dry-run] [--no-submit]

默认依次执行：采集 Agent 会话 → 刷新当前任务 → 生成日报 → 通过 Jira API 提交工时。
  --date          指定日期，默认北京时间今天
  --no-collect    不采集 Claude Code / Codex 会话
  --no-refresh    不查询 Jira，使用已有当前任务.md
  --dry-run       预览采集结果和日报，不写日报/提交记录、不提交
  --no-submit     只生成日报，不提交 Jira
EOF
            exit 0 ;;
        *) echo "未知参数：$1" >&2; exit 2 ;;
    esac
done

if [[ -z "$DAY" ]]; then
    DAY="$("$TASK_ROOT/run_python.sh" today.py)"
fi

if (( COLLECT )); then
    if (( DRY_RUN )); then
        "$TASK_ROOT/collect_agents.sh" --date "$DAY" --dry-run
    else
        "$TASK_ROOT/collect_agents.sh" --date "$DAY"
    fi
fi

if (( REFRESH )); then
    "$TASK_ROOT/update_tasks.sh"
fi
# run_daily owns the refresh step; never let generate_daily refresh a second time.
GENERATE_ARGS+=(--no-refresh)

if (( DRY_RUN )); then
    TMP="$(mktemp "${TMPDIR:-/tmp}/daily-report.XXXXXX")"
    trap 'rm -f "$TMP"' EXIT
    if [[ ${#GENERATE_ARGS[@]} -gt 0 ]]; then
        "$TASK_ROOT/generate_daily.sh" "${GENERATE_ARGS[@]}" --dry-run | tee "$TMP"
    else
        "$TASK_ROOT/generate_daily.sh" --dry-run | tee "$TMP"
    fi
    if (( SUBMIT )); then
        "$TASK_ROOT/submit_daily.sh" --date "$DAY" --report "$TMP" --dry-run
    else
        echo "已跳过提交（--no-submit）。"
    fi
    exit 0
fi

if [[ ${#GENERATE_ARGS[@]} -gt 0 ]]; then
    "$TASK_ROOT/generate_daily.sh" "${GENERATE_ARGS[@]}"
else
    "$TASK_ROOT/generate_daily.sh"
fi

if (( SUBMIT )); then
    "$TASK_ROOT/submit_daily.sh" --date "$DAY"
else
    echo "已跳过提交（--no-submit）。"
fi
