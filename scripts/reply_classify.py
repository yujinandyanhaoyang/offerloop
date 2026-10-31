"""沟通跟进：BOSS 回复分类 + 阶段映射（消息读取由 browser_cdp.js 完成，本脚本只做分类与映射）。

回复类型 → 台账阶段（pipeline.py record 的 stage）：
  invitation    邀约面试  → interview
  question      询问/沟通  → reply_received（需回复/跟进）
  rejection     拒绝      → closed
  read_no_reply 已读未回  → submitted（继续跟进）
  other         其他      → reply_received

用法：
  python -X utf8 scripts/reply_classify.py init --job APP-001 > reply.json
  python -X utf8 scripts/reply_classify.py validate --card reply.json
"""
import argparse
import json
from datetime import date
from pathlib import Path

REPLY_TYPES = {
    "invitation": {"label": "邀约面试", "stage": "interview"},
    "question": {"label": "询问/沟通", "stage": "reply_received"},
    "rejection": {"label": "拒绝", "stage": "closed"},
    "read_no_reply": {"label": "已读未回", "stage": "submitted"},
    "other": {"label": "其他", "stage": "reply_received"},
}


def init_card(job):
    return {
        "job_id": job,
        "classified_on": date.today().isoformat(),
        "reply_type": "",
        "reply_summary": "",
        "message_source": "",
        "stage": "",
        "due_at": "",
        "next_action": "",
    }


def validate_card(card):
    errors = []
    if not card.get("job_id"):
        errors.append("缺 job_id")
    if card.get("reply_type") not in REPLY_TYPES:
        errors.append(f"reply_type 非法（{', '.join(REPLY_TYPES)}）")
    if not card.get("reply_summary"):
        errors.append("缺 reply_summary")
    if card.get("stage") not in {"submitted", "reply_received", "interview", "offer", "closed"}:
        errors.append("stage 非法")
    if card.get("stage") in {"interview", "reply_received"} and not card.get("due_at"):
        errors.append("interview/reply_received 需 due_at")
    return errors


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('init')
    a.add_argument('--job', required=True)
    b = sub.add_parser('validate')
    b.add_argument('--card', type=Path, required=True)
    args = ap.parse_args()

    if args.cmd == 'init':
        print(json.dumps(init_card(args.job), ensure_ascii=False, indent=2))
        print('# 回复类型 → 阶段：', json.dumps(REPLY_TYPES, ensure_ascii=False))
    elif args.cmd == 'validate':
        card = json.loads(args.card.read_text(encoding='utf-8'))
        errors = validate_card(card)
        if errors:
            print(json.dumps({'valid': False, 'errors': errors}, ensure_ascii=False, indent=2))
            return 1
        t = REPLY_TYPES[card['reply_type']]
        print(json.dumps({'valid': True, 'job_id': card['job_id'], 'reply_type': t['label'],
                          'stage': card['stage']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
