"""Shared configuration, prompts, Claude runner and atomic writer.

``config.toml`` only needs the values that differ per machine. Everything else
falls back to DEFAULTS; optional sections can still override any default.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import tomllib
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
CONFIG_PATH = Path(os.environ.get('DAILY_SUMMARY_CONFIG', ROOT / 'config.toml'))

DEFAULTS = {
    'timezone': 'Asia/Shanghai',
    'claude': {
        'bin': 'claude',
        'settings': '',
        'extra_args': [
            '--dangerously-skip-permissions',
            '--print',
            '--output-format', 'json',
            '--tools', '',
            '--no-session-persistence',
        ],
        'timeout_seconds': 600,
    },
    'jira': {
        'project': 'PLS',
        'label': 'ConnerMain',
        'jql': 'project = {project} AND labels = "{label}" ORDER BY updated DESC, key ASC',
        'fields': 'summary,description,status,updated,issuetype,parent,labels',
        'key_pattern': r'PLS-\d+',
        'output': 'data/当前任务.md',
        'credentials': 'data/jira_auth.json',
    },
    'report': {
        'sources_root': 'data',
        'output_dir': 'data/日报',
        'file_name': '{date}-日报.md',
        'debug_file_name': '.debug-{date}.json',
        'source_glob': '{date}-*.md',
        'exclude_dirs': ['日报', '__pycache__', 'tests'],
        'default_daily_seconds': 28800,
        'max_task_seconds': 86400,
        'max_body_chars': 200,
    },
    'submit': {
        'state_file_name': '{date}-提交.json',
        'max_seconds_per_task': 86400,
    },
    'agents': {
        'output_dir': 'data/AI总结',
        'file_name': '{date}-Agent.md',
        'providers': [
            {
                'id': 'claude-code',
                'name': 'Claude Code',
                'type': 'claude',
                'enabled': True,
                'projects_dir': '~/.claude/projects',
            },
            {
                'id': 'codex',
                'name': 'Codex',
                'type': 'codex',
                'enabled': True,
                'sessions_dir': '~/.codex/sessions',
            },
        ],
        'limits': {
            'user_chars': 600,
            'assistant_chars': 800,
            'max_assistant_messages': 30,
            'max_commands': 40,
            'max_files': 40,
            'max_chars_per_session': 20000,
            'max_total_chars': 200000,
        },
    },
    'prompts': {
        'daily_report': 'prompts/daily_report.md',
        'agent_summary': 'prompts/agent_summary.md',
    },
}


def deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path=CONFIG_PATH):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'找不到配置文件：{path}（可参考 config.example.toml）')
    with path.open('rb') as stream:
        user = tomllib.load(stream)
    if not isinstance(user, dict):
        raise ValueError(f'配置文件格式无效：{path}')
    config = deep_merge(deepcopy(DEFAULTS), user)
    ZoneInfo(config['timezone'])
    return config


CFG = load_config()


def tz():
    return ZoneInfo(CFG['timezone'])


def now_local():
    return datetime.now(tz())


def today_iso():
    return now_local().date().isoformat()


def project_path(value):
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return path if path.is_absolute() else ROOT / path


def claude_command():
    claude = CFG['claude']
    command = [os.path.expanduser(os.path.expandvars(str(claude.get('bin') or 'claude')))]
    settings = claude.get('settings')
    if settings:
        command += ['--settings', os.path.expanduser(os.path.expandvars(str(settings)))]
    command += [os.path.expanduser(os.path.expandvars(str(arg).replace('{root}', str(ROOT))))
                for arg in (claude.get('extra_args') or [])]
    return command


def render_prompt(name, **values):
    target = CFG['prompts'].get(name)
    if isinstance(target, list):
        template = '\n'.join(str(line) for line in target)
    elif isinstance(target, str) and target:
        path = project_path(target)
        if not path.is_file():
            raise ValueError(f'找不到提示词文件：{path}')
        template = path.read_text(encoding='utf-8')
    else:
        raise ValueError(f'配置缺少 prompts.{name}')
    for key, value in values.items():
        template = template.replace('{' + key + '}', str(value))
    return template


def run_claude(prompt):
    completed = subprocess.run(
        claude_command(), input=prompt, text=True, capture_output=True, cwd=ROOT,
        timeout=CFG['claude']['timeout_seconds'],
    )
    if completed.returncode:
        raise RuntimeError(f"Claude 退出码 {completed.returncode}：{completed.stderr[-2000:]}")
    try:
        envelope = json.loads(completed.stdout)
    except ValueError as exc:
        raise RuntimeError(f'Claude 返回的不是 JSON：{completed.stdout[:2000]}') from exc
    if envelope.get('is_error'):
        raise RuntimeError(f"Claude 生成失败：{envelope.get('result', envelope.get('subtype'))}")
    result = envelope.get('result')
    if not isinstance(result, str):
        raise RuntimeError('Claude 返回缺少 result')
    return result.strip(), envelope


def write_atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
