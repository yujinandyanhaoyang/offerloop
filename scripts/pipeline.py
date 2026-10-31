"""Campaign planner and evidence ledger; optional Feishu sync, no recruiter send adapter."""
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from assistant import Ledger, DEFAULT_DB, PROJECT, stamp, canonical_url
from scope import read_campaign, validate, fingerprint, eligible, search_plan

from config import POLICY


class Pipeline:
    def __init__(self, db=DEFAULT_DB, policy=None, campaign=None):
        self.l = Ledger(db)
        self.db = self.l.db
        self.policy = policy or json.loads(POLICY.read_text(encoding='utf-8'))
        self.campaign = campaign if campaign is not None else read_campaign()
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS discovery (
          id INTEGER PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL,
          expires_at TEXT NOT NULL, completed_at TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS applications (
          job_id TEXT PRIMARY KEY REFERENCES jobs(id), revision INTEGER NOT NULL,
          stage TEXT NOT NULL, resume_path TEXT NOT NULL, resume_hash TEXT NOT NULL,
          evidence TEXT NOT NULL, due_at TEXT, updated_at TEXT NOT NULL);
        ''')
        # Additive migration: preserve all historical batches and application receipts.
        columns = {r['name'] for r in self.db.execute('PRAGMA table_info(discovery)')}
        for name, kind in [('scope_hash', 'TEXT'), ('cell_id', 'TEXT'), ('scope_snapshot', 'TEXT'),
                           ('event_boundary', 'INTEGER')]:
            if name not in columns:
                self.db.execute(f'ALTER TABLE discovery ADD COLUMN {name} {kind}')

    def now(self):
        return datetime.now(timezone.utc)

    def eligible(self, payload):
        return eligible(payload, self.campaign)

    def claim(self, task_id):
        if validate(self.campaign):
            raise ValueError('direction not confirmed')
        return self.l.claim(task_id, eligible=self.eligible)

    def plan(self):
        if self.db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == 'true':
            return {'action': 'wait', 'reason': 'paused'}
        now = self.now()
        active = self.db.execute("SELECT * FROM discovery WHERE status IN ('running','needs_review') ORDER BY id DESC LIMIT 1").fetchone()
        if active:
            if active['status'] == 'running' and datetime.fromisoformat(active['expires_at']) <= now:
                self.db.execute("UPDATE discovery SET status='needs_review' WHERE id=?", (active['id'],))
            return {'action': 'wait', 'reason': 'discovery_in_progress_or_reconcile', 'batch_id': active['id']}
        due = self.db.execute("SELECT * FROM applications WHERE due_at IS NOT NULL AND stage IN ('submitted','reply_received','interview') ORDER BY due_at LIMIT 1").fetchone()
        if due and datetime.fromisoformat(due['due_at']) <= now:
            return {'action': 'prepare_followup', 'job_id': due['job_id'], 'stage': due['stage'], 'external_send': False}
        gate = validate(self.campaign)
        if gate:
            return {'action': 'wait', 'reason': gate,
                    'resume_when': '记录本人最终确认的行业、城市与岗位检索范围后，同轮重新plan并开始检索'}
        nxt = self.l.next_task(self.eligible)
        if nxt['action'] != 'wait' or nxt.get('reason') == 'task_running':
            return nxt
        ready = self.db.execute("SELECT count(*) FROM applications WHERE stage='ready'").fetchone()[0]
        if ready < self.policy['ready_buffer']:
            for r in self.db.execute("SELECT j.* FROM jobs j LEFT JOIN applications a ON a.job_id=j.id WHERE j.decision='shortlist' AND (a.job_id IS NULL OR a.revision!=j.revision)"):
                if self.eligible(json.loads(r['payload'])):
                    return {'action': 'prepare_resume', 'job_id': r['id'], 'revision': r['revision']}
        scope_hash = fingerprint(self.campaign)
        candidates, waiting = [], []
        for index, cell in enumerate(self.campaign['cells']):
            recent = self.db.execute("SELECT * FROM discovery WHERE status='done' AND scope_hash=? AND cell_id=? ORDER BY id DESC LIMIT 2",
                                     (scope_hash, cell['id'])).fetchall()
            if recent:
                empty_twice = len(recent) == 2 and all(not json.loads(r['result'])['job_ids'] for r in recent)
                last_had_increment = bool(json.loads(recent[0]['result'])['job_ids'])
                delay = (self.policy.get('productive_interval_hours', 0) if last_had_increment else
                         self.policy['empty_twice_cooldown_hours'] if empty_twice else self.policy['discovery_interval_hours'])
                next_at = datetime.fromisoformat(recent[0]['completed_at']) + timedelta(hours=delay)
                if now < next_at:
                    waiting.append(next_at)
                    continue
            # Untouched cells first; then oldest completed cell, preserving explicit priority on ties.
            candidates.append((recent[0]['completed_at'] if recent else '', index, cell))
        if not candidates:
            return {'action': 'wait', 'reason': 'discovery_cooldown', 'next_at': min(waiting).isoformat(),
                    'resume_when': '同检索单元冷却到期；新确认范围不受旧范围冷却阻塞'}
        cell = min(candidates, key=lambda x: (x[0], x[1]))[2]
        previous = self.db.execute("SELECT result FROM discovery WHERE status='done' AND scope_hash=? AND cell_id=? ORDER BY id DESC LIMIT 1",
                                   (scope_hash, cell['id'])).fetchone()
        return {'action': 'discover', 'max_jobs': self.policy['batch_max_jobs'],
                'max_minutes': self.policy['batch_max_minutes'], 'scope_hash': scope_hash,
                'previous_result': json.loads(previous[0]) if previous else None,
                **search_plan(cell, now.astimezone(timezone(timedelta(hours=8))).date())}

    def start(self):
        with self.l.tx():
            plan = self.plan()
            if plan['action'] != 'discover':
                raise ValueError('discovery not currently runnable')
            now = self.now()
            boundary = self.db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
            cur = self.db.execute("INSERT INTO discovery(status,started_at,expires_at,scope_hash,cell_id,scope_snapshot,event_boundary) VALUES('running',?,?,?,?,?,?)",
                (now.isoformat(), (now+timedelta(minutes=self.policy['batch_max_minutes'])).isoformat(),
                 plan['scope_hash'], plan['cell']['id'], json.dumps(self.campaign, ensure_ascii=False), boundary))
            self.l.event('discovery_started', {'batch_id': cur.lastrowid})
            return {'batch_id': cur.lastrowid, **plan}

    def track(self, jid, data):
        """Annotate an existing opportunity without inventing an application or reply."""
        fields = {'platform', 'application_url', 'platform_job_id', 'contact', 'preparation', 'next_action', 'evidence'}
        if set(data) - fields:
            raise ValueError('unsupported tracking field; real stages/deadlines use record/defer')
        if not isinstance(data.get('evidence'), list) or not data['evidence'] or any(not isinstance(v, str) or not v.strip() for v in data['evidence']):
            raise ValueError('tracking evidence required')
        if not any(k in data for k in fields - {'evidence'}):
            raise ValueError('tracking context required')
        clean = dict(data)
        for key in fields - {'evidence'}:
            if key in clean and not isinstance(clean[key], str):
                raise ValueError('tracking fields must be text')
        if clean.get('application_url'):
            clean['application_url'] = canonical_url(clean['application_url'])
        with self.l.tx():
            if not self.db.execute('SELECT 1 FROM jobs WHERE id=?', (jid,)).fetchone():
                raise ValueError('unknown job')
            self.l.event('opportunity_context', {'job_id': jid, **clean})
        return {'job_id': jid, 'context_saved': True, 'external_send': False}

    def complete(self, batch_id, result):
        ids = result.get('job_ids')
        if not isinstance(ids, list) or len(ids) > self.policy['batch_max_jobs'] or len(set(ids)) != len(ids):
            raise ValueError('job_ids must be unique and within batch cap')
        if not result.get('evidence') or not result.get('summary'):
            raise ValueError('research evidence and summary required, including zero-result searches')
        with self.l.tx():
            row = self.db.execute('SELECT * FROM discovery WHERE id=?', (batch_id,)).fetchone()
            if not row or row['status'] not in {'running','needs_review'}:
                raise ValueError('batch is not active')
            expired = datetime.fromisoformat(row['expires_at']) <= self.now()
            if (expired or row['status']=='needs_review') and not result.get('reconciliation'):
                raise ValueError('expired batch requires reconciliation evidence; do not rerun blindly')
            changed = {json.loads(r[0])['job_id'] for r in self.db.execute(
                "SELECT data FROM events WHERE kind='job_revision' AND id>?", (row['event_boundary'] or 0,))}
            batch_scope = json.loads(row['scope_snapshot']) if row['scope_snapshot'] else None
            if row['scope_hash'] != fingerprint(self.campaign) and not result.get('reconciliation'):
                raise ValueError('scope changed; reconcile previous batch before starting a new one')
            for jid in ids:
                job = self.db.execute('SELECT payload FROM jobs WHERE id=?', (jid,)).fetchone()
                payload = json.loads(job[0]) if job else {}
                if not batch_scope or not eligible(payload, batch_scope) or payload['research_scope']['cell_id'] != row['cell_id']:
                    raise ValueError('job lacks confirmed scope and evidence mapping: '+jid)
                if jid not in changed:
                    raise ValueError('unchanged historical job is not a new discovery: '+jid)
            self.db.execute("UPDATE discovery SET status='done',completed_at=?,result=? WHERE id=?",
                            (self.now().isoformat(),json.dumps(result,ensure_ascii=False),batch_id))
            self.l.event('discovery_completed', {'batch_id':batch_id, **result})
        return {'batch_id': batch_id, 'status': 'done', 'job_ids': ids}

    def prepare(self, jid, data):
        row = self.db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        if not row or row['decision']!='shortlist' or not self.eligible(json.loads(row['payload'])):
            raise ValueError('requires shortlisted in-scope job')
        if not data.get('evidence') or data.get('sanitized') is not True or not data.get('jd_mapping'):
            raise ValueError('fact evidence, JD mapping and sanitization confirmation required')
        path=Path(data['resume_path']).resolve()
        if not path.is_file(): raise ValueError('resume file missing')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.l.tx():
            old=self.db.execute('SELECT stage FROM applications WHERE job_id=?',(jid,)).fetchone()
            if old and old[0] not in {'ready','closed'}: raise ValueError('cannot overwrite active application')
            self.db.execute('INSERT OR REPLACE INTO applications VALUES(?,?,?,?,?,?,?,?)',
                (jid,row['revision'],'ready',str(path),digest,json.dumps(data,ensure_ascii=False),None,stamp()))
            self.l.event('application_prepared', {'job_id':jid,'resume_hash':digest,'evidence':data})
        return {'job_id':jid,'stage':'ready','resume_hash':digest,'external_send':False}

    def chain_prepare(self, jid, data):
        """简化的 chain 流程投递准备：只要求 shortlist + 简历文件，不要求 research_scope（贴近 boss_discover 的简化路径）。"""
        row = self.db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        if not row or row['decision'] != 'shortlist':
            raise ValueError('requires shortlisted job (先填证据卡→chain.py check→确认)')
        if not data.get('evidence') or not data.get('resume_path'):
            raise ValueError('evidence and resume_path required')
        path = Path(data['resume_path']).resolve()
        if not path.is_file(): raise ValueError('resume file missing')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.l.tx():
            old = self.db.execute('SELECT stage FROM applications WHERE job_id=?', (jid,)).fetchone()
            if old and old[0] not in {'ready', 'closed'}: raise ValueError('cannot overwrite active application')
            self.db.execute('INSERT OR REPLACE INTO applications VALUES(?,?,?,?,?,?,?,?)',
                (jid, row['revision'], 'ready', str(path), digest, json.dumps(data, ensure_ascii=False), None, stamp()))
            self.l.event('application_prepared', {'job_id': jid, 'resume_hash': digest, 'evidence': data})
        return {'job_id': jid, 'stage': 'ready', 'resume_hash': digest, 'external_send': False}

    def record(self, jid, data):
        # Records a separately obtained real receipt; this command cannot send anything.
        transitions={'ready':{'submitted','submission_unknown','closed'}, 'submission_unknown':{'submitted','ready','closed'},
                     'submitted':{'reply_received','closed'},'reply_received':{'reply_received','interview','closed'},
                     'interview':{'interview','offer','closed'},'offer':{'closed'},'closed':set()}
        stage=data.get('stage')
        if not data.get('evidence') or not data.get('summary'): raise ValueError('real event evidence and summary required')
        due=data.get('due_at')
        if due:
            d=datetime.fromisoformat(due)
            if d.tzinfo is None: raise ValueError('due_at must include timezone')
            due=d.astimezone(timezone.utc).isoformat()
        if stage in {'submitted','reply_received','interview'} and not due:
            raise ValueError('next followup or interview time required')
        with self.l.tx():
            r=self.db.execute('SELECT * FROM applications WHERE job_id=?',(jid,)).fetchone()
            if not r or stage not in transitions[r['stage']]: raise ValueError('invalid application transition')
            if stage=='submitted' and (not data.get('receipt') or data.get('resume_hash')!=r['resume_hash']):
                raise ValueError('submission requires real receipt and matching resume hash')
            if stage=='submitted':
                rev=self.db.execute('SELECT revision FROM jobs WHERE id=?',(jid,)).fetchone()[0]
                if rev!=r['revision'] or hashlib.sha256(Path(r['resume_path']).read_bytes()).hexdigest()!=r['resume_hash']:
                    raise ValueError('JD or resume changed; reconcile actual submitted version first')
            if stage=='ready' and not data.get('verified_not_sent'):
                raise ValueError('unknown submission must be reconciled before retry')
            self.db.execute('UPDATE applications SET stage=?,due_at=?,evidence=?,updated_at=? WHERE job_id=?',
                (stage,due,json.dumps(data,ensure_ascii=False),stamp(),jid))
            self.l.event('application_event', {'job_id':jid,**data})
        return {'job_id':jid,'stage':stage,'external_send':False}

    def defer(self, jid, data):
        if not data.get('evidence') or not data.get('reason'):
            raise ValueError('followup draft/reconciliation evidence and reason required')
        due=data.get('due_at')
        if due:
            d=datetime.fromisoformat(due)
            if d.tzinfo is None or d<=self.now(): raise ValueError('new due_at must be a future zoned time')
            due=d.astimezone(timezone.utc).isoformat()
        with self.l.tx():
            r=self.db.execute('SELECT stage FROM applications WHERE job_id=?',(jid,)).fetchone()
            if not r or r[0] not in {'submitted','reply_received','interview'}:raise ValueError('no active followup')
            self.db.execute('UPDATE applications SET due_at=?,updated_at=? WHERE job_id=?',(due,stamp(),jid))
            self.l.event('followup_reviewed',{'job_id':jid,**data})
        return {'job_id':jid,'due_at':due,'external_send':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--db',type=Path,default=DEFAULT_DB)
    ap.add_argument('--campaign',type=Path,help='confirmed scope JSON; defaults to project current scope')
    ap.add_argument('--sync-progress',action='store_true',help='after committing, refresh local HTML and verified Feishu progress; never sends to recruiters')
    sub=ap.add_subparsers(dest='cmd',required=True)
    for c in ['plan','start']:sub.add_parser(c)
    p=sub.add_parser('claim');p.add_argument('task_id',type=int)
    p=sub.add_parser('complete');p.add_argument('batch_id',type=int);p.add_argument('file',type=Path)
    for c in ['prepare','record','defer','track']:
        p=sub.add_parser(c);p.add_argument('job_id');p.add_argument('file',type=Path)
    a=ap.parse_args()
    if a.sync_progress:
        from feishu_base import validate_progress_target, publish_progress
        if a.cmd not in {'complete','prepare','record','defer','track'}:
            ap.error('--sync-progress is for completed business records, not planner/claim operations')
        try: validate_progress_target(a.db)
        except ValueError as exc: ap.error(str(exc))
    p=Pipeline(a.db, campaign=read_campaign(a.campaign) if a.campaign else None)
    try:
        data=json.loads(a.file.read_text(encoding='utf-8-sig')) if hasattr(a,'file') else None
        r=p.claim(a.task_id) if a.cmd=='claim' else p.complete(a.batch_id,data) if a.cmd=='complete' else getattr(p,a.cmd)(a.job_id,data) if a.cmd in {'prepare','record','defer','track'} else getattr(p,a.cmd)()
        if a.sync_progress:
            r['progress_sync'] = publish_progress(p.l)
        print(json.dumps(r,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,OSError) as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False));return 1
    finally:p.l.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
