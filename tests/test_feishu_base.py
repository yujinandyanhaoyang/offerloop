import tempfile
import unittest
import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timezone
from pipeline import Pipeline
from test_pipeline import campaign, scoped_record
from feishu_base import project_rows, comparable, keyed, SCHEMAS, publish_progress
import pipeline
import assistant


class FeishuProjectionTests(unittest.TestCase):
    def test_closed_application_keeps_cumulative_history_and_deduplicates_replies(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'ledger.sqlite'
            p = Pipeline(db, campaign=campaign())
            p.l.ingest([scoped_record(phone='private-phone-must-not-be-exported')])
            for stage in ['submitted', 'reply_received', 'reply_received', 'interview', 'closed']:
                p.l.event('application_event', {'job_id':'APP-001', 'stage':stage, 'summary':'fixture'})
            p.l.close()
            data = project_rows(db)
            row = data['机会台账'][0]
            self.assertEqual([row[k] for k in ['累计投递','累计回复','累计面试','累计Offer']], [1,1,1,0])
            self.assertEqual(len(data['关键事件']),5)
            self.assertNotIn('private-phone-must-not-be-exported', str(data))
            self.assertEqual(data['每日复盘'][0]['回复率口径'],'1/1=100.0%')

    def test_empty_denominator_is_not_zero_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'ledger.sqlite'
            p = Pipeline(db, campaign=campaign());p.l.close()
            row = project_rows(db)['每日复盘'][0]
            self.assertEqual(row['回复率口径'],'不适用：实际投递分母为0')

    def test_duplicate_remote_keys_stop_upsert(self):
        with self.assertRaises(RuntimeError):
            keyed([{'机会ID':'APP-001'},{'机会ID':'APP-001'}], '机会ID')

    def test_datetime_normalization_and_empty_text(self):
        schema=[{'name':'时间','type':'datetime'},{'name':'摘要','type':'text'}]
        expected={'时间':'2026-10-25T04:00:00.123999+00:00','摘要':''}
        observed={'时间':'2026-10-25T12:00:00.123+08:00','摘要':None}
        self.assertEqual(comparable(expected,schema),comparable(observed,schema))

    def test_cloud_failure_keeps_committed_event_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); db = root/'ledger.sqlite'
            p = Pipeline(db, campaign=campaign())
            p.l.ingest([scoped_record()]); p.l.close()
            data = root/'track.json'
            data.write_text(json.dumps({'next_action':'fixture followup','evidence':['fixture']}))
            (root/'connection.json').write_text('{}')
            out = io.StringIO()
            with patch('feishu_base.DEFAULT_DB', db), patch('feishu_base.PROJECT', root), \
                 patch('feishu_base.CONFIG', root/'connection.json'), \
                 patch('feishu_base.sync', side_effect=RuntimeError('remote timeout')) as remote, \
                 patch.object(sys,'argv',['pipeline.py','--db',str(db),'--sync-progress','track','APP-001',str(data)]), redirect_stdout(out):
                self.assertEqual(pipeline.main(),0)
            result = json.loads(out.getvalue())['progress_sync']
            self.assertTrue(result['local_committed'])
            self.assertTrue(result['html_refreshed'])
            self.assertFalse(result['feishu_verified'])
            self.assertIn('Do not repeat',result['next_action'])
            remote.assert_called_once_with(apply=True)
            p = Pipeline(db,campaign=campaign())
            self.assertEqual(p.db.execute("SELECT count(*) FROM events WHERE kind='opportunity_context'").fetchone()[0],1)
            p.l.close()
            self.assertTrue((root/'求职台账.html').is_file())

    def test_alternate_database_rejected_before_local_mutation_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'must-not-exist.sqlite'
            with patch('feishu_base.sync') as remote:
                for main, command in [(assistant.main,['report']), (pipeline.main,['track','APP-001','missing.json'])]:
                    with patch.object(sys,'argv',['tool','--db',str(db),'--sync-progress',*command]), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        main()
                remote.assert_not_called()
            self.assertFalse(db.exists())


if __name__ == '__main__':
    unittest.main()
