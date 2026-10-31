#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chain.py — 求职「发现 → 筛选 → 海投」主链路固定入口。

让 V4-flash 只按 `chain.py <步骤>` 顺序执行，无需理解各脚本参数：

    python -X utf8 scripts/chain.py discover [--platform boss|zhaopin]
    python -X utf8 scripts/chain.py import   [--apply] [--jobs-json <file>]
    python -X utf8 scripts/chain.py screen
    python -X utf8 scripts/chain.py ready    [--scope ready|shortlist|all]
    python -X utf8 scripts/chain.py apply    [--execute]   # 仅外包岗，默认 dry-run
    python -X utf8 scripts/chain.py run      # 串起来，全 dry-run

边界（来自 harness.json boundary）：真实投递仅外包岗（外企德科/华为OD）；正编与「在考虑范围」岗只登记不真投。
本脚本默认全部 dry-run，不真实投递、不真实打招呼。空参 / --help 打印本用法。
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assistant import Ledger, DEFAULT_DB, PROJECT, stamp
import company_check
import job_check
from ready_list import build as build_ready

SCRIPT = Path(__file__).resolve().parent
from config import CHAIN_DIR
DEFAULT_JOBS = CHAIN_DIR / 'jobs.json'
DEFAULT_CARDS = CHAIN_DIR / '证据卡'

# 外包岗判定标记（小写比较，中文不受影响）。命中即视为外包、可 dry-run 投递测试；
# 其余（正编 / 在考虑范围）只登记不投。判定为启发式，最终以实际劳动主体核验为准。
OUTSOURCING_MARKERS = ('外企德科', '德科', '华为od', '华为 od', 'od外包')


def _text(payload):
    parts = [str(payload.get(k) or '') for k in ('company', 'title', 'city', 'summary', 'next_action')]
    return ' '.join(parts).lower()


def is_outsourcing(payload):
    text = _text(payload)
    return any(m in text for m in OUTSOURCING_MARKERS)


def cmd_discover(a):
    jobs_path = Path(a.jobs_json)
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    node_script = SCRIPT / 'browser_cdp.js'
    cmd = ['node', str(node_script), '--platform', a.platform, 'jobs']
    print('[discover] ' + subprocess.list2cmdline(cmd))
    print('[discover] 前置：宿主机已运行 browser_launch.cmd，且已登录标签停留在目标平台搜索结果页')
    try:
        with open(jobs_path, 'wb') as f:
            r = subprocess.run(cmd, stdout=f)
    except OSError as e:
        print('[discover] 启动失败: ' + str(e))
        return 2
    if r.returncode != 0:
        print('[discover] node 退出码 %d，见 %s' % (r.returncode, jobs_path))
        return r.returncode
    try:
        items = json.loads(jobs_path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        print('[discover] 输出非 JSON（浏览器未就绪或结果页无岗位），原文见 %s' % jobs_path)
        return 1
    if not isinstance(items, list):
        print('[discover] 输出不是岗位数组')
        return 1
    print('[discover] 提取 %d 条 → %s' % (len(items), jobs_path))
    return 0


def cmd_import(a):
    jobs_path = Path(a.jobs_json)
    if not jobs_path.is_file():
        print('[import] 找不到 jobs.json：%s（先 chain.py discover）' % jobs_path)
        return 1
    script = SCRIPT / 'boss_discover.py'
    cmd = [sys.executable, '-X', 'utf8', str(script), '--jobs-json', str(jobs_path)]
    if a.apply:
        cmd += ['--apply']
    if getattr(a, 'db', None):
        cmd += ['--db', str(a.db)]
    print('[import] ' + subprocess.list2cmdline(cmd))
    return subprocess.run(cmd).returncode


def cmd_screen(a):
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(getattr(a, 'db', None) or DEFAULT_DB)
    try:
        rows = ledger.db.execute("SELECT * FROM jobs WHERE decision != 'exclude' ORDER BY id").fetchall()
        made = 0
        for row in rows:
            payload = json.loads(row['payload'])
            company = payload.get('company') or '待核'
            title = payload.get('title') or ''
            job_label = (company + '-' + title) if title else company
            sub = out_dir / row['id']
            sub.mkdir(exist_ok=True)
            (sub / 'company_card.json').write_text(
                json.dumps(company_check.init_card(company), ensure_ascii=False, indent=2), encoding='utf-8')
            (sub / 'job_card.json').write_text(
                json.dumps(job_check.init_card(job_label), ensure_ascii=False, indent=2), encoding='utf-8')
            made += 1
        print(json.dumps({'cards': made, 'out_dir': str(out_dir),
                          'next': '填证据卡→company_check/job_check validate→shortlist 后 prepare/track'},
                         ensure_ascii=False, indent=2))
    finally:
        ledger.close()
    return 0


def cmd_ready(a):
    script = SCRIPT / 'ready_list.py'
    cmd = [sys.executable, '-X', 'utf8', str(script), '--scope', a.scope]
    if getattr(a, 'output', None):
        cmd += ['--output', str(a.output)]
    if getattr(a, 'db', None):
        cmd += ['--db', str(a.db)]
    print('[ready] ' + subprocess.list2cmdline(cmd))
    return subprocess.run(cmd).returncode


def cmd_apply(a):
    ledger = Ledger(getattr(a, 'db', None) or DEFAULT_DB)
    try:
        items = build_ready(ledger, 'ready')
        outsourcing, register_only = [], []
        for jid, payload, row, app, ctx in items:
            (outsourcing if is_outsourcing(payload) else register_only).append((jid, payload, ctx))
        print(json.dumps({'ready_total': len(items), 'outsourcing_apply': len(outsourcing),
                          'register_only': len(register_only), 'dry_run': True, 'send': False},
                         ensure_ascii=False, indent=2))
        for jid, payload, _ in register_only:
            print('[登记不投] %s｜%s｜%s' % (jid, payload.get('company'), payload.get('title')))
        if not outsourcing:
            print('无外包岗处于 ready；正编/在考虑范围岗只登记不投。')
            return 0
        print('\n== 外包岗（可 dry-run 投递测试；真实投递需另行授权并核对回执）==')
        for jid, payload, ctx in outsourcing:
            platform = (ctx.get('platform') or '').strip()
            platform_key = platform if platform in ('boss', 'zhaopin', 'meituan') else ''
            print('%s｜%s｜%s｜平台=%s' % (jid, payload.get('company'), payload.get('title'),
                                         platform_key or '待登记'))
            if not platform_key:
                print('  → 平台未登记，跳过（先 pipeline.py track 登记 platform）')
                continue
            cmd = [sys.executable, '-X', 'utf8', str(SCRIPT / 'harness.py'), 'apply', platform_key, jid]
            print('  ' + subprocess.list2cmdline(cmd))
            if a.execute:
                r = subprocess.run(cmd)
                print('  → 退出码 %d（harness.py apply 为 dry-run，不 send）' % r.returncode)
        if not a.execute:
            print('\n默认仅列出命令（plan）。加 --execute 才调用 harness.py apply（仍 dry-run，不投）。')
        return 0
    finally:
        ledger.close()


def cmd_submit(a):
    import harness
    from pipeline import Pipeline
    ledger = Ledger(getattr(a, 'db', None) or DEFAULT_DB)
    try:
        items = build_ready(ledger, 'ready')
        outsourcing, register_only = [], []
        for jid, payload, row, app, ctx in items:
            (outsourcing if is_outsourcing(payload) else register_only).append((jid, payload, ctx, app))
        print(json.dumps({'ready_total': len(items), 'outsourcing_apply': len(outsourcing),
                          'register_only': len(register_only), 'execute': bool(a.execute),
                          'external_send': bool(a.execute)}, ensure_ascii=False, indent=2))
        for jid, payload, ctx, app in register_only:
            print('[登记不投] %s｜%s｜%s' % (jid, payload.get('company'), payload.get('title')))
        if not outsourcing:
            print('无外包岗处于 ready；先 chain.py screen 生成证据卡→填卡→chain.py check→pipeline.py prepare 造样本（见海投链路.md）。')
            return 0
        for jid, payload, ctx, app in outsourcing:
            platform = (ctx.get('platform') or '').strip()
            platform_key = platform if platform in ('boss', 'zhaopin', 'meituan') else ''
            print('%s｜%s｜%s｜平台=%s' % (jid, payload.get('company'), payload.get('title'), platform_key or '待登记'))
            if not platform_key:
                print('  → 平台未登记，跳过（先 pipeline.py track 登记 platform）')
                continue
            if not a.execute:
                print('  python -X utf8 scripts/harness.py apply %s %s --execute' % (platform_key, jid))
                continue
            receipt = harness.apply(platform_key, jid, execute=True)
            if not receipt:
                print('  → 无回执（执行器失败或页面不可达）')
                continue
            state = receipt.get('state')
            if state == 'success':
                due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
                rec = {'stage': 'submitted',
                       'receipt': (receipt.get('url_after') or '') + ' ' + ','.join(receipt.get('success_markers') or []),
                       'summary': '投递成功 ' + (receipt.get('url_after') or ''),
                       'evidence': [receipt.get('screenshot') or 'no-screenshot', receipt.get('url_after') or '',
                                    'markers=' + ','.join(receipt.get('success_markers') or [])],
                       'resume_hash': (app['resume_hash'] if app else ''),
                       'due_at': due}
                try:
                    pl = Pipeline(getattr(a, 'db', None) or DEFAULT_DB)
                    pl.record(jid, rec)
                    pl.l.close()
                    print('  → 已登记 submitted（due_at=%s）' % due)
                except Exception as e:
                    print('  → 投递成功但登记失败：' + str(e))
            elif state == 'confirm_dialog':
                print('  → 需人工确认：' + json.dumps(receipt.get('dialog'), ensure_ascii=False))
            else:
                print('  → 回执状态=%s' % state)
        return 0
    finally:
        ledger.close()


def cmd_followup(a):
    ledger = Ledger(getattr(a, 'db', None) or DEFAULT_DB)
    try:
        has_apps = ledger.db.execute("SELECT 1 FROM sqlite_master WHERE name='applications'").fetchone()
        if not has_apps:
            print('无 applications 表（先 pipeline.py prepare/record）')
            return 0
        rows = ledger.db.execute("SELECT * FROM applications WHERE stage IN ('submitted','reply_received','interview') ORDER BY due_at").fetchall()
        items = []
        for r in rows:
            job = ledger.db.execute('SELECT payload FROM jobs WHERE id=?', (r['job_id'],)).fetchone()
            payload = json.loads(job['payload']) if job else {}
            items.append({'job_id': r['job_id'], 'company': payload.get('company', ''),
                          'title': payload.get('title', ''), 'stage': r['stage'],
                          'due_at': r['due_at'],
                          'next': '回复/跟进' if r['stage'] != 'submitted' else '等回复；逾期跟进'})
        print(json.dumps({'active': len(items), 'items': items}, ensure_ascii=False, indent=2))
        if a.mail:
            try:
                import mail_followup
                mails = mail_followup.fetch_emails(limit=20)
                print(json.dumps({'mail_fetched': len(mails), 'mails': mails[:10]}, ensure_ascii=False, indent=2))
            except Exception as e:
                print(json.dumps({'mail_error': str(e),
                                  'hint': '先配置 credential_store（email.imap.host/user/pass）'}, ensure_ascii=False))
        if a.draft:
            jid = a.draft
            job = ledger.db.execute('SELECT payload FROM jobs WHERE id=?', (jid,)).fetchone()
            payload = json.loads(job['payload']) if job else {}
            name = json.loads((PROJECT / '投递线/投递数据.json').read_text(encoding='utf-8'))['name']
            draft = ('您好，我是%s，已于近期投递贵司「%s」岗位。想了解下简历筛选进度；'
                     '如有需要我可以补充项目经历或安排沟通，谢谢！') % (name, payload.get('title', '该岗位'))
            print(json.dumps({'job_id': jid, 'draft': draft,
                              'note': '人工确认后经 browser_cdp.js sendmsg 或邮件发送'}, ensure_ascii=False, indent=2))
        return 0
    finally:
        ledger.close()


def cmd_check(a):
    # 筛选固化：校验已填证据卡（C1–C5 / J1–J5），输出可 shortlist 的岗位与缺口。
    out_dir = Path(a.cards_dir)
    results = []
    subs = sorted(out_dir.iterdir()) if out_dir.is_dir() else []
    for sub in subs:
        if not sub.is_dir():
            continue
        cc, jc = sub / 'company_card.json', sub / 'job_card.json'
        if not cc.is_file() or not jc.is_file():
            continue
        jid = sub.name
        try:
            ccard = json.loads(cc.read_text(encoding='utf-8'))
            jcard = json.loads(jc.read_text(encoding='utf-8'))
        except Exception as e:
            results.append({'job_id': jid, 'valid': False, 'errors': [str(e)]})
            continue
        c_err = company_check.validate_card(ccard)
        j_err = job_check.validate_card(jcard)
        results.append({'job_id': jid, 'company_decision': ccard.get('overall_decision'),
                        'job_decision': jcard.get('overall_decision'),
                        'valid': not c_err and not j_err, 'errors': c_err + j_err})
    ready = [r for r in results if r.get('valid') and r.get('job_decision') == 'shortlist']
    print(json.dumps({'checked': len(results), 'shortlist_ready': len(ready),
                      'results': results}, ensure_ascii=False, indent=2))
    return 0


def cmd_shortlist(a):
    # 筛选固化：证据卡校验通过且结论=shortlist → 写回台账 decision=shortlist。
    out_dir = Path(a.cards_dir)
    jid = a.job_id
    cc = out_dir / jid / 'company_card.json'
    jc = out_dir / jid / 'job_card.json'
    if not cc.is_file() or not jc.is_file():
        print(json.dumps({'error': 'missing cards', 'job_id': jid, 'cards_dir': str(out_dir)}, ensure_ascii=False))
        return 1
    ccard = json.loads(cc.read_text(encoding='utf-8'))
    jcard = json.loads(jc.read_text(encoding='utf-8'))
    errs = company_check.validate_card(ccard) + job_check.validate_card(jcard)
    if errs:
        print(json.dumps({'valid': False, 'job_id': jid, 'errors': errs}, ensure_ascii=False, indent=2))
        return 1
    if jcard.get('overall_decision') != 'shortlist':
        print(json.dumps({'valid': True, 'job_id': jid, 'decision': jcard.get('overall_decision'),
                          'note': '卡结论非 shortlist，不写入'}, ensure_ascii=False))
        return 0
    ledger = Ledger(getattr(a, 'db', None) or DEFAULT_DB)
    try:
        row = ledger.db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        if not row:
            print(json.dumps({'error': 'unknown job', 'job_id': jid}, ensure_ascii=False))
            return 1
        evidence = json.dumps([ccard.get('overall_decision'), jcard.get('overall_decision'),
                               'chain.shortlist from cards'], ensure_ascii=False)
        ledger.db.execute("UPDATE jobs SET decision='shortlist', reason=?, evidence=?, updated_at=? WHERE id=?",
                          (jcard.get('next_action') or ccard.get('next_action') or '', evidence, stamp(), jid))
        print(json.dumps({'job_id': jid, 'decision': 'shortlist', 'valid': True}, ensure_ascii=False))
        return 0
    finally:
        ledger.close()


def cmd_prepare(a):
    from pipeline import Pipeline
    try:
        evidence = json.loads(a.evidence) if a.evidence else {'source': 'chain.prepare', 'cards_checked': True}
        pl = Pipeline(getattr(a, 'db', None) or DEFAULT_DB)
        try:
            result = pl.chain_prepare(a.job_id, {'resume_path': a.resume, 'evidence': evidence})
        finally:
            pl.l.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(json.dumps({'error': str(e)}, ensure_ascii=False))
        return 1


def cmd_run(a):
    # discover → import(dry) → screen → ready → apply(plan)，全部非破坏性。
    rc = cmd_discover(a)
    if rc:
        return rc
    a.apply = False
    rc = cmd_import(a)
    if rc:
        return rc
    rc = cmd_screen(a)
    if rc:
        return rc
    rc = cmd_ready(a)
    if rc:
        return rc
    a.execute = False
    return cmd_apply(a)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='chain.py', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')

    p = sub.add_parser('discover', help='发现岗位：browser_cdp jobs → jobs.json')
    p.add_argument('--platform', choices=['boss', 'zhaopin'], default='boss')
    p.add_argument('--jobs-json', default=str(DEFAULT_JOBS))

    p = sub.add_parser('import', help='入库：boss_discover（默认 dry-run）')
    p.add_argument('--jobs-json', default=str(DEFAULT_JOBS))
    p.add_argument('--apply', action='store_true', help='真正入库（否则只打印记录）')
    p.add_argument('--db', type=Path, default=None)

    p = sub.add_parser('screen', help='筛选证据卡：company_check/job_check init')
    p.add_argument('--out-dir', default=str(DEFAULT_CARDS))
    p.add_argument('--db', type=Path, default=None)

    p = sub.add_parser('ready', help='出投递清单：ready_list')
    p.add_argument('--scope', choices=['ready', 'shortlist', 'all'], default='ready')
    p.add_argument('--output', default=None)
    p.add_argument('--db', type=Path, default=None)

    p = sub.add_parser('apply', help='海投外包岗：harness.py apply（dry-run）')
    p.add_argument('--execute', action='store_true', help='实际调用 harness.py apply（仍 dry-run，不 send）')
    p.add_argument('--db', type=Path, default=None)

    p = sub.add_parser('submit', help='投递执行：dry-run 定位；--execute 真实提交并抓回执')
    p.add_argument('--execute', action='store_true', help='真实点击投递并抓回执（仅外包岗；默认 dry-run）')
    p.add_argument('--db', type=Path, default=None)

    p = sub.add_parser('followup', help='跟进：列活跃申请 / 拉邮件 / 生成草稿')
    p.add_argument('--mail', action='store_true', help='拉取专用邮箱并分类')
    p.add_argument('--draft', default=None, metavar='JOB_ID', help='为指定岗位生成跟进草稿')
    p.add_argument('--db', type=Path, default=None)

    p = sub.add_parser('check', help='筛选固化：校验证据卡，输出可 shortlist 岗位')
    p.add_argument('--cards-dir', default=str(DEFAULT_CARDS))
    p.add_argument('--db', type=Path, default=None)

    p = sub.add_parser('shortlist', help='筛选固化：卡校验通过→写回 decision=shortlist')
    p.add_argument('job_id')
    p.add_argument('--cards-dir', default=str(DEFAULT_CARDS))
    p.add_argument('--db', type=Path, default=None)

    p = sub.add_parser('prepare', help='chain 流程投递准备：shortlist 岗 + 简历 → applications.stage=ready')
    p.add_argument('job_id')
    p.add_argument('--resume', required=True)
    p.add_argument('--evidence', default=None, help='JSON evidence（默认最小证据）')
    p.add_argument('--db', type=Path, default=None)

    p = sub.add_parser('run', help='串起 discover→import→screen→ready→apply（全 dry-run）')
    p.add_argument('--platform', choices=['boss', 'zhaopin'], default='boss')
    p.add_argument('--jobs-json', default=str(DEFAULT_JOBS))
    p.add_argument('--out-dir', default=str(DEFAULT_CARDS))
    p.add_argument('--scope', choices=['ready', 'shortlist', 'all'], default='ready')
    p.add_argument('--output', default=None)
    p.add_argument('--db', type=Path, default=None)

    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    dispatch = {'discover': cmd_discover, 'import': cmd_import, 'screen': cmd_screen,
                'ready': cmd_ready, 'apply': cmd_apply, 'run': cmd_run,
                'submit': cmd_submit, 'followup': cmd_followup, 'check': cmd_check,
                'shortlist': cmd_shortlist, 'prepare': cmd_prepare}
    return dispatch[a.cmd](a)


if __name__ == '__main__':
    raise SystemExit(main())
