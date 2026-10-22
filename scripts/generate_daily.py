"""Generate a daily report from dated source Markdown and global Jira tasks."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date

from project_config import (CFG, SCRIPT_DIR, project_path, render_prompt,
                            run_claude, today_iso, write_atomic)


def read_sources(root, day):
    if not root.is_dir():
        return {}
    excluded = set(CFG['report']['exclude_dirs'])
    pattern = CFG['report']['source_glob'].format(date=day)
    return {
        str(path.relative_to(root)): path.read_text(encoding='utf-8')
        for folder in sorted(root.iterdir())
        if folder.is_dir() and not folder.name.startswith('.') and folder.name not in excluded
        for path in sorted(folder.rglob(pattern))
    }


def task_keys(markdown):
    # Subtasks roll up to the parent rather than receiving a second default share.
    pattern = CFG['jira']['key_pattern']
    keys = []
    for key, section in re.findall(rf'^## ({pattern}) [^\n]*\n(.*?)(?=^## {pattern} |\Z)',
                                   markdown, re.M | re.S):
        parent = re.search(rf'^- 父任务：\[({pattern})\]', section, re.M)
        main = parent[1] if parent else key
        if main not in keys:
            keys.append(main)
    return keys


def make_prompt(day, tasks, keys, sources):
    return render_prompt(
        'daily_report',
        DAY=day,
        KEYS=json.dumps(keys),
        MAX_CHARS=CFG['report']['max_body_chars'],
        DATA=json.dumps({'current_tasks': tasks, 'sources': sources}, ensure_ascii=False),
    )


def validate_item(item, sources, allow_empty, limit, label='条目'):
    if not isinstance(item, dict):
        raise ValueError('日报条目格式无效')
    body = item.get('body')
    if not isinstance(body, str) or (not allow_empty and not body.strip()):
        raise ValueError('日报正文格式无效')
    if len(body.strip()) > limit:
        raise ValueError(f'{label}正文超过 {limit} 字')
    item_sources = item.get('sources')
    if not isinstance(item_sources, list) or any(not isinstance(source, str) or source not in sources for source in item_sources):
        raise ValueError('日报引用了未提供的来源')
    if body.strip() and body != '当天记录未体现此任务的实际进展' and not item_sources:
        raise ValueError('日报正文缺少来源')
    seconds = item.get('seconds')
    if seconds is not None:
        maximum = CFG['report']['max_task_seconds']
        if type(seconds) is not int or not 0 <= seconds <= maximum:
            raise ValueError(f'实际工时必须是 0 到 {maximum} 的整数秒或 null')
        if not item.get('time_evidence'):
            raise ValueError('实际工时缺少原文时间证据')
    evidence_list = item.get('time_evidence', [])
    if not isinstance(evidence_list, list):
        raise ValueError('时间证据格式无效')
    for evidence in evidence_list:
        if not isinstance(evidence, dict):
            raise ValueError('时间证据格式无效')
        source, quote = evidence.get('source'), evidence.get('quote')
        if (not isinstance(source, str) or not isinstance(quote, str) or not quote.strip()
                or source not in item_sources or quote not in sources[source]):
            raise ValueError('工时时间证据与来源原文不符')


def validate_report(report, keys, sources):
    if not isinstance(report, dict) or not isinstance(report.get('tasks'), list):
        raise ValueError('Claude 返回结构无效')
    tasks = report['tasks']
    unmatched = report.get('unmatched')
    if not isinstance(unmatched, dict):
        raise ValueError('Claude 返回缺少 unmatched')
    if any(not isinstance(item, dict) for item in tasks):
        raise ValueError('日报条目格式无效')
    if sorted(item.get('key') for item in tasks) != sorted(keys):
        raise ValueError('Claude 返回的主任务集合与当前任务不一致')
    limit = CFG['report']['max_body_chars']
    for item in tasks:
        validate_item(item, sources, allow_empty=False, limit=limit, label=item.get('key', '主任务'))
    validate_item(unmatched, sources, allow_empty=True, limit=limit, label='未归属工作')
    explicit = any(item.get('seconds') is not None for item in [*tasks, unmatched])
    if not explicit:
        total_default = CFG['report']['default_daily_seconds']
        seconds, remainder = divmod(total_default, len(keys))
        for i, item in enumerate(tasks):
            item['allocated_seconds'] = seconds + (i < remainder)
        report['hours_mode'] = (f'无工时记录：总计 {total_default / 3600:g} 小时按 Jira 主任务平均分配'
                                '（余秒依任务顺序分配）')
    else:
        for item in tasks:
            item['allocated_seconds'] = item.get('seconds')
        report['hours_mode'] = '按实际记录汇总；缺少工时的任务保留未记录，不自动补齐'
    return report


def source_link(source, output_dir):
    # Relative from the report directory, so sources_root/output_dir can move independently.
    sources_root = project_path(CFG['report']['sources_root'])
    return os.path.relpath(sources_root / source, output_dir).replace(os.sep, '/')


def render_report(day, report, sources):
    output_dir = project_path(CFG['report']['output_dir'])
    lines = [f'# {day} 工作日报', '', f"- 工时规则：{report['hours_mode']}", '- 生成方式：Claude（config.toml）', '']
    for item in report['tasks']:
        seconds = item['allocated_seconds']
        hours = '未记录' if seconds is None else f'{seconds / 3600:.6f}'.rstrip('0').rstrip('.') + ' 小时'
        lines.extend([f"## {item['key']}", '', f'- 工时：{hours}', '', item['body'], ''])
        lines.extend(f'- 来源：[{source}]({source_link(source, output_dir)})' for source in item['sources'])
        lines.append('')
    unmatched = report['unmatched']
    if unmatched['body'].strip():
        lines.extend(['## 未归属工作', '', unmatched['body'], ''])
        if unmatched.get('seconds') is not None:
            lines.extend([f"- 未归属工时：{unmatched['seconds'] / 3600:g} 小时", ''])
        lines.extend(f'- 来源：[{source}]({source_link(source, output_dir)})' for source in unmatched['sources'])
        lines.append('')
    total = sum(item['allocated_seconds'] or 0 for item in report['tasks'])
    lines.extend([f'- Jira 主任务已分配工时合计：{total / 3600:g} 小时', '', '## 输入记录', ''])
    lines.extend(f'- [{source}]({source_link(source, output_dir)})' for source in sources)
    return '\n'.join(lines) + '\n'


def preserve_raw_output(day, raw):
    # Keep Claude's unvalidated output so a failed run can be diagnosed without paying for another call.
    report = CFG['report']
    path = project_path(report['output_dir']) / report['debug_file_name'].format(date=day)
    try:
        write_atomic(path, raw if raw.endswith('\n') else raw + '\n')
        return f'原始输出已保存到 {path}'
    except OSError:
        return f'原始输出：{raw[:2000]}'


def run(args):
    day = date.fromisoformat(args.date).isoformat()
    pattern = CFG['report']['source_glob'].format(date=day)
    sources_root = project_path(CFG['report']['sources_root'])
    sources = read_sources(sources_root, day)
    if not sources or not any(text.strip() for text in sources.values()):
        raise ValueError(f'{sources_root} 中没有 {pattern} 的有效工作记录，未调用 Claude')
    if not args.no_refresh:
        subprocess.run([str(SCRIPT_DIR / 'update_tasks.sh')], check=True)
    task_file = project_path(CFG['jira']['output'])
    tasks = task_file.read_text(encoding='utf-8')
    keys = task_keys(tasks)
    if not keys:
        raise ValueError(f'{task_file.name} 中没有可关联的 Jira 主任务')
    result, envelope = run_claude(make_prompt(day, tasks, keys, sources))
    result = re.sub(r'^```(?:json)?\s*\n(.*?)\n```$', r'\1', result, flags=re.S)
    try:
        report = validate_report(json.loads(result), keys, sources)
    except (ValueError, KeyError, TypeError) as exc:
        location = preserve_raw_output(day, envelope.get('result', ''))
        raise ValueError(f'Claude 返回内容无效：{exc}；{location}') from exc
    content = render_report(day, report, sources)
    output = project_path(CFG['report']['output_dir']) / CFG['report']['file_name'].format(date=day)
    if args.dry_run:
        print(content, end='')
    else:
        write_atomic(output, content)
        print(f'已生成 {output}，共 {len(keys)} 个 Jira 主任务')


def main():
    parser = argparse.ArgumentParser(description='使用 Claude 汇总各来源当天记录，按 Jira 主任务生成日报')
    parser.add_argument('--date', default=today_iso())
    parser.add_argument('--no-refresh', action='store_true', help='使用已有当前任务.md，不查询 Jira')
    parser.add_argument('--dry-run', action='store_true', help='调用 Claude 并预览，不写日报；默认仍刷新当前任务')
    args = parser.parse_args()
    try:
        run(args)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'生成失败：{exc}；已有日报未覆盖。', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
