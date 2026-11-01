import copy
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parent.parent / 'scripts' / 'interviews.py'
if MODULE_PATH.is_file():
    spec = importlib.util.spec_from_file_location('interviews', MODULE_PATH)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
else:
    tool = None

_READY = tool is not None and Path(tool.CONFIG).is_file()


@unittest.skipUnless(_READY, 'interview-harness.json 配置不在本仓库（项目级数据），跳过')
class InterviewHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config=tool.read(tool.CONFIG)
        cls.data=tool.read(tool.PROJECT/config['dataset'])
        cls.evidence=tool.read(tool.PROJECT/config['evidence'])

    def test_actual_delivered_sample(self):
        result=tool.validate(self.data,self.evidence)
        self.assertEqual((result['direct_experiences'],result['all_experiences'],result['all_posts']),(13,14,17))

    def test_fetch_does_not_replace_semantic_review(self):
        data=copy.deepcopy(self.data)
        data['entries'][0]['review']['questions_checked']=False
        with self.assertRaisesRegex(ValueError,'审查'):tool.validate(data,self.evidence)

    def test_duplicate_source_even_with_separate_flow(self):
        data=copy.deepcopy(self.data)
        item=copy.deepcopy(data['entries'][0]);item['id']='duplicate';item['separate_flow']='不同流程也不能复用原帖'
        item['sources'][0]['url']+='?tracking=duplicate';data['entries'].append(item)
        with self.assertRaisesRegex(ValueError,'重复来源'):tool.validate(data,self.evidence)

    def test_month_day_is_not_full_date(self):
        data=copy.deepcopy(self.data);evidence=copy.deepcopy(self.evidence)
        source=data['entries'][0]['sources'][0]
        source['dates']={};evidence[source['source_id']]['dates']={}
        with self.assertRaisesRegex(ValueError,'日期'):tool.validate(data,evidence)

    def test_cached_success_needs_no_network(self):
        previous=self.evidence['T1']
        with patch.object(tool.urllib.request,'build_opener',side_effect=AssertionError('must not fetch')):
            result,body,status=tool.collect_one(previous['url'],previous)
        self.assertEqual(result,previous);self.assertIsNone(body);self.assertEqual(status,'cached')

    def test_refresh_failure_keeps_success(self):
        previous=self.evidence['T1']
        with patch.object(tool.urllib.request,'build_opener',side_effect=OSError('temporary failure')):
            result,body,status=tool.collect_one(previous['url'],previous,refresh=True)
        self.assertEqual(result['dates'],previous['dates'])
        self.assertEqual(result['content_sha256'],previous['content_sha256'])
        self.assertEqual(status,'refresh_failed_kept_previous')
        self.assertEqual(result['last_refresh']['status'],'read_failed')

    def test_readback_detects_link_tampering_and_preserves_reserved_encoding(self):
        expected='<title>x</title><p><a href="https://example.com/Agent开发/?q=a%26b">原文</a></p>'
        good='<title>x</title><p><a href="https://example.com/Agent%E5%BC%80%E5%8F%91/?q=a%26b">原文</a></p>'
        response={'ok':True,'data':{'document':{'content':good,'document_id':'test','revision_id':1}}}
        self.assertEqual(tool.verify(expected,response)['status'],'verified')
        response['data']['document']['content']=good.replace('%26','&amp;')
        with self.assertRaisesRegex(ValueError,'链接'):tool.verify(expected,response)

    def test_collector_rejects_external_and_private_urls(self):
        for url in ['http://www.nowcoder.com/discuss/123','https://127.0.0.1/discuss/123',
                    'https://www.nowcoder.com.evil.example/discuss/123','https://user:secret@www.nowcoder.com/discuss/123']:
            with self.subTest(url=url),self.assertRaises(ValueError):tool.validate_fetch_url(url)

    def test_other_platform_content_query_is_preserved(self):
        first=tool.canonical_url('https://example.com/post?id=1&utm_source=search')
        second=tool.canonical_url('https://example.com/post?id=2&utm_source=search')
        self.assertNotEqual(first,second)
        self.assertEqual(first,'https://example.com/post?id=1')

    def test_cross_role_social_sample_and_render(self):
        profile=tool.read(tool.CONFIG)['topics']['sdet-social']
        data=tool.read(tool.PROJECT/profile['dataset'])
        evidence=tool.read(tool.PROJECT/profile['evidence'])
        stats=tool.validate(data,evidence)
        self.assertEqual((stats['all_experiences'],stats['authors']),(5,3))
        md,xml=tool.render(data,stats)
        self.assertNotIn('历史相邻参考单列',md)
        self.assertIn('测开能力与原题对应',xml)

    def test_social_selection_rejects_campus(self):
        data=copy.deepcopy(self.data);data['selection']={'track':'社招'}
        data['entries'][0]['track']='校招'
        with self.assertRaisesRegex(ValueError,'招聘身份超出'):tool.validate(data,self.evidence)

    def test_window_rejects_original_published_before_start(self):
        data=copy.deepcopy(self.data)
        data['range']['since']='2026-10-26'
        with self.assertRaisesRegex(ValueError,'超窗'):tool.validate(data,self.evidence)

if __name__=='__main__':unittest.main()
