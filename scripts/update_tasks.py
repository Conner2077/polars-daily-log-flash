"""Read labelled Jira tasks using local credentials; replace the global Markdown."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import httpx

import jira_auth
from project_config import CFG, now_local, project_path


JIRA = CFG['jira']
JQL = JIRA['jql'].replace('{project}', JIRA['project']).replace('{label}', JIRA['label'])
FIELDS = JIRA['fields']


async def fetch_tasks(client, url, headers):
    issues = []
    start = 0
    while True:
        response = await client.get(
            url,
            headers=headers,
            params={"jql": JQL, "fields": FIELDS, "startAt": start, "maxResults": 100},
        )
        response.raise_for_status()
        data = response.json()
        page = data["issues"]
        issues.extend(page)
        start += len(page)
        if start >= data["total"]:
            return issues
        if not page:
            raise ValueError("Jira 分页未返回完整任务，取消更新")


def quote_block(text):
    # Quote the raw description so its own headings or "## PLS-xxx" lines cannot
    # masquerade as document structure when generate_daily parses this file.
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())


def render_tasks(issues, base_url, synced_at):
    lines = [
        "# 当前任务", "",
        f"- 同步时间：{synced_at}",
        f"- 查询条件：`{JQL}`",
        f"- 匹配工单数：{len(issues)}",
        "- 本文件由 update_tasks.sh 自动生成；任务内容请在 Jira 中维护。",
        "- 工单描述表示任务要求；当天实际进展以各来源文件夹的工作记录为准。",
        "",
    ]
    if not issues:
        lines.extend(["当前没有匹配标签的任务。", ""])
    for issue in issues:
        key, fields = issue["key"], issue["fields"]
        title = " ".join((fields.get("summary") or "未命名任务").splitlines())
        lines.extend([
            f"## {key} {title}", "",
            f"- 工单：[{key}]({base_url.rstrip('/')}/browse/{key})",
            f"- 状态：{(fields.get('status') or {}).get('name', '未说明')}",
            f"- 类型：{(fields.get('issuetype') or {}).get('name', '未说明')}",
            f"- Jira 更新时间：{fields.get('updated') or '未说明'}",
        ])
        parent = fields.get("parent")
        if parent:
            lines.append(f"- 父任务：[{parent['key']}]({base_url.rstrip('/')}/browse/{parent['key']})")
        description = fields.get("description") or "未说明"
        lines.extend(["", "### Jira 原始描述", "", quote_block(description), ""])
    return "\n".join(lines)


def write_atomic(path, content):
    # Write in the same directory so os.replace is atomic on this filesystem.
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def run(args):
    jira = jira_auth.build_client(args.credentials)
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
        issues = await fetch_tasks(client, jira._url("/rest/api/2/search"), jira._headers())
    base_url = jira.server_url
    content = render_tasks(issues, base_url, now_local().isoformat(timespec="seconds"))
    if args.dry_run:
        print(content, end="")
    else:
        path = args.output.expanduser().resolve()
        write_atomic(path, content)
        print(f"已更新 {path}，共 {len(issues)} 个 Jira 任务")


def main():
    parser = argparse.ArgumentParser(
        description=f"同步 {JIRA['project']} 中带 {JIRA['label']} 标签的任务到全局当前任务.md")
    parser.add_argument("--credentials", help="Jira 凭据文件；默认 data/jira_auth.json")
    parser.add_argument("--output", type=Path, default=project_path(CFG['jira']['output']))
    parser.add_argument("--dry-run", action="store_true", help="查询并预览，不写文件")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except httpx.HTTPStatusError as exc:
        print(f"同步失败：Jira HTTP {exc.response.status_code}；请检查登录状态及查询权限。原文件未更新。", file=sys.stderr)
        return 1
    except (Exception, KeyboardInterrupt) as exc:
        print(f"同步失败：{exc}。原文件未更新。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
