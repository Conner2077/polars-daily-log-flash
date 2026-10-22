"""Submit the hours recorded in a generated daily report through pdl-log."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from project_config import CFG, now_local, project_path, today_iso, write_atomic


def pdl_log_path():
    configured = project_path(CFG['paths']['pdl_log'])
    if configured.is_file():
        return configured
    found = shutil.which('pdl-log')
    if found:
        return Path(found)
    raise ValueError('找不到 pdl-log；请检查 config.toml 的 paths.pdl_log 或安装 CLI')


def history_path():
    # Same database pdl-log resolves; the manual history sits next to it.
    from auto_daily_log.config import resolve_db_path

    return resolve_db_path().with_name('manual-worklogs.jsonl')


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


def history_record(key, day, history):
    # "unconfirmed" also blocks: pdl-log could not tell whether Jira received the POST.
    if not history.is_file():
        return None
    for line in reversed(history.read_text(encoding='utf-8').splitlines()):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (record.get('issue_key') == key and record.get('date') == day
                and record.get('status') in ('submitted', 'unconfirmed')):
            return record
    return None


def submit(key, seconds, body, day, executable):
    command = [str(executable), '-i', key, '-H', f'{seconds / 3600:.6f}', '-d', day]
    timeout = CFG['submit']['pdl_log_timeout_seconds']
    return subprocess.run(command, input=body, text=True, capture_output=True, timeout=timeout)


def run(args):
    day = date.fromisoformat(args.date).isoformat()
    output_dir = project_path(CFG['report']['output_dir'])
    report = (Path(args.report).expanduser() if args.report
              else output_dir / CFG['report']['file_name'].format(date=day))
    if not report.is_file():
        raise ValueError(f'找不到日报：{report}，请先运行 generate_daily.sh')
    tasks = parse_report(report)
    executable = pdl_log_path()
    history = history_path()
    state_path = output_dir / CFG['submit']['state_file_name'].format(date=day)
    state = load_state(state_path)
    submissions = state['submissions']
    failures = 0

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
            print(f'跳过 {key}：上次提交结果未确认，请先到 Jira 核对；确认未写入后可加 --retry-unconfirmed', file=sys.stderr)
            failures += 1
            continue
        found = history_record(key, day, history)
        if found and found.get('status') == 'unconfirmed' and not args.retry_unconfirmed:
            print(f'跳过 {key}：pdl-log 历史显示上次提交结果未确认，请先到 Jira 核对；确认未写入后可加 --retry-unconfirmed',
                  file=sys.stderr)
            failures += 1
            continue
        if found and found.get('status') == 'submitted':
            submissions[key] = {'seconds': found.get('time_spent_sec'), 'status': 'submitted',
                                'worklog_id': found.get('jira_worklog_id'), 'source': 'pdl-log 历史'}
            if not args.dry_run:
                write_state(state_path, day, report, submissions)
            print(f"跳过 {key}：pdl-log 历史显示已提交（Jira ID {found.get('jira_worklog_id') or '未知'}）")
            continue

        hours = f'{seconds / 3600:.6f}'.rstrip('0').rstrip('.')
        if args.dry_run:
            preview = next((line.strip() for line in body.splitlines()
                            if line.strip() and line.strip() not in ('**实际工作**', '**未完成事项**')), '无正文')
            print(f'[dry-run] 将提交 {key} · {hours} 小时 · {preview[:120]}')
            continue

        completed = submit(key, seconds, body, day, executable)
        now = now_local().isoformat(timespec='seconds')
        if completed.returncode == 0:
            match = re.search(r'Jira ID (\S+)', completed.stdout)
            worklog_id = match.group(1) if match else None
            submissions[key] = {'seconds': seconds, 'status': 'submitted',
                                'worklog_id': worklog_id, 'submitted_at': now}
            print(f'已提交 {key} · {hours} 小时 · Jira ID {worklog_id or "未知"}')
        else:
            unconfirmed = '提交未确认' in completed.stderr
            submissions[key] = {'seconds': seconds, 'status': 'unconfirmed' if unconfirmed else 'failed',
                                'error': completed.stderr.strip()[-2000:], 'attempted_at': now}
            failures += 1
            label = '结果未确认' if unconfirmed else '提交失败'
            print(f'{label} {key}：{completed.stderr.strip()}', file=sys.stderr)
        write_state(state_path, day, report, submissions)

    if args.dry_run:
        print('dry-run：未提交、未写提交记录。')
    elif failures:
        print(f'有 {failures} 个任务未完成提交，详见 {state_path}', file=sys.stderr)
    else:
        print(f'提交完成，记录见 {state_path}')
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description='把日报中的工时通过 pdl-log 提交到 Jira')
    parser.add_argument('--date', default=today_iso())
    parser.add_argument('--report', help='日报路径；默认按 config.toml 的 report 配置')
    parser.add_argument('--dry-run', action='store_true', help='只预览将提交的内容')
    parser.add_argument('--retry-unconfirmed', action='store_true',
                        help='重试上次结果未确认的工单（请先到 Jira 核对，避免重复）')
    args = parser.parse_args()
    try:
        return run(args)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'提交失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
