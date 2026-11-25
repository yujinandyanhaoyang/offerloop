"""Local conversational intake: merge stated facts; report missing starting context."""
import argparse
import copy
import json
import sys
from pathlib import Path
from config import PROFILE, PROJECT_ROOT, SCOPE

FIELDS = {'name', 'phone', 'email', 'education', 'employment_status', 'work_experience',
          'career_preferences', 'eligibility', 'capabilities', 'resume_pdf', 'resume_photo'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def merge(existing, updates):
    result = copy.deepcopy(existing)
    for key, value in updates.items():
        result[key] = merge(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else value
    return result


def apply(path, payload):
    source, updates = payload.get('source'), payload.get('updates')
    if not isinstance(source, str) or not source.strip():
        raise ValueError('需要用户陈述或已授权材料的来源说明')
    if not isinstance(updates, dict) or not updates or set(updates) - FIELDS:
        raise ValueError('updates 为空或包含不支持的字段')
    objects = {'education', 'career_preferences', 'eligibility', 'capabilities'}
    for key, value in updates.items():
        expected = dict if key in objects else list if key == 'work_experience' else str
        if not isinstance(value, expected):
            raise ValueError('字段类型错误: ' + key)
    for item in updates.get('work_experience', []):
        if not isinstance(item, dict) or item.get('kind') not in {'internship', 'formal', 'other'}:
            raise ValueError('每段经历须注明 kind=internship/formal/other')
    before = path.read_bytes()
    data = merge(json.loads(before.decode('utf-8-sig')), updates)
    onboarding = data.setdefault('onboarding', {})
    onboarding['source'] = source
    onboarding['known_fields'] = sorted(set(onboarding.get('known_fields', [])) | set(updates))
    sources = onboarding.setdefault('field_sources', {})
    sources.update({key: source for key in updates})
    pending = path.with_name(path.name + '.pending')
    with pending.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    if path.read_bytes() != before:
        raise ValueError('另一会话已改档案，保留 pending，先核对再续做')
    pending.replace(path)
    return {'updated_fields': sorted(updates), 'external_actions': False}


def status(path=PROFILE):
    if not path.is_file():
        return {'stage': 'uninitialized', 'next': '先运行 scripts/setup.py'}
    data = read(path)
    missing = []
    education = data.get('education', {})
    if not education.get('degree') or not education.get('major'):
        missing.append('教育背景（不适用可明确说明）')
    if not data.get('employment_status'):
        missing.append('当前在读或就业状态')
    prefs = data.get('career_preferences', {})
    if not prefs.get('objective') and not prefs.get('primary_role'):
        missing.append('当前求职问题（方向未定也可）')
    if not prefs.get('preferred_regions') and not data.get('expected_cities'):
        missing.append('地区范围（不限也可）')
    if not data.get('capabilities', {}).get('summary') and not data.get('work_experience'):
        missing.append('已有经历或能力概况（暂无也可）')
    scope = read(SCOPE) if SCOPE.is_file() else {}
    return {'stage': 'needs_context' if missing else 'ready_for_research', 'missing': missing,
            'scope_status': scope.get('status', 'missing'),
            'next': '按 docs/建档与接续.md 只补影响当前任务的条件；已有信息可先工作',
            'memory': str(PROJECT_ROOT / 'memory' / 'CURRENT_STATE.md')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status')
    update = sub.add_parser('apply')
    update.add_argument('--json', required=True, help='私有 JSON 文件或 - 读取 stdin')
    args = parser.parse_args()
    if args.cmd == 'status':
        result = status()
    else:
        raw = sys.stdin.read() if args.json == '-' else Path(args.json).read_text(encoding='utf-8-sig')
        result = apply(PROFILE, json.loads(raw))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
