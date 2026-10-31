"""Platform view of the existing queue, application records and event history."""
import html
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit


STAGES = {'ready': '材料就绪', 'submitted': '已投递', 'submission_unknown': '提交结果待核',
          'reply_received': '收到回复', 'interview': '面试中', 'offer': '收到offer', 'closed': '已结束'}
DECISIONS = {'pending': '待核验', 'clarify': '待澄清', 'exclude': '已排除', 'shortlist': '初筛候选'}


def source_platform(url):
    host = (urlsplit(url).hostname or '').lower()
    for domain, label in [('zhaopin.com', '智联招聘'), ('zhipin.com', 'BOSS直聘'),
                          ('nowcoder.com', '牛客'), ('watchjobs.net', 'WatchJobs'),
                          ('mianshima.com', '面试马')]:
        if host == domain or host.endswith('.' + domain):
            return label
    return host or '来源待核'


def local_time(value):
    if not value:
        return '未设置'
    try:
        date = datetime.fromisoformat(value)
        if date.tzinfo is None:
            return str(value) + '（时区待核）'
        return date.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return str(value) + '（时间待核）'


def report(ledger, output):
    e = lambda value: html.escape(str(value), quote=True)

    def link(url, label):
        try:
            parsed = urlsplit(url)
            safe = parsed.scheme in {'http', 'https'} and parsed.netloc and not parsed.username and not parsed.password
        except ValueError:
            safe = False
        return '<a href="' + e(url) + '" target="_blank" rel="noreferrer">' + e(label) + '</a>' if safe else e(label)

    has_apps = ledger.db.execute("SELECT 1 FROM sqlite_master WHERE name='applications'").fetchone()
    apps = {r['job_id']: dict(r) for r in ledger.db.execute('SELECT * FROM applications')} if has_apps else {}
    history, contexts = {}, {}
    for row in ledger.db.execute("SELECT at,kind,data FROM events WHERE kind IN ('opportunity_context','application_prepared','application_event','followup_reviewed') ORDER BY id"):
        data = json.loads(row['data'])
        jid = data.get('job_id')
        if not jid:
            continue
        history.setdefault(jid, []).append((row['at'], row['kind'], data))
        # Preparation metadata remains available after application evidence changes.
        values = data.get('evidence') if row['kind'] == 'application_prepared' else data
        if isinstance(values, dict):
            contexts.setdefault(jid, {}).update(values)

    jobs = list(ledger.db.execute('SELECT * FROM jobs ORDER BY id'))
    counts, rows, alerts = Counter(), [], []
    now = datetime.now(timezone.utc)
    for row in jobs:
        jid, payload = row['id'], json.loads(row['payload'])
        app, context = apps.get(jid), contexts.get(jid, {})
        source = source_platform(payload['source_url'])
        platform = context.get('platform') or source
        counts[platform] += 1
        task = ledger.db.execute('SELECT next_action FROM tasks WHERE job_id=? AND revision=? ORDER BY id DESC LIMIT 1', (jid, row['revision'])).fetchone()
        stage = app['stage'] if app else 'not_prepared'
        label = STAGES.get(stage, '未登记投递材料')
        next_action = context.get('next_action') or (task['next_action'] if task and not app else '')
        due = app['due_at'] if app else None
        urgent = stage == 'submission_unknown'
        warnings = []
        if urgent:
            warnings.append('先核对提交结果，禁止直接重投')
        if due:
            try:
                urgent = urgent or datetime.fromisoformat(due) <= now
                if datetime.fromisoformat(due) <= now:
                    warnings.append('已到下次检查时间')
            except (ValueError, TypeError):
                warnings.append('检查时间需修正')
        elif stage in {'submitted', 'reply_received', 'interview'}:
            warnings.append('缺下次检查时间／恢复条件需核对')
            urgent = True
        if app and app['revision'] != row['revision']:
            warnings.append('当前JD已变更，沟通须使用投递时版本')
            urgent = True
        if app and not context.get('platform'):
            warnings.append('实际投递平台待登记')
            urgent = True
        if stage in {'submitted', 'reply_received', 'interview'} and not next_action:
            warnings.append('缺下一行动')
            urgent = True
        if urgent:
            alerts.append(jid + '：' + '；'.join(warnings))
        events = history.get(jid, [])
        actual = [(at, data) for at, kind, data in events if kind == 'application_event']
        latest = actual[-1] if actual else None
        submitted = next(((at, data) for at, data in reversed(actual) if data.get('stage') == 'submitted'), None)
        resume = '未准备'
        if app:
            resume = e(Path(app['resume_path']).name) + '<br><small>SHA256 ' + e(app['resume_hash']) + '</small>'
        timeline = ''.join('<li>' + e(local_time(at)) + ' · ' + e(STAGES.get(data.get('stage'),
                    '跟进记录' if kind == 'followup_reviewed' else '准备／备注')) + '：' +
                    e(data.get('summary') or data.get('reason') or data.get('preparation') or '材料与渠道记录') +
                    '<br><small>' + e(json.dumps(data.get('evidence', []), ensure_ascii=False)) + '</small></li>'
                    for at, kind, data in events)
        preparation = '<details><summary>准备卡与历史</summary><p>' + e(context.get('preparation') or '尚未填写岗位沟通准备') + '</p>'
        preparation += '<p>岗位依据：' + e(row['reason'] or payload['summary']) + '</p>'
        preparation += '<p>核验证据：' + e(row['evidence']) + '</p><ol>' + timeline + '</ol></details>'
        platform_cell = e(platform) + '<br><small>' + ('拟投渠道已登记' if context.get('platform') else '按来源归组，拟投待确认') + '<br>来源：' + e(source) + '</small>'
        role_cell = '<strong>' + e(jid) + '</strong><br>' + e(payload['company']) + '<br>' + e(payload['title']) + '<br><small>' + e(payload['city']) + '<br>平台职位ID：' + e(context.get('platform_job_id') or '待核') + '</small>'
        status_cell = e(DECISIONS[row['decision']]) + '<br><strong>' + e(label) + '</strong>'
        status_cell += '<br><small>' + ('投递登记：' + e(local_time(submitted[0])) if submitted else '无已投回执记录') + '</small>'
        communication = e(context.get('contact') or '联系人未取得') + '<br>'
        communication += (e(latest[1].get('summary', '')) + '<br><small>事件登记：' + e(local_time(latest[0])) + '</small>') if latest else '暂无真实投递／招聘回复'
        action = e(next_action or '待补下一行动') + '<br><small>下次检查（北京时间）：' + e(local_time(due)) + '</small>'
        action += ''.join('<p class="warning">' + e(w) + '</p>' for w in warnings)
        sources = link(payload['source_url'], '原始JD／来源') + '<br><small>读取：' + e(payload['observed_on']) + '</small>'
        if context.get('application_url'):
            sources += '<br>' + link(context['application_url'], '拟投入口')
        search = ' '.join([jid, platform, payload['company'], payload['title'], context.get('contact', '')])
        rows.append('<tr data-platform="' + e(platform) + '" data-stage="' + e(stage) + '" data-urgent="' + str(int(urgent)) + '" data-search="' + e(search.lower()) + '">' +
                    ''.join('<td>' + value + '</td>' for value in [platform_cell, role_cell, status_cell, resume, communication, action, preparation, sources]) + '</tr>')

    options = ''.join('<option value="' + e(name) + '">' + e(name) + '</option>' for name in sorted(counts))
    stage_options = '<option value="not_prepared">未登记投递材料</option>' + ''.join('<option value="' + key + '">' + e(value) + '</option>' for key, value in STAGES.items())
    cards = ''.join('<div class="card"><strong>' + e(name) + '</strong><br>' + str(count) + ' 条机会记录</div>' for name, count in counts.items())
    actual_total = sum(any(kind == 'application_event' and data.get('stage') == 'submitted'
                           for _, kind, data in events) for events in history.values())
    alert_html = '<ul>' + ''.join('<li>' + e(item) + '</li>' for item in alerts) + '</ul>' if alerts else '<p>暂无已登记的到期跟进。平台回复尚未自动接入，不能据此认定没有未读消息。</p>'
    content = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>求职台账</title>
<style>body{font:15px/1.65 system-ui,sans-serif;margin:24px;color:#24374a;background:#f7f9fc}h1{margin-bottom:4px}small{color:#57677c;overflow-wrap:anywhere}.cards{display:flex;gap:12px;flex-wrap:wrap}.card{background:white;border:1px solid #dbe3ef;border-radius:10px;padding:12px 20px}.panel{background:#eaf3ff;padding:16px;border-radius:10px;margin:18px 0}.controls{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}input,select{font:inherit;padding:7px;max-width:100%;box-sizing:border-box}.wrap{overflow:auto;max-width:100%}table{border-collapse:collapse;background:white;min-width:1600px;width:100%;font-size:14px}td,th{border:1px solid #dbe3ef;padding:12px;vertical-align:top;min-width:130px;max-width:290px;overflow-wrap:anywhere}th{background:#eaf0f9;text-align:left}a{color:#205caa}.warning{color:#a53321;font-weight:600}details{min-width:210px}details p,li{overflow-wrap:anywhere}#shown{color:#57677c}[hidden]{display:none!important}@media(max-width:800px){body{margin:12px}}</style>
<h1>求职台账</h1><p>招聘平台优先 · 企业官网补充 · 台账登记不会发送简历</p>
'''
    content += '<p>' + str(len(jobs)) + ' 条岗位记录 · ' + str(len(apps)) + ' 条材料／申请记录 · ' + str(actual_total) + ' 条有投递回执记录（含历史已结束）</p>'
    content += '<p><small>生成：' + e(local_time(now.isoformat())) + '（北京时间）。按来源归组不代表已选择该投递平台；未填信息保留未知。事件时间为本地登记时间，非平台送达时间。</small></p><div class="cards">' + cards + '</div>'
    content += '<section class="panel"><strong>待处理与到期检查</strong>' + alert_html + '<a href="../../scripts/RUNBOOK.md">台账维护与执行手册</a></section>'
    content += '<div class="controls"><label>平台 <select id="platform"><option value="">全部</option>' + options + '</select></label><label>投递阶段 <select id="stage"><option value="">全部</option>' + stage_options + '</select></label><input id="search" aria-label="搜索企业岗位联系人" placeholder="搜索企业、岗位、ID、联系人"><label><input id="urgent" type="checkbox">只看需处理</label></div><p id="shown"></p>'
    headers = ['平台', '企业与岗位', '核验与投递状态', '所用简历', '联系人与最近事件', '下一行动与期限', '沟通／面试准备', '入口与来源']
    content += '<div class="wrap"><table id="opportunities"><thead><tr>' + ''.join('<th>' + label + '</th>' for label in headers) + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
    content += '''<script type="text/javascript">
const controls=['platform','stage','search','urgent'].map(id=>document.getElementById(id));
function filter(){let n=0;const [p,s,q,u]=controls;document.querySelectorAll('#opportunities tbody tr').forEach(r=>{r.hidden=!!((p.value&&r.dataset.platform!==p.value)||(s.value&&r.dataset.stage!==s.value)||(q.value&&!r.dataset.search.includes(q.value.toLowerCase()))||(u.checked&&r.dataset.urgent!=='1'));if(!r.hidden)n++;});document.getElementById('shown').textContent='显示 '+n+' 条记录';}
controls.forEach(c=>c.addEventListener('input',filter));filter();
</script></html>'''
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + '.tmp')
    temp.write_text(content, encoding='utf-8')
    temp.replace(output)
    return {'report': str(output.resolve()), 'jobs': len(jobs), 'applications': len(apps),
            'platforms': dict(counts), 'needs_attention': len(alerts)}
