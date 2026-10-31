"""Confirmed research scope and deterministic search cells; no network calls."""
import hashlib
import json
from datetime import date
from pathlib import Path
from config import SCOPE as CAMPAIGN


def read_campaign(path=CAMPAIGN):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate(campaign):
    if not isinstance(campaign, dict):
        return 'invalid_direction_confirmation'
    if campaign.get('status') != 'confirmed':
        return 'awaiting_direction_confirmation'
    for key in ('id', 'confirmation_reference', 'confirmed_on'):
        if not isinstance(campaign.get(key), str) or not campaign[key].strip():
            return 'invalid_direction_confirmation'
    try:
        date.fromisoformat(campaign['confirmed_on'])
    except ValueError:
        return 'invalid_direction_confirmation'
    cells = campaign.get('cells')
    if not isinstance(cells, list) or not cells:
        return 'empty_search_scope'
    ids = set()
    for c in cells:
        if not isinstance(c, dict):
            return 'invalid_search_cell'
        for key in ('id', 'industry_id', 'industry', 'city'):
            if not isinstance(c.get(key), str) or not c[key].strip():
                return 'invalid_search_cell'
        terms = c.get('role_terms')
        if not isinstance(terms, list) or not terms or any(not isinstance(t, str) or not t.strip() for t in terms):
            return 'invalid_search_cell'
        if c['id'] in ids:
            return 'duplicate_search_cell'
        ids.add(c['id'])
    return None


def fingerprint(campaign):
    return hashlib.sha256(json.dumps(campaign, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def eligible(payload, campaign):
    if validate(campaign):
        return False
    scope = payload.get('research_scope', {})
    if not isinstance(scope, dict) or scope.get('campaign_hash') != fingerprint(campaign):
        return False
    evidence = scope.get('evidence')
    if not isinstance(evidence, list) or not evidence or any(not isinstance(e, str) or not e.strip() for e in evidence):
        return False
    cell = next((c for c in campaign['cells'] if c['id'] == scope.get('cell_id')), None)
    # Role terms generate searches, never establish professional fit by themselves.
    return bool(cell and cell['city'] in payload.get('city', ''))


def search_plan(cell, today):
    month = today.year * 12 + today.month - 1 - 3
    import calendar
    year, m = divmod(month, 12)
    m += 1
    since = today.replace(year=year, month=m, day=min(today.day, calendar.monthrange(year, m)[1]))
    base = f"{cell['industry']} {cell['city']}"
    job_queries = [f"{base} {term} 招聘" for term in cell['role_terms']]
    # These are evidence searches, not assertions that a cluster or leader exists.
    evidence_queries = [f"{base} 产业链 客户 配套 企业",
                        f"{base} 细分市场 份额 竞争格局",
                        f"{base} 客户 采购 中标 经营现金流"]
    return {
        'cell': cell, 'query_period': {'from': since.isoformat(), 'to': today.isoformat()},
        'queries': evidence_queries + job_queries,
        'query_groups': {'cluster_and_company': evidence_queries, 'jobs': job_queries},
        'source_order': ['recruitment_platform', 'company_careers'],
        'evidence_fields': ['原JD与读取日期', '发布日期或未知', '招聘主体和团队', '实际职责',
                            '专业身份技能资质缺口', '招聘有效性与U0/U1/U2', '薪资工时出差',
                            '细分市场与集群及实际工作地', '客户和价值位置',
                            '细分领先证据及比较范围', '赚钱能力与现金／回款依据',
                            '公司C1-C5与岗位J1-J5', '本阶段关键缺口与面试核验项',
                            '筛选规则版本', '结论及下一行动'],
        'screening_rules_path': str(PROJECT / 'AI时代公司与岗位过滤器.md'),
        'evidence_policy': '按初筛、争取名单、面试与offer分阶段核验；有效招聘必要，急招用于排序；查询命中不代表业务或岗位通过。',
        'note': '仅生成检索任务；需使用当前受支持公开工具取得证据，不代表已联网或在招。'
    }
