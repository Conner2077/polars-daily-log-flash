"""Query recent daily reports, agent records, submissions and scheduler logs."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

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
    parser.add_argument('--json', action='store_true', help='列表输出 JSON')
    args = parser.parse_args()

    try:
        if args.days <= 0 or args.days > 365:
            raise ValueError('--days 需在 1-365 之间')
        date.fromisoformat(args.end)
        if args.date:
            date.fromisoformat(args.date)
            return show_day(args.date, args.source)
        if args.search:
            return search(args.days, args.end, args.search)
        return list_days(args.days, args.end, args.json)
    except (ValueError, OSError) as exc:
        print(f'查询失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
