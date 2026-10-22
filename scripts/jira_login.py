"""Save Jira credentials locally; supports importing them from pdl's data.db."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sqlite3
import sys
from pathlib import Path

from jira_auth import JiraAuthError, JiraClient, load_credentials, save_credentials


def from_pdl(db_path: str) -> dict:
    db = Path(db_path).expanduser()
    if not db.is_file():
        raise ValueError(f'找不到 pdl 配置数据库：{db}')
    connection = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        rows = dict(connection.execute('SELECT key, value FROM settings').fetchall())
    finally:
        connection.close()
    return {
        'server_url': rows.get('jira_server_url', ''),
        'username': rows.get('jira_username', ''),
        'pat': rows.get('jira_pat', ''),
        'cookie': rows.get('jira_cookie', ''),
        'auth_mode': rows.get('jira_auth_mode') or ('pat' if rows.get('jira_pat') else 'cookie'),
    }


def prompt_missing(data: dict) -> dict:
    if not sys.stdin.isatty() and not data.get('server_url'):
        raise ValueError('非交互模式下需要提供 --server-url 等参数')
    if not data.get('server_url'):
        data['server_url'] = input('Jira 地址（如 https://work.example.com）：').strip()
    mode = (data.get('auth_mode') or 'pat').lower()
    if mode == 'bearer':
        mode = 'pat'
    if mode == 'cookie':
        if not data.get('cookie'):
            data['cookie'] = getpass.getpass('Jira Cookie：').strip()
    else:
        mode = 'pat'
        if not data.get('username'):
            data['username'] = input('Jira 用户名：').strip()
        if not data.get('pat'):
            data['pat'] = getpass.getpass('Jira PAT：').strip()
    data['auth_mode'] = mode
    return data


def main():
    parser = argparse.ArgumentParser(description='保存本项目使用的 Jira 登录凭据')
    parser.add_argument('--server-url')
    parser.add_argument('--auth-mode', choices=['pat', 'cookie'])
    parser.add_argument('--username')
    parser.add_argument('--pat')
    parser.add_argument('--cookie')
    parser.add_argument('--from-pdl', metavar='DATA_DB',
                        help='从 pdl 的 data.db 读取现有登录配置')
    parser.add_argument('--test', action='store_true', help='保存后调用 /myself 验证')
    args = parser.parse_args()

    try:
        if args.from_pdl:
            data = from_pdl(args.from_pdl)
        else:
            try:
                data = load_credentials()
            except JiraAuthError:
                data = {}
        for key in ('server_url', 'auth_mode', 'username', 'pat', 'cookie'):
            value = getattr(args, key)
            if value:
                data[key] = value
        data = prompt_missing(data)
        path = save_credentials(data)
        print(f"已保存 Jira 凭据：{path}（{data['server_url']}，{data['auth_mode']}）")
        if args.test:
            user = asyncio.run(JiraClient(data).get_myself())
            if user is None:
                print('连接验证失败：请检查地址和凭据', file=sys.stderr)
                return 1
            print('连接验证成功：', user.get('displayName') or user.get('name') or user.get('key'))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Jira 登录配置失败：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
