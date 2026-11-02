import _bootstrap  # noqa: F401
import copy
import json
import tempfile
import unittest
from pathlib import Path
from profile import prepare, compare, save, CONFIG, FACT_FIELDS


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.facts = self.root / 'facts.json'
        self.resume = self.root / 'resume.md'
        values = {
            'name': '测试姓名', 'gender': '男', 'identity': '职场人', 'current_city': '杭州',
            'monthly_salary_cny': 20000,
            'education': {'school': '测试大学', 'degree': '本科', 'major': '信息工程', 'start': '2022-09', 'end': '2026-06'},
            'current_employment': {'company': '现公司', 'position': '测试开发工程师', 'start': '2026-07', 'end': 'present', 'monthly_salary_cny': 20000},
            'prior_employment': {'company': '前公司', 'position': '实习生', 'start': '2025-05', 'end': '2025-07', 'monthly_salary_cny': 6300},
            'graduation_project_period': {'start': '2026-01', 'end': '2026-04'},
        }
        self.data = {'facts': {k: {'value': values[k], 'status': 'user_confirmed', 'source': 'test evidence'} for k in FACT_FIELDS},
                     'password': 'DO_NOT_EXPORT', 'unverified': {'birth_month': 'DO_NOT_EXPORT'}}
        save(self.facts, self.data)
        self.resume.write_text('# 别名\n手机号 DO_NOT_EXPORT\n## 工作经历\n### 现公司\n2026.07—至今\n- **工具**：真实职责\n### 前公司\n2025.05—07\n- 自动化\n## 项目经历\n### 推荐项目\n请求理解\n- Top-K和MMR\n- 反馈与UCB\n## 专业技能\n- Python\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, baseline=None):
        return prepare(self.facts, self.resume, CONFIG, baseline)

    def observed(self, fields):
        p = self.root / 'observed.json'
        save(p, {'platform': '智联招聘', 'source_reference': 'synthetic fixture',
                 'observed_at': '2026-10-24T20:00:00+08:00', 'fields': fields})
        return p

    def test_payload_excludes_secrets_and_preserves_complete_content(self):
        p = self.plan()
        self.assertNotIn('DO_NOT_EXPORT', json.dumps(p, ensure_ascii=False))
        self.assertIn('反馈与UCB', p['fields']['project_body'])
        self.assertEqual(p['fields']['current_employment.position'], '测试开发工程师')
        self.assertFalse(p['execution']['browser_actions'])

    def test_matching_baseline_skips_fields_and_diff_is_local(self):
        fields = self.plan()['fields']
        observed = copy.deepcopy(fields)
        observed['name'] = '旧名'
        observed['project_body'] = fields['project_body'].replace(' ', '\n')
        p = self.plan(self.observed(observed))
        self.assertEqual([x['field'] for x in p['changes'] if x['state'] == 'different'], ['name'])

    def test_truncated_project_and_missing_field_cannot_pass(self):
        p = self.plan()
        fields = copy.deepcopy(p['fields'])
        fields['project_body'] = '请求理解'
        del fields['gender']
        r = compare(p, self.observed(fields))
        self.assertFalse(r['verified'])
        self.assertIn('project_body', r['different'])
        self.assertIn('gender', r['unobserved'])

    def test_stale_sources_and_unresolved_mapping_block_completion(self):
        p = self.plan()
        r = compare(p, self.observed(p['fields']))
        self.assertFalse(r['verified'])
        self.assertTrue(r['blocked'])
        p['blocked'] = []
        self.assertTrue(compare(p, self.observed(p['fields']))['verified'])
        self.resume.write_text(self.resume.read_text(encoding='utf-8') + '\nnew source', encoding='utf-8')
        self.assertFalse(compare(p, self.observed(p['fields']))['verified'])

    def test_unknown_sensitive_observation_rejected(self):
        with self.assertRaises(ValueError):
            compare(self.plan(), self.observed({'password': 'secret'}))

    def test_unknown_facts_not_promoted_and_salary_conflict_rejected(self):
        self.data['facts']['gender']['status'] = 'unverified'
        save(self.facts, self.data)
        p = self.plan()
        self.assertNotIn('gender', p['fields'])
        self.assertTrue(any(x.startswith('gender:') for x in p['blocked']))
        self.data['facts']['monthly_salary_cny']['value'] = 16000
        save(self.facts, self.data)
        with self.assertRaises(ValueError):
            self.plan()

    def test_invalid_dates_and_changed_resume_structure_fail_closed(self):
        self.data['facts']['graduation_project_period']['value']['start'] = '2026-13'
        save(self.facts, self.data)
        with self.assertRaises(ValueError):
            self.plan()
        self.data['facts']['graduation_project_period']['value']['start'] = '2026-05'
        save(self.facts, self.data)
        with self.assertRaises(ValueError):
            self.plan()
        self.data['facts']['graduation_project_period']['value']['start'] = '2026-01'
        save(self.facts, self.data)
        self.resume.write_text('## 工作经历\n### 一个新结构\n- 内容', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.plan()


if __name__ == '__main__':
    unittest.main()
