"""Validate local dependencies and configuration for this project."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from project_config import CFG, ROOT, claude_command, project_path

import jira_auth


def main():
    failures = []

    def check(ok, label, detail=''):
        print(('OK   ' if ok else 'FAIL ') + label + (f'：{detail}' if detail else ''))
        if not ok:
            failures.append(label)

    check(sys.version_info >= (3, 11), 'Python 3.11+',
          f'{sys.version.split()[0]} ({sys.executable})')

    try:
        import httpx  # noqa: F401
        check(True, 'httpx 可导入')
    except Exception as exc:
        check(False, 'httpx 可导入', str(exc))

    try:
        jira_auth.load_credentials()
        check(True, 'Jira 凭据', str(jira_auth.credentials_path()))
    except Exception as exc:
        check(False, 'Jira 凭据', str(exc))

    command = claude_command()
    executable = shutil.which(command[0]) or (command[0] if Path(command[0]).is_file() else None)
    check(executable is not None, 'Claude 命令', command[0])

    settings = CFG['claude'].get('settings')
    if settings:
        settings_path = project_path(settings)
        check(settings_path.is_file(), 'Claude settings', str(settings_path))
    else:
        check(True, 'Claude settings', '未设置，使用 Claude 默认配置')

    data = ROOT / 'data'
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / '.write-test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        check(True, 'data 目录可写', str(data))
    except OSError as exc:
        check(False, 'data 目录可写', str(exc))

    label = CFG['jira']['label']
    check(bool(label), 'Jira 标签', label)

    print()
    if failures:
        print(f'有 {len(failures)} 项未通过：' + '、'.join(failures))
        return 1
    print('基础配置检查通过。下一步：./scripts/update_tasks.sh --dry-run')
    return 0


if __name__ == '__main__':
    sys.exit(main())
