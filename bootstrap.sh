#!/usr/bin/env bash
# One-time local setup: config, venv, Jira login, data directories, checks.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TASK_ROOT="$ROOT/scripts"
CONFIG="$ROOT/config.toml"
EXAMPLE="$ROOT/config.example.toml"

YES=0
SKIP_SETUP=0
SKIP_LOGIN=0
SKIP_CHECK=0
TEST_JIRA=0
FROM_PDL=""
JIRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes) YES=1; shift ;;
        --skip-setup) SKIP_SETUP=1; shift ;;
        --skip-login) SKIP_LOGIN=1; shift ;;
        --skip-check) SKIP_CHECK=1; shift ;;
        --test-jira) TEST_JIRA=1; shift ;;
        --from-pdl)
            [[ $# -ge 2 ]] || { echo "缺少 --from-pdl 的值" >&2; exit 2; }
            FROM_PDL="$2"; shift 2 ;;
        --jira-server-url)
            [[ $# -ge 2 ]] || { echo "缺少 --jira-server-url 的值" >&2; exit 2; }
            JIRA_ARGS+=(--server-url "$2"); shift 2 ;;
        --jira-auth-mode)
            [[ $# -ge 2 ]] || { echo "缺少 --jira-auth-mode 的值" >&2; exit 2; }
            JIRA_ARGS+=(--auth-mode "$2"); shift 2 ;;
        --jira-username)
            [[ $# -ge 2 ]] || { echo "缺少 --jira-username 的值" >&2; exit 2; }
            JIRA_ARGS+=(--username "$2"); shift 2 ;;
        --jira-pat)
            [[ $# -ge 2 ]] || { echo "缺少 --jira-pat 的值" >&2; exit 2; }
            JIRA_ARGS+=(--pat "$2"); shift 2 ;;
        --jira-cookie)
            [[ $# -ge 2 ]] || { echo "缺少 --jira-cookie 的值" >&2; exit 2; }
            JIRA_ARGS+=(--cookie "$2"); shift 2 ;;
        -h|--help)
            cat <<'EOF'
用法：./bootstrap.sh [选项]

默认执行：生成配置（如缺失）→ 创建 .venv → 导入/配置 Jira 登录 → 创建 data 目录 → 自检。

  --yes                非交互模式；检测到旧 pdl 配置时自动导入
  --skip-setup         跳过创建 .venv/安装依赖
  --skip-login         跳过 Jira 登录配置
  --skip-check         跳过最后自检
  --test-jira          配置完成后验证 Jira 连接
  --from-pdl PATH      从 pdl 的 data.db 导入 Jira 登录
  --jira-server-url URL
  --jira-auth-mode pat|cookie
  --jira-username USER
  --jira-pat PAT
  --jira-cookie COOKIE
EOF
            exit 0 ;;
        *) echo "未知参数：$1" >&2; exit 2 ;;
    esac
done

if [[ ! -f "$CONFIG" ]]; then
    cp "$EXAMPLE" "$CONFIG"
    echo "已生成 $CONFIG"
    echo "请先编辑 [claude].settings 和 [jira].label，然后重新运行 ./bootstrap.sh"
    exit 0
fi

mkdir -p "$ROOT/data/AI总结" "$ROOT/data/企业微信总结" "$ROOT/data/日报"

if (( ! SKIP_SETUP )); then
    need_setup=0
    if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
        need_setup=1
    elif ! "$ROOT/.venv/bin/python" -c 'import httpx' 2>/dev/null; then
        need_setup=1
    fi
    if (( need_setup )); then
        echo "创建本地 .venv 并安装依赖..."
        "$ROOT/setup.sh"
    else
        echo "本地 .venv 已就绪"
    fi
fi

if (( ! SKIP_LOGIN )); then
    credentials="$ROOT/data/jira_auth.json"
    has_override=0
    [[ -n "$FROM_PDL" || ${#JIRA_ARGS[@]} -gt 0 ]] && has_override=1

    if [[ -f "$credentials" && $has_override -eq 0 ]]; then
        echo "Jira 凭据已存在：$credentials"
        if (( TEST_JIRA )); then
            "$TASK_ROOT/jira_login.sh" --test || true
        fi
    else
        login_args=()
        if [[ -n "$FROM_PDL" ]]; then
            login_args+=(--from-pdl "$FROM_PDL")
        elif [[ -f "$HOME/.auto_daily_log/data.db" ]]; then
            if (( YES )); then
                login_args+=(--from-pdl "$HOME/.auto_daily_log/data.db")
            elif [[ -t 0 ]]; then
                read -r -p "检测到旧 pdl 配置，导入 Jira 登录？[Y/n] " answer
                if [[ -z "${answer:-}" || "$answer" =~ ^[Yy]$ ]]; then
                    login_args+=(--from-pdl "$HOME/.auto_daily_log/data.db")
                fi
            fi
        fi
        login_args+=("${JIRA_ARGS[@]}")

        if [[ ${#login_args[@]} -eq 0 ]]; then
            if [[ -t 0 ]]; then
                if (( TEST_JIRA )); then
                    "$TASK_ROOT/jira_login.sh" --test
                else
                    "$TASK_ROOT/jira_login.sh"
                fi
            else
                echo "未找到 Jira 凭据。请运行：" >&2
                echo "  ./scripts/jira_login.sh --server-url ... --auth-mode pat --username ... --pat ..." >&2
                exit 1
            fi
        else
            if (( TEST_JIRA )); then
                login_args+=(--test)
            fi
            "$TASK_ROOT/jira_login.sh" "${login_args[@]}"
        fi
    fi
fi

if (( ! SKIP_CHECK )); then
    "$TASK_ROOT/check_setup.sh"
fi

echo
echo "初始化完成。下一步：./scripts/run_daily.sh --no-submit"
