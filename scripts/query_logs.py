"""Query recent daily reports, agent records, submissions and scheduler logs."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import jira_auth
from project_config import CFG, ROOT, project_path, today_iso


def paths_for(day: str):
    report_dir = project_path(CFG['report']['output_dir'])
    agent_dir = project_path(CFG['agents']['output_dir'])
    log_dir = ROOT / 'data/logs'
    return {
        'report': report_dir / CFG['report']['file_name'].format(date=day),
        'agent': agent_dir / CFG['agents']['file_name'].format(date=day),
        'state': report_dir / CFG['submit']['state_file_name'].format(date=day),
        'log': log_dir / f'{day}.log',
    }


def schedule_status(log_path: Path) -> str:
    if not log_path.is_file():
        return '未运行'
    status = 'incomplete'
    for line in log_path.read_text(encoding='utf-8', errors='replace').splitlines():
        if 'FAILED' in line:
            status = 'failed'
        elif 'success' in line:
            status = 'success'
    return status


def submission_summary(state_path: Path) -> dict:
    if not state_path.is_file():
        return {'count': 0, 'seconds': 0, 'worklogs': []}
    try:
        data = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'count': 0, 'seconds': 0, 'worklogs': []}
    submitted = [item for item in (data.get('submissions') or {}).values()
                 if item.get('status') == 'submitted']
    return {
        'count': len(submitted),
        'seconds': sum(int(item.get('seconds') or 0) for item in submitted),
        'worklogs': [{'key': key, 'worklog_id': item.get('worklog_id')}
                     for key, item in (data.get('submissions') or {}).items()
                     if item.get('status') == 'submitted'],
    }


def list_days(days: int, end: str, as_json: bool):
    end_day = date.fromisoformat(end)
    rows = []
    for offset in range(days):
        day = (end_day - timedelta(days=offset)).isoformat()
        paths = paths_for(day)
        row = {
            'date': day,
            'report': paths['report'].is_file(),
            'agent': paths['agent'].is_file(),
            'submission': submission_summary(paths['state']),
            'schedule': schedule_status(paths['log']),
        }
        rows.append(row)

    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    print('日期\t\t日报\tAgent\t提交\t\t\t定时')
    for row in rows:
        sub = row['submission']
        submit = (f"{sub['count']} 条 / {sub['seconds'] / 3600:g} 小时"
                  if sub['count'] else '-')
        print(f"{row['date']}\t{'✓' if row['report'] else '-'}\t"
              f"{'✓' if row['agent'] else '-'}\t{submit}\t{row['schedule']}")
    return 0


def adf_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get('type') == 'text':
            return value.get('text', '')
        return ''.join(adf_text(item) for item in value.get('content', []))
    if isinstance(value, list):
        return ''.join(adf_text(item) for item in value)
    return ''


def fill_local_comments(rows):
    from submit_daily import parse_report

    cache = {}
    for row in rows:
        if row.get('comment') and row.get('comment_source') != 'error':
            continue
        day = row['date']
        if day not in cache:
            report = paths_for(day)['report']
            try:
                cache[day] = ({item['key']: item['body'] for item in parse_report(report)}
                              if report.is_file() else {})
            except (OSError, ValueError):
                cache[day] = {}
        row['comment'] = cache[day].get(row['key'], '')
        row['comment_source'] = 'local-report'


async def fill_jira_comments(rows):
    client = jira_auth.build_client()

    async def fetch(row):
        if not row.get('worklog_id'):
            row['comment'] = '（没有 Jira worklog ID）'
            row['comment_source'] = 'error'
            return
        try:
            worklog = await client.get_worklog(row['key'], row['worklog_id'])
            row['comment'] = adf_text(worklog.get('comment')) or str(worklog.get('comment') or '')
            row['comment_source'] = 'jira'
        except Exception as exc:
            row['comment'] = f'（Jira 获取失败：{exc}）'
            row['comment_source'] = 'error'

    await asyncio.gather(*(fetch(row) for row in rows))


def list_submissions(days: int, end: str, as_json: bool,
                     with_content: bool = False, use_jira: bool = False):
    end_day = date.fromisoformat(end)
    rows = []
    for offset in range(days):
        day = (end_day - timedelta(days=offset)).isoformat()
        state = paths_for(day)['state']
        if not state.is_file():
            continue
        try:
            data = json.loads(state.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        for key, item in (data.get('submissions') or {}).items():
            if item.get('status') != 'submitted':
                continue
            seconds = int(item.get('seconds') or 0)
            rows.append({
                'date': day,
                'key': key,
                'seconds': seconds,
                'hours': seconds / 3600,
                'worklog_id': item.get('worklog_id'),
                'submitted_at': item.get('submitted_at'),
                'comment': item.get('comment', ''),
                'comment_source': 'state' if item.get('comment') else None,
            })
    rows.sort(key=lambda row: (row['date'], row['submitted_at'] or ''), reverse=True)

    if use_jira and rows:
        try:
            asyncio.run(fill_jira_comments(rows))
        except Exception as exc:
            print(f'Jira 查询失败：{exc}', file=sys.stderr)
            if with_content:
                fill_local_comments(rows)
            else:
                return 1
    elif with_content and rows:
        fill_local_comments(rows)

    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print(f'最近 {days} 天没有已提交的工时')
        return 0

    if with_content or use_jira:
        for row in rows:
            print(f"{row['date']}  {row['key']}  {row['hours']:g} 小时  "
                  f"Jira {row['worklog_id'] or '-'}  {row['submitted_at'] or '-'}")
            print(f"  {row['comment'] or '（无正文）'}")
    else:
        print('日期\t\t工单\t\t工时\tJira ID\t提交时间')
        for row in rows:
            print(f"{row['date']}\t{row['key']}\t{row['hours']:g} 小时\t"
                  f"{row['worklog_id'] or '-'}\t{row['submitted_at'] or '-'}")
    return 0


def show_day(day: str, source: str):
    path = paths_for(day)[source]
    if not path.is_file():
        print(f'没有找到 {day} 的 {source}：{path}', file=sys.stderr)
        return 1
    print(path.read_text(encoding='utf-8'))
    return 0


def search(days: int, end: str, keyword: str):
    end_day = date.fromisoformat(end)
    needle = keyword.lower()
    matches = 0
    for offset in range(days):
        day = (end_day - timedelta(days=offset)).isoformat()
        paths = paths_for(day)
        for source in ('report', 'agent'):
            path = paths[source]
            if not path.is_file():
                continue
            for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if needle in line.lower():
                    label = '日报' if source == 'report' else 'Agent'
                    print(f'{day} [{label}] {line_no}: {line.strip()}')
                    matches += 1
                    if matches >= 50:
                        print('（已达到 50 条上限，请缩小范围或加 --days/--keyword）')
                        return 0
    if not matches:
        print(f'最近 {days} 天没有匹配“{keyword}”的内容')
    return 0


def main():
    parser = argparse.ArgumentParser(description='查询近期工作日报、Agent 记录和定时状态')
    parser.add_argument('--days', type=int, default=7, help='最近天数，默认 7')
    parser.add_argument('--end', default=today_iso(), help='结束日期，默认今天')
    parser.add_argument('--date', help='查看某一天的完整文件，格式 YYYY-MM-DD')
    parser.add_argument('--source', choices=['report', 'agent', 'log', 'state'],
                        default='report', help='配合 --date 使用，默认 report')
    parser.add_argument('--search', metavar='KEYWORD', help='在最近日报和 Agent 记录中搜索')
    parser.add_argument('--submissions', action='store_true', help='列出最近的已提交工时')
    parser.add_argument('--content', action='store_true', help='显示提交正文（本地日报）')
    parser.add_argument('--jira', action='store_true', help='从 Jira 获取 worklog 实际备注')
    parser.add_argument('--json', action='store_true', help='列表输出 JSON')
    args = parser.parse_args()
    if args.content or args.jira:
        args.submissions = True

    try:
        if args.days <= 0 or args.days > 365:
            raise ValueError('--days 需在 1-365 之间')
        date.fromisoformat(args.end)
        if args.date and args.submissions:
            raise ValueError('--date 和 --submissions 不能同时使用')
        if args.date:
            date.fromisoformat(args.date)
            return show_day(args.date, args.source)
        if args.submissions:
            return list_submissions(args.days, args.end, args.json, args.content, args.jira)
        if args.search:
            return search(args.days, args.end, args.search)
        return list_days(args.days, args.end, args.json)
    except (ValueError, OSError) as exc:
        print(f'查询失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
