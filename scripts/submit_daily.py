"""Submit the hours recorded in a generated daily report directly to Jira."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path

import httpx

import jira_auth
from project_config import CFG, now_local, project_path, today_iso, write_atomic


def parse_report(path):
    # Mirrors render_report in generate_daily.py: each task is a "## PLS-xxx"
    # section with a "- 工时：" line followed by the body and "- 来源：" links.
    tasks = []
    pattern = CFG['jira']['key_pattern']
    text = path.read_text(encoding='utf-8')
    for key, section in re.findall(rf'^## ({pattern})\n(.*?)(?=^## |\Z)', text, re.M | re.S):
        head = section.split('\n- 来源：', 1)[0]
        match = re.search(r'^- 工时：(.+)$', head, re.M)
        if not match:
            raise ValueError(f'{key} 缺少工时行')
        label = match.group(1).strip()
        if label == '未记录':
            seconds = None
        elif label.endswith(' 小时'):
            seconds = round(float(label[:-3].strip()) * 3600)
        else:
            raise ValueError(f'{key} 的工时无法识别：{label}')
        body = re.sub(r'^- 工时：.*\n?', '', head, count=1, flags=re.M).strip()
        tasks.append({'key': key, 'seconds': seconds, 'body': body})
    if not tasks:
        raise ValueError('日报中没有 Jira 主任务')
    return tasks


def load_state(path):
    if not path.exists():
        return {'submissions': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('submissions'), dict):
        raise ValueError(f'提交记录格式无效：{path}')
    return data


def write_state(path, day, report, submissions):
    content = json.dumps({'date': day, 'report': str(report), 'submissions': submissions},
                         ensure_ascii=False, indent=2) + '\n'
    write_atomic(path, content)


async def run(args):
    day = date.fromisoformat(args.date).isoformat()
    output_dir = project_path(CFG['report']['output_dir'])
    report = (Path(args.report).expanduser() if args.report
              else output_dir / CFG['report']['file_name'].format(date=day))
    if not report.is_file():
        raise ValueError(f'找不到日报：{report}，请先运行 generate_daily.sh')
    tasks = parse_report(report)
    state_path = output_dir / CFG['submit']['state_file_name'].format(date=day)
    state = load_state(state_path)
    submissions = state['submissions']
    failures = 0
    client = None
    started = f"{day}T09:00:00.000{now_local().strftime('%z')}"

    for task in tasks:
        key, seconds, body = task['key'], task['seconds'], task['body']
        if seconds is None:
            print(f'跳过 {key}：日报未记录工时')
            continue
        maximum = CFG['submit']['max_seconds_per_task']
        if seconds <= 0 or seconds > maximum:
            print(f'跳过 {key}：工时 {seconds} 秒不在可提交范围内（上限 {maximum}）', file=sys.stderr)
            failures += 1
            continue
        previous = submissions.get(key)
        if previous and previous.get('status') == 'submitted':
            print(f"跳过 {key}：已提交过（Jira ID {previous.get('worklog_id') or '未知'}）")
            continue
        if previous and previous.get('status') == 'unconfirmed' and not args.retry_unconfirmed:
            print(f'跳过 {key}：上次提交结果未确认，请先到 Jira 核对；确认未写入后可加 --retry-unconfirmed',
                  file=sys.stderr)
            failures += 1
            continue

        hours = f'{seconds / 3600:.6f}'.rstrip('0').rstrip('.')
        if args.dry_run:
            preview = next((line.strip() for line in body.splitlines()
                            if line.strip() and line.strip() not in ('**实际工作**', '**未完成事项**')), '无正文')
            print(f'[dry-run] 将提交 {key} · {hours} 小时 · {preview[:120]}')
            continue

        if client is None:
            client = jira_auth.build_client(args.credentials)
        now = now_local().isoformat(timespec='seconds')
        try:
            result = await client.submit_worklog(key, seconds, body, started)
        except httpx.RequestError as exc:
            submissions[key] = {'seconds': seconds, 'status': 'unconfirmed',
                                'error': str(exc)[-2000:], 'attempted_at': now}
            failures += 1
            print(f'结果未确认 {key}：{exc}', file=sys.stderr)
        except Exception as exc:
            submissions[key] = {'seconds': seconds, 'status': 'failed',
                                'error': str(exc)[-2000:], 'attempted_at': now}
            failures += 1
            print(f'提交失败 {key}：{exc}', file=sys.stderr)
        else:
            worklog_id = str(result.get('id') or '') or None
            submissions[key] = {'seconds': seconds, 'status': 'submitted',
                                'worklog_id': worklog_id, 'submitted_at': now}
            print(f'已提交 {key} · {hours} 小时 · Jira ID {worklog_id or "未知"}')
        write_state(state_path, day, report, submissions)

    if args.dry_run:
        print('dry-run：未提交、未写提交记录。')
    elif failures:
        print(f'有 {failures} 个任务未完成提交，详见 {state_path}', file=sys.stderr)
    else:
        print(f'提交完成，记录见 {state_path}')
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description='把日报中的工时直接提交到 Jira')
    parser.add_argument('--date', default=today_iso())
    parser.add_argument('--report', help='日报路径；默认按 config.toml 的 report 配置')
    parser.add_argument('--credentials', help='Jira 凭据文件；默认 data/jira_auth.json')
    parser.add_argument('--dry-run', action='store_true', help='只预览将提交的内容')
    parser.add_argument('--retry-unconfirmed', action='store_true',
                        help='重试上次结果未确认的工单（请先到 Jira 核对，避免重复）')
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (Exception, KeyboardInterrupt) as exc:
        print(f'提交失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
