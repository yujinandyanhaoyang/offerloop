"""岗位列表识别：把 browser_cdp.js jobs 输出转成 assistant.py import 记录（dry-run 默认）。

平台无关：配合 `browser_cdp.js --platform boss|zhaopin jobs` 使用，任何平台的 jobs JSON 都能转。
用法：
  node scripts/browser_cdp.js --platform boss jobs > jobs.json
  python -X utf8 scripts/boss_discover.py --jobs-json jobs.json            # 只打印 import 记录
  python -X utf8 scripts/boss_discover.py --jobs-json jobs.json --apply    # 入库
"""
import argparse
import json
import re
import sys
from pathlib import Path

from assistant import Ledger, DEFAULT_DB


def max_app_id(ledger):
    n = 0
    for r in ledger.db.execute('SELECT id FROM jobs'):
        m = re.match(r'APP-(\d+)', r['id'])
        if m:
            n = max(n, int(m.group(1)))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs-json', type=Path, required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--start-id', type=int, default=0, help='dry-run 起始 APP 序号；apply 时默认自动取台账最大号+1')
    ap.add_argument('--db', type=Path, default=DEFAULT_DB)
    args = ap.parse_args()

    items = json.loads(args.jobs_json.read_text(encoding='utf-8'))
    records = []
    start = args.start_id
    if args.apply:
        ledger = Ledger(args.db)
        start = max_app_id(ledger) + 1
    else:
        start = args.start_id or 1

    for it in items:
        if not it.get('title') or not it.get('source_url'):
            continue
        records.append({
            'id': f'APP-{start:03d}',
            'company': it.get('company') or '待核',
            'title': it['title'],
            'city': it.get('city') or '待核',
            'source_url': it['source_url'],
            'source_level': 'partial',
            'observed_on': it.get('observed_on') or '',
            'summary': it.get('summary') or '',
            'next_action': it.get('next_action') or '打开详情页核验原JD与准入',
        })
        start += 1

    if args.apply:
        out = ledger.ingest(records)
        print(json.dumps(out, ensure_ascii=False))
        ledger.close()
    else:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        print(f'# 共 {len(records)} 条（dry-run，未入库）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
