#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OfferLoop 总览（统一入口）。

只读：读台账 ledger.sqlite3、记忆 memory/、能力配置 harness.json、证据卡 hold 标记，
生成自包含 总览.html（offerloop 项目根），并打印控制台摘要。
不写台账、不改记忆；纯 Python 标准库，无外部依赖。

用法：python -X utf8 harness/scripts/overview.py
"""
import html
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from config import LEDGER, CONFIG, ADAPTERS, REPO

ROOT = REPO.parent                      # offerloop 项目根
MEMORY = ROOT / 'memory'
CARDS = LEDGER.parent / 'chain' / '证据卡'
HARNESS_JSON = ADAPTERS / 'harness.json'
OUT = ROOT / '总览.html'

DECISIONS = {'pending': '待核验', 'clarify': '待澄清', 'exclude': '已排除', 'shortlist': '初筛候选'}
PLATFORM_LABEL = {'boss': 'BOSS', 'zhaopin': '智联', 'example': '示例官网'}
PLATFORM_ORDER = ['boss', 'zhaopin', 'example']
CAP_LABEL = {'greet': '打招呼', 'apply': '投递', 'update_resume': '更新简历'}
DETAIL_ORDER = ['shortlist', 'clarify', 'exclude', 'pending']
STAGE_LABEL = {'ready': '材料就绪', 'submitted': '已投递', 'submission_unknown': '提交待核',
               'reply_received': '有回复', 'interview': '面试', 'offer': 'offer', 'closed': '已结束'}

JS_FILTER = '''<script>
(function(){var q=document.getElementById('jobFilter');var rows=document.querySelectorAll('#jobDetail tbody tr[data-s]');var groups=document.querySelectorAll('#jobDetail tbody tr.group');var shown=document.getElementById('jobCount');function apply(){var v=q.value.trim().toLowerCase(),n=0;rows.forEach(function(r){var on=!v||r.getAttribute('data-s').indexOf(v)>=0;r.style.display=on?'':'none';if(on)n++;});groups.forEach(function(g){var s=g.nextElementSibling,any=false;while(s&&!s.classList.contains('group')){if(s.style.display!=='none'){any=true;break;}s=s.nextElementSibling;}g.style.display=any?'':'none';});shown.textContent='显示 '+n+' / '+rows.length+' 岗（按结论分组 · 输入即筛选）';}q.addEventListener('input',apply);apply();})();
</script>'''


def esc(v):
    return html.escape(str(v), quote=True)


def bj(iso):
    if not iso:
        return '—'
    try:
        d = datetime.fromisoformat(iso)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return str(iso)


def platform(url):
    h = (urlsplit(url or '').hostname or '').lower()
    for dom, lab in [('zhaopin.com', '智联'), ('zhipin.com', 'BOSS'), ('nowcoder.com', '牛客'),
                     ('mianshima.com', '面试马'), ('liepin.com', '猎聘'), ('watchjobs.net', 'WatchJobs')]:
        if h == dom or h.endswith('.' + dom):
            return lab
    return h or '待核'


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def ledger_data():
    con = sqlite3.connect('file:%s?mode=ro' % LEDGER, uri=True)
    con.row_factory = sqlite3.Row
    try:
        jobs = [dict(r) for r in con.execute('SELECT * FROM jobs ORDER BY id')]
        has_apps = con.execute("SELECT 1 FROM sqlite_master WHERE name='applications'").fetchone()
        apps = {r['job_id']: dict(r) for r in con.execute('SELECT * FROM applications')} if has_apps else {}
        submitted = 0
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone():
            for r in con.execute("SELECT data FROM events WHERE kind='application_event'"):
                try:
                    if json.loads(r['data']).get('stage') == 'submitted':
                        submitted += 1
                except ValueError:
                    pass
        return jobs, apps, submitted
    finally:
        con.close()


def md_items(text, heading):
    out, inside = [], False
    for ln in text.splitlines():
        if ln.startswith(heading):
            inside = True
            continue
        if inside and ln.startswith('#'):
            break
        if inside and ln.strip().startswith('- '):
            out.append(ln.strip()[2:].strip())
    return out


def first_heading(text):
    for ln in text.splitlines():
        if ln.startswith('# '):
            return ln[2:].strip()
    return ''


def section(title, body):
    return '<section><h2>%s</h2>%s</section>' % (esc(title), body)


def stat_card(label, value, tone=''):
    cls = ('card ' + tone).strip()
    return '<div class="%s"><div class="num">%s</div><div class="lbl">%s</div></div>' % (cls, esc(value), esc(label))


def env_snapshot():
    """环境就绪探测（只读；CDP 探测失败不阻断总览生成）。"""
    try:
        from env_health import probe
        return probe()
    except Exception as exc:  # noqa: BLE001
        return {'error': str(exc)}


def env_card(env):
    if not env or 'error' in env:
        msg = esc(env.get('error', '未知')) if env else '未知'
        return section('环境就绪', '<p class="muted">环境探测不可用：%s（可运行 '
                       '<span class="mono">python -X utf8 harness/scripts/env_health.py</span> 手动查看）</p>' % msg)
    cdp = env.get('cdp') or {}
    circuit = env.get('circuit') or {}
    ledger = env.get('ledger') or {}
    login = env.get('login_state') or {}
    online = bool(cdp.get('online'))
    tabs = cdp.get('platform_tabs') or []
    inc = circuit.get('incidents') or {}
    fresh = ledger.get('latest_minutes_ago')
    fresh_label = ('%s 分钟前' % fresh) if fresh is not None else '—'
    cards = ('<div class="cards">'
             + stat_card('CDP 9222', '在线' if online else '离线', 'ok' if online else 'warn')
             + stat_card('平台标签', len(tabs), 'ok' if tabs else '')
             + stat_card('浏览器阻断', len(inc), 'warn' if inc else 'ok')
             + stat_card('台账新鲜度', fresh_label, 'warn' if (fresh is None or fresh > 60) else 'ok')
             + stat_card('最新回执', ledger.get('submitted_receipts', 0))
             + '</div>')
    browser = cdp.get('browser') or '—'
    login_bits = []
    for key, label in (('boss', 'BOSS'), ('zhaopin', '智联')):
        if login.get(key):
            login_bits.append('%s=%s' % (label, login[key]))
    note = ('浏览器：%s · 阻断：%s · 台账最近更新 %s（北京时间）· 登录态：%s。'
            '<br>CDP 在线只说明浏览器已起、未读回 DOM，不证明登录态仍有效；投递/读取前仍须读回页面核验。'
            % (esc(browser), esc(', '.join(sorted(inc.keys())) if inc else '无'),
               bj(ledger.get('latest_updated_at')), esc('；'.join(login_bits) if login_bits else '未登记')))
    return section('环境就绪', cards + '<p class="muted">%s</p>' % note)


def detail_table(rows_by_decision):
    out = ['<input id="jobFilter" type="search" placeholder="筛选：公司 / 岗位 / 结论 / 依据 / 城市…" '
           'style="width:100%;box-sizing:border-box;font:inherit;padding:8px 11px;margin:0 0 8px">']
    out.append('<table id="jobDetail"><thead><tr><th>ID</th><th>公司</th><th>岗位</th><th>城市</th>'
               '<th>结论</th><th>材料</th><th>依据</th></tr></thead><tbody>')
    total = 0
    for dec in DETAIL_ORDER:
        rows = rows_by_decision.get(dec, [])
        if not rows:
            continue
        total += len(rows)
        out.append('<tr class="group"><td colspan="7">%s（%d）</td></tr>'
                   % (esc(DECISIONS.get(dec, dec)), len(rows)))
        for r in rows:
            stage = STAGE_LABEL.get(r['stage'], r['stage'])
            search = ' '.join([r['id'], r['company'], r['title'], r['city'],
                               DECISIONS.get(r['decision'], r['decision']), stage, r['reason']]).lower()
            out.append('<tr data-s="%s"><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                       '<td>%s</td><td>%s</td><td class="muted">%s</td></tr>'
                       % (esc(search), esc(r['id']), esc(r['company']), esc(r['title']), esc(r['city']),
                          esc(DECISIONS.get(r['decision'], r['decision'])),
                          esc(stage), esc(r['reason'] or '—')))
    out.append('</tbody></table>')
    out.append('<p class="muted" id="jobCount">共 %d 岗（按结论分组 · 输入即筛选）</p>' % total)
    out.append(JS_FILTER)
    return ''.join(out)


def build():
    jobs, apps, submitted = ledger_data()
    counts = Counter(r['decision'] for r in jobs)
    ready_cnt = sum(1 for a in apps.values() if a['stage'] == 'ready')

    idx = read_json(MEMORY / 'project-memory.json')
    active_phase = idx.get('active_phase', '?')
    phase_title = ''
    phase_path = ''
    phases = idx.get('phases', {})
    if active_phase in phases:
        phase_path = phases[active_phase].get('path', '')
        pp = (ROOT / phase_path) if phase_path else None
        if pp and pp.is_file():
            phase_title = first_heading(pp.read_text(encoding='utf-8'))
    lc = idx.get('latest_checkpoint', {})
    handoff = ROOT.parent.parent / '.project-handoffs' / '20261031-offerloop-restructure.json'

    # 下一动作：CURRENT_STATE 与 ROADMAP
    cs_text = (MEMORY / 'CURRENT_STATE.md').read_text(encoding='utf-8') if (MEMORY / 'CURRENT_STATE.md').is_file() else ''
    rm_text = (MEMORY / 'ROADMAP.md').read_text(encoding='utf-8') if (MEMORY / 'ROADMAP.md').is_file() else ''
    next_actions = md_items(cs_text, '## 下一动作与停止条件') or md_items(rm_text, '## 近期')

    # ready 短名单（decision=shortlist）
    ready = []
    for r in jobs:
        if r['decision'] != 'shortlist':
            continue
        p = json.loads(r['payload'])
        app = apps.get(r['id'])
        ready.append({'id': r['id'], 'company': p.get('company', ''), 'title': p.get('title', ''),
                      'city': p.get('city', ''), 'platform': platform(p.get('source_url', '')),
                      'stage': app['stage'] if app else '未备材料'})

    # 暂挂候选：证据卡带 hold 标记
    holds = []
    if CARDS.is_dir():
        for d in sorted(CARDS.iterdir()):
            jc = d / 'job_card.json'
            if not jc.is_file():
                continue
            card = read_json(jc)
            if card.get('hold'):
                holds.append({'id': d.name, 'job': card.get('job', ''), 'jd_status': card.get('jd_status', ''),
                              'hold': card.get('hold', '')})

    # 能力 × 平台矩阵
    caps = read_json(HARNESS_JSON).get('capabilities', {})
    cap_rows = []
    for cap in ['greet', 'apply', 'update_resume']:
        c = caps.get(cap, {}).get('platforms', {})
        cells = {pl: c.get(pl, {}).get('status', '—') for pl in PLATFORM_ORDER}
        cap_rows.append((CAP_LABEL.get(cap, cap), cells))

    now = datetime.now(timezone.utc)
    env = env_snapshot()

    # 岗位明细（按结论分组，供前端文本筛选）
    rows_by_decision = {}
    for r in jobs:
        p = json.loads(r['payload'])
        app = apps.get(r['id'])
        rows_by_decision.setdefault(r['decision'], []).append({
            'id': r['id'], 'company': p.get('company', ''), 'title': p.get('title', ''),
            'city': p.get('city', ''), 'decision': r['decision'],
            'reason': r['reason'] or '', 'stage': app['stage'] if app else '未备材料'})

    # ---------- HTML ----------
    parts = []
    parts.append('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width"><title>OfferLoop 总览</title>')
    parts.append('<style>body{font:15px/1.6 system-ui,sans-serif;margin:0;color:#24374a;background:#f7f9fc}'
                 'header{background:#14233b;color:#fff;padding:20px 28px}header h1{margin:0;font-size:22px}'
                 'header p{margin:6px 0 0;color:#aebcd2;font-size:13px}main{padding:20px 28px;max-width:1080px;margin:0 auto}'
                 'h2{font-size:17px;border-bottom:2px solid #dbe3ef;padding-bottom:6px;margin:26px 0 12px}'
                 '.cards{display:flex;gap:12px;flex-wrap:wrap}.card{background:#fff;border:1px solid #dbe3ef;border-radius:10px;padding:12px 18px;min-width:110px}'
                 '.card .num{font-size:24px;font-weight:700}.card .lbl{color:#57677c;font-size:13px}.card.ok{background:#eefaf1}.card.warn{background:#fff7e8}'
                 'table{border-collapse:collapse;background:#fff;width:100%;font-size:14px}td,th{border:1px solid #dbe3ef;padding:8px 11px;text-align:left;vertical-align:top}'
                 'th{background:#eaf0f9}a{color:#205caa;text-decoration:none}a:hover{text-decoration:underline}'
                 'tr.group td{background:#eaf0f9;font-weight:600}tr.group td{padding:6px 11px}'
                 '.nav ul{columns:2;padding-left:18px;line-height:1.9}.nav li{break-inside:avoid}'
                 'ul.todo{padding-left:18px;line-height:1.8}.muted{color:#57677c}details{margin:8px 0}.mono{font-family:ui-monospace,monospace;font-size:12px}'
                 '@media(max-width:700px){.nav ul{columns:1}} </style>')

    parts.append('<header><h1>OfferLoop 总览</h1><p>业务流程型 Agent 求职执行 harness · 统一入口 · '
                 '生成 %s（北京时间）· 只读生成，不写台账</p></header><main>' % bj(now.isoformat()))

    # 阶段
    stage_html = ('<div class="cards">'
                  + stat_card('当前阶段', '阶段 %s' % active_phase, 'ok')
                  + stat_card('阶段名', phase_title or '?')
                  + stat_card('最新检查点', lc.get('id', '—'))
                  + stat_card('真实投递回执', submitted)
                  + '</div>')
    if phase_path:
        stage_html += '<p class="muted">阶段文件：<a href="%s">%s</a></p>' % (esc(phase_path), esc(phase_path))
    parts.append(section('现在到哪了', stage_html))

    # 环境就绪
    parts.append(env_card(env))

    # 台账统计
    stat_html = '<div class="cards">' + stat_card('岗位总数', len(jobs)) \
        + stat_card('初筛候选 shortlist', counts.get('shortlist', 0), 'ok') \
        + stat_card('待澄清 clarify', counts.get('clarify', 0), 'warn') \
        + stat_card('已排除 exclude', counts.get('exclude', 0)) \
        + stat_card('待核验 pending', counts.get('pending', 0)) \
        + stat_card('材料就绪 ready', ready_cnt) + '</div>'
    parts.append(section('台账统计', stat_html))

    # 岗位明细（按结论分组 · 可筛选）
    parts.append(section('岗位明细（%d 岗 · 按结论分组可筛选）' % len(jobs), detail_table(rows_by_decision)))

    # ready 短名单
    if ready:
        rows = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                       % (esc(r['id']), esc(r['company']), esc(r['title']), esc(r['city']),
                          esc(r['platform']), esc(r['stage'])) for r in ready)
        parts.append(section('ready 短名单（可准备投递）',
                             '<table><thead><tr><th>ID</th><th>公司</th><th>岗位</th><th>城市</th><th>平台</th><th>材料</th></tr></thead><tbody>%s</tbody></table>' % rows))
    else:
        parts.append(section('ready 短名单（可准备投递）', '<p class="muted">暂无。</p>'))

    # 暂挂候选
    if holds:
        rows = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                       % (esc(h['id']), esc(h['job']), esc(h['jd_status']), esc(h['hold'])) for h in holds)
        parts.append(section('短名单候选·暂挂（在招/可投未核）',
                             '<table><thead><tr><th>ID</th><th>岗位</th><th>JD 状态</th><th>暂挂原因</th></tr></thead><tbody>%s</tbody></table>' % rows))
    else:
        parts.append(section('短名单候选·暂挂', '<p class="muted">暂无。</p>'))

    # 能力 × 平台矩阵
    mh = ''.join('<th>%s</th>' % esc(PLATFORM_LABEL.get(p, p)) for p in PLATFORM_ORDER)
    mrows = ''.join('<tr><th>%s</th>%s</tr>' % (esc(cap), ''.join('<td>%s</td>' % esc(cells[p]) for p in PLATFORM_ORDER))
                    for cap, cells in cap_rows)
    parts.append(section('能力 × 平台实测',
                         '<table><thead><tr><th></th>%s</tr></thead><tbody>%s</tbody></table>'
                         '<p class="muted">状态来自 harness/config/harness.json；"已实测"=真实跑通，"选择器已配/已定位"=定位但未完整验证。</p>' % (mh, mrows)))

    # 下一动作
    if next_actions:
        todo = ''.join('<li>%s</li>' % esc(x) for x in next_actions)
    else:
        todo = '<li class="muted">见 ROADMAP / CURRENT_STATE。</li>'
    parts.append(section('下一步', '<ul class="todo">%s</ul><p class="muted">来源：<a href="memory/CURRENT_STATE.md">CURRENT_STATE</a> · <a href="memory/ROADMAP.md">ROADMAP</a></p>' % todo))

    # 统一导航
    nav = '<div class="nav"><ul>'
    nav += '<li>启动：<a href="启动浏览器.cmd">启动浏览器.cmd</a>（CDP 9222）· <a href="harness/scripts/browser_launch.cmd">browser_launch.cmd</a> · <a href="harness/scripts/overview.py">overview.py</a></li>'
    nav += '<li><a href="README.md">README</a> · <a href=".local/offerloop/求职台账.html">求职台账（明细）</a> · <a href="投递线/投递清单.md">投递清单</a> · <a href="投递线/候选暂挂名单.md">候选暂挂名单</a></li>'
    nav += '<li>规则：<a href="规则/职业适配工作流.md">职业适配工作流</a> · <a href="规则/AI时代公司与岗位过滤器.md">公司与岗位过滤器</a> · <a href="规则/企业背调方法论.md">企业背调方法论</a> · <a href="投递线/执行策略.json">执行策略</a></li>'
    nav += '<li>手册：<a href="harness/docs/RUNBOOK.md">RUNBOOK</a> · <a href="harness/docs/能力手册.md">能力手册</a> · <a href="harness/docs/海投链路.md">海投链路</a> · <a href="harness/docs/INTERVIEWS.md">面经工具</a></li>'
    nav += '<li>记忆：<a href="memory/CURRENT_STATE.md">当前状态</a> · <a href="memory/ROADMAP.md">路线图</a> · <a href="memory/DECISIONS.md">决策</a> · <a href="memory/PROJECT_GOAL.md">目标</a> · <a href="memory/checkpoints/C-002.md">检查点 C-002</a></li>'
    nav += '<li>证据与交接：<a href=".local/offerloop/chain/证据卡/">证据卡目录</a> · <a href=".local/offerloop/平台接入状态.json">平台接入状态</a> · <a href="../../.project-handoffs/20261031-offerloop-restructure.json">交接清单</a></li>'
    nav += '</ul></div>'
    parts.append(section('统一导航', nav))

    parts.append('<p class="muted">生成命令：<span class="mono">python -X utf8 harness/scripts/overview.py</span>（只读；台账更新后重跑即可刷新）</p>')
    parts.append('</main></html>')

    return '\n'.join(parts), {
        'generated_at': now.isoformat(),
        'jobs': len(jobs), 'shortlist': counts.get('shortlist', 0), 'clarify': counts.get('clarify', 0),
        'exclude': counts.get('exclude', 0), 'pending': counts.get('pending', 0),
        'ready': ready_cnt, 'submitted': submitted, 'holds': len(holds), 'phase': active_phase,
        'decisions': dict(counts),
        'ready_shortlist': ready,
        'holds_detail': holds,
        'environment': env,
    }


def main():
    html_text, summary = build()
    OUT.write_text(html_text, encoding='utf-8')
    summary_path = LEDGER.parent / 'overview-summary.json'
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(OUT.resolve()), 'summary_json': str(summary_path.resolve()),
                      'summary': {k: summary[k] for k in ('jobs', 'shortlist', 'clarify', 'exclude',
                                                          'ready', 'submitted', 'holds', 'phase')}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
