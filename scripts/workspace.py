"""One current-work view for every user; decisions + live records, no network writes."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import PROJECT_ROOT, SCOPE, PROFILE, LEDGER, INTERVIEW_LEDGER, RESUME, REPO

STATE = PROJECT_ROOT / 'memory/workspace.json'
VIEW = PROJECT_ROOT / 'memory/CURRENT_STATE.md'
MARKER = '<!-- offerloop:current-work -->'
STAGES = {'ready':'材料就绪', 'submitted':'台账记已投', 'submission_unknown':'提交结果未知',
          'reply_received':'已记录回复', 'interview':'已记录面试', 'offer':'已记录 offer', 'closed':'已结束'}
SECTIONS = {'direction', 'materials', 'next_actions', 'open_questions', 'retained_constraints', 'cloud'}


def read(path, fallback=None):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else fallback


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def scope_hash():
    data = read(SCOPE, {})
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def local_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError('材料需非空相对路径')
    p = (PROJECT_ROOT / value).resolve()
    if Path(value).is_absolute() or not p.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError('材料必须位于当前实例内，使用相对路径')
    return p


def ledger_snapshot():
    out = {'jobs':0, 'applications':[], 'receipt_events':0, 'receipt_jobs':0, 'latest_record':None}
    if not LEDGER.is_file():
        return out
    connection = sqlite3.connect(LEDGER.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'jobs' not in tables:
            raise ValueError('台账缺少 jobs 表')
        out['jobs'] = connection.execute('SELECT count(*) FROM jobs').fetchone()[0]
        receipts, contexts = set(), {}
        if 'events' in tables:
            for event in connection.execute('SELECT at,kind,data FROM events ORDER BY id'):
                item = json.loads(event['data'])
                if event['kind'] == 'application_event' and item.get('stage') == 'submitted' and item.get('receipt'):
                    out['receipt_events'] += 1
                    receipts.add(item.get('job_id'))
                if event['kind'] == 'opportunity_context':
                    contexts[item.get('job_id')] = item
            out['receipt_jobs'] = len(receipts - {None})
        if 'applications' in tables:
            for row in connection.execute('SELECT a.*,j.payload,j.decision FROM applications a JOIN jobs j ON a.job_id=j.id ORDER BY a.updated_at DESC,a.job_id'):
                payload, context = json.loads(row['payload']), contexts.get(row['job_id'], {})
                evidence = json.loads(row['evidence']) if row['evidence'] else {}
                evidence = evidence if isinstance(evidence, dict) else {}
                out['applications'].append({'id':row['job_id'], 'company':payload.get('company','未知'),
                    'title':payload.get('title','未知'), 'url':payload.get('source_url',''),
                    'stage':row['stage'], 'decision':row['decision'], 'receipt':row['job_id'] in receipts,
                    'updated_at':row['updated_at'], 'next_action':context.get('next_action') or payload.get('next_action') or '待确认',
                    'resume_path':row['resume_path'], 'resume_hash':row['resume_hash'],
                    'summary':evidence.get('summary', ''), 'feedback_type':evidence.get('feedback_type','未分类')})
        out['latest_record'] = max((r['updated_at'] for r in out['applications']), default=None)
        return out
    finally:
        connection.close()


def snapshot():
    state = read(STATE, {})
    issues = []
    if not state:
        issues.append('尚未建立当前工作状态，先运行 setup.py。')
    scope = read(SCOPE, {})
    direction = state.get('direction', {})
    if direction.get('profile_hash') and direction['profile_hash'] != digest(PROFILE):
        issues.append('个人条件已更新，当前方向与材料适配需要复核。')
    if direction.get('scope_hash') and direction['scope_hash'] != scope_hash():
        issues.append('检索配置已改变，当前方向说明尚未对齐。')
    if not direction.get('scope_hash') and scope.get('status') == 'confirmed':
        issues.append('已有检索范围，但尚未核对它与当前方向是否一致。')
    if direction.get('status') != '已确认':
        issues.append('方向仍在研究或复核，不应把已有候选写成最终决定。')
    materials = []
    for material in state.get('materials', []):
        item = dict(material)
        path = local_path(item['path'])
        item['current_hash'] = digest(path)
        if not item['current_hash']:
            item['effective_status'] = '文件缺失'
            issues.append('材料文件缺失：' + item['path'])
        elif item.get('reviewed_sha256') and item['reviewed_sha256'] != item['current_hash']:
            item['effective_status'] = '内容已变化，需重新审阅'
            issues.append('材料自上次审阅后变化：' + item['path'])
        elif item.get('status') == '可投' and not item.get('reviewed_sha256'):
            item['effective_status'] = '缺少对应版本的确认'
            issues.append('可投状态没有对应版本依据：' + item['path'])
        else:
            item['effective_status'] = item.get('status', '待审阅')
        materials.append(item)
    if RESUME.is_file() and not any(local_path(m['path']) == RESUME.resolve() for m in materials):
        issues.append('配置所指简历未进入材料清单，版本状态不明确。')
    try:
        jobs = ledger_snapshot()
    except (OSError, ValueError, sqlite3.Error) as exc:
        jobs = {'error':str(exc), 'jobs':None, 'applications':[], 'receipt_events':None, 'receipt_jobs':None}
        issues.append('台账读取失败，不能显示为零投递。')
    training = read(INTERVIEW_LEDGER, {'training_records':[], 'records':[]})
    gaps = [g for g in training.get('records', []) if g.get('补习状态') not in ('已补', '已复验', '已完成')]
    for app in jobs['applications']:
        if app['stage'] == 'submitted' and not app['receipt']:
            issues.append(app['id'] + ' 记为已投，但未找到独立提交回执事件，需核对。')
    return {'state':state, 'scope':scope, 'materials':materials, 'ledger':jobs,
            'training':{'total':len(training.get('training_records', [])), 'gaps':gaps}, 'issues':issues}


def cell(value):
    return str(value or '—').replace('|','／').replace('\n',' ')


def event_time(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M') if parsed.tzinfo else value
    except (TypeError, ValueError):
        return value


def link(path, label):
    try:
        target = os.path.relpath(path, VIEW.parent).replace('\\','/')
    except ValueError:
        target = str(path.resolve()).replace('\\','/')
    return '[' + cell(label) + '](<' + target + '>)'


def render(data):
    state, ledger = data['state'], data['ledger']
    d = state.get('direction', {})
    out = [MARKER, '# 当前求职工作', '',
        '> 由同一套 harness 根据当前决定、材料文件和业务台账生成。修改源数据后刷新，不手工维护另一份进度。',
        '', '## 先看需要处理什么', '']
    out += ['- ' + x for x in data['issues']] or ['- 当前未发现结构冲突；招聘事实仍按来源核实。']
    out += ['', '## 目前往哪里走', '', '- 判断状态：' + d.get('status','待研究')]
    for field, title in [('primary','主投／当前假说'),('parallel','并行验证'),('deferred','暂缓')]:
        out.append('- ' + title + '：' + ('；'.join(d.get(field,[])) or '尚未确定'))
    out += ['- 依据与边界：' + d.get('reason','尚未记录'),
            '- 实际检索配置：' + str(data['scope'].get('status','未配置'))]
    out += ['  - ' + cell(c.get('industry')) + ' / ' + cell(c.get('city')) + ' / ' + '、'.join(c.get('role_terms',[])) for c in data['scope'].get('cells',[])]
    out += ['', '## 简历和项目材料更新到哪里', '',
            '| 当前材料 | 用途 | 状态 | 说明 |', '| --- | --- | --- | --- |']
    for m in data['materials']:
        out.append('| ' + link(local_path(m['path']), m.get('label') or m['path']) + ' | ' + cell(m.get('purpose')) + ' | ' + cell(m['effective_status']) + ' | ' + cell(m.get('note')) + ' |')
    if not data['materials']:
        out.append('| 尚无在用材料 | — | 待准备 | 不从文件修改时间推定已定稿 |')
    out += ['', '## 投递了哪些企业和岗位', '',
        f"台账收录 {ledger['jobs']} 个岗位；有申请状态 {len(ledger['applications'])} 个；可核提交回执事件 {ledger['receipt_events']} 条，涉及 {ledger['receipt_jobs']} 个岗位。",
        '', '以下是本地已记录事实。未接入最新平台消息时，不能认定当前仍在招、尚无回复或仍应继续跟进。',
        '', '| ID | 企业／岗位 | 已记录状态 | 提交回执 | 最近反馈 | 最近业务记录（北京时间） | 上次记录的下一行动 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for a in ledger['applications'][:30]:
        out.append('| ' + ' | '.join(map(cell,[a['id'], a['company']+'／'+a['title'],STAGES.get(a['stage'],a['stage']),
                       '有独立记录' if a['receipt'] else '未找到独立记录', a['summary'][:160], event_time(a['updated_at']), a['next_action']])) + ' |')
    if len(ledger['applications']) > 30:
        out += ['', '此页显示最近 30 个申请状态，完整记录沿业务台账和飞书看板读取。']
    if not ledger['applications']:
        out.append('| — | 尚无申请记录 | 未登记 | — | — | — | 有真实动作后登记 |')
    cloud = state.get('cloud',{})
    if cloud.get('url'):
        out += ['', '[飞书推进看板](' + cloud['url'] + ')。' + cloud.get('note','云端状态需核对同步结果。')]
    out += ['', '## 笔面准备', '', f"已记录 {data['training']['total']} 次作答；尚待处理的缺口 {len(data['training']['gaps'])} 项。"]
    for gap in data['training']['gaps']:
        out.append('- ' + cell(gap.get('id')) + '：' + cell(gap.get('标题') or gap.get('问题') or gap.get('缺口') or gap.get('主题')) + '；' + cell(gap.get('补习状态')))
    for key, title in [('next_actions','下一步'),('open_questions','尚未确认'),('retained_constraints','恢复与执行约束')]:
        out += ['', '## ' + title, ''] + (['- ' + x for x in state.get(key,[])] or ['- 暂无记录。'])
    out += ['', '## 信息写到哪里', '',
        '- 个人条件只写个人档案；方向、材料状态和下一步只更新 ' + link(STATE,'工作状态') + '。',
        '- 原 JD、投递回执、招聘反馈只写原业务台账；题目、原回答和缺口只写训练台账。',
        '- 通用方法只更新 ' + link(REPO / 'docs/工作闭环.md','工作闭环') + ' 所指的 harness 文档。四条线保存现用产物，不另写进度流水账。',
        '- 一次性材料消费后提炼回现行来源，确认无未完事项和唯一证据后清理。', '']
    return '\n'.join(out)


def refresh(adopt=False):
    if VIEW.is_file() and MARKER not in VIEW.read_text(encoding='utf-8-sig') and not adopt:
        raise ValueError('现有 CURRENT_STATE 尚未迁入统一状态；先提炼未决事项，再 refresh --adopt，禁止直接覆盖')
    data = snapshot()
    VIEW.parent.mkdir(parents=True, exist_ok=True)
    VIEW.write_text(render(data), encoding='utf-8')
    return {'view':str(VIEW), 'issues':data['issues']}


def close(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('source'), str) or not payload['source'].strip():
        raise ValueError('收尾须说明事实或决定来源')
    updates = payload.get('updates', {})
    if not isinstance(updates, dict) or set(updates) - SECTIONS:
        raise ValueError('只更新既有状态栏目，岗位事件仍写台账')
    before = STATE.read_bytes()
    state = json.loads(before.decode('utf-8-sig'))
    for k,v in updates.items():
        if not isinstance(v, dict if k in {'direction','cloud'} else list):
            raise ValueError('状态栏目类型错误：' + k)
        state[k] = v
    for key in ('next_actions','open_questions','retained_constraints'):
        if any(not isinstance(x,str) for x in state[key]):
            raise ValueError('状态条目必须是文字')
    direction = state['direction']
    for key in ('primary', 'parallel', 'deferred'):
        if not isinstance(direction.get(key), list) or any(not isinstance(x, str) for x in direction[key]):
            raise ValueError('方向分组必须是文字列表：' + key)
    if not isinstance(direction.get('status'), str) or not isinstance(direction.get('reason'), str):
        raise ValueError('方向须说明状态和依据')
    for item in state['materials']:
        if not isinstance(item, dict):
            raise ValueError('材料条目须为对象')
        local_path(item['path'])
        if item.get('status') == '可投' and not item.get('reviewed_sha256'):
            raise ValueError('可投材料需当前内容哈希及真实确认依据')
    state['source'] = payload['source']
    if payload.get('align_scope'):
        if 'direction' not in updates:
            raise ValueError('核对范围时必须同时更新方向说明')
        state['direction']['scope_hash'] = scope_hash()
        state['direction']['profile_hash'] = digest(PROFILE)
    pending = STATE.with_suffix('.pending')
    with pending.open('x',encoding='utf-8') as f:
        f.write(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    if STATE.read_bytes() != before:
        raise ValueError('工作状态被其他会话修改，先核对 pending')
    pending.replace(STATE)
    return refresh()


def refresh_after_write():
    if STATE.is_file() and VIEW.is_file() and MARKER in VIEW.read_text(encoding='utf-8-sig'):
        try:
            refresh()
        except (ValueError, OSError, sqlite3.Error) as exc:
            print('业务写入已完成，但当前工作页刷新失败，请运行 workspace.py refresh：' + str(exc),file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    r = sub.add_parser('refresh');r.add_argument('--adopt',action='store_true')
    c = sub.add_parser('close');c.add_argument('--json',required=True)
    a=p.parse_args()
    if a.command=='status':
        result=snapshot()
    elif a.command=='refresh':
        result=refresh(a.adopt)
    else:
        payload=json.loads(sys.stdin.read() if a.json=='-' else Path(a.json).read_text(encoding='utf-8-sig'))
        result=close(payload)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
