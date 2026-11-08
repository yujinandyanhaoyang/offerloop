"""面试回放训练：本地台账读写 + 每 5 题分批归档。通用版，不含个人数据。

    python -X utf8 scripts/interview_drill.py add --json q.json
    python -X utf8 scripts/interview_drill.py batches
    python -X utf8 scripts/interview_drill.py status
    python -X utf8 scripts/interview_drill.py mark-synced 1

默认台账 data/interview-ledger.json（已在 .gitignore，不入库）。
批次文件写到 data/batches/。
"""
import argparse
import json
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_LEDGER = ROOT / "data" / "interview-ledger.json"
BATCH_SIZE = 5

REQUIRED = ("qid", "date", "source", "company", "question", "answer_status")
LONG_FIELDS = ("我的原始回答", "参考口述", "追问与纠偏")


def load(path):
    if not path.exists():
        return {"meta": {"title": "面试训练台账", "batch_size": BATCH_SIZE}, "records": [], "training_records": []}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    data["meta"]["training_record_count"] = len(data.get("training_records", []))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assign_batches(records):
    ordered = sorted(records, key=lambda r: (r["date"], r["qid"]))
    for idx, rec in enumerate(ordered):
        rec["batch"] = idx // BATCH_SIZE + 1
        rec.setdefault("sync_state", "待同步")
    return ordered


def render_batch(batch_no, items):
    out = [f"# 面试训练 第 {batch_no:02d} 批（{items[0]['date']}）", "",
           f"> 本批 {len(items)} 题。参考答案为可口述的连贯段落，供脱稿复述。", ""]
    for r in items:
        out += [f"## {r['qid']}｜{r['company']}｜{r['question']}", ""]
        out += [f"- 来源：{r['source']}　·　结果：`{r['answer_status']}`　·　关联缺口：{'、'.join(r.get('gap_ids') or [])}", ""]
        for label in LONG_FIELDS:
            val = str(r.get(label) or "").strip()
            if not val:
                continue
            out += [f"**{label}**", ""]
            out += [f"> {line}".rstrip() for line in val.splitlines()]
            out += [""]
    return "\n".join(out).rstrip() + "\n"


def cmd_add(args, ledger):
    raw = sys.stdin.read() if args.json == "-" else pathlib.Path(args.json).read_text(encoding="utf-8-sig")
    rec = json.loads(raw)
    missing = [k for k in REQUIRED if not rec.get(k)]
    if missing:
        raise SystemExit("缺少必填字段: " + ", ".join(missing))
    rec.setdefault("gap_ids", [])
    rec.setdefault("sync_state", "待同步")

    data = load(ledger)
    recs = data.setdefault("training_records", [])
    if any(r["qid"] == rec["qid"] for r in recs):
        data["training_records"] = [rec if r["qid"] == rec["qid"] else r for r in recs]
        action = "replaced"
    else:
        recs.append(rec)
        action = "added"
    save(ledger, data)
    print(json.dumps({"action": action, "qid": rec["qid"], "total": len(data["training_records"])}, ensure_ascii=False))


def cmd_batches(args, ledger):
    data = load(ledger)
    ordered = assign_batches(data.get("training_records", []))
    outdir = ledger.parent / "batches"

    grouped = {}
    for r in ordered:
        grouped.setdefault(r["batch"], []).append(r)

    written = []
    for no, items in sorted(grouped.items()):
        path = outdir / f"batch-{no:02d}.md"
        content = render_batch(no, items)
        outdir.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8") == content:
            written.append({"batch": no, "status": "unchanged"})
            continue
        path.write_text(content, encoding="utf-8")
        written.append({"batch": no, "status": "written"})

    data["training_records"] = ordered
    save(ledger, data)
    print(json.dumps({"batches": {no: {"records": len(v),
                                       "sync_state": sorted({r["sync_state"] for r in v})}
                                 for no, v in sorted(grouped.items())},
                      "files": written}, ensure_ascii=False, indent=2))


def cmd_mark(args, ledger):
    data = load(ledger)
    n = 0
    for r in data.get("training_records", []):
        if r.get("batch") in args.batches:
            r["sync_state"] = "已同步"
            n += 1
    save(ledger, data)
    print(json.dumps({"marked": n, "batches": args.batches}, ensure_ascii=False))


def cmd_status(args, ledger):
    data = load(ledger)
    recs = data.get("training_records", [])
    print(json.dumps({
        "total": len(recs),
        "pending_sync": len([r for r in recs if r.get("sync_state") != "已同步"]),
        "by_batch": {no: len([r for r in recs if r.get("batch") == no])
                     for no in sorted({r.get("batch") for r in recs if r.get("batch")})},
        "gaps": {g["id"]: {"状态": g.get("补习状态"), "掌握度": g.get("掌握度")}
                 for g in data.get("records", [])},
        "ledger": str(ledger),
    }, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER), help="台账 JSON 路径")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="追加或更新一道题")
    p.add_argument("--json", required=True, help="payload JSON 文件，或 - 表示 stdin")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("batches", help="按 5 题一批归档并生成批次 Markdown")
    p.set_defaults(func=cmd_batches)

    p = sub.add_parser("mark-synced", help="标记批次已同步")
    p.add_argument("batches", nargs="+", type=int)
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("status", help="查看训练与同步进度")
    p.set_defaults(func=cmd_status)

    args = ap.parse_args()
    args.func(args, pathlib.Path(args.ledger))


if __name__ == "__main__":
    main()