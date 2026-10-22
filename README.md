# 每日总结

## 目录结构

```text
每日总结/
├── config.toml          # 最小配置
├── config.example.toml
├── requirements.txt
├── bootstrap.sh         # 一键初始化
├── setup.sh             # 创建 .venv 并安装依赖
├── prompts/             # 提示词
│   ├── daily_report.md
│   └── agent_summary.md
├── scripts/             # 代码
│   ├── collect_agents.py/.sh
│   ├── update_tasks.py/.sh
│   ├── generate_daily.py/.sh
│   ├── submit_daily.py/.sh
│   ├── jira_auth.py
│   ├── jira_login.py/.sh
│   ├── run_daily.sh
│   ├── run_python.sh
│   ├── today.py
│   ├── check_setup.py/.sh
│   └── project_config.py
├── tools/wechat-macos/  # 可选：企业微信 macOS 辅助脚本
├── data/                # 运行数据
│   ├── 当前任务.md
│   ├── AI总结/
│   ├── 企业微信总结/
│   └── 日报/
└── README.md
```

各来源在 `data/` 下独立维护工作记录，例如 `data/AI总结/`、`data/企业微信总结/`、后续的 IDEA 等文件夹。这些是工作记录来源，不是 Jira 项目。记录文件使用 `YYYY-MM-DD-项目.md` 命名。

## 配置文件

根目录 `config.toml` 只保留两项：

```toml
[claude]
settings = "~/path/to/ds.json"

[jira]
label = "YourMainLabel"
```

Jira 项目固定为 `PLS`，工单号模式固定为 `PLS-\d+`，不需要配置；只有标签（默认 `ConnerMain`）需要按人调整。

其余默认值在 `scripts/project_config.py` 的 `DEFAULTS`：

- `jira.credentials` 默认 `data/jira_auth.json`
- `report`：来源根目录、日报命名、200 字正文上限、8 小时规则
- `agents`：Claude Code / Codex 目录、截断上限
- `submit`：提交记录、单任务工时上限

需要时可以在 `config.toml` 覆盖任意默认值，示例见 `config.example.toml`。

提示词在 `prompts/daily_report.md` 和 `prompts/agent_summary.md`，使用 `{DAY}`、`{KEYS}`、`{MAX_CHARS}`、`{DATA}` 占位。改措辞或字数要求直接改文件，不用动代码；也可在 `config.toml` 的 `[prompts]` 覆盖文件路径。

`scripts/run_python.sh` 优先使用项目内 `.venv/bin/python`，没有时回退到系统 `python3`；不再依赖 pdl 环境或 `PYTHONPATH`。

## Jira 登录

凭据保存在 `data/jira_auth.json`（0600），不进入 git。

```bash
# 从旧 pdl 配置导入一次（可选）
./scripts/jira_login.sh --from-pdl ~/.auto_daily_log/data.db --test

# 或直接填写 PAT
./scripts/jira_login.sh --server-url https://work.example.com \
  --auth-mode pat --username your-name --pat "xxxx" --test

# Cookie 模式
./scripts/jira_login.sh --server-url https://work.example.com \
  --auth-mode cookie --cookie "..." --test
```

也支持环境变量 `JIRA_SERVER_URL`、`JIRA_USERNAME`、`JIRA_PAT`、`JIRA_COOKIE`、`JIRA_AUTH_MODE` 临时覆盖。

## 他人部署

```bash
./bootstrap.sh   # 首次会生成 config.toml 后退出
# 编辑 config.toml 的 claude.settings 和 jira.label
./bootstrap.sh   # 创建 .venv、导入/配置 Jira、自检
```

`bootstrap.sh` 会：

- 缺 `config.toml` 时从 `config.example.toml` 生成并提示编辑；
- 缺 `.venv` 或 httpx 时运行 `setup.sh`；
- 缺 Jira 凭据时，检测到 `~/.auto_daily_log/data.db` 会询问导入，否则进入 `jira_login`；
- 创建 `data/` 和默认来源目录；
- 最后运行 `check_setup.sh`。

常用参数：

```bash
./bootstrap.sh --yes                  # 非交互；自动导入旧 pdl 配置
./bootstrap.sh --from-pdl PATH        # 指定 pdl 的 data.db
./bootstrap.sh --jira-server-url https://work.example.com \
  --jira-auth-mode pat --jira-username your-name --jira-pat "xxxx" --test-jira
```

确认配置后，先跑 `./scripts/run_daily.sh --no-submit`，没问题再去掉 `--no-submit`。

`wechat/` 是可选的企业微信工具（本地保留，不纳入仓库）；`tools/wechat-macos/` 记录了 macOS 密钥提取尝试，当前环境被 hardened runtime/SIP 阻塞，不影响主流程。

## 版本管理

仓库不提交以下内容：

- `data/`：个人工作记录、日报、提交记录、`当前任务.md`；
- `config.toml`：Claude 配置和 Jira 标签；
- `data/jira_auth.json`：Jira 登录凭据（属于 `data/`，已被忽略）；
- `.venv/`：本地依赖环境；
- `wechat/` 工具本体（第三方、Linux/Wine 版，本地保留但不提交）；
- `tools/wechat-macos/` 辅助脚本会提交。

克隆后：

```bash
./bootstrap.sh   # 首次生成 config.toml 后退出
# 编辑 config.toml
./bootstrap.sh   # 安装依赖、配置 Jira、自检
```

## 采集 Agent 工作记录

```bash
./scripts/collect_agents.sh
./scripts/collect_agents.sh --date 2026-10-22
./scripts/collect_agents.sh --dry-run
./scripts/collect_agents.sh --agent codex
./scripts/collect_agents.sh --show-digest
```

默认使用内置 provider：Claude Code（`~/.claude/projects`）和 Codex（`~/.codex/sessions`），可在 `config.toml` 覆盖。按指定日期筛选会话记录，抽取用户需求、阶段结论、涉及文件与命令，再用与日报相同的 Claude 命令总结为 `data/AI总结/YYYY-MM-DD-Agent.md`。没有会话时不调用 Claude、不写文件；调用或写入失败时保留旧记录。`--dry-run` 只列出找到的会话，`--agent` 按 provider id 过滤。

会话清单只保留 Agent、工作目录和会话 ID，不保留时间，避免把日志跨度误当成工时。新增 Agent 时，在 `agents.providers` 增加条目，实现对应的 `extract_<type>` 并注册到 `EXTRACTORS` 即可。

## 当前任务同步

```bash
./scripts/update_tasks.sh
./scripts/update_tasks.sh --dry-run
```

从 Jira 查询 `jira.jql`，项目固定为 `PLS`，`{label}` 替换为 `jira.label`（默认 `ConnerMain`），分页读取全部匹配工单，生成 `data/当前任务.md`。描述以引用块写入，避免任务描述里的标题或 `## PLS-xxx` 行被日报脚本误认为文档结构。保留状态与父任务关系，不额外按经办人或完成状态过滤。该步骤不调用 Claude；日报生成时再由 Claude 将任务要求与当天实际记录结合。

使用项目自带的 `scripts/jira_auth.py` 读取 `data/jira_auth.json`（或环境变量）直接查询 Jira，不再依赖 pdl 环境。查询完成后原子替换文档，失败时保留上一版。同步结果为空时明确写入“没有匹配标签的任务”。

## 日报与工时约定

1. 刷新全局 `data/当前任务.md`。
2. 读取 `data/` 各来源文件夹中指定日期的 Markdown 工作记录，结合任务描述，由 Claude 生成按项目归档的当天日志。任务目标不能当成完成事实；同一工作在多个来源出现时应合并。
3. 每个 Jira 主任务正文不超过 `report.max_body_chars`（默认 200 字），只保留最重要的 2–3 项结果，不写长清单。
4. 有明确工时记录时按 Jira 主任务归属汇总，同一段工作不重复计时；当天没有工时记录时，总时间默认 8 小时，按 Jira 主任务平均分配，不按来源文件夹分配。
5. 使用项目自带的 Jira 客户端按工单、日期和分配后的工时提交，并保留提交结果。

## 生成日报

```bash
./scripts/generate_daily.sh
./scripts/generate_daily.sh --date 2026-10-22
./scripts/generate_daily.sh --no-refresh --dry-run
```

默认先更新全局任务，然后递归读取 `data/` 下各来源文件夹中的 `YYYY-MM-DD-*.md`，生成 `data/日报/YYYY-MM-DD-日报.md`，按 Jira 主任务分节。跳过 `日报/`、隐藏目录及配置中的排除目录。没有有效当天记录时退出，不调用 AI、不生成空日报。同日重跑成功后覆盖对应日报，失败时保留上一版。

AI 命令由 `config.toml` 的 `claude.bin`、`claude.settings` 和可选的 `claude.extra_args` 组成，通过标准输入传递任务和来源记录。此处只需要文本归纳，因此关闭内置工具。Claude 返回结构化正文、来源和原文工时证据，脚本校验工单编号、来源、正文非空、**正文长度**与时间证据后计算默认分配工时，并生成 Markdown。校验失败时，Claude 的原始输出会保存到 `data/日报/.debug-YYYY-MM-DD.json`，便于排查且无需重新调用。

工时全部缺失时，脚本将 28800 秒按 Jira 主任务均分，余秒依任务顺序分配，确保总计恰好 8 小时；有实际工时记录时汇总这些记录，部分任务缺失工时则标记“未记录”，不擅自补足到 8 小时。子任务按文档中的父任务归属汇总。

`--dry-run` 仍会调用 Claude，但不覆盖日报；默认仍同步当前任务，若也要跳过同步可同时加 `--no-refresh`。

## 一键运行与提交工时

```bash
./scripts/run_daily.sh
./scripts/run_daily.sh --date 2026-10-22
./scripts/run_daily.sh --dry-run
./scripts/run_daily.sh --no-collect
./scripts/run_daily.sh --no-submit
```

依次执行：`collect_agents.sh` → `update_tasks.sh` → `generate_daily.sh --no-refresh` → `submit_daily.sh`。前 3 步失败时立即停止，不会用旧日报提交工时；`--dry-run` 时采集只列会话、日报只预览，不提交。

`submit_daily.sh` 可单独运行：

```bash
./scripts/submit_daily.sh --date 2026-10-22
./scripts/submit_daily.sh --date 2026-10-22 --dry-run
./scripts/submit_daily.sh --date 2026-10-22 --retry-unconfirmed
```

它解析 `data/日报/YYYY-MM-DD-日报.md` 中每个 Jira 主任务的 `- 工时：` 行，对有效工时逐条调用 Jira REST API 写入 worklog，正文作为工时备注。工时记录在 `data/日报/YYYY-MM-DD-提交.json`；重跑时已提交的工单自动跳过。

`未记录` 的任务不提交。网络异常等导致结果无法确认时记为 `unconfirmed`，重跑不会自动重试；请先到 Jira 核对，确认未写入后再加 `--retry-unconfirmed`。`--dry-run` 输出日报并列出将提交的工单，但不写日报、不写提交记录、不提交；`--no-submit` 只生成日报。
