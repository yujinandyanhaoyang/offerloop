"""Read-only, bounded Codex browser-log check; no browser control or credentials."""
import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from config import BROWSER_STATE as STATE


def latch(report, state, backend, incident=None):
    """Quiet logs never clear a previously observed failure."""
    key = backend + '|' + report['host']
    existing = state.get('incidents', {}).get(key)
    if incident or report['status'] == 'blocked':
        state.setdefault('incidents', {})[key] = existing or {
            'recorded_at': report['checked_at'], 'reason': incident or ','.join(report['reasons']),
            'release_condition': 'Explicit recovery decision after changed conditions and logged-in navigation validation; no time-based reset.'}
        existing = state['incidents'][key]
    if existing:
        report['status'] = 'blocked'
        report['latched_incident'] = existing
        if 'persistent_incident' not in report['reasons']:
            report['reasons'].append('persistent_incident')
        report['next_action'] = 'do not reopen/retry this site in this backend; preserve session and inspect changed conditions'
    report['backend'] = backend
    return report


def parse_line(line, number):
    try:
        at = datetime.fromisoformat(line[:24].replace('Z', '+00:00'))
    except ValueError:
        return None
    match = re.search(r'conversationId=(\S+)', line)
    event = {'at': at.isoformat(), 'line': number, 'backend': 'iab',
             'conversation': match.group(1) if match else None}
    if 'browser sidebar dom-ready' in line:
        url = re.search(r'url=(\S+)', line)
        if not url:
            return None
        parsed = urlsplit(url.group(1).strip('"'))
        event.update(kind='dom_ready', host=parsed.hostname, path=parsed.path)
    elif 'No ChatGPT browser route is available' in line:
        event['kind'] = 'route_missing'
    elif 'Invalid InterceptionId' in line:
        event['kind'] = 'interception_invalid'
    elif 'closed browser sidebar page' in line:
        event['kind'] = 'tab_closed'
    else:
        return None
    return event


def load_events(path, max_bytes=3 * 1024 * 1024):
    path = Path(path)
    with path.open('rb') as stream:
        size = path.stat().st_size
        start = max(0, size - max_bytes)
        stream.seek(start)
        if start:
            stream.readline()
        data = stream.read(max_bytes).decode('utf-8', errors='replace')
    # Numbers are relative to the bounded tail; byte offset keeps evidence locatable.
    events = [parse_line(line, i) for i, line in enumerate(data.splitlines(), 1)]
    return [e for e in events if e], {'path': str(path), 'tail_byte_offset': start}


def burst(events, threshold=3, seconds=30):
    times = sorted(datetime.fromisoformat(e['at']) for e in events)
    return any((times[i + threshold - 1] - times[i]).total_seconds() <= seconds
               for i in range(len(times) - threshold + 1))


def assess(events, host, conversation, now, window_seconds=120, backend='iab'):
    # These app-log markers describe the built-in browser, not Chrome extension traffic.
    recent = [e for e in events if e.get('backend', 'iab') == backend and now - timedelta(seconds=window_seconds)
              <= datetime.fromisoformat(e['at']) <= now]
    ready = [e for e in recent if e['kind'] == 'dom_ready' and e.get('host') == host]
    # Readiness is grouped by the site even if the app uses a temporary conversation alias.
    pages = defaultdict(list)
    for event in ready:
        pages[event['path']].append(event)
    errors = [e for e in recent if e['kind'] in {'route_missing', 'interception_invalid'}
              and e['conversation'] == conversation]
    reasons = []
    if any(burst(values) for values in pages.values()):
        reasons.append('repeated_page_ready_3_in_30_seconds')
    if burst([e for e in errors if e['kind'] == 'route_missing'], threshold=2):
        reasons.append('repeated_session_route_missing')
    if any(e['kind'] == 'interception_invalid' for e in errors):
        reasons.append('interception_identifier_invalid')
    return {
        'schema_version': 1, 'checked_at': now.isoformat(), 'host': host,
        'window_seconds': window_seconds, 'status': 'blocked' if reasons else 'no_recent_loop_detected',
        'log_coverage': 'built_in_browser_events' if backend == 'iab' else 'app log does not cover external browser navigation; verify current DOM separately',
        'reasons': reasons, 'page_ready_count': len(ready),
        'route_error_counts': dict(Counter(e['kind'] for e in errors)),
        'evidence': sorted(ready + errors, key=lambda e: e['at'])[-30:],
        'next_action': 'stop login/write; inspect once; recover at most one empty owned tab' if reasons else
                       'read current URL and rendered form once before proceeding',
        'boundary': 'Log symptoms only. No recent error does not prove visual stability, login success or root cause.',
        'network_calls': 0, 'browser_actions': 0,
    }


def default_log():
    base = Path(os.environ.get('LOCALAPPDATA', '')) / 'Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/Codex/Logs'
    today = base / datetime.now().strftime('%Y/%m/%d')
    files = list(today.glob('*.log'))
    if not files:
        raise ValueError('no current app log; supply --log explicitly')
    return max(files, key=lambda p: p.stat().st_mtime)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--log', type=Path)
    ap.add_argument('--host', required=True)
    ap.add_argument('--conversation', required=True)
    ap.add_argument('--window-seconds', type=int, default=120)
    ap.add_argument('--at', help='Zoned ISO cutoff for replaying historical evidence')
    ap.add_argument('--backend', default='iab', choices=['iab', 'chrome', 'edge'])
    ap.add_argument('--state', type=Path, default=STATE)
    ap.add_argument('--record-incident', help='Record a confirmed/user-reported incident; never store credentials here')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        now = datetime.fromisoformat(a.at.replace('Z', '+00:00')) if a.at else datetime.now(timezone.utc)
        if now.tzinfo is None or not 30 <= a.window_seconds <= 900:
            raise ValueError('zoned time and window between 30 and 900 seconds required')
        if a.out.exists():
            raise ValueError('receipt exists; choose a new output path')
        if a.at and a.record_incident:
            raise ValueError('historical replay must not record a live incident')
        events, source = load_events(a.log or default_log())
        result = assess(events, a.host, a.conversation, now, a.window_seconds, a.backend)
        result['source'] = source
        if not a.at:
            state = json.loads(a.state.read_text(encoding='utf-8-sig')) if a.state.exists() else {'schema_version': 1, 'incidents': {}}
            before = json.dumps(state, sort_keys=True)
            result = latch(result, state, a.backend, a.record_incident)
            if json.dumps(state, sort_keys=True) != before:
                a.state.parent.mkdir(parents=True, exist_ok=True)
                temporary = a.state.with_suffix('.pending.json')
                temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                temporary.replace(a.state)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in result.items() if k not in {'evidence', 'source'}}, ensure_ascii=False))
        return 2 if result['status'] == 'blocked' else 0
    except (OSError, ValueError) as exc:
        print(json.dumps({'status': 'unknown', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
