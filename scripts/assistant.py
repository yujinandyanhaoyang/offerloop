"""Local research queue; explicit --sync-progress publishes the authorized Feishu projection.

No recruitment uploads, credentials or recruiter send adapter.
"""
import argparse
import hashlib
import html
import json
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parents[2]
from config import HOME as PROJECT, LEDGER as DEFAULT_DB
KINDS = {'verify_jd', 'research_company', 'research_channel'}
LEVELS = {'primary_full', 'secondary_full', 'partial'}
DECISIONS = {'pending', 'clarify', 'exclude', 'shortlist'}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def canonical_url(value):
    u = urlsplit(value)
    if u.scheme not in {'https', 'http'} or not u.netloc or u.username or u.password:
        raise ValueError('source_url must be a public http(s) URL without credentials')
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in
             {'channel', 'deliversource', 'pagesource', 'sourcessr', 'urlsource', 'fromsource', 'logid'}]
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip('/'),
                       urlencode(sorted(query)), ''))


class Ledger:
    def __init__(self, path=DEFAULT_DB):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, identity_key TEXT UNIQUE NOT NULL,
          revision INTEGER NOT NULL, payload TEXT NOT NULL, content_hash TEXT NOT NULL,
          decision TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '',
          evidence TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS versions (
          job_id TEXT NOT NULL REFERENCES jobs(id), revision INTEGER NOT NULL,
          payload TEXT NOT NULL, content_hash TEXT NOT NULL, observed_at TEXT NOT NULL,
          PRIMARY KEY(job_id,revision));
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
          revision INTEGER NOT NULL, kind TEXT NOT NULL, next_action TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', priority INTEGER NOT NULL DEFAULT 0,
          attempts INTEGER NOT NULL DEFAULT 0, token TEXT, lease_until REAL,
          result TEXT, UNIQUE(job_id,revision,kind));
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT OR IGNORE INTO settings VALUES ('paused','false');
        INSERT OR IGNORE INTO settings VALUES ('schema_version','1');
        ''')

    def close(self):
        self.db.close()

    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def event(self, kind, data):
        self.db.execute('INSERT INTO events(at,kind,data) VALUES(?,?,?)',
                        (stamp(), kind, json.dumps(data, ensure_ascii=False)))

    def ingest(self, records):
        counts = {'created': 0, 'updated': 0, 'unchanged': 0}
        with self.tx():
            for original in records:
                p = dict(original)
                for key in ('id', 'company', 'title', 'city', 'source_url', 'source_level',
                            'observed_on', 'summary', 'next_action'):
                    if not isinstance(p.get(key), str) or not p[key].strip():
                        raise ValueError('missing field: ' + key)
                if p['source_level'] not in LEVELS:
                    raise ValueError('invalid source_level')
                datetime.strptime(p['observed_on'], '%Y-%m-%d')
                p['source_url'] = canonical_url(p['source_url'])
                # Only exact source identity auto-merges. Cross-platform similarity is not proof.
                key = p['source_url']
                prior = self.db.execute('SELECT * FROM jobs WHERE identity_key=?', (key,)).fetchone()
                if prior:
                    p['id'] = prior['id']
                elif self.db.execute('SELECT 1 FROM jobs WHERE id=?', (p['id'],)).fetchone():
                    raise ValueError('ID reused for another source; resolve manually')
                p.setdefault('published_on', None)
                semantic = {k: v for k, v in p.items() if k != 'observed_on'}
                digest = hashlib.sha256(json.dumps(semantic, ensure_ascii=False,
                                      sort_keys=True).encode()).hexdigest()
                if prior and prior['content_hash'] == digest:
                    counts['unchanged'] += 1
                    continue
                rev = prior['revision'] + 1 if prior else 1
                payload = json.dumps(p, ensure_ascii=False, sort_keys=True)
                if prior:
                    self.db.execute("UPDATE jobs SET revision=?,payload=?,content_hash=?,decision='pending',"
                                    "reason='',evidence='[]',updated_at=? WHERE id=?",
                                    (rev, payload, digest, stamp(), p['id']))
                    self.db.execute("UPDATE tasks SET status='superseded',token=NULL,lease_until=NULL "
                                    "WHERE job_id=? AND status IN ('pending','running','blocked','needs_review')", (p['id'],))
                else:
                    self.db.execute('INSERT INTO jobs(id,identity_key,revision,payload,content_hash,updated_at) '
                                    'VALUES(?,?,?,?,?,?)', (p['id'], key, rev, payload, digest, stamp()))
                self.db.execute('INSERT INTO versions VALUES(?,?,?,?,?)',
                                (p['id'], rev, payload, digest, stamp()))
                self.db.execute('INSERT INTO tasks(job_id,revision,kind,next_action,priority) VALUES(?,?,?,?,?)',
                                (p['id'], rev, 'verify_jd', p['next_action'], p.get('priority', 0)))
                self.event('job_revision', {'job_id': p['id'], 'revision': rev, 'hash': digest})
                counts['updated' if prior else 'created'] += 1
        return counts

    def guard_kind(self, kind):
        if kind not in KINDS:
            raise ValueError('external/unknown action disabled in research-only v1: ' + kind)

    def enqueue(self, job_id, kind, action):
        self.guard_kind(kind)
        if not action.strip():
            raise ValueError('next_action required')
        with self.tx():
            row = self.db.execute('SELECT revision FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ValueError('unknown job')
            self.db.execute('INSERT OR IGNORE INTO tasks(job_id,revision,kind,next_action) VALUES(?,?,?,?)',
                            (job_id, row['revision'], kind, action))
        return {'queued': job_id, 'kind': kind}

    def recover(self, now=None):
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        with self.tx():
            expired = self.db.execute("SELECT id FROM tasks WHERE status='running' AND lease_until<=?", (now,)).fetchall()
            for r in expired:
                # Never silently re-run expired work, even read-only work may have produced files.
                self.db.execute("UPDATE tasks SET status='needs_review',token=NULL,lease_until=NULL WHERE id=?", (r['id'],))
                self.event('lease_expired', {'task_id': r['id'], 'next': 'reconcile local outputs before requeue'})
        return {'needs_review': [r['id'] for r in expired]}

    def next_task(self, eligible=None):
        if self.db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == 'true':
            return {'action': 'wait', 'reason': 'paused'}
        running = self.db.execute("SELECT id FROM tasks WHERE status='running' LIMIT 1").fetchone()
        if running:
            return {'action': 'wait', 'reason': 'task_running', 'task_id': running['id']}
        rows = self.db.execute("SELECT t.*,j.payload FROM tasks t JOIN jobs j ON j.id=t.job_id "
                              "WHERE t.status='pending' AND t.revision=j.revision AND j.decision!='exclude' "
                              "ORDER BY t.priority DESC,t.id").fetchall()
        row = next((r for r in rows if eligible is None or eligible(json.loads(r['payload']))), None)
        if not row:
            return {'action': 'wait', 'reason': 'no_actionable_task'}
        d = dict(row)
        self.guard_kind(d['kind'])
        d['payload'] = json.loads(d['payload'])
        return {'action': 'research', 'task': d}

    def claim(self, task_id, now=None, eligible=None):
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        with self.tx():
            nxt = self.next_task(eligible)
            if nxt['action'] != 'research' or nxt['task']['id'] != task_id:
                raise ValueError('task is not the current runnable task')
            token = uuid.uuid4().hex
            self.db.execute("UPDATE tasks SET status='running',token=?,lease_until=?,attempts=attempts+1 WHERE id=?",
                            (token, now + 15 * 60, task_id))
            self.event('claimed', {'task_id': task_id})
        return {'task_id': task_id, 'claim_token': token, 'lease_seconds': 900}

    def finish(self, task_id, token, result, now=None):
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        outcome = result.get('outcome')
        decision = result.get('decision', 'pending')
        if outcome not in {'done', 'blocked'} or decision not in DECISIONS:
            raise ValueError('invalid outcome/decision')
        if not result.get('reason') or not result.get('evidence') or not result.get('next_action'):
            raise ValueError('reason, evidence and next_action required')
        if not isinstance(result['evidence'], list) or any(not isinstance(e, str) or not e.strip() for e in result['evidence']):
            raise ValueError('evidence must be a nonempty list of references')
        if outcome == 'blocked' and decision not in {'pending', 'clarify'}:
            raise ValueError('blocked result cannot be shortlisted/excluded')
        with self.tx():
            row = self.db.execute('SELECT t.*,j.payload,j.revision AS current_rev FROM tasks t JOIN jobs j '
                                  'ON t.job_id=j.id WHERE t.id=?', (task_id,)).fetchone()
            if not row or row['status'] != 'running' or row['token'] != token or row['lease_until'] <= now or row['revision'] != row['current_rev']:
                raise ValueError('stale/invalid claim; reconcile before completing')
            p = json.loads(row['payload'])
            if decision == 'shortlist':
                if p['source_level'] != 'primary_full' or not result.get('hard_requirements_checked'):
                    raise ValueError('shortlist requires primary full JD and explicit hard-requirement check')
                if p.get('known_hard_mismatch'):
                    raise ValueError('known hard mismatch; update evidence and source revision first')
            self.db.execute('UPDATE tasks SET status=?,result=?,next_action=?,token=NULL,lease_until=NULL WHERE id=?',
                            (outcome, json.dumps(result, ensure_ascii=False), result['next_action'], task_id))
            self.db.execute('UPDATE jobs SET decision=?,reason=?,evidence=?,updated_at=? WHERE id=?',
                            (decision, result['reason'], json.dumps(result['evidence'], ensure_ascii=False), stamp(), row['job_id']))
            self.event('result', {'task_id': task_id, 'job_id': row['job_id'], 'result': result})
        return {'task_id': task_id, 'status': outcome, 'decision': decision}

    def release(self, task_id, evidence):
        if not evidence.strip():
            raise ValueError('reconciliation evidence required')
        with self.tx():
            row = self.db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row or row['status'] not in {'blocked', 'needs_review'}:
                raise ValueError('only reconciled blocked/expired tasks can be requeued')
            if row['attempts'] >= 2:
                raise ValueError('two attempts reached; new source revision needed')
            self.db.execute("UPDATE tasks SET status='pending' WHERE id=?", (task_id,))
            self.event('requeued_after_review', {'task_id': task_id, 'evidence': evidence})
        return {'task_id': task_id, 'status': 'pending'}

    def pause(self, enabled):
        with self.tx():
            self.db.execute("UPDATE settings SET value=? WHERE key='paused'", ('true' if enabled else 'false',))
            self.event('pause', {'enabled': enabled})
        return {'paused': enabled}

    def status(self):
        return {'mode': 'research_only', 'external_actions_enabled': False,
                'jobs': self.db.execute('SELECT count(*) FROM jobs').fetchone()[0],
                'tasks': {r[0]: r[1] for r in self.db.execute('SELECT status,count(*) FROM tasks GROUP BY status')},
                'next': self.next_task()}

    def report(self, output):
        from reporting import report
        return report(self, output)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', type=Path, default=DEFAULT_DB)
    ap.add_argument('--sync-progress', action='store_true', help='after committing, refresh local HTML and verified Feishu progress')
    sub = ap.add_subparsers(dest='command', required=True)
    for name in ['init', 'status', 'next', 'recover', 'pause', 'resume']:
        sub.add_parser(name)
    sub.add_parser('import').add_argument('file', type=Path)
    sub.add_parser('report').add_argument('--output', type=Path, default=PROJECT/'求职台账.html')
    sub.add_parser('claim').add_argument('task_id', type=int)
    en = sub.add_parser('enqueue'); en.add_argument('job_id'); en.add_argument('kind'); en.add_argument('next_action')
    fi = sub.add_parser('finish'); fi.add_argument('task_id', type=int); fi.add_argument('token'); fi.add_argument('file', type=Path)
    re = sub.add_parser('release'); re.add_argument('task_id', type=int); re.add_argument('evidence')
    args = ap.parse_args()
    if args.sync_progress:
        from feishu_base import validate_progress_target, publish_progress
        if args.command not in {'import','finish','report'}:
            ap.error('--sync-progress supports import/finish/report only')
        try: validate_progress_target(args.db)
        except ValueError as exc: ap.error(str(exc))
    ledger = Ledger(args.db)
    try:
        c = args.command
        if c == 'import': result = ledger.ingest(json.loads(args.file.read_text(encoding='utf-8-sig')))
        elif c == 'report': result = ledger.report(args.output)
        elif c == 'claim': result = ledger.claim(args.task_id)
        elif c == 'finish': result = ledger.finish(args.task_id, args.token, json.loads(args.file.read_text(encoding='utf-8-sig')))
        elif c == 'release': result = ledger.release(args.task_id, args.evidence)
        elif c == 'enqueue': result = ledger.enqueue(args.job_id, args.kind, args.next_action)
        elif c == 'recover': result = ledger.recover()
        elif c in {'pause','resume'}: result = ledger.pause(c == 'pause')
        elif c == 'next': result = ledger.next_task()
        else: result = ledger.status()
        if args.sync_progress:
            result['progress_sync'] = publish_progress(ledger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, sqlite3.Error, OSError) as ex:
        print(json.dumps({'error': str(ex)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        ledger.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
