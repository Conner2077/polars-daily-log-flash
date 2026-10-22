"""Install/uninstall a macOS launchd LaunchAgent for the daily run."""
from __future__ import annotations

import argparse
import getpass
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from project_config import CFG, ROOT

LABEL = f'com.{getpass.getuser()}.polars-daily-log'
AGENT_DIR = Path.home() / 'Library/LaunchAgents'


def plist_path() -> Path:
    return AGENT_DIR / f'{LABEL}.plist'


def domain() -> str:
    return f'gui/{os.getuid()}'


def path_env() -> str:
    parts = ['/opt/homebrew/bin', str(Path.home() / '.local/bin'),
             '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin']
    for item in os.environ.get('PATH', '').split(':'):
        if item and item not in parts:
            parts.append(item)
    return ':'.join(parts)


def unload():
    subprocess.run(['launchctl', 'bootout', f'{domain()}/{LABEL}'],
                   capture_output=True, text=True)
    subprocess.run(['launchctl', 'unload', '-w', str(plist_path())],
                   capture_output=True, text=True)


def install(hour: int, minute: int):
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError('时间需在 00:00-23:59 范围内')
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / 'data/logs').mkdir(parents=True, exist_ok=True)
    plist = {
        'Label': LABEL,
        'ProgramArguments': ['/bin/bash', str(ROOT / 'scripts/run_scheduled.sh')],
        'WorkingDirectory': str(ROOT),
        'StartCalendarInterval': {'Hour': hour, 'Minute': minute},
        'RunAtLoad': False,
        'StandardOutPath': str(ROOT / 'data/logs/launchd.out.log'),
        'StandardErrorPath': str(ROOT / 'data/logs/launchd.err.log'),
        'EnvironmentVariables': {
            'PATH': path_env(),
            'HOME': str(Path.home()),
            'LANG': 'en_US.UTF-8',
            'LC_ALL': 'en_US.UTF-8',
        },
    }
    path = plist_path()
    with path.open('wb') as stream:
        plistlib.dump(plist, stream)
    unload()
    result = subprocess.run(['launchctl', 'bootstrap', domain(), str(path)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        result = subprocess.run(['launchctl', 'load', '-w', str(path)],
                                capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'launchctl 加载失败：{result.stderr.strip()}')
    print(f'已安装：{path}')
    print(f'每天 {hour:02d}:{minute:02d} 运行（当天，自动提交）')
    print(f'日志目录：{ROOT / "data/logs"}')


def uninstall():
    unload()
    plist_path().unlink(missing_ok=True)
    print(f'已卸载：{plist_path()}')


def status():
    result = subprocess.run(['launchctl', 'print', f'{domain()}/{LABEL}'],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print('未安装')
        return 1
    print(result.stdout[:1200])
    return 0


def run_now():
    result = subprocess.run(['launchctl', 'kickstart', '-k', f'{domain()}/{LABEL}'],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    print('已触发一次立即运行（会按配置提交 Jira）')


def main():
    parser = argparse.ArgumentParser(description='安装每日总结的 launchd 定时任务')
    parser.add_argument('--hour', type=int, default=CFG['schedule']['hour'])
    parser.add_argument('--minute', type=int, default=CFG['schedule']['minute'])
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--run-now', action='store_true')
    args = parser.parse_args()
    try:
        if args.uninstall:
            uninstall()
        elif args.status:
            return status()
        elif args.run_now:
            run_now()
        else:
            install(args.hour, args.minute)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f'定时任务操作失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
