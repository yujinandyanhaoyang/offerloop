"""牛客 JD 解析（接口识别模式）：把 web_fetch 抓取的牛客岗位详情正文解析成结构化字段。

牛客是 SSR，详情页用 web_fetch 即可取全文（无需浏览器/登录）。
用法：把 web_fetch 返回正文存为文本文件后：
  python -X utf8 scripts/nowcoder_parse.py --text 正文.txt --url https://www.nowcoder.com/jobs/detail/464519
"""
import argparse
import json
import re


def parse(text):
    title = ''
    m = re.search(r'([^\n_]+)_[^_]*?(?:社招|校招|实习)_牛客网', text)
    if m:
        title = m.group(1).strip()
    salary = ''
    m = re.search(r'(\d+-\d+K|\d+-\d+千|\d+-\d+万|\d+-\d+元)', text)
    if m:
        salary = m.group(1)
    city = ''
    m = re.search(r'(杭州|深圳|上海|北京|广州|成都|南京|武汉|西安|苏州|合肥|长沙|天津|重庆|宁波|厦门|青岛)', text)
    if m:
        city = m.group(1)
    edu = ''
    m = re.search(r'(本科|硕士|博士|大专|学历不限)', text)
    if m:
        edu = m.group(1)
    years = ''
    m = re.search(r'(\d+-\d+年|\d+年以上|经验不限|应届生|在校生|在校/应届)', text)
    if m:
        years = m.group(1)
    company = ''
    m = re.search(r'([^\n·]+公司)', text)
    if m:
        company = m.group(1).strip()
    jd = ''
    m = re.search(r'岗位职责[：:]?\s*([\s\S]*?)(?:岗位要求|任职要求|$)', text)
    if m:
        jd = m.group(1).strip()[:800]
    req = ''
    m = re.search(r'(?:岗位要求|任职要求)[：:]?\s*([\s\S]*?)(?:加分项|牛客安全提示|$)', text)
    if m:
        req = m.group(1).strip()[:800]
    return {'title': title, 'company': company, 'city': city, 'salary': salary,
            'education': edu, 'years': years, 'jd': jd, 'requirements': req}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--text', required=True)
    ap.add_argument('--url', default='')
    args = ap.parse_args()
    with open(args.text, encoding='utf-8') as f:
        text = f.read()
    r = parse(text)
    r['source_url'] = args.url
    r['source_level'] = 'primary_full'
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
