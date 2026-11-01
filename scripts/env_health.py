#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境就绪探测（只读）。

一键回答「现在能不能干活」：探测宿主机 CDP（127.0.0.1:9222）在线状态、已开标签、
浏览器电路阻断、平台登录态、台账新鲜度与最新投递回执数。

只读：不写台账、不改浏览器、不发请求到目标平台（仅探测本机 CDP 元信息端点）。
纯 Python 标准库，无外部依赖。

用法：
    python -X utf8 harness/scripts/env_health.py [--db <sqlite>]
    输出单份 JSON；也可被 overview.py / chain.py status 以 probe() 直接复用。
"""
import argparse
import json
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from config import LEDGER as DEFAULT_DB, BROWSER_STATE, PLATFORM_STATE

CDP = 'http://127.0.0.1:9222'
TIMEOUT = 1.5
TARGET_HOSTS = ('zhipin.com', 'zhaopin.com', 'nowcoder.com',
                'liepin.com', 'mianshima.com', 'watchjobs.net')


def _get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={'User-Agent': 'offerloop-env-health/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


def _host(url):
    return (urlsplit(url or '').hostname or '').lower()


def _target_of(host):
    for t in TARGET_HOSTS:
        if host == t or host.endswith('.' + t):
            return t
    return ''


def _now():
    return datetime.now(timezone.utc)


def _minutes_ago(iso, now):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return round((now - d.astimezone(timezone.utc)).total_seconds() / 60.0, 1)
    except (ValueError, TypeError):
        return None


def _max_iso(*values):
    vals = [v for v in values if v]
    return max(vals) if vals else ''


def cdp_probe():
    out = {'url': CDP, 'online': False, 'browser': '', 'error': None,
           'tabs': [], 'platform_tabs': []}
    try:
        version = json.loads(_get(CDP + '/json/version'))
        out['browser'] = version.get('Browser', '')
        out['online'] = True
    except Exception as exc:  # noqa: BLE001 — 探测失败即离线，保留原因
        out['error'] = str(exc)
        return out
    try:
        tabs = json.loads(_get(CDP + '/json/list'))
    except Exception:
        tabs = []
    seen = set()
    for t in tabs:
        if t.get('type') != 'page':
            continue
        host = _host(t.get('url'))
        entry = {'id': t.get('id'), 'url': t.get('url', ''),
                 'title': t.get('title', ''), 'host': host}
        out['tabs'].append(entry)
        target = _target_of(host)
        if target and target not in seen:
            seen.add(target)
            out['platform_tabs'].append(target)
    return out


def circuit_probe():
    incidents = {}
    if BROWSER_STATE.is_file():
        try:
            incidents = json.loads(BROWSER_STATE.read_text(encoding='utf-8')).get('incidents', {})
        except (OSError, ValueError):
            incidents = {}
    return {'count': len(incidents), 'incidents': {k: {'reason': v.get('reason', ''),
                                                        'recorded_at': v.get('recorded_at', '')}
                                                   for k, v in incidents.items()}}


def login_probe():
    """登录态：仅汇总已登记事实，不重新读回线上字段（读回需另走 CDP DOM）。"""
    out = {'boss': '', 'zhaopin': '', 'automation': {}}
    if PLATFORM_STATE.is_file():
        try:
            state = json.loads(PLATFORM_STATE.read_text(encoding='utf-8')).get('platforms', {})
        except (OSError, ValueError):
            state = {}
        for label, key in (('BOSS直聘', 'boss'), ('智联招聘', 'zhaopin')):
            p = state.get(label, {})
            out[key] = p.get('login_status', '')
            out['automation'][key] = p.get('automation_status', '')
    return out


def ledger_probe(db_path):
    con = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    con.row_factory = sqlite3.Row
    try:
        jobs = list(con.execute('SELECT id, decision, updated_at FROM jobs ORDER BY id'))
        decisions = {}
        for r in jobs:
            decisions[r['decision']] = decisions.get(r['decision'], 0) + 1
        has_apps = con.execute("SELECT 1 FROM sqlite_master WHERE name='applications'").fetchone()
        ready = 0
        latest = _max_iso(*(r['updated_at'] for r in jobs))
        if has_apps:
            apps = list(con.execute('SELECT stage, updated_at FROM applications'))
            ready = sum(1 for a in apps if a['stage'] == 'ready')
            latest = _max_iso(latest, *(a['updated_at'] for a in apps if a['updated_at']))
        submitted = 0
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone():
            events = list(con.execute("SELECT at, data FROM events WHERE kind='application_event'"))
            latest = _max_iso(latest, *(e['at'] for e in events if e['at']))
            for e in events:
                try:
                    if json.loads(e['data']).get('stage') == 'submitted':
                        submitted += 1
                except ValueError:
                    pass
    finally:
        con.close()
    now = _now()
    return {'path': str(db_path), 'jobs_total': len(jobs), 'decisions': decisions,
            'ready': ready, 'submitted_receipts': submitted,
            'latest_updated_at': latest, 'latest_minutes_ago': _minutes_ago(latest, now)}


def probe(db_path=DEFAULT_DB):
    """组合全部只读探测结果。"""
    return {
        'schema_version': 1,
        'checked_at': _now().isoformat(),
        'cdp': cdp_probe(),
        'circuit': circuit_probe(),
        'login_state': login_probe(),
        'ledger': ledger_probe(Path(db_path)),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', type=Path, default=DEFAULT_DB)
    a = ap.parse_args()
    try:
        print(json.dumps(probe(a.db), ensure_ascii=False, indent=2))
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({'status': 'unknown', 'error': str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
