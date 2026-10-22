# AGENTS.md

你是负责运行和维护本项目的编码 Agent。用户通常让你代替他执行每日工作总结。先读完本文件再动手。

## 目标

每天：

1. 采集本机 Agent 会话（Claude Code / Codex）；
2. 从 Jira 同步 `PLS` 项目下带标签的任务；
3. 读取 `data/` 各来源当天的工作记录；
4. 用 Claude 生成日报；
5. **用户明确要求时**才提交 Jira 工时。

## 绝对规则

- 不提交 `data/`、`config.toml`、`data/jira_auth.json`、`.venv/`、`wechat/`。
- 不打印 PAT、Cookie、API key、聊天内容或凭据文件内容。
- 默认不提交 Jira。先用 `--no-submit` 或 `--dry-run`；只有用户明确说“提交”才执行。
- 不手工改 `data/` 下生成的文件；要改内容就改来源记录或 `prompts/`。
- 所有命令从项目根目录执行。

## 目录

```text
config.toml             # 最小配置：claude.settings、jira.label
bootstrap.sh            # 一键初始化
setup.sh                # 创建 .venv 并安装 httpx
prompts/                # 日报/Agent 总结提示词
scripts/                # 所有执行脚本
data/                   # 运行数据，已被 git 忽略
  ├── 当前任务.md
  ├── AI总结/
  ├── 企业微信总结/
  └── 日报/
```

## 首次初始化

```bash
./bootstrap.sh
```

- 如果它生成了 `config.toml` 后退出：先问用户 `[claude].settings`（Claude 配置 JSON）和 `[jira].label`，写入后重新运行。
- 有旧 pdl 配置时可以非交互导入：
  `./bootstrap.sh --yes` 或 `./scripts/jira_login.sh --from-pdl ~/.auto_daily_log/data.db --test`

检查登录状态：

```bash
./scripts/jira_login.sh --status
```

- 返回 0 表示已登录，只输出 Jira 地址、认证方式和用户名，不输出密钥。
- 返回非 0 表示未登录：
  - 有 `~/.auto_daily_log/data.db` → `./scripts/jira_login.sh --from-pdl ~/.auto_daily_log/data.db --test`
  - 否则向用户索要 Jira 地址和 PAT/Cookie，使用显式参数：
    `./scripts/jira_login.sh --server-url ... --auth-mode pat --username ... --pat ... --test`
  - **不要裸跑 `jira_login.sh`**：无参数时它会交互式等待输入，非 TTY 环境会失败或阻塞。

初始化验收：

```bash
./scripts/check_setup.sh          # 必须全部 OK
./scripts/update_tasks.sh --dry-run
./scripts/run_daily.sh --no-submit
```

## 日常命令

| 目的 | 命令 |
|---|---|
| 只生成，不提交 | `./scripts/run_daily.sh --no-submit` |
| 预览，不落盘、不提交 | `./scripts/run_daily.sh --dry-run` |
| 生成并提交（需用户明确要求） | `./scripts/run_daily.sh` |
| 指定日期 | 任意上述命令加 `--date YYYY-MM-DD` |
| 只刷新 Jira 任务 | `./scripts/update_tasks.sh` |
| 只生成日报 | `./scripts/generate_daily.sh --no-refresh` |
| 只提交日报工时 | `./scripts/submit_daily.sh --date YYYY-MM-DD` |
| 只采集 Agent 会话 | `./scripts/collect_agents.sh --date YYYY-MM-DD` |
| Jira 登录状态 | `./scripts/jira_login.sh --status` |
| 定时任务状态 | `./scripts/install_schedule.sh --status` |
| 安装/卸载定时 | `./scripts/install_schedule.sh` / `--uninstall` |

## 定时任务

- 已安装 launchd，默认每天 21:00 跑当天流程并自动提交 Jira；
- 不要随意执行 `./scripts/install_schedule.sh --run-now`：它会立即触发并提交 Jira，只有用户明确要求时才能用；
- 手动测试但不提交：`SCHEDULED_NO_SUBMIT=1 ./scripts/run_scheduled.sh`；
- 失败会写 `data/logs/last-failure.txt`、发 macOS 通知，并可选 POST 到 `[notify].webhook_url`；
- 日志在 `data/logs/`，属于 `data/`，不提交。

## 输出位置

- `data/当前任务.md`：Jira 任务快照；
- `data/AI总结/YYYY-MM-DD-Agent.md`：Agent 会话总结；
- `data/日报/YYYY-MM-DD-日报.md`：最终日报；
- `data/日报/YYYY-MM-DD-提交.json`：提交记录和 Jira worklog ID；
- `data/<来源>/YYYY-MM-DD-*.md`：各来源工作记录。

日报每个 Jira 主任务正文上限 200 字；无工时记录时总计 8 小时按主任务均分。

## 配置

`config.toml` 只放每台机器必须改的：

```toml
[claude]
settings = "~/path/to/ds.json"

[jira]
label = "YourMainLabel"
```

- Jira 项目固定 `PLS`，工单号模式固定 `PLS-\d+`，不需要配置；
- 其他默认值在 `scripts/project_config.py` 的 `DEFAULTS`；
- 提示词在 `prompts/daily_report.md` 和 `prompts/agent_summary.md`；
- 可覆盖默认值，示例见 `config.example.toml`。

## Agent 采集

- 默认扫描 Claude Code `~/.claude/projects` 和 Codex `~/.codex/sessions`；
- 按记录时间过滤指定日期；没有会话时不调用 Claude、不写文件；
- 新增 Agent：在 `agents.providers` 增加 provider，实现 `extract_<type>` 并注册到 `EXTRACTORS`；
- 企业微信暂未接入；`wechat/` 是本地工具，不纳入仓库。

## 故障排查

| 现象 | 处理 |
|---|---|
| `ModuleNotFoundError: httpx` | 运行 `./setup.sh` |
| `Jira 未登录` / 401/403 | `./scripts/jira_login.sh --status`，必要时重新登录 |
| `Claude settings` FAIL | 修改 `config.toml` 的 `claude.settings` |
| 没有来源记录 | 检查 `data/*/YYYY-MM-DD-*.md`；先跑 `collect_agents.sh` |
| 提交状态 `unconfirmed` | 去 Jira 核对；确认未写入后用 `--retry-unconfirmed` |
| 重复提交保护 | 已提交工单在 `data/日报/*-提交.json`，重跑会自动跳过 |

## 提交代码前

```bash
git status --short
```

确认没有 `data/`、`config.toml`、`data/jira_auth.json`、`.venv/`、`wechat/`。若出现，先修 `.gitignore`，不要强推。
