"""Render a human-actionable submission checklist from the existing ledger.

Reads shortlisted / prepared jobs plus their track/prepare context and writes a
single Markdown file the user opens and acts on.  This script never submits or
sends anything: the final click stays with the user (human-in-the-loop).
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assistant import Ledger, DEFAULT_DB, PROJECT, stamp
from config import READY_OUTPUT

STAGES = {'ready': '材料就绪·待投递', 'submitted': '已投递', 'submission_unknown': '提交结果待核',
          'reply_received': '收到回复', 'interview': '面试中', 'offer': '收到offer', 'closed': '已结束'}
DECISIONS = {'pending': '待核验', 'clarify': '待澄清', 'exclude': '已排除', 'shortlist': '初筛候选'}


def local_time(value):
    if not value:
        return '未设置'
    try:
        d = datetime.fromisoformat(value)
        if d.tzinfo is None:
            return str(value) + '（时区待核）'
        return d.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return str(value) + '（待核）'


def build(ledger, scope='ready'):
    """Return the structured checklist; scope = ready|shortlist|all."""
    has_apps = ledger.db.execute("SELECT 1 FROM sqlite_master WHERE name='applications'").fetchone()
    apps = {r['job_id']: dict(r) for r in ledger.db.execute('SELECT * FROM applications')} if has_apps else {}
    contexts = {}
    for row in ledger.db.execute("SELECT at,kind,data FROM events WHERE kind IN ('opportunity_context','application_prepared') ORDER BY id"):
        data = json.loads(row['data'])
        jid = data.get('job_id')
        if not jid:
            continue
        values = data.get('evidence') if row['kind'] == 'application_prepared' else data
        if isinstance(values, dict):
            contexts.setdefault(jid, {}).update(values)

    items = []
    for row in ledger.db.execute('SELECT * FROM jobs ORDER BY id'):
        jid = row['id']
        payload = json.loads(row['payload'])
        app = apps.get(jid)
        ctx = contexts.get(jid, {})
        if scope == 'ready' and (not app or app['stage'] != 'ready'):
            continue
        if scope == 'shortlist' and row['decision'] != 'shortlist':
            continue
        items.append((jid, payload, row, app, ctx))
    return items


def render_markdown(items, now):
    lines = [
        '# 求职投递清单',
        '',
        '> 本清单只做“投递前一刻”的准备；**最后点击投递由本人完成**。本文件不会发送简历或消息。',
        '',
        f'- 生成时间（北京时间）：{local_time(now.isoformat())}',
        f'- 待投递岗位：{len(items)} 个',
        '',
        '每个岗位按「投递入口 → 逐岗简历 → 硬条件 → 打招呼/准备 → 下一行动」执行。',
        '',
    ]
    if not items:
        lines += ['当前没有状态为“材料就绪·待投递”的岗位。', '',
                  '补充方式：先取得原 JD 并 `assistant.py import`，通过筛选后 `pipeline.py prepare` 登记逐岗简历，',
                  '再 `pipeline.py track` 登记投递入口与打招呼话术，最后重跑本脚本。']
        return '\n'.join(lines)

    for jid, payload, row, app, ctx in items:
        lines += ['---', '', f'## {jid}｜{payload["company"]}｜{payload["title"]}', '']
        lines += [f'- **城市/来源**：{payload["city"]} · {payload.get("observed_on") or "未记录"}读取 · [原 JD]（{payload["source_url"]}）', '']
        entry = ctx.get('application_url') or payload.get('source_url')
        lines += [f'- **投递入口**：{entry}', '']
        if app:
            lines += [f'- **逐岗简历**：`{app["resume_path"]}`（SHA256 `{app["resume_hash"]}`）', '']
        else:
            lines += ['- **逐岗简历**：未登记（先 `pipeline.py prepare`）', '']
        lines += [f'- **筛选结论**：{DECISIONS.get(row["decision"], row["decision"])}']
        if row['reason']:
            lines += [f'  - 依据：{row["reason"]}']
        lines += ['']
        prep = ctx.get('preparation') or '（未填写：JD 核心职责、本人对应项目、待澄清问题、打招呼话术）'
        lines += [f'- **打招呼/准备卡**：', f'  {prep}', '']
        nxt = ctx.get('next_action') or '（待补：本次具体下一行动）'
        lines += [f'- **下一行动**：{nxt}', '']
        if row['evidence']:
            lines += [f'- **核验证据**：{row["evidence"]}', '']
    lines += ['---', '', '> 投递后用 `pipeline.py record` 登记真实回执与简历哈希；提交结果未知先对账，不重投。']
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', type=Path, default=DEFAULT_DB)
    ap.add_argument('--scope', choices=['ready', 'shortlist', 'all'], default='ready',
                    help='ready=待投递；shortlist=初筛候选（含未备材料）；all=全部')
    ap.add_argument('--output', type=Path, default=READY_OUTPUT)
    args = ap.parse_args()
    ledger = Ledger(args.db)
    try:
        items = build(ledger, args.scope)
        md = render_markdown(items, datetime.now(timezone.utc))
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding='utf-8')
        print(json.dumps({'output': str(out.resolve()), 'count': len(items),
                          'scope': args.scope, 'external_send': False}, ensure_ascii=False, indent=2))
    finally:
        ledger.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
