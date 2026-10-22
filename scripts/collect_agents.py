"""Collect local agent session logs and summarize one day's work with Claude.

Providers are registered by ``type`` in EXTRACTORS. To add a new agent, add a
config entry under agents.providers and implement ``extract_<type>`` returning
session dicts in the same shape as the built-in extractors.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

from project_config import (CFG, project_path, render_prompt, run_claude,
                            today_iso, tz as project_tz, write_atomic)


CFG_TZ = project_tz()


def parse_dt(value):
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=CFG_TZ)
    return parsed


def day_of(value, tz):
    parsed = parse_dt(value)
    return parsed.astimezone(tz).date() if parsed else None


def iter_jsonl(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def trim(text, limit):
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def clean_text(text):
    text = re.sub(r'<system-reminder>.*?</system-reminder>', ' ', text, flags=re.S)
    text = re.sub(r'<task-notification>.*?</task-notification>', ' ', text, flags=re.S)
    text = re.sub(r'<environment_context>.*?</environment_context>', ' ', text, flags=re.S)
    return re.sub(r'\s+', ' ', text).strip()


def message_text(message):
    if not isinstance(message, dict):
        return ''
    content = message.get('content')
    if isinstance(content, str):
        return clean_text(content)
    if isinstance(content, list):
        # Claude uses type "text"; Codex uses "input_text" / "output_text".
        parts = [block['text'] for block in content
                 if isinstance(block, dict) and isinstance(block.get('text'), str)]
        return clean_text(' '.join(parts))
    return ''


def blocks(message):
    content = (message or {}).get('content')
    return [block for block in content or [] if isinstance(block, dict)]


def is_real_prompt(text):
    if not text:
        return False
    if text.startswith('<') or 'task-notification' in text:
        return False
    if text.startswith('Caveat:') or text.startswith('[Request interrupted'):
        return False
    if '# AGENTS.md instructions' in text:
        return False
    return True


def cap_session(session, max_chars):
    def size():
        return len(json.dumps(session, ensure_ascii=False))

    while size() > max_chars and (session['commands'] or session['conclusions'] or session['user_requests']):
        if session['commands']:
            session['commands'].pop()
        elif len(session['conclusions']) > 8:
            session['conclusions'].pop(0)
        elif len(session['user_requests']) > 3:
            session['user_requests'].pop(0)
        else:
            break
    if size() > max_chars:
        session['commands'] = []
        session['conclusions'] = session['conclusions'][-5:]
        session['note'] = '内容过长，已截断命令和部分结论'
    return session


def read_claude_session(path, day, tz, limits):
    users, conclusions, commands = [], [], []
    files, tools, cwds = Counter(), Counter(), Counter()
    seen_prompts = set()
    first = last = None
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            parsed = parse_dt(record.get('timestamp'))
            if not parsed or parsed.astimezone(tz).date() != day:
                continue
            first = parsed if first is None or parsed < first else first
            last = parsed if last is None or parsed > last else last
            if record.get('cwd'):
                cwds[record['cwd']] += 1
            kind = record.get('type')
            if kind == 'user' and not record.get('isMeta') and not record.get('isSidechain'):
                text = message_text(record.get('message'))
                if is_real_prompt(text) and text not in seen_prompts:
                    seen_prompts.add(text)
                    users.append(trim(text, limits['user_chars']))
            elif kind == 'assistant':
                for block in blocks(record.get('message')):
                    if block.get('type') == 'tool_use':
                        name = block.get('name', '')
                        tools[name] += 1
                        tool_input = block.get('input') or {}
                        if tool_input.get('file_path'):
                            files[tool_input['file_path']] += 1
                        if name == 'Bash' and tool_input.get('command'):
                            commands.append(trim(tool_input['command'].splitlines()[0], 200))
                    elif block.get('type') == 'text' and block.get('text', '').strip():
                        conclusions.append(trim(block['text'], limits['assistant_chars']))
    if first is None:
        return None
    session = {
        'agent': 'Claude Code',
        'provider': 'claude-code',
        'session': path.stem,
        'cwd': cwds.most_common(1)[0][0] if cwds else '',
        'start': first.astimezone(tz).isoformat(timespec='minutes'),
        'end': last.astimezone(tz).isoformat(timespec='minutes'),
        'user_requests': users,
        'conclusions': conclusions[-limits['max_assistant_messages']:],
        'files': [name for name, _ in files.most_common(limits['max_files'])],
        'commands': commands[:limits['max_commands']],
        'tool_counts': dict(tools.most_common(10)),
    }
    return cap_session(session, limits['max_chars_per_session'])


def extract_claude(provider, day, tz, limits):
    root = Path(provider['projects_dir']).expanduser()
    if not root.is_dir():
        print(f"跳过 {provider['name']}：找不到 {root}", file=sys.stderr)
        return []
    cutoff = datetime.combine(day - timedelta(days=1), time.min, tzinfo=tz).timestamp()
    sessions = []
    for path in sorted(root.glob('*/*.jsonl')):
        if 'subagents' in path.parts:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        session = read_claude_session(path, day, tz, limits)
        if session:
            sessions.append(session)
    return sessions


def read_codex_session(path, day, tz, limits):
    users, conclusions, commands = [], [], []
    files, cwds = Counter(), Counter()
    seen_prompts = set()
    first = last = None
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get('payload') or {}
            # session_meta appears on the session's first day, so read cwd before
            # filtering by date or a multi-day session loses its project.
            if record.get('type') == 'session_meta' and payload.get('cwd'):
                cwds[payload['cwd']] += 1
            parsed = parse_dt(record.get('timestamp'))
            if not parsed or parsed.astimezone(tz).date() != day:
                continue
            first = parsed if first is None or parsed < first else first
            last = parsed if last is None or parsed > last else last
            kind = payload.get('type')
            if kind == 'message':
                role = payload.get('role')
                if role not in ('user', 'assistant'):
                    continue
                text = message_text(payload)
                if role == 'user':
                    if is_real_prompt(text) and text not in seen_prompts:
                        seen_prompts.add(text)
                        users.append(trim(text, limits['user_chars']))
                elif text:
                    conclusions.append(trim(text, limits['assistant_chars']))
            elif kind == 'custom_tool_call':
                raw = payload.get('input') or ''
                if not isinstance(raw, str):
                    continue
                for quote, command in re.findall(r'cmd\s*:\s*(["\'])(.*?)\1', raw, re.S):
                    commands.append(trim(command, 200))
                for file_path in re.findall(r'/(?:Users|private|tmp)/[^\s"\'\\]+', raw):
                    files[file_path] += 1
    if first is None:
        return None
    session = {
        'agent': 'Codex',
        'provider': 'codex',
        'session': path.stem,
        'cwd': cwds.most_common(1)[0][0] if cwds else '',
        'start': first.astimezone(tz).isoformat(timespec='minutes'),
        'end': last.astimezone(tz).isoformat(timespec='minutes'),
        'user_requests': users,
        'conclusions': conclusions[-limits['max_assistant_messages']:],
        'files': [name for name, _ in files.most_common(limits['max_files'])],
        'commands': commands[:limits['max_commands']],
    }
    return cap_session(session, limits['max_chars_per_session'])


def extract_codex(provider, day, tz, limits):
    root = Path(provider['sessions_dir']).expanduser()
    if not root.is_dir():
        print(f"跳过 {provider['name']}：找不到 {root}", file=sys.stderr)
        return []
    cutoff = datetime.combine(day - timedelta(days=1), time.min, tzinfo=tz).timestamp()
    sessions = []
    for path in sorted(root.rglob('*.jsonl')):
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        session = read_codex_session(path, day, tz, limits)
        if session:
            sessions.append(session)
    return sessions


EXTRACTORS = {
    'claude': extract_claude,
    'codex': extract_codex,
}


def collect(day, tz, providers, limits, only=None):
    sessions = []
    for provider in providers:
        if not provider.get('enabled', True):
            continue
        if only and provider['id'] not in only:
            continue
        extractor = EXTRACTORS.get(provider.get('type'))
        if extractor is None:
            print(f"跳过 {provider.get('id')}：未支持的 agent 类型 {provider.get('type')}", file=sys.stderr)
            continue
        try:
            found = extractor(provider, day, tz, limits)
        except Exception as exc:
            print(f"跳过 {provider.get('id')}：{exc}", file=sys.stderr)
            continue
        # Sessions with neither a request nor a conclusion carry no work content.
        sessions.extend(session for session in found if session['user_requests'] or session['conclusions'])
    sessions.sort(key=lambda item: item['start'])
    total = limits['max_total_chars']
    dropped = 0
    while len(sessions) > 1 and len(json.dumps(sessions, ensure_ascii=False)) > total:
        sessions.pop(0)
        dropped += 1
    if dropped:
        print(f'注意：会话内容超过 {total} 字符，已省略最早的 {dropped} 段', file=sys.stderr)
    return sessions


def make_prompt(day, sessions):
    return render_prompt(
        'agent_summary',
        DAY=day,
        DATA=json.dumps({'date': day, 'sessions': sessions}, ensure_ascii=False),
    )


def strip_fence(text):
    return re.sub(r'^```(?:markdown|md)?\s*\n(.*?)\n```$', r'\1', text.strip(), flags=re.S)


def render(day, sessions, body):
    by_agent = Counter(session['agent'] for session in sessions)
    lines = [
        f'# {day} Agent 工作记录', '',
        '- 生成方式：Claude（config.toml）',
        '- 数据来源：本机 Agent 会话日志摘要；原始 transcript 未上传。',
        '- 本记录不包含工时信息；会话清单仅用于追溯，文中时间范围（如数据分析窗口）均不作为工时证据。',
        f'- 会话数：{len(sessions)}（' + '；'.join(f'{name} {count} 段' for name, count in by_agent.items()) + '）',
        '', body, '', '## 会话清单', '',
    ]
    for session in sessions:
        cwd = session['cwd'] or '未知目录'
        lines.append(f"- {session['agent']} · `{cwd}` · `{session['session']}`")
    return '\n'.join(lines) + '\n'


def run(args):
    day = date.fromisoformat(args.date)
    tz = CFG_TZ
    agents = CFG['agents']
    limits = agents['limits']
    sessions = collect(day, tz, agents['providers'], limits, only=set(args.agent or []))
    if not sessions:
        print(f'没有找到 {day} 的 Agent 会话，未生成记录。')
        return 0
    if args.dry_run:
        print(f'{day} 找到 {len(sessions)} 段会话：')
        for session in sessions:
            cwd = session['cwd'] or '未知目录'
            print(f"- {session['agent']} · {cwd} · {session['start']}–{session['end']} · "
                  f"需求 {len(session['user_requests'])} 条 · 结论 {len(session['conclusions'])} 条")
        print('dry-run：未调用 Claude、未写文件。')
        return 0
    if args.show_digest:
        print(json.dumps(sessions, ensure_ascii=False, indent=2))
    body, _ = run_claude(make_prompt(day.isoformat(), sessions))
    body = strip_fence(body)
    if not body.strip():
        raise ValueError('Claude 返回了空的总结')
    output = project_path(agents['output_dir']) / agents['file_name'].format(date=day.isoformat())
    write_atomic(output, render(day.isoformat(), sessions, body))
    print(f'已生成 {output}，共 {len(sessions)} 段会话')
    return 0


def main():
    parser = argparse.ArgumentParser(description='采集本机 Agent 会话并用 Claude 生成当天工作记录')
    parser.add_argument('--date', default=today_iso())
    parser.add_argument('--agent', action='append', help='只采集指定 provider id，可重复')
    parser.add_argument('--dry-run', action='store_true', help='只列出找到的会话，不调用 Claude、不写文件')
    parser.add_argument('--show-digest', action='store_true', help='总结前输出完整摘要 JSON')
    args = parser.parse_args()
    try:
        return run(args)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'采集失败：{exc}；已有记录未覆盖。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
