"""Minimal Jira credentials and client, independent of auto_daily_log."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional

import httpx

from project_config import CFG, project_path, write_atomic

ENV_MAP = {
    'server_url': 'JIRA_SERVER_URL',
    'username': 'JIRA_USERNAME',
    'pat': 'JIRA_PAT',
    'cookie': 'JIRA_COOKIE',
    'auth_mode': 'JIRA_AUTH_MODE',
}


class JiraAuthError(Exception):
    pass


def credentials_path(override=None) -> Path:
    if override:
        return Path(override).expanduser()
    return project_path(CFG['jira'].get('credentials') or 'data/jira_auth.json')


def load_credentials(override=None) -> dict:
    target = credentials_path(override)
    data = {}
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise JiraAuthError(f'Jira 凭据格式无效：{target}') from exc
        if not isinstance(data, dict):
            raise JiraAuthError(f'Jira 凭据格式无效：{target}')

    # Environment variables override the file, which makes one-off runs easy.
    for key, env in ENV_MAP.items():
        if os.environ.get(env):
            data[key] = os.environ[env]

    mode = (data.get('auth_mode') or ('pat' if data.get('pat') else 'cookie')).lower()
    if mode == 'bearer':
        mode = 'pat'
    data['auth_mode'] = mode
    for key in ('server_url', 'username', 'pat', 'cookie'):
        data.setdefault(key, '')

    if not data['server_url']:
        raise JiraAuthError(
            f'Jira 未登录：缺少 server_url。运行 ./scripts/jira_login.sh，'
            f'或设置 JIRA_SERVER_URL/JIRA_PAT 环境变量（凭据文件：{target}）')
    if mode == 'pat' and not data['pat']:
        raise JiraAuthError('Jira PAT 未配置：运行 ./scripts/jira_login.sh --pat ...')
    if mode == 'pat' and not data['username']:
        raise JiraAuthError('Jira 用户名未配置：运行 ./scripts/jira_login.sh --username ...')
    if mode == 'cookie' and not data['cookie']:
        raise JiraAuthError('Jira Cookie 未配置：运行 ./scripts/jira_login.sh --cookie ...')
    return data


def save_credentials(data: dict, override=None) -> Path:
    target = credentials_path(override)
    content = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    write_atomic(target, content)
    os.chmod(target, 0o600)
    return target


def _strip_4byte(text: str) -> str:
    # Some Jira/MySQL installations reject 4-byte UTF-8 (emoji).
    return ''.join(char for char in text if ord(char) <= 0xFFFF)


class JiraClient:
    def __init__(self, credentials: dict):
        self.credentials = credentials

    @property
    def server_url(self) -> str:
        return self.credentials['server_url']

    def _headers(self) -> dict:
        if self.credentials['auth_mode'] == 'cookie':
            return {
                'Cookie': self.credentials['cookie'],
                'Content-Type': 'application/json',
                'X-Atlassian-Token': 'no-check',
            }
        credentials = base64.b64encode(
            f"{self.credentials['username']}:{self.credentials['pat']}".encode()
        ).decode()
        return {'Authorization': f'Basic {credentials}', 'Content-Type': 'application/json'}

    def _url(self, path: str) -> str:
        return f"{self.server_url.rstrip('/')}{path}"

    async def submit_worklog(self, issue_key: str, time_spent_sec: int,
                             comment: str, started: str) -> dict:
        payload = {
            'timeSpentSeconds': time_spent_sec,
            'started': started,
            'comment': _strip_4byte(comment),
        }
        url = self._url(f'/rest/api/2/issue/{issue_key}/worklog')
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
            if response.status_code >= 400:
                raise Exception(f'Jira {response.status_code} on {issue_key}/worklog: {response.text[:400]}')
            return response.json()

    async def fetch_issue(self, issue_key: str) -> dict:
        url = self._url(f'/rest/api/2/issue/{issue_key}?fields=summary,description')
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            return {
                'key': data['key'],
                'summary': data['fields'].get('summary', ''),
                'description': data['fields'].get('description', ''),
            }

    async def get_myself(self) -> Optional[dict]:
        try:
            url = self._url('/rest/api/2/myself')
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                response = await client.get(url, headers=self._headers())
                if response.status_code == 200:
                    return response.json()
        except Exception:
            pass
        return None


def build_client(override=None) -> JiraClient:
    return JiraClient(load_credentials(override))
