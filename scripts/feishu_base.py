"""One-way projection of the local job ledger into the user's Feishu Base.

No recruitment messages, resume uploads, record deletion or platform automation.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from assistant import ROOT, PROJECT, DEFAULT_DB
from config import FEISHU_DIR as LOCAL, PLATFORM_STATE
from reporting import source_platform, STAGES, DECISIONS

CONFIG = LOCAL / 'connection.json'
TZ = timezone(timedelta(hours=8))


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def cli(args, logdir, write=False):
    """Reuse the same installed executable and JSON contract as scripts/feishu_sync.py."""
    logdir.mkdir(parents=True, exist_ok=True)
    request = logdir / (uuid.uuid4().hex + '.json')
    envelope = {'args': args, 'write': write, 'status': 'pending'}
    atomic(request, envelope)
    exe = os.environ.get('FEISHU_CLI_EXE') or str(
        Path(os.environ.get('APPDATA', '')) / 'npm/node_modules/@larksuite/cli/bin/lark-cli.exe')
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
    try:
        r = subprocess.run([exe, 'base', *args, '--as', 'user'], cwd=ROOT,
                           capture_output=True, text=True, encoding='utf-8', timeout=90, env=env)
        obj = json.loads(r.stdout if r.returncode == 0 else r.stderr)
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        envelope.update(status='unknown', error=type(exc).__name__)
        atomic(request, envelope)
        raise RuntimeError('CLI outcome unknown; reconcile remote state, never replay writes blindly') from exc
    artifact_response = (not write and args[0] == '+record-list' and obj.get('format') == 'ndjson'
                         and 'record_file' in obj and 'has_more' in obj)
    success = r.returncode == 0 and (artifact_response or (obj.get('ok') is True and obj.get('identity') == 'user'))
    envelope.update(status='success' if success else 'failed', response=obj, exit_code=r.returncode)
    atomic(request, envelope)
    if not success:
        raise RuntimeError('Feishu CLI failed; receipt: ' + str(request))
    data = obj if artifact_response else obj['data']
    if data.get('ignored_fields'):
        raise RuntimeError('Feishu ignored fields; inspect receipt before continuing')
    return data


def field(name, kind='text', options=None):
    result = {'name': name, 'type': kind}
    if options:
        result.update(multiple=False, options=[{'name': v} for v in options])
    if kind == 'number':
        result['style'] = {'type': 'plain', 'precision': 0}
    if kind == 'datetime':
        result['style'] = {'format': 'yyyy-MM-dd HH:mm'}
    return result


SCHEMAS = {
    '机会台账': [field('机会ID'), field('企业'), field('岗位'), field('城市'), field('来源平台'),
        field('拟投平台'), field('原JD链接'), field('核验结论', 'select', list(DECISIONS.values())),
        field('当前阶段', 'select', ['研究线索'] + list(STAGES.values())), field('行业归属'),
        field('判断依据'), field('下一行动'), field('下次检查', 'datetime'), field('最近响应摘要'),
        field('响应登记时间', 'datetime'), field('简历SHA256'), field('JD版本', 'number'),
        field('累计投递', 'number'), field('累计回复', 'number'), field('累计面试', 'number'),
        field('累计Offer', 'number'), field('需处理', 'number'), field('记录更新时间', 'datetime')],
    '关键事件': [field('事件ID'), field('机会ID'), field('企业岗位'), field('事件类型'),
        field('事件摘要'), field('登记时间', 'datetime'), field('原JD链接'), field('证据定位'),
        field('下一行动')],
    '平台接入': [field('平台'), field('官网入口'), field('资料状态'), field('自动操作状态'),
        field('投递验证'), field('沟通验证'), field('阻塞与下一步')],
    '每日复盘': [field('日期'), field('研究机会', 'number'), field('已证实投递', 'number'),
        field('已证实回复', 'number'), field('已证实面试', 'number'), field('已证实Offer', 'number'),
        field('待处理', 'number'), field('回复率口径'), field('覆盖与限制'), field('截点', 'datetime')]
}


def project_rows(db=DEFAULT_DB, now=None):
    now = now or datetime.now(timezone.utc)
    conn = sqlite3.connect(f'{Path(db).resolve().as_uri()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        jobs = {r['id']: dict(r) for r in conn.execute('SELECT * FROM jobs ORDER BY id')}
        apps = {r['job_id']: dict(r) for r in conn.execute('SELECT * FROM applications')}
        events = [dict(r) for r in conn.execute("SELECT * FROM events WHERE kind IN ('opportunity_context','application_event','followup_reviewed') ORDER BY id")]
    finally:
        conn.close()
    context, actual = {}, {}
    for ev in events:
        d = json.loads(ev['data']); jid = d.get('job_id')
        if ev['kind'] == 'opportunity_context':
            context.setdefault(jid, {}).update(d)
        elif ev['kind'] == 'application_event':
            actual.setdefault(jid, []).append((ev, d))
    rows, history = [], []
    for jid, job in jobs.items():
        p = json.loads(job['payload']); a = apps.get(jid, {}); c = context.get(jid, {})
        observed = actual.get(jid, [])
        reached = {d.get('stage') for _, d in observed}
        latest_response = next(((ev, d) for ev, d in reversed(observed)
                                if d.get('stage') in {'reply_received', 'interview', 'offer'}), None)
        stage = a.get('stage')
        due = a.get('due_at')
        overdue = bool(due and datetime.fromisoformat(due) <= now)
        row = {'机会ID': jid, '企业': p['company'], '岗位': p['title'], '城市': p['city'],
            '来源平台': source_platform(p['source_url']), '拟投平台': c.get('platform', '待确认'),
            '原JD链接': p['source_url'], '核验结论': [DECISIONS[job['decision']]],
            '当前阶段': [STAGES.get(stage, '研究线索')], '行业归属': p.get('industry', '待确认'),
            '判断依据': job['reason'] or p['summary'], '下一行动': c.get('next_action') or p['next_action'],
            '下次检查': due, '最近响应摘要': latest_response[1].get('summary', '') if latest_response else '',
            '响应登记时间': latest_response[0]['at'] if latest_response else None,
            '简历SHA256': a.get('resume_hash', ''), 'JD版本': job['revision'],
            '累计投递': int('submitted' in reached), '累计回复': int('reply_received' in reached),
            '累计面试': int('interview' in reached), '累计Offer': int('offer' in reached),
            '需处理': int(stage == 'submission_unknown' or overdue), '记录更新时间': job['updated_at']}
        rows.append(row)
    for ev in events:
        if ev['kind'] not in {'application_event', 'followup_reviewed'}:
            continue
        d = json.loads(ev['data']); jid = d.get('job_id')
        if jid not in jobs:
            continue
        p = json.loads(jobs[jid]['payload'])
        history.append({'事件ID': 'EVENT-' + str(ev['id']), '机会ID': jid,
            '企业岗位': p['company'] + '｜' + p['title'],
            '事件类型': STAGES.get(d.get('stage'), '跟进检查'),
            '事件摘要': d.get('summary') or d.get('reason', ''), '登记时间': ev['at'],
            '原JD链接': p['source_url'], '证据定位': '本地事件号 ' + str(ev['id']),
            '下一行动': context.get(jid, {}).get('next_action', '')})
    platforms = json.loads((PLATFORM_STATE).read_text(encoding='utf-8'))
    platform_rows = [{'平台': name, '官网入口': p['homepage'], '资料状态': p.get('profile_status', '待核'),
        '自动操作状态': p.get('automation_status', '待实时验证'),
        '投递验证': '已取得真实回执' if p.get('submission_verified') else '未完成真实投递验证',
        '沟通验证': '已核验' if p.get('live_hr_interaction_verified') else '未完成实际沟通验证',
        '阻塞与下一步': p.get('known_blocker', '') + '；' + p.get('next_action', '')}
        for name, p in platforms['platforms'].items()]
    sent = sum(r['累计投递'] for r in rows)
    responses_to_sent = sum(r['累计回复'] for r in rows if r['累计投递'])
    daily = {'日期': now.astimezone(TZ).date().isoformat(), '研究机会': len(rows),
        '已证实投递': sent, '已证实回复': sum(r['累计回复'] for r in rows),
        '已证实面试': sum(r['累计面试'] for r in rows), '已证实Offer': sum(r['累计Offer'] for r in rows),
        '待处理': sum(r['需处理'] for r in rows),
        '回复率口径': f'{responses_to_sent}/{sent}={responses_to_sent/sent:.1%}' if sent else '不适用：实际投递分母为0',
        '覆盖与限制': '仅本地有证据事件；按机会ID去重累计。事件时间为登记时间。平台消息尚未自动接入，0不表示平台没有未读消息。',
        '截点': now.isoformat()}
    return {'机会台账': rows, '关键事件': history, '平台接入': platform_rows, '每日复盘': [daily]}


def read_records(config, name, logdir):
    rows, offset = [], 0
    while True:
        path = logdir / (uuid.uuid4().hex + '.ndjson')
        args = ['+record-list', '--base-token', config['base_token'], '--table-id', config['tables'][name],
                '--format', 'ndjson', '--output', path.relative_to(ROOT).as_posix(), '--offset', str(offset)]
        for f in SCHEMAS[name]:
            args += ['--field-id', f['name']]
        result = cli(args, logdir)
        chunk = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if len(chunk) != result['records_count']:
            raise RuntimeError('incomplete record artifact')
        rows.extend(chunk)
        if not result['has_more']:
            return rows
        if not chunk:
            raise RuntimeError('pagination made no progress')
        offset += len(chunk)


def comparable(row, schema):
    result = {}
    for f in schema:
        val = row.get(f['name'])
        if f['type'] == 'datetime' and val is not None:
            if isinstance(val, str):
                dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TZ)
                val = int(dt.timestamp() * 1000)
        elif f['type'] == 'text':
            val = val or ''
        elif f['type'] == 'select':
            val = val or []
        result[f['name']] = val
    return result


def keyed(rows, key):
    result = {}
    for row in rows:
        value = row.get(key)
        if not value or value in result:
            raise RuntimeError('missing/duplicate business key; reconcile before writing: ' + key)
        result[value] = row
    return result


def sync(apply=False):
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    LOCAL.mkdir(parents=True, exist_ok=True)
    lock = LOCAL / 'sync.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError('another sync may be active; check process before lock recovery')
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    run = LOCAL / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6])
    try:
        # Unknown writes require deliberate reconciliation. Never turn a timeout into duplicate creates.
        for receipt in (LOCAL / 'runs').glob('*/*.json'):
            old = json.loads(receipt.read_text(encoding='utf-8'))
            if old.get('write') and old.get('status') in {'pending', 'unknown'}:
                raise RuntimeError('unreconciled write receipt: ' + str(receipt))
        desired = project_rows()
        atomic(run / 'projection.json', desired)
        report = {'mode': 'apply' if apply else 'preview', 'tables': {}, 'verified': False}
        for name, wanted in desired.items():
            schema = cli(['+field-list', '--base-token', config['base_token'], '--table-id', config['tables'][name]], run)
            found = {f['name']: f['type'] for f in schema['fields']}
            if any(found.get(f['name']) != f['type'] for f in SCHEMAS[name]):
                raise RuntimeError('remote schema changed: ' + name)
            key = SCHEMAS[name][0]['name']
            current = keyed(read_records(config, name, run), key)
            wanted_by_key = keyed(wanted, key)
            if name == '每日复盘':
                # An unchanged snapshot must not cause a remote write on every wakeup.
                stable_schema = [f for f in SCHEMAS[name] if f['name'] != '截点']
                for k, row in wanted_by_key.items():
                    if k in current and comparable(row, stable_schema) == comparable(current[k], stable_schema):
                        row['截点'] = current[k].get('截点')
            creates = [r for k, r in wanted_by_key.items() if k not in current]
            updates = {current[k]['record_id']: r for k, r in wanted_by_key.items()
                       if k in current and comparable(r, SCHEMAS[name]) != comparable(current[k], SCHEMAS[name])}
            report['tables'][name] = {'create': len(creates), 'update': len(updates), 'local_rows': len(wanted)}
            if apply:
                for start in range(0, len(creates), 200):
                    cli(['+record-batch-create', '--base-token', config['base_token'], '--table-id', config['tables'][name],
                         '--json', json.dumps({'create_records': creates[start:start+200]}, ensure_ascii=False)], run, write=True)
                pairs = list(updates.items())
                for start in range(0, len(pairs), 200):
                    cli(['+record-batch-update', '--base-token', config['base_token'], '--table-id', config['tables'][name],
                         '--json', json.dumps({'update_records': dict(pairs[start:start+200])}, ensure_ascii=False)], run, write=True)
                after = keyed(read_records(config, name, run), key) if creates or updates else current
                def differs():
                    return any(k not in after or comparable(r, SCHEMAS[name]) != comparable(after[k], SCHEMAS[name])
                               for k, r in wanted_by_key.items())
                # Base updates can become visible asynchronously. Re-read, never re-send.
                for _ in range(2):
                    if not differs():
                        break
                    time.sleep(1)
                    after = keyed(read_records(config, name, run), key)
                if differs():
                    raise RuntimeError('write returned but readback differs: ' + name)
        report['verified'] = apply
        atomic(run / 'projection.json', desired)
        atomic(run / 'summary.json', report)
        if apply:
            atomic(LOCAL / 'last-success.json', {'at': datetime.now(timezone.utc).isoformat(), 'run': str(run), **report})
        return {'run': str(run), **report}
    finally:
        lock.unlink()


def validate_progress_target(db):
    """Never publish a fixture/alternate database into the real personal dashboard."""
    if Path(db).resolve() != DEFAULT_DB.resolve():
        raise ValueError('--sync-progress only supports the canonical personal ledger')
    if not CONFIG.is_file():
        raise ValueError('Feishu connection is not configured')


def publish_progress(ledger):
    """Post-commit projection: cloud failure must never invite replay of a local event."""
    result = {'local_committed': True, 'html_refreshed': False, 'feishu_verified': False}
    try:
        ledger.report(PROJECT / '求职台账.html')
        result['html_refreshed'] = True
        result['feishu'] = sync(apply=True)
        result['feishu_verified'] = result['feishu']['verified']
    except Exception as exc:
        result['failure_type'] = type(exc).__name__
        result['next_action'] = ('Local command already committed. Do not repeat import/record/finish. '
                                 'Inspect Feishu receipts and reconcile unknown writes; '
                                 'then retry feishu_base.py --sync --apply only.')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--export', type=Path, help='new local output file, no network')
    ap.add_argument('--sync', action='store_true', help='read remote state and preview differences')
    ap.add_argument('--apply', action='store_true', help='apply one-way sync and verify readback')
    args = ap.parse_args()
    if args.sync:
        if args.export:
            ap.error('choose export or sync')
        print(json.dumps(sync(args.apply), ensure_ascii=False, indent=2))
        return
    if not args.export or args.apply:
        ap.error('use --export FILE or --sync [--apply]')
    if args.export.exists():
        raise ValueError('export already exists')
    atomic(args.export, project_rows())
    print(json.dumps({'export': str(args.export), 'network': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
