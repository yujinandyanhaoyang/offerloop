import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pipeline import Pipeline
from test_assistant import record
from scope import fingerprint


def campaign():
    return {'id':'test-direction', 'status':'confirmed', 'confirmed_on':'2026-10-25',
            'confirmation_reference':'fixture-only', 'cells':[
                {'id':'industry-shenzhen', 'industry_id':'I2', 'industry':'工业装备',
                 'city':'深圳', 'role_terms':['系统测试', '应用工程']}]}


def scoped_record(id='APP-001', **changes):
    p = record(id, research_scope={'campaign_hash':fingerprint(campaign()),
                'cell_id':'industry-shenzhen', 'evidence':['fixture-industry-mapping']})
    p.update(changes)
    return p


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Pipeline(Path(self.tmp.name)/'db.sqlite', campaign=campaign())
        self.now=datetime(2026,10,24,tzinfo=timezone.utc);self.p.now=lambda:self.now
    def tearDown(self):
        self.p.l.close();self.tmp.cleanup()
    def test_empty_queue_creates_discovery_action_without_fake_job(self):
        self.assertEqual(self.p.plan()['action'],'discover')
        self.p.start()
        self.assertEqual(self.p.plan()['reason'],'discovery_in_progress_or_reconcile')
        with self.assertRaises(ValueError):self.p.start()
        self.assertEqual(self.p.l.status()['jobs'],0)
    def test_industry_evidence_replaces_title_filter(self):
        for title in ['设备系统验证', '应用工程师', '生产质量', 'Python后端工程师']:
            self.assertTrue(self.p.eligible(scoped_record(title=title)))
        self.assertFalse(self.p.eligible(record(title='Agent工程师')))
        self.assertFalse(self.p.eligible(scoped_record(city='杭州')))
        self.assertFalse(self.p.eligible(scoped_record(research_scope={})))
    def test_expired_batch_requires_reconcile(self):
        b=self.p.start();self.now+=timedelta(minutes=16)
        self.p.plan()
        with self.assertRaises(ValueError):self.p.complete(b['batch_id'],{'job_ids':[],'summary':'无匹配','evidence':['record']})
        self.p.complete(b['batch_id'],{'job_ids':[],'summary':'无匹配','evidence':['record'],'reconciliation':'已查本地产物'})
    def test_daily_limit_and_empty_backoff(self):
        for i in range(2):
            b=self.p.start();self.p.complete(b['batch_id'],{'job_ids':[],'summary':'无匹配','evidence':['record']})
            self.p.db.execute('UPDATE discovery SET completed_at=? WHERE id=?',(self.now.isoformat(),b['batch_id']))
            self.assertEqual(self.p.plan()['reason'],'discovery_cooldown')
            self.now+=timedelta(hours=25)
        self.assertEqual(self.p.plan()['reason'],'discovery_cooldown')
        self.now+=timedelta(hours=49)
        self.assertEqual(self.p.plan()['action'],'discover')
    def test_scope_and_sample_cap_enforced(self):
        b=self.p.start();self.p.l.ingest([record(title='Python后端工程师')])
        with self.assertRaises(ValueError):self.p.complete(b['batch_id'],{'job_ids':['APP-001'],'summary':'x','evidence':['x']})
        with self.assertRaises(ValueError):self.p.complete(b['batch_id'],{'job_ids':['1','2','3','4'],'summary':'x','evidence':['x']})
    def setup_application(self):
        self.p.l.ingest([scoped_record()]);self.p.db.execute("UPDATE jobs SET decision='shortlist'")
        f=Path(self.tmp.name)/'resume.md';f.write_text('test resume')
        return self.p.prepare('APP-001',{'resume_path':str(f),'evidence':['facts'],'jd_mapping':['mapped'],'sanitized':True})
    def test_preparation_requires_facts_and_real_file(self):
        self.p.l.ingest([scoped_record()])
        with self.assertRaises(ValueError):self.p.prepare('APP-001',{})
        self.p.db.execute("UPDATE jobs SET decision='shortlist'")
        self.p.db.execute("UPDATE tasks SET status='done'")
        self.assertEqual(self.p.plan()['action'],'prepare_resume')
    def test_submission_receipt_and_followup(self):
        r=self.setup_application()
        with self.assertRaises(ValueError):self.p.record('APP-001',{'stage':'submitted','summary':'x','evidence':['x'],'due_at':self.now.isoformat()})
        self.p.record('APP-001',{'stage':'submitted','summary':'真实回执记录测试','evidence':['receipt'],'receipt':'receipt-id','resume_hash':r['resume_hash'],'due_at':self.now.isoformat()})
        self.assertEqual(self.p.plan()['action'],'prepare_followup')
        self.assertFalse(self.p.plan()['external_send'])

    def test_unconfirmed_blocks_old_queue_and_new_discovery(self):
        self.p.l.ingest([scoped_record()])
        self.p.campaign['status']='awaiting_direction_confirmation'
        self.assertEqual(self.p.plan()['reason'],'awaiting_direction_confirmation')
        with self.assertRaises(ValueError):self.p.start()
        with self.assertRaises(ValueError):self.p.claim(1)

    def test_new_cell_not_blocked_by_other_cell_cooldown(self):
        self.p.campaign['cells'].append({'id':'nanjing','industry_id':'I3','industry':'电力设备',
                                        'city':'南京','role_terms':['设备测试']})
        b=self.p.start()
        self.p.complete(b['batch_id'],{'job_ids':[],'summary':'无新增','evidence':['checked']})
        plan=self.p.plan()
        self.assertEqual(plan['cell']['city'],'南京')
        self.assertTrue(any('设备测试' in q for q in plan['queries']))

    def test_ready_buffer_does_not_stop_discovery(self):
        self.setup_application()
        self.p.db.execute("UPDATE tasks SET status='done'")
        self.p.policy['ready_buffer']=1
        self.assertEqual(self.p.plan()['action'],'discover')

    def test_scope_change_requires_reconcile_and_preserves_batch_snapshot(self):
        b=self.p.start()
        self.p.campaign['id']='new-confirmation'
        result={'job_ids':[],'summary':'旧范围收束','evidence':['receipt']}
        with self.assertRaises(ValueError):self.p.complete(b['batch_id'],result)
        self.p.complete(b['batch_id'],dict(result,reconciliation='checked old artifacts'))
        self.assertEqual(self.p.plan()['action'],'discover')

    def test_scoped_claim_skips_unrelated_old_queue(self):
        self.p.l.ingest([record(),scoped_record('APP-002')])
        plan=self.p.plan()
        self.assertEqual(plan['task']['job_id'],'APP-002')
        self.p.claim(plan['task']['id'])

    def test_reused_old_jobs_cannot_fake_new_discovery(self):
        self.p.l.ingest([scoped_record()])
        self.p.db.execute("UPDATE tasks SET status='done'")
        b=self.p.start()
        with self.assertRaises(ValueError):
            self.p.complete(b['batch_id'],{'job_ids':['APP-001'],'summary':'旧记录','evidence':['x']})

    def test_new_job_completes_then_flows_to_research(self):
        b=self.p.start()
        self.p.l.ingest([scoped_record(title='仪器系统验证')])
        self.p.complete(b['batch_id'],{'job_ids':['APP-001'],'summary':'新原JD','evidence':['fixture']})
        self.assertEqual(self.p.plan()['action'],'research')
        self.p.db.execute("UPDATE tasks SET status='done'")
        self.assertEqual(self.p.plan()['action'],'discover')
        self.assertEqual(self.p.plan()['previous_result']['job_ids'],['APP-001'])
    def test_unknown_send_must_reconcile(self):
        self.setup_application()
        self.p.record('APP-001',{'stage':'submission_unknown','summary':'unknown','evidence':['x']})
        with self.assertRaises(ValueError):self.p.record('APP-001',{'stage':'ready','summary':'retry','evidence':['x']})
        self.p.record('APP-001',{'stage':'ready','summary':'confirmed unsent','evidence':['x'],'verified_not_sent':True})
    def test_changed_resume_blocks_submission_record(self):
        r=self.setup_application()
        (Path(self.tmp.name)/'resume.md').write_text('changed')
        with self.assertRaises(ValueError):
            self.p.record('APP-001',{'stage':'submitted','summary':'x','evidence':['x'],'receipt':'receipt','resume_hash':r['resume_hash'],'due_at':self.now.isoformat()})
    def test_followup_defer_preserves_stage_without_fake_reply(self):
        r=self.setup_application()
        self.p.record('APP-001',{'stage':'submitted','summary':'x','evidence':['x'],'receipt':'receipt','resume_hash':r['resume_hash'],'due_at':self.now.isoformat()})
        self.p.defer('APP-001',{'reason':'仅保存草稿等待外发授权','evidence':['draft'],'due_at':None})
        row=self.p.db.execute('SELECT stage,due_at FROM applications').fetchone()
        self.assertEqual(row['stage'],'submitted');self.assertIsNone(row['due_at'])

    def test_tracking_reuses_job_without_creating_application(self):
        self.p.l.ingest([record()])
        before = self.p.db.execute('SELECT revision,decision FROM jobs').fetchone()
        self.p.track('APP-001', {'platform':'智联招聘','contact':'岗位联系人待核',
                               'preparation':'先核年限与开发责任','evidence':['local-note']})
        self.p.track('APP-001', {'next_action':'取得原JD后核对','evidence':['local-note-2']})
        self.assertEqual(tuple(before), tuple(self.p.db.execute('SELECT revision,decision FROM jobs').fetchone()))
        self.assertEqual(self.p.db.execute('SELECT count(*) FROM applications').fetchone()[0],0)
        out=Path(self.tmp.name)/'report.html';self.p.l.report(out);s=out.read_text(encoding='utf-8')
        for text in ['智联招聘','先核年限与开发责任','取得原JD后核对','无已投回执记录']:
            self.assertIn(text,s)
        with self.assertRaises(ValueError):
            self.p.track('APP-001',{'stage':'submitted','evidence':['fake']})
        with self.assertRaises(ValueError):
            self.p.track('APP-001',{'application_url':'javascript:alert(1)','evidence':['bad-url']})

    def test_report_keeps_resume_contact_and_submission_history_after_reply(self):
        r=self.setup_application()
        self.p.track('APP-001',{'platform':'BOSS直聘','contact':'测试联系人',
                               'preparation':'准备交易工具项目说明','next_action':'准备技术沟通','evidence':['context']})
        self.p.record('APP-001',{'stage':'submitted','summary':'测试投递回执','evidence':['test-receipt'],
                                'receipt':'test-receipt-id','resume_hash':r['resume_hash'],'due_at':self.now.isoformat()})
        self.p.record('APP-001',{'stage':'reply_received','summary':'测试招聘回复','evidence':['test-reply'],
                                'due_at':self.now.isoformat()})
        out=Path(self.tmp.name)/'report.html';self.p.l.report(out);s=out.read_text(encoding='utf-8')
        for text in ['测试联系人','准备交易工具项目说明','测试投递回执','测试招聘回复',r['resume_hash'],
                     '收到回复','下次检查（北京时间）','1 条有投递回执记录']:
            self.assertIn(text,s)


if __name__=='__main__':unittest.main()
