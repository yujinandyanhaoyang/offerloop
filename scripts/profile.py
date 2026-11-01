"""Local profile preparation/diff/readback. No browser, network or model calls."""
import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from config import HOME as BASE, RESUME, ADAPTERS, CONFIG as CONFIG_DIR
CONFIG = ADAPTERS / '简历字段标签.json'
FACTS = CONFIG_DIR / '投递数据.json'
TRUSTED = {'user_confirmed', 'existing_resume_fact', 'platform_existing_readback'}
FACT_FIELDS = {
    'name': ['name'], 'gender': ['gender'], 'identity': ['identity'],
    'current_city': ['current_city'], 'monthly_salary_cny': ['monthly_salary_cny'],
    'education': ['school', 'degree', 'major', 'start', 'end'],
    'current_employment': ['company', 'position', 'start', 'end', 'monthly_salary_cny'],
    'prior_employment': ['company', 'position', 'start', 'end', 'monthly_salary_cny'],
    'graduation_project_period': ['start', 'end'],
}
TEXT_FIELDS = {'current_work_body', 'prior_work_body', 'project_body', 'skills_body'}
ALLOWED = TEXT_FIELDS | {
    (key if names == [key] else key + '.' + name)
    for key, names in FACT_FIELDS.items() for name in names
}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized(value):
    if isinstance(value, str):
        return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))
    return value


def plain(text):
    text = text.replace('**', '').replace('`', '')
    return re.sub(r'^- ', '• ', text.strip(), flags=re.M)


def section(text, title):
    match = re.search(r'^## ' + re.escape(title) + r'\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not match:
        raise ValueError('resume section missing: ' + title)
    return match.group(1).strip()


def expected_fields(facts_path, resume_path):
    facts = read(facts_path)
    fields, provenance, blocked = {}, {}, []
    for key, names in FACT_FIELDS.items():
        item = facts.get('facts', {}).get(key, {})
        if item.get('status') not in TRUSTED or not item.get('source'):
            blocked.append(key + ': missing trusted source')
            continue
        value = item.get('value')
        for name in names:
            field = key if names == [key] else key + '.' + name
            v = value if names == [key] else value.get(name) if isinstance(value, dict) else None
            if not isinstance(v, (str, int)) or isinstance(v, bool) or v == '':
                blocked.append(field + ': missing scalar value')
                continue
            if name in {'start', 'end'} and v != 'present' and not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', str(v)):
                raise ValueError('invalid month: ' + field)
            fields[field] = v
            provenance[field] = {'source': item['source'], 'status': item['status']}
        if isinstance(value, dict) and value.get('end') != 'present' and value.get('start') and value.get('end'):
            if value['start'] > value['end']:
                raise ValueError('reversed date range: ' + key)
    if fields.get('monthly_salary_cny') != fields.get('current_employment.monthly_salary_cny'):
        raise ValueError('current salary sources conflict; reconcile first')
    resume = Path(resume_path).read_text(encoding='utf-8-sig')
    work = re.split(r'^### .+\n', section(resume, '工作经历'), flags=re.M)[1:]
    if len(work) != 2:
        raise ValueError('expected two work sections; review parser mapping')
    project = re.split(r'^### .+\n', section(resume, '项目经历'), flags=re.M)[1:]
    if len(project) != 1:
        raise ValueError('expected one project; review parser mapping')
    for key, text in [('current_work_body', work[0]), ('prior_work_body', work[1])]:
        bullets = text.find('- ')
        if bullets < 0:
            raise ValueError('work content missing: ' + key)
        fields[key] = plain(text[bullets:])
    fields['project_body'] = plain(project[0])
    fields['skills_body'] = plain(section(resume, '专业技能'))
    for key in TEXT_FIELDS:
        if not fields[key]:
            raise ValueError('empty resume content: ' + key)
        provenance[key] = {'source': str(Path(resume_path).resolve()), 'status': 'existing_resume_fact'}
    return fields, provenance, blocked


def observation(path, platform):
    data = read(path)
    if data.get('platform') != platform or not data.get('source_reference'):
        raise ValueError('observation needs matching platform and source_reference')
    when = datetime.fromisoformat(data.get('observed_at', ''))
    if when.tzinfo is None:
        raise ValueError('observed_at needs timezone')
    values = data.get('fields')
    if not isinstance(values, dict) or set(values) - ALLOWED:
        raise ValueError('unsupported observation fields; identity/secrets are excluded')
    for key, value in values.items():
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError('observation fields must be scalar: ' + key)
    return data


def prepare(facts_path, resume_path, config_path, baseline=None):
    config = read(config_path)
    fields, provenance, blocked = expected_fields(facts_path, resume_path)
    if set(config['labels']) != ALLOWED:
        raise ValueError('platform field mapping is incomplete or unsupported')
    old = observation(baseline, config['platform'])['fields'] if baseline else {}
    changes = []
    for key, value in fields.items():
        state = 'unobserved' if key not in old else 'unchanged' if normalized(old[key]) == normalized(value) else 'different'
        changes.append({'field': key, 'label': config['labels'][key], 'state': state})
    return {
        'schema_version': 1, 'platform': config['platform'],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'inputs': [{'path': str(Path(p).resolve()), 'sha256': digest(p)} for p in (facts_path, resume_path, config_path)],
        'fields': fields, 'provenance': provenance, 'changes': changes,
        'blocked': blocked + config['unmapped'], 'modules': config['modules'],
        'edit_url': config['edit_url'], 'baseline': str(Path(baseline).resolve()) if baseline else None,
        'rules': {'unobserved': 'read module before deciding to write',
                  'different': 'recheck current page; update only confirmed differences',
                  'unchanged': 'skip candidate from baseline; confirm with current module readback before execution',
                  'unknown_save_result': 'read back before retry'},
        'limits': {'minutes': 15, 'corrections_per_failure': 1},
        'execution': {'network': False, 'browser_actions': False, 'model_calls': 0,
                      'job_submission': False, 'hr_messaging': False},
    }


def compare(plan, observed_path):
    if set(plan['fields']) - ALLOWED:
        raise ValueError('unsupported plan fields')
    observed = observation(observed_path, plan['platform'])
    stale = [Path(i['path']).name for i in plan['inputs']
             if not Path(i['path']).is_file() or digest(i['path']) != i['sha256']]
    groups = {'matched': [], 'different': [], 'unobserved': []}
    for key, value in plan['fields'].items():
        state = 'unobserved' if key not in observed['fields'] else 'matched' if normalized(value) == normalized(observed['fields'][key]) else 'different'
        groups[state].append(key)
    return {'platform': plan['platform'], 'source_reference': observed['source_reference'],
            'observed_at': observed['observed_at'], 'stale_inputs': stale, **groups,
            'verified': not stale and not groups['different'] and not groups['unobserved'] and not plan['blocked'],
            'blocked': plan['blocked'], 'external_send': False,
            'boundary': 'Compares supplied observations only; does not prove page truth or perform saving.'}


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--facts', type=Path, default=FACTS)
    p.add_argument('--resume', type=Path, default=RESUME)
    p.add_argument('--config', type=Path, default=CONFIG)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('compare')
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--observed', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    try:
        if args.cmd == 'prepare':
            plan = prepare(args.facts, args.resume, args.config, args.baseline)
            args.out.mkdir(parents=True, exist_ok=False)
            save(args.out / 'plan.json', plan)
            for key in TEXT_FIELDS:
                (args.out / (key + '.txt')).write_text(plan['fields'][key] + '\n', encoding='utf-8')
            summary = {'plan': str(args.out / 'plan.json'), 'states': {
                s: sum(x['state'] == s for x in plan['changes']) for s in ['unchanged', 'different', 'unobserved']},
                'blocked': plan['blocked'], 'external_send': False}
            save(args.out / 'summary.json', summary)
        else:
            summary = compare(read(args.plan), args.observed)
            if args.out.exists():
                raise ValueError('output exists; choose a new receipt path')
            save(args.out, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc), 'external_send': False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
