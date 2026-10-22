"""Send a failure alert via macOS notification and/or a webhook."""
from __future__ import annotations

import argparse
import json
import subprocess

import httpx

from project_config import CFG


def main():
    parser = argparse.ArgumentParser(description='发送每日总结失败告警')
    parser.add_argument('--date', required=True)
    parser.add_argument('--code', default='1')
    parser.add_argument('--log', default='')
    args = parser.parse_args()

    message = f'{args.date} 每日总结失败（exit {args.code}）'
    if args.log:
        message += f'，日志：{args.log}'

    notify = CFG.get('notify') or {}
    if notify.get('macos_notification', True):
        script = (f'display notification {json.dumps(message, ensure_ascii=False)} '
                  'with title "每日总结失败" sound name "Basso"')
        subprocess.run(['/usr/bin/osascript', '-e', script], check=False,
                       capture_output=True, text=True)

    webhook = (notify.get('webhook_url') or '').strip()
    if webhook:
        try:
            httpx.post(webhook, json={'text': message}, timeout=10.0)
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
