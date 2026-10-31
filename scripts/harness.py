"""harness.py — 求职执行 harness 统一入口（三通用能力：greet/apply/update_resume）。

用法（模型只需按下面固定命令调用，平台细节在 harness.json）：
  python -X utf8 scripts/harness.py list
  python -X utf8 scripts/harness.py greet <platform> <contact> <message>
  python -X utf8 scripts/harness.py apply <platform> <job_id>
  python -X utf8 scripts/harness.py update_resume <platform>
"""
import argparse
import json
import sqlite3
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent
ROOT = SCRIPT.parent.parent
from config import HARNESS as HARNESS_PATH, LEDGER as LEDGER_DB
HARNESS = json.loads(HARNESS_PATH.read_text(encoding='utf-8'))


def run_node(script, *args):
    """执行 node 脚本，直接继承 stdio（沙箱下不能 capture 子进程管道）。"""
    full = ['node', str(SCRIPT / script)] + [str(a) for a in args if a is not None]
    return subprocess.run(full).returncode


def run_node_capture(script, *args):
    """执行 node 并把 stdout/stderr 落到系统临时文件，读回 JSON（沙箱下不能走 pipe，用文件 fd）。"""
    tmp = Path(tempfile.gettempdir()) / ('dsh-node-' + uuid.uuid4().hex + '.json')
    full = ['node', str(SCRIPT / script)] + [str(a) for a in args if a is not None]
    with open(tmp, 'w', encoding='utf-8') as f:
        subprocess.run(full, stdout=f, stderr=subprocess.STDOUT)
    text = tmp.read_text(encoding='utf-8', errors='replace')
    tmp.unlink(missing_ok=True)
    start = text.find('{')
    return json.loads(text[start:]) if start >= 0 else {'raw': text[:1000], 'parse_failed': True}


def job_source_url(job_id):
    """从台账查岗位详情 URL（jobs.payload.source_url）。"""
    if not LEDGER_DB.exists():
        return None
    conn = sqlite3.connect(str(LEDGER_DB))
    try:
        row = conn.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return json.loads(row[0]).get('source_url')


def greet(platform, contact, message):
    cfg = HARNESS['capabilities']['greet']['platforms'].get(platform)
    if not cfg:
        print(f'greet {platform}: 未知平台'); return 2
    if cfg.get('status') != '已实测':
        print(f'greet {platform}: {cfg.get("status", "未配置")} - {cfg.get("note", "")}'); return 2
    chat = cfg['chat_url']
    for step in cfg['steps']:
        if step['cmd'] == 'click':
            run_node('browser_cdp.js', '--url', chat, 'click', contact)
        elif step['cmd'] == 'sendmsg':
            run_node('browser_cdp.js', '--url', chat, 'sendmsg', message)
    return 0


def apply(platform, job_id, execute=False):
    cfg = HARNESS['capabilities']['apply']['platforms'].get(platform)
    if not cfg:
        print(f'apply {platform}: 未知平台'); return 2
    url = job_source_url(job_id)
    if not url:
        print(f'apply {platform} {job_id}: 台账无该岗位的 source_url，无法定向投递'); return 2
    # 打开岗位详情页，等加载，再定位/点击投递按钮
    run_node('browser_cdp.js', 'open', url)
    time.sleep(4)
    receipt = None
    if cfg.get('tool') == 'cdp' and cfg.get('cmd') == 'apply':
        # submit：dry-run 定位；--execute 真实点击并抓回执（仍受外包岗授权约束）
        if execute:
            receipt = run_node_capture('browser_cdp.js', '--platform', platform, '--url', url, 'submit', 'execute')
        else:
            run_node('browser_cdp.js', '--platform', platform, '--url', url, 'submit', None)
    elif cfg.get('cmd') == 'click':
        run_node('browser_cdp.js', '--platform', platform, '--url', url, 'click', cfg['arg'])
    return receipt


def update_resume(platform):
    cfg = HARNESS['capabilities']['update_resume']['platforms'].get(platform)
    if not cfg:
        print(f'update_resume {platform}: 未知平台'); return 2
    status = cfg.get('status', '')
    print(f'update_resume {platform}: status={status} driver={cfg.get("driver", "")} mapping={cfg.get("mapping", "")}')
    if '阻塞' in status:
        print(f'  → {cfg.get("note", "")}')
        return 2
    # 实际填表由 field_mapping.json 的选择器 + browser_pw.js 的 upload/fill/select/日期选择器 驱动
    print(f'  → {cfg.get("note", "")}')
    return 0


def list_caps():
    print('== 三通用能力 ==')
    for cap, c in HARNESS['capabilities'].items():
        print(f'[{cap}] {c["description"]}  参数: {" ".join(c.get("params", []))}')
        for p, pc in c['platforms'].items():
            print(f'    {p}: {pc.get("status", "未配置")}')
    print('\n== 边界 ==')
    for k, v in HARNESS['boundary'].items():
        print(f'  {k}: {v}')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('capability', choices=['greet', 'apply', 'update_resume', 'list'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--execute', action='store_true', help='真实执行（仅 apply；默认 dry-run）')
    a = ap.parse_args()
    if a.capability == 'list':
        return list_caps()
    if a.capability == 'greet':
        if len(a.args) < 3:
            print('用法: harness.py greet <platform> <contact> <message>'); return 2
        return greet(a.args[0], a.args[1], ' '.join(a.args[2:]))
    if a.capability == 'apply':
        if len(a.args) < 2:
            print('用法: harness.py apply <platform> <job_id> [--execute]'); return 2
        receipt = apply(a.args[0], a.args[1], a.execute)
        if receipt:
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    if a.capability == 'update_resume':
        if len(a.args) < 1:
            print('用法: harness.py update_resume <platform>'); return 2
        return update_resume(a.args[0])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
