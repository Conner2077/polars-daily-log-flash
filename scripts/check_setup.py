"""Validate local dependencies and configuration for this project."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from project_config import CFG, ROOT, claude_command, project_path


def main():
    failures = []

    def check(ok, label, detail=''):
        print(('OK   ' if ok else 'FAIL ') + label + (f'：{detail}' if detail else ''))
        if not ok:
            failures.append(label)

    paths = CFG['paths']
    python = project_path(paths['pdl_python'])
    check(python.is_file(), 'pdl Python', str(python))

    pdl_root = project_path(paths['pdl_root'])
    check(pdl_root.is_dir(), 'pdl 根目录', str(pdl_root))

    server_config = paths.get('pdl_server_config')
    server_path = project_path(server_config) if server_config else None
    check(server_path is None or server_path.is_file(), 'PDL_SERVER_CONFIG',
          str(server_path or '（未设置）'))

    pdl_log = project_path(paths['pdl_log'])
    check(pdl_log.is_file() or shutil.which('pdl-log') is not None, 'pdl-log', str(pdl_log))

    command = claude_command()
    executable = shutil.which(command[0]) or (command[0] if Path(command[0]).is_file() else None)
    check(executable is not None, 'Claude 命令', command[0])

    try:
        import auto_daily_log  # noqa: F401
        check(True, 'auto_daily_log 可导入')
    except Exception as exc:
        check(False, 'auto_daily_log 可导入', str(exc))

    data = ROOT / 'data'
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / '.write-test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        check(True, 'data 目录可写', str(data))
    except OSError as exc:
        check(False, 'data 目录可写', str(exc))

    project, label = CFG['jira']['project'], CFG['jira']['label']
    check(bool(project) and bool(label), 'Jira 项目/标签', f'{project} / {label}')

    print()
    if failures:
        print(f'有 {len(failures)} 项未通过：' + '、'.join(failures))
        return 1
    print('基础配置检查通过。下一步：./scripts/update_tasks.sh --dry-run')
    return 0


if __name__ == '__main__':
    sys.exit(main())
