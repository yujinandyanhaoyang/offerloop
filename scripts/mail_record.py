"""邮件反馈 → 台账记录：按公司名匹配岗位，生成 pipeline.py record JSON。

用法：
  python -X utf8 scripts/mail_record.py --mail <邮件JSON文件> [--job-id APP-xxx]
未给 --job-id 时按发件人/主题里的公司名匹配台账岗位。
"""
import argparse
import json
import re
import sqlite3
from pathlib import Path

from config import LEDGER as DB


def load_jobs():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    jobs = [(r['id'], json.loads(r['payload']).get('company', ''))
            for r in c.execute('select id,payload from jobs where decision != "exclude"')]
    c.close()
    return jobs


def match_job(frm, subject, jobs):
    hay = (frm or '') + ' ' + (subject or '')
    for jid, jcompany in jobs:
        key = re.sub(r'[（(].*?[)）]', '', jcompany).strip()
        if key and len(key) >= 2 and key in hay:
            return jid
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mail', required=True)
    ap.add_argument('--job-id', default='')
    args = ap.parse_args()
    mail = json.loads(Path(args.mail).read_text(encoding='utf-8'))
    jid = args.job_id or match_job(mail.get('from', ''), mail.get('subject', ''), load_jobs())
    if not jid:
        print(json.dumps({'error': '未匹配到岗位', 'mail_from': mail.get('from'),
                          'subject': mail.get('subject')}, ensure_ascii=False))
        return 1
    rec = {'stage': mail.get('stage', 'reply_received'),
           'summary': mail.get('subject', ''),
           'evidence': [mail.get('from', ''), mail.get('subject', '')]}
    if rec['stage'] in ('interview', 'reply_received'):
        rec['due_at'] = 'TBD'
    print(json.dumps({'job_id': jid, 'record': rec}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
