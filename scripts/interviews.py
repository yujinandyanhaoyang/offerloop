"""Project-scoped interview research: evidence cache, validation, rendering, readback.

Source judgement and publishing remain with the agent and the supported Lark CLI.
Python standard library only. No background service and no remote write operation.
"""
import argparse
import calendar
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(__file__).resolve().parents[2]
PROJECT = WORKSPACE
CONFIG = PROJECT / 'interview-harness.json'
TRACKS = {'社招', '校招', '实习', '招聘类型未明', '历史相邻参考'}
HOSTS = {'www.nowcoder.com', 'nowcoder.com', 'api-cdn.nowcoder.com', 'ac.nowcoder.com', 'm.nowcoder.com'}

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))

def local_path(value):
    path = Path(value)
    path = (WORKSPACE / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(WORKSPACE):
        raise ValueError('输出/缓存路径必须位于当前工作区')
    return path

def save(path, value):
    path = local_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    # Exclusive temporary file and atomic replacement, with an optimistic conflict check.
    before = path.read_bytes() if path.exists() else None
    temp = path.with_name(path.name + '.pending')
    with temp.open('x', encoding='utf-8') as stream:
        stream.write(content)
    if (path.read_bytes() if path.exists() else None) != before:
        raise ValueError('并发修改，保留pending文件并停止')
    temp.replace(path)

def canonical_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('来源必须是无凭据的HTTPS链接')
    host = parsed.hostname.lower()
    path = parsed.path.rstrip('/')
    query = parsed.query
    if host in HOSTS:
        host = 'www.nowcoder.com'
        query = ''
    else:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
        query = urllib.parse.urlencode([(k,v) for k,v in pairs if not k.lower().startswith('utm_') and k.lower() not in ('spm','fbclid','gclid')])
    return urllib.parse.urlunsplit(('https', host, path, query, ''))

def source_key(source):
    host = urllib.parse.urlsplit(source['url']).hostname
    if host in HOSTS and source.get('uuid'):
        return 'nowcoder:' + source['uuid']
    return canonical_url(source['url'])

def validate(data, evidence):
    start = date.fromisoformat(data['range']['since'])
    end = date.fromisoformat(data['range']['until'])
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    if start > end or end > today:
        raise ValueError('范围倒置或包含尚未发生的日期')
    ids, urls, identities, flows = set(), set(), set(), set()
    for entry in data['entries']:
        if entry['id'] in ids or entry['track'] not in TRACKS:
            raise ValueError('重复事项ID或未知招聘身份: ' + entry['id'])
        ids.add(entry['id'])
        if data.get('selection',{}).get('track') and entry['track'] != data['selection']['track']:
            raise ValueError('招聘身份超出本批范围: '+entry['id'])
        flow = (entry['author'], entry['company'], entry.get('separate_flow', ''))
        if flow in flows:
            raise ValueError('同作者同公司重复；合并轮次或注明separate_flow依据')
        flows.add(flow)
        review = entry.get('review', {})
        if not (review.get('body_read') is True and review.get('questions_checked') is True
                and review.get('promotion_in_body') is False
                and review.get('experience_claim') == 'candidate_self_report'):
            raise ValueError('缺少原文/问题/引流人工语义审查: ' + entry['id'])
        if not entry.get('questions') or not entry.get('sources'):
            raise ValueError('缺少实质问题或原文链接: ' + entry['id'])
        for source in entry['sources']:
            key = canonical_url(source['url'])
            saved = evidence.get(source['source_id'], {})
            if saved.get('status') != 'original_body_read':
                raise ValueError('原文未取得，不能用摘要代替: ' + source['source_id'])
            if canonical_url(saved['url']) != key or saved.get('author') != entry['author']:
                raise ValueError('来源链接或作者与证据不符: ' + source['source_id'])
            ident = source_key(saved)
            if key in urls or ident in identities:
                raise ValueError('跨条目重复来源: ' + source['source_id'])
            urls.add(key)
            identities.add(ident)
            dates = saved.get('dates', {})
            for value in dates.values():
                if 'timestamp_ms' in value:
                    iso = datetime.fromisoformat(value['iso'])
                    if abs(iso.timestamp()*1000-value['timestamp_ms'])>1:
                        raise ValueError('原页时间戳与日期冲突: '+source['source_id'])
            candidates = [date.fromisoformat(dates[k]['iso'][:10])
                          for k in ('createdAt', 'createTime', 'editTime') if k in dates]
            if not candidates or not start <= candidates[0] <= end:
                raise ValueError('完整日期缺失或超窗: ' + source['source_id'])
            # A source cannot silently replace a cached timestamp with an inferred year.
            if source.get('dates') != dates:
                raise ValueError('正文来源日期与证据不一致: ' + source['source_id'])
    direct = [e for e in data['entries'] if e['track'] != '历史相邻参考']
    return {'direct_experiences': len(direct), 'direct_posts': sum(len(e['sources']) for e in direct),
            'all_experiences': len(data['entries']), 'all_posts': len(urls),
            'authors': len({e['author'] for e in data['entries']}),
            'companies': len({e['company'] for e in data['entries']}),
            'track_counts': dict(Counter(e['track'] for e in data['entries']))}

class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_fetch_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def validate_fetch_url(url):
    parsed = urllib.parse.urlsplit(url)
    canonical_url(url)
    if parsed.hostname not in HOSTS or parsed.port not in (None, 443):
        raise ValueError('采集器仅支持已核牛客公开原页；其他平台使用网页工具')
    if not re.match(r'^/(discuss/\d+|feed/main/detail/[a-f0-9]{32})(?:/|$)', parsed.path):
        raise ValueError('不是支持的公开原帖路径')

def collect_one(url, previous=None, refresh=False, max_attempts=2):
    validate_fetch_url(url)
    # A failed repeat must never erase an earlier usable record.
    successful = previous and previous.get('status') == 'original_body_read'
    if successful and not refresh:
        return previous, None, 'cached'
    attempts = 0 if successful else int((previous or {}).get('attempts', 0))
    if attempts >= max_attempts:
        return previous, None, 'attempt_limit'
    item = {'url': url, 'attempts': attempts + 1,
            'retrieved_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
    try:
        opener = urllib.request.build_opener(RestrictedRedirect())
        with opener.open(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=20) as response:
            content = response.read(4 * 1024 * 1024 + 1)
        if len(content) > 4 * 1024 * 1024:
            raise ValueError('原页超过4MiB限制')
        page = content.decode('utf-8')
        marker = 'window.__INITIAL_STATE__='
        if marker not in page:
            item['status'] = 'body_not_available'
            if successful:
                return {**previous, 'last_refresh': item}, None, 'refresh_failed_kept_previous'
            return item, None, 'needs_web_read'
        state, _ = json.JSONDecoder().raw_decode(page.split(marker, 1)[1])
        node = next(v for v in state.get('prefetchData', {}).values()
                    if isinstance(v, dict) and 'ssrCommonData' in v)
        data = node['ssrCommonData']['contentData']
        raw = data.get('content', '')
        body = re.sub(r'\n\s*\n+', '\n', html.unescape(re.sub('<[^>]+>', '\n', raw))).strip()
        brief = data.get('userBrief') or {}
        dates = {}
        for key in ('createTime', 'createdAt', 'editTime', 'showTime'):
            value = data.get(key)
            if isinstance(value, (int,float)) and value > 1e11:
                dates[key] = {'timestamp_ms': value, 'iso': datetime.fromtimestamp(value/1000, ZoneInfo('Asia/Shanghai')).isoformat()}
        item.update(status='original_body_read', title=data.get('title'),
                    author=brief.get('nickname') or brief.get('name') or brief.get('userName'),
                    uuid=data.get('uuid'), dates=dates, body_chars=len(body), short_excerpt=body[:100],
                    content_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                    source_fields='window.__INITIAL_STATE__.prefetchData.*.ssrCommonData.contentData',
                    review_required=True)
        return item, body, 'fetched_needs_semantic_review'
    except Exception as exc:
        item.update(status='read_failed', error=type(exc).__name__+': '+str(exc))
        if successful:
            return {**previous, 'last_refresh': item}, None, 'refresh_failed_kept_previous'
        return item, None, 'needs_web_read'

def render(data, stats):
    title = data['title']
    opening = (f"本批{stats['direct_experiences']}组直接相关面经、{stats['direct_posts']}篇原帖；"
               f"合计{stats['all_experiences']}组、{stats['authors']}位作者、{stats['companies']}家公司。")
    if stats['track_counts'].get('历史相邻参考'):
        opening += '历史相邻参考单列。'
    note = ('候选人亲历自述，身份和过程未经企业侧独立确认。问题为原帖题意整理，不补标准答案；'
            '发布/编辑日与面试日分开，未知项不补造，不推算必考概率。')
    md = ['# '+title, '', opening, '', note, '']
    xml = ['<title>'+html.escape(title)+'</title>']
    def paragraph(text):
        md.extend([text,'']); xml.append('<p>'+html.escape(text)+'</p>')
    def heading(text):
        md.extend(['## '+text,'']); xml.append('<h1 seq="auto">'+html.escape(text)+'</h1>')
    def link(source):
        return '<a href="'+html.escape(source['url'],quote=True)+'">'+html.escape(source.get('title',source.get('source_id','来源')))+'</a>'
    def table(headers, rows):
        md.append('| '+' | '.join(headers)+' |'); md.append('| '+' | '.join('---' for _ in headers)+' |')
        xml.append('<table><thead><tr>'+''.join('<th background-color="light-gray"><p>'+html.escape(h)+'</p></th>' for h in headers)+'</tr></thead><tbody>')
        for plain, rich in rows:
            md.append('| '+' | '.join(s.replace('|','／').replace('\n',' ') for s in plain)+' |')
            xml.append('<tr>'+''.join('<td><p>'+cell+'</p></td>' for cell in rich)+'</tr>')
        md.append(''); xml.append('</tbody></table>')
    xml.extend('<p>'+html.escape(text)+'</p>' for text in (opening,note))
    paragraph('资料窗口：'+data['range']['since']+'—'+data['range']['until']+'；查询：'+data['queried_at']+'。日期按原页完整时间核验，缺首次发布时使用已明确注明的编辑时间。')
    analysis=data.get('analysis',{})
    if analysis:
        heading(analysis.get('title','主要发现与准备重点'))
        if analysis.get('summary'):paragraph(analysis['summary'])
        for finding in analysis.get('findings',[]):
            paragraph(finding['claim']+'（依据：'+finding['references']+'）')
        if analysis.get('recommendation'):paragraph('准备建议：'+analysis['recommendation'])
    heading('原帖索引')
    for track in ('社招','校招','实习','招聘类型未明','历史相邻参考'):
        group=[e for e in data['entries'] if e['track']==track]
        if not group: continue
        paragraph(track)
        rows=[]
        for e in group:
            sources=' / '.join(f"[{s['source_id']}]({s['url']})" for s in e['sources'])
            values=[e['id']+' '+e['priority'],e['company']+' '+e['role'],e['published'],e['focus']]
            rows.append((values+[sources],[html.escape(v) for v in values]+[' / '.join(link({**s,'title':s['source_id']}) for s in e['sources'])]))
        table(['编号','公司／岗位','发布日期','重点','原文'],rows)
    for e in data['entries']:
        heading(e['id']+'｜'+e['company']+'｜'+e['role'])
        paragraph('作者：'+e['author']+'；身份：'+e['track']+'；地点：'+e['location']+'。')
        paragraph('面试：'+e['interview_date']+'；发布：'+e['published']+'；更新：'+e['edited']+'。')
        md.extend(['原文：'+'；'.join(f"[{s['title']}]({s['url']})" for s in e['sources']),''])
        xml.append('<p>原文：'+'；'.join(link(s) for s in e['sources'])+'</p>')
        md.extend(['- '+q for q in e['questions']]+[''])
        xml.append('<ul>'+''.join('<li>'+html.escape(q)+'</li>' for q in e['questions'])+'</ul>')
        for field,label in [('coding','编码／现场任务'),('process','流程与结果'),('why','用途'),('limitations','限制')]:
            paragraph(label+'：'+e[field])
    if data.get('stack_mapping'):
        heading(data.get('mapping_title','目标技术栈对应'))
        rows=[]
        for row in data['stack_mapping']:
            values=[row['domain'],row['observed_topics'],row['references']]
            rows.append((values,[html.escape(v) for v in values]))
        table(['技术块','考察点','记录'],rows)
    heading('范围与筛除')
    paragraph(data.get('method','定向筛选，非全网系统综述；同作者同公司多轮合并。'))
    paragraph('样本平台、招聘身份和月份的覆盖由本批数据决定；不据此推断未收录的平台或时期没有相关面经。')
    for excluded in data.get('exclusions',[]):
        paragraph(excluded['title']+'：'+excluded['reason'])
        md.extend(['[来源]('+excluded['url']+')','']); xml.append('<p>'+link({'url':excluded['url'],'title':'来源'})+'</p>')
    return '\n'.join(md)+'\n', '\n'.join(xml)+'\n'

def verify(expected_text, readback):
    if not readback.get('ok'):
        raise ValueError('云端读取未成功')
    expected=ET.fromstring('<doc>'+expected_text+'</doc>')
    actual=ET.fromstring('<doc>'+readback['data']['document']['content']+'</doc>')
    clean=lambda s:re.sub(r'\s+','',s)
    if clean(''.join(expected.itertext())) != clean(''.join(actual.itertext())):
        raise ValueError('云端正文不一致')
    def normalize_link(value):
        # Encode actual Unicode without decoding reserved delimiters such as %26.
        value=urllib.parse.quote(value, safe="/:?#[]@!$&'()*+,;=-._~%")
        return re.sub(r'%[0-9a-fA-F]{2}',lambda m:m.group().upper(),value)
    links=lambda t:[normalize_link(n.attrib['href']) for n in t.iter('a')]
    if links(expected) != links(actual):
        raise ValueError('云端链接或顺序不一致')
    tables=lambda t:len(list(t.iter('table')))
    if tables(expected)!=tables(actual):
        raise ValueError('云端表格数量不一致')
    return {'status':'verified','document_id':readback['data']['document']['document_id'],
            'revision':readback['data']['document']['revision_id'],'links':len(links(actual)),'tables':tables(actual)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('plan');p.add_argument('--since');p.add_argument('--until');p.add_argument('--topic',default='agent')
    p=sub.add_parser('collect');p.add_argument('--sources',required=True);p.add_argument('--cache',required=True);p.add_argument('--show-body',action='store_true');p.add_argument('--refresh',action='store_true')
    for name in ('validate','render'):
        p=sub.add_parser(name);p.add_argument('--input');p.add_argument('--evidence');p.add_argument('--topic',default='agent')
        if name=='render':p.add_argument('--out-prefix',required=True);p.add_argument('--draft',required=True)
    p=sub.add_parser('verify');p.add_argument('--expected',required=True);p.add_argument('--readback',required=True);p.add_argument('--output')
    args=parser.parse_args()
    if args.command=='verify':
        result=verify(Path(args.expected).read_text(encoding='utf-8'),read(args.readback))
        if args.output:save(args.output,result)
        emit(result);return
    config=read(CONFIG)
    if read(PROJECT/'project-memory.json')['project_id']!=config['project_id']:
        raise ValueError('不是目标求职项目')
    if args.command=='plan':
        end=date.fromisoformat(args.until) if args.until else datetime.now(ZoneInfo('Asia/Shanghai')).date()
        month_index=end.year*12+end.month-2;year,month=divmod(month_index,12);month+=1
        start=date.fromisoformat(args.since) if args.since else date(year,month,min(end.day,calendar.monthrange(year,month)[1]))
        if start>end or end>datetime.now(ZoneInfo('Asia/Shanghai')).date():raise ValueError('日期范围无效')
        topic=config.get('topics',{}).get(args.topic)
        if args.topic!='agent' and topic is None:raise ValueError('未知岗位主题；先在配置登记主题和独立绑定')
        profile=topic or config
        dataset=PROJECT/profile['dataset']
        data=read(dataset) if dataset.exists() else {'entries':[]}
        binding=read(PROJECT/'求职材料云端绑定.json')
        emit({'topic':args.topic,'range':{'since':str(start),'until':str(end)},'queries':[f'{term} 面经 {start} {end}' for term in profile['search_terms']],
              'known_source_urls':sorted({canonical_url(s['url']) for e in data['entries'] for s in e['sources']}),
              'existing_document':binding.get(profile.get('binding_key','agent_interview_library')),'tool_routes':config['tool_routes'],
              'stop':config['stop'],'note':'默认先近一个月；不足时按问题扩至三到六个月。当前明确时间窗优先；脚本不执行搜索或远端写入。'});return
    if args.command=='collect':
        jobs=read(args.sources)
        if len(jobs)>config['stop']['max_sources_per_batch']:raise ValueError('超过本批候选上限；交付已有结果')
        cache=read(args.cache) if Path(args.cache).exists() else {}
        # Validate all identities before any fetch; successful cache records are reused.
        seen=set()
        for source in jobs:
            validate_fetch_url(source['url'])
            key=canonical_url(source['url'])
            if source['source_id'] in seen or key in seen:raise ValueError('本批候选ID或URL重复')
            seen.update((source['source_id'],key))
            prior=cache.get(source['source_id'])
            if prior and canonical_url(prior['url'])!=canonical_url(source['url']):raise ValueError('source_id已绑定其他来源')
        for source in jobs:
            item,body,status=collect_one(source['url'],cache.get(source['source_id']),args.refresh,config['stop']['max_attempts_per_source'])
            cache[source['source_id']]={**item,'source_id':source['source_id']}
            save(args.cache,cache)
            emit({'source_id':source['source_id'],'status':status,'evidence':item,
                  'review_body':body if args.show_body else None})
        return
    profile=config.get('topics',{}).get(args.topic)
    if args.topic!='agent' and profile is None:raise ValueError('未知岗位主题')
    profile=profile or config
    data=read(args.input or PROJECT/profile['dataset']);evidence=read(args.evidence or PROJECT/profile['evidence'])
    stats=validate(data,evidence)
    if args.command=='validate':emit({'status':'passed','stats':stats,'semantic_limit':'检查证据字段和一致性，不证明亲历真实性或问题转述正确。'});return
    md,xml=render(data,stats);ET.fromstring('<doc>'+xml+'</doc>')
    outputs=[(local_path(args.out_prefix+'.md'),md),(local_path(args.draft),xml)]
    for path,content in outputs:
        if path.exists():raise ValueError('输出已存在，停止覆盖: '+str(path))
    for path,content in outputs:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as stream:stream.write(content)
    emit({'status':'rendered','stats':stats,'outputs':[str(p) for p,_ in outputs],
          'next':'按lark-doc创建工作流parse；已有绑定页面做局部更新；远端写后运行verify。'})

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,TypeError,StopIteration,OSError,ET.ParseError) as exc:
        emit({'status':'failed','error':str(exc)});sys.exit(1)
