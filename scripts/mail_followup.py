"""专用邮箱读取 + 投递反馈分类（IMAP）。

从专用求职邮箱读收件箱，按发件人/主题/正文分类投递反馈，输出结构化 JSON。
邮箱凭据从 credential_store.py 读取（email.imap.host / email.imap.user / email.imap.pass）。
分类复用 reply_classify 的口径：invitation / question / rejection / other。

用法：
  python -X utf8 scripts/mail_followup.py fetch [--limit 20]
"""
import argparse
import email
import imaplib
import json
import sys
from email.header import decode_header
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from credential_store import get_secret
from reply_classify import REPLY_TYPES


def stage_of(mail_type):
    return REPLY_TYPES.get(mail_type, {}).get('stage', 'reply_received')


def decode_h(s):
    if not s:
        return ''
    out = []
    for text, enc in decode_header(s):
        if isinstance(text, bytes):
            out.append(text.decode(enc or 'utf-8', errors='replace'))
        else:
            out.append(text)
    return ''.join(out)


def classify(subject, body, sender):
    text = (subject + ' ' + body).lower()
    if any(k in text for k in ['面试', 'interview', '邀约', '面谈', '笔试', '测评']):
        return 'invitation'
    if any(k in text for k in ['遗憾', '不合适', '暂不考虑', 'reject', '未通过', '已招满', '感谢关注']):
        return 'rejection'
    if any(k in text for k in ['请问', '想了解', '感兴趣', '方便', '是否有意向', '考虑一下', '是否接受']):
        return 'question'
    return 'other'


def fetch_emails(limit=20):
    host = get_secret('email.imap.host')
    user = get_secret('email.imap.user')
    pw = get_secret('email.imap.pass')
    M = imaplib.IMAP4_SSL(host)
    M.login(user, pw)
    M.select('INBOX')
    typ, data = M.search(None, 'ALL')
    ids = data[0].split()[-limit:] if data and data[0] else []
    mails = []
    for i in ids:
        typ, msg_data = M.fetch(i, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        subject = decode_h(msg.get('Subject'))
        sender = decode_h(msg.get('From'))
        date = msg.get('Date', '')
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    payload = part.get_payload(decode=True)
                    body += payload.decode('utf-8', errors='replace') if payload else ''
        else:
            payload = msg.get_payload(decode=True)
            body = payload.decode('utf-8', errors='replace') if payload else ''
        mails.append({'from': sender, 'subject': subject, 'date': date,
                      'type': classify(subject, body, sender),
                      'stage': stage_of(classify(subject, body, sender)),
                      'body': body[:400]})
    M.logout()
    return mails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fetch'], default='fetch', nargs='?')
    ap.add_argument('--limit', type=int, default=20)
    args = ap.parse_args()
    try:
        mails = fetch_emails(args.limit)
        print(json.dumps(mails, ensure_ascii=False, indent=2))
    except (KeyError, Exception) as e:
        print(json.dumps({'error': str(e),
                          'hint': '先用 credential_store.py 配置 email.imap.host/user/pass（secret 走 stdin）'},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
