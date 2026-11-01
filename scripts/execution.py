"""Offline execution entry: routes and form preparation, never logs in or sends.

Reuses platform/company adapters and field_mapping.json. Preview omits personal
values; a private --output plan contains values for the explicitly selected form.
Selectors must be re-observed in the actual page before use. This is not a browser
runner and does not claim authentication, persistence or submission success.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
from config import HOME as PROJECT, ADAPTERS, CONFIG


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def registry():
    platforms = read(ADAPTERS / 'platforms.json')
    companies = read(ADAPTERS / 'companies.json')
    mapping = read(ADAPTERS / 'field_mapping.json')
    result = {}
    for key, adapter in {**platforms, **{k: v for k, v in companies.items() if not k.startswith('_')}}.items():
        form = mapping.get(key, {})
        home = adapter.get('base_url') or adapter.get('careers_url')
        result[key] = {
            'name': adapter['name'], 'home': home,
            'resume': form.get('resume_url'), 'application_form': form.get('form_url'),
            'login_mode': adapter.get('login_mode', 'observe_current_page'),
            'allowed_hosts': adapter.get('allowed_hosts', [urlparse(home).hostname]),
            'submission_kind': adapter.get('submit_kind', 'apply'),
            'submission_selector': adapter.get('submit_selector') or adapter.get('apply_selector'),
            'mapping_status': form.get('mapping_status') or form.get('note', 'unverified'),
            'authentication': 'not_checked', 'saved_resume': 'not_checked',
            'submission_receipt': 'not_checked',
        }
    return result


def lookup(data, key):
    for part in key.split('.'):
        if not isinstance(data, dict) or part not in data:
            raise KeyError(key)
        data = data[part]
    return data


def prepare(platform, data, mapping, data_dir):
    fields = list(mapping.get('fields', {}).items())
    for section, config in mapping.get('sections', {}).items():
        fields.extend((section + '.' + name, field) for name, field in config.get('field_selectors', {}).items())
    steps = []
    for name, field in fields:
        kind, source = field.get('fill_type'), field.get('source_field')
        step = {'field': name, 'type': kind, 'source_field': source, 'selector': field.get('selector')}
        steps.append(step)
        if kind == 'submit':
            step.update(status='separate_submission', reason='never part of form fill')
            continue
        if kind in {'skip', 'follow_login'}:
            step.update(status='observe_only', reason='compare on page; do not overwrite')
            continue
        if field.get('blocked_reason'):
            step.update(status='blocked', reason=field['blocked_reason'])
            continue
        if not source or not step['selector']:
            step.update(status='blocked', reason='mapping_missing')
            continue
        try:
            value = lookup(data, source)
        except KeyError:
            step.update(status='blocked', reason='source_missing')
            continue
        if value is None or value == '' or value == []:
            step.update(status='blocked', reason='source_empty')
            continue
        if kind == 'file_upload':
            file = Path(value)
            if not file.is_absolute():
                file = data_dir / file
            if not file.is_file():
                step.update(status='blocked', reason='file_missing')
                continue
            if field.get('accept') and file.suffix.lower() not in field['accept']:
                step.update(status='blocked', reason='file_type_mismatch')
                continue
            step['sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
            value = str(file.resolve())
        step.update(status='prepared_needs_page_verification', value=value,
                    verification='read back field; save; reopen and compare persisted value')
    return {'platform': platform, 'external_action': False, 'steps': steps,
            'unmapped_sections': [k for k, v in mapping.get('sections', {}).items() if not v.get('field_selectors')],
            'next': 'observe exact destination and account, reconcile mappings, then execute only authorized steps'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['routes', 'prepare'])
    parser.add_argument('--platform')
    parser.add_argument('--data', type=Path, default=CONFIG / '投递数据.json')
    parser.add_argument('--base-dir', type=Path, default=PROJECT, help='base for relative attachment paths; default: career project')
    parser.add_argument('--output', type=Path, help='new private JSON file; contains personal values; never overwrite')
    args = parser.parse_args()
    routes = registry()
    if args.platform and args.platform not in routes:
        parser.error('unknown platform')
    if args.command == 'routes':
        result = routes[args.platform] if args.platform else routes
    else:
        if not args.platform:
            parser.error('--platform required')
        mapping = read(ADAPTERS / 'field_mapping.json').get(args.platform, {})
        result = prepare(args.platform, read(args.data), mapping, args.base_dir.resolve())
        result['route'] = routes[args.platform]
    if args.output:
        with args.output.open('x', encoding='utf-8') as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
    for step in result.get('steps', []):
        step.pop('value', None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
