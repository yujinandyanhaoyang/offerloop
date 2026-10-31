"""岗位判定证据卡：J1–J5 结构化采集与校验（配合 AI时代公司与岗位过滤器.md v4）。

用法：
  python -X utf8 scripts/job_check.py init --job "蚂蚁集团-AI应用工程师" > card.json
  python -X utf8 scripts/job_check.py validate --card card.json
"""
import argparse
import json
from datetime import date
from pathlib import Path

J_CHECKS = {
    "J1": "业务责任",
    "J2": "可迁移积累",
    "J3": "资源与组织",
    "J4": "真实准入",
    "J5": "个人回报",
}

JUDGMENTS = {"", "待核", "已满足", "可补", "待招聘方确认", "明确不符"}


def init_card(job):
    return {
        "job": job,
        "checked_on": date.today().isoformat(),
        "checks": {jid: {"name": name, "judgment": "", "evidence": "", "jd_quote": "", "gap": ""}
                   for jid, name in J_CHECKS.items()},
        "overall_decision": "",
        "next_action": "",
    }


def validate_card(card):
    errors = []
    if not card.get("job"):
        errors.append("缺 job")
    checks = card.get("checks", {})
    for jid, name in J_CHECKS.items():
        c = checks.get(jid)
        if not c:
            errors.append(f"缺 {jid} {name}")
            continue
        if c.get("judgment") not in JUDGMENTS:
            errors.append(f"{jid} judgment 非法")
        if not c.get("evidence"):
            errors.append(f"{jid} {name} 缺 evidence")
    if card.get("overall_decision") not in {"shortlist", "clarify", "exclude"}:
        errors.append("overall_decision 必须是 shortlist/clarify/exclude")
    if not card.get("next_action"):
        errors.append("缺 next_action")
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
    elif args.cmd == 'validate':
        card = json.loads(args.card.read_text(encoding='utf-8'))
        errors = validate_card(card)
        if errors:
            print(json.dumps({'valid': False, 'errors': errors}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({'valid': True, 'job': card['job'],
                          'decision': card['overall_decision']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
