"""Print shell assignments for the scheduled runner's date and submit policy."""
from __future__ import annotations

import argparse
from datetime import date

from project_config import CFG, today_iso


def main():
    parser = argparse.ArgumentParser(description='输出定时任务的日期和是否提交')
    parser.add_argument('--date', default=today_iso(), help='默认今天')
    args = parser.parse_args()
    day = date.fromisoformat(args.date)
    weekdays = CFG['schedule'].get('submit_weekdays', [0, 1, 2, 3, 4])
    print(f'DAY={day.isoformat()}')
    print(f'WEEKDAY={day.weekday()}')
    print(f'SUBMIT={1 if day.weekday() in weekdays else 0}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
