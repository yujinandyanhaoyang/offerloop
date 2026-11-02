import _bootstrap  # noqa: F401
import copy
import tempfile
import unittest
from pathlib import Path
from assistant import Ledger, canonical_url


def record(id='APP-001', **changes):
    p = dict(id=id, company='示例公司', title='Agent工程师', city='深圳',
             source_url='https://example.org/jobs/'+id, source_level='primary_full',
             observed_on='2026-10-23', summary='待核', next_action='核实原始JD')
    p.update(changes)
    return p


def result(**changes):
    r = dict(outcome='done', decision='clarify', reason='年限待核',
             evidence=['https://example.org/jobs/APP-001'], next_action='核实年限')
    r.update(changes)
    return r


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'test.sqlite3'
        self.l = Ledger(self.path)

    def tearDown(self):
        self.l.close()
        self.tmp.cleanup()

    def claim(self):
        return self.l.claim(self.l.next_task()['task']['id'], now=1000)

    def finish(self, c, r=None):
        return self.l.finish(c['task_id'], c['claim_token'], r or result(), now=1001)

    def test_repeat_import_no_duplicate(self):
        records = [record('APP-'+str(i)) for i in range(6)]
        self.assertEqual(self.l.ingest(records)['created'], 6)
        for _ in range(2):
            self.assertEqual(self.l.ingest(records)['unchanged'], 6)
        self.assertEqual(self.l.status()['jobs'], 6)
        self.assertEqual(self.l.status()['tasks'], {'pending': 6})
        self.assertEqual(self.l.db.execute('SELECT count(*) FROM events').fetchone()[0], 6)

    def test_tracking_alias_dedup_but_distinct_jobs_kept(self):
        self.l.ingest([record()])
        self.assertEqual(self.l.ingest([record(id='ALIAS', source_url='https://example.org/jobs/APP-001?utm_source=x#top')])['unchanged'], 1)
        self.l.ingest([record('APP-002')])
        self.assertEqual(self.l.status()['jobs'], 2)

    def test_batch_rollback_id_conflict(self):
        self.l.ingest([record()])
        with self.assertRaises(ValueError):
            self.l.ingest([record('APP-002'), record(source_url='https://example.org/other')])
        self.assertEqual(self.l.status()['jobs'], 1)

    def test_revision_supersedes_and_retains_snapshot(self):
        self.l.ingest([record()]); c = self.claim()
        self.l.ingest([record(summary='职责变更')])
        self.assertEqual(self.l.db.execute('SELECT count(*) FROM versions').fetchone()[0], 2)
        self.assertEqual(self.l.status()['tasks'], {'pending': 1, 'superseded': 1})
        with self.assertRaises(ValueError): self.finish(c)

    def test_competing_connections_cannot_claim_twice(self):
        self.l.ingest([record()]); other = Ledger(self.path)
        try:
            tid = other.next_task()['task']['id']
            self.claim()
            with self.assertRaises(ValueError): other.claim(tid, now=1000)
        finally: other.close()

    def test_restart_expiry_requires_reconciliation(self):
        self.l.ingest([record()]); old = self.claim()
        self.l.close(); self.l = Ledger(self.path)
        self.assertEqual(self.l.next_task()['reason'], 'task_running')
        self.assertEqual(self.l.recover(now=1900)['needs_review'], [old['task_id']])
        self.assertEqual(self.l.next_task()['reason'], 'no_actionable_task')
        with self.assertRaises(ValueError): self.l.release(old['task_id'], '')
        self.l.release(old['task_id'], '已检查本地未产生结论')
        new = self.claim()
        with self.assertRaises(ValueError): self.finish(old)
        self.finish(new)

    def test_blocked_retry_bound_and_other_work_continues(self):
        self.l.ingest([record(), record('APP-002')]); c = self.claim()
        self.finish(c, result(outcome='blocked'))
        self.assertEqual(self.l.next_task()['task']['job_id'], 'APP-002')
        self.l.release(c['task_id'], '新增官方页面证据')
        c = self.claim(); self.finish(c, result(outcome='blocked'))
        with self.assertRaises(ValueError): self.l.release(c['task_id'], '同样失败')

    def test_pause_persists_and_prevents_claim(self):
        self.l.ingest([record()]); tid = self.l.next_task()['task']['id']
        self.l.pause(True)
        with self.assertRaises(ValueError): self.l.claim(tid)
        self.l.pause(False); self.assertEqual(self.l.next_task()['action'], 'research')

    def test_external_actions_not_supported(self):
        self.l.ingest([record()])
        for kind in ['send', 'apply', 'upload', 'login', 'schedule_interview']:
            with self.assertRaises(ValueError): self.l.enqueue('APP-001', kind, '执行')
        self.assertFalse(self.l.status()['external_actions_enabled'])
        self.assertEqual(self.l.status()['tasks'], {'pending': 1})

    def test_partial_evidence_never_shortlists(self):
        for level in ['partial', 'secondary_full']:
            self.l.ingest([record(source_level=level)])
            c = self.claim()
            with self.assertRaises(ValueError):
                self.finish(c, result(decision='shortlist', hard_requirements_checked=True))

    def test_hard_mismatch_never_shortlists(self):
        self.l.ingest([record(known_hard_mismatch=True)]); c = self.claim()
        with self.assertRaises(ValueError):
            self.finish(c, result(decision='shortlist', hard_requirements_checked=True))

    def test_shortlist_requires_check_and_keeps_evidence(self):
        self.l.ingest([record()]); c = self.claim()
        with self.assertRaises(ValueError): self.finish(c, result(decision='shortlist'))
        self.finish(c, result(decision='shortlist', hard_requirements_checked=True))
        self.assertEqual(self.l.db.execute('SELECT decision FROM jobs').fetchone()[0], 'shortlist')

    def test_missing_evidence_and_expired_claim(self):
        self.l.ingest([record()]); c = self.claim()
        for key in ['reason', 'evidence', 'next_action']:
            r = result(); r[key] = [] if key == 'evidence' else ''
            with self.assertRaises(ValueError): self.finish(c, r)
        with self.assertRaises(ValueError):
            self.l.finish(c['task_id'], c['claim_token'], result(), now=1900)

    def test_html_escapes_source_text(self):
        self.l.ingest([record(company='<script>alert(1)</script>')])
        out = Path(self.tmp.name)/'report.html'; self.l.report(out)
        page = out.read_text(encoding='utf-8')
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        for url in ['javascript:alert(1)', 'https://user:pw@example.org']:
            with self.assertRaises(ValueError): canonical_url(url)


if __name__ == '__main__':
    unittest.main()
