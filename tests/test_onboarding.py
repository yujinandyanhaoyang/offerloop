"""Isolated new-user replay. All people, jobs and answers here are synthetic."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'checkout'
        self.repo.mkdir()
        # Only public source/template files; never copy a developer's private instance.
        for directory in ('scripts', 'docs', 'skills', 'templates'):
            shutil.copytree(REPO / directory, self.repo / directory,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (self.repo / 'config').mkdir()
        for name in ('执行策略.example.json', '当前检索范围.example.json', '投递数据.example.json',
                     'interview-harness.example.json', 'harness.json', 'field_mapping.json',
                     'platforms.json', 'companies.json', '简历字段标签.json'):
            shutil.copy2(REPO / 'config' / name, self.repo / 'config' / name)
        for name in ('AGENTS.md', 'README.md', '.gitignore', 'LICENSE'):
            shutil.copy2(REPO / name, self.repo / name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('OFFERLOOP_')}
        self.env.pop('PYTHONPATH', None)
        self.env['PYTHONIOENCODING'] = 'utf-8'

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, script, *args, payload=None, env=None, success=True, repo=None):
        command = [sys.executable, '-B', '-X', 'utf8', 'scripts/' + script, *map(str, args)]
        result = subprocess.run(command, cwd=repo or self.repo, env=env or self.env,
                                input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def load(self, path):
        return json.loads(path.read_text(encoding='utf-8'))

    def test_new_user_conversation_research_training_and_resume_on_new_device(self):
        self.run_cli('setup.py')
        profile = self.repo / '.local/profile/投递数据.json'
        initial = self.load(profile)
        self.assertIsNone(initial['eligibility']['social_insurance'])
        self.assertEqual(initial['career_preferences']['primary_role'], '')
        self.assertEqual(self.run_cli('onboard.py', 'status')['stage'], 'needs_context')
        self.assertEqual(self.run_cli('pipeline.py', 'plan')['reason'], 'awaiting_direction_confirmation')
        self.run_cli('onboard.py', 'apply', '--json', '-', payload={
            'source': 'synthetic conversation: user background',
            'updates': {'education': {'degree': '本科', 'major': '机械工程', 'graduation_date': '2024-06'},
                        'employment_status': '在职', 'work_experience': [
                            {'kind': 'internship', 'company': '测试实习单位', 'period': '2023-01/2023-03'},
                            {'kind': 'formal', 'company': '测试正式单位', 'period': '2024-07/至今'}]}})
        self.run_cli('onboard.py', 'apply', '--json', '-', payload={
            'source': 'synthetic conversation: user preferences',
            'updates': {'career_preferences': {'objective': '探索设备维护与应用岗位', 'preferred_regions': ['不限']},
                        'capabilities': {'summary': '能解释设备维护案例，效果尚未量化'}}})
        self.assertEqual(self.run_cli('onboard.py', 'status')['stage'], 'ready_for_research')
        facts = self.load(profile)
        self.assertEqual([x['kind'] for x in facts['work_experience']], ['internship', 'formal'])
        self.assertIsNone(facts['eligibility']['social_insurance'])
        self.assertEqual(self.load(self.repo / '.local/config/当前检索范围.json')['status'], 'draft')

        scope = {'id': 'fixture', 'status': 'confirmed', 'confirmation_reference': 'synthetic explicit user request',
                 'external_actions_enabled': False, 'cells': [
                     {'id': 'equipment', 'industry_id': 'manufacturing', 'industry': '设备制造',
                      'city': '南京', 'role_terms': ['设备维护']}]}
        (self.repo / '.local/config/当前检索范围.json').write_text(json.dumps(scope), encoding='utf-8')
        self.assertEqual(self.run_cli('pipeline.py', 'plan')['action'], 'discover')
        jobs = self.repo / '.local/jobs.json'
        jobs.write_text(json.dumps([{'id': 'APP-FIXTURE', 'company': '虚构测试公司', 'title': '设备维护',
            'city': '南京', 'source_url': 'https://example.org/jobs/fixture', 'source_level': 'primary_full',
            'observed_on': '2026-01-01', 'summary': '仅用于离线验证', 'next_action': '核实原JD'}]), encoding='utf-8')
        self.run_cli('assistant.py', 'import', jobs)
        self.run_cli('assistant.py', 'import', jobs)
        self.assertEqual(self.run_cli('chain.py', 'status')['ledger']['jobs_total'], 1)
        self.run_cli('interview_drill.py', 'add', '--json', '-', payload={
            'qid': 'FIXTURE-Q1', 'date': '2026-01-01', 'source': '模拟题', 'company': '虚构测试公司',
            'question': '说明一次设备故障排查', 'answer_status': '部分答出', '我的原始回答': '先查看故障日志。'})
        self.assertEqual(self.run_cli('interview_drill.py', 'status')['total'], 1)
        (self.repo / '内容线/简历.md').write_text('# 合成测试简历\n仅供测试。', encoding='utf-8')
        memory = self.repo / 'memory/CURRENT_STATE.md'
        self.run_cli('workspace.py', 'close', '--json', '-', payload={'source':'synthetic continuation', 'updates':{'next_actions':['复验设备排查题，核对 APP-FIXTURE 原 JD。']}})
        snapshots = {p: p.read_bytes() for p in [profile, memory, self.repo / '内容线/简历.md',
                                                self.repo / 'data/interview-ledger.json']}
        self.run_cli('setup.py')
        for path, content in snapshots.items():
            self.assertEqual(path.read_bytes(), content)
        # A different process and a relocated checkout use only the persisted instance.
        moved = self.root / 'another-device'
        shutil.copytree(self.repo, moved)
        self.assertEqual(self.run_cli('onboard.py', 'status', repo=moved)['stage'], 'ready_for_research')
        self.assertEqual(self.run_cli('chain.py', 'status', repo=moved)['ledger']['jobs_total'], 1)
        self.assertEqual(self.run_cli('interview_drill.py', 'status', repo=moved)['total'], 1)
        self.assertIn('APP-FIXTURE', (moved / 'memory/CURRENT_STATE.md').read_text(encoding='utf-8'))
        self.assertFalse(self.load(moved / '.local/config/执行策略.json')['external_actions_enabled'])

    def test_other_user_unknown_direction_and_safe_reinitialization(self):
        self.run_cli('setup.py')
        first_profile = self.repo / '.local/profile/投递数据.json'
        before = first_profile.read_bytes()
        second = self.root / 'other-user'
        self.run_cli('setup.py', '--workspace', second)
        env = dict(self.env, OFFERLOOP_LOCAL=str(second / 'offerloop.local.json'))
        self.run_cli('onboard.py', 'apply', '--json', '-', env=env, payload={
            'source': 'synthetic nontechnical user',
            'updates': {'education': {'degree': '大专', 'major': '行政管理'}, 'employment_status': '待业',
                        'career_preferences': {'objective': '方向未定，先探索', 'preferred_regions': ['不限']},
                        'capabilities': {'summary': '暂无项目，做过门店服务'}}})
        self.assertEqual(self.run_cli('onboard.py', 'status', env=env)['stage'], 'ready_for_research')
        self.assertEqual(first_profile.read_bytes(), before)
        own_profile = second / '.local/profile/投递数据.json'
        before_second = own_profile.read_bytes()
        (second / '笔面线/README.md').unlink()  # Simulate interrupted initialization of disposable fixture.
        self.run_cli('setup.py', env=env)
        self.assertTrue((second / '笔面线/README.md').is_file())
        self.assertEqual(own_profile.read_bytes(), before_second)
        self.assertEqual(self.run_cli('interview_drill.py', 'status', env=env)['total'], 0)
        self.assertEqual(self.run_cli('interviews.py', 'plan', env=env)['status'], 'needs_topic')

    def test_legacy_parent_manifest_and_explicit_missing_override(self):
        legacy = self.root / 'offerloop.local.json'
        legacy.write_text(json.dumps({'home': 'private-data', 'config': '投递线', 'personal': 'private-profile',
                                      'adapters': 'checkout/config'}), encoding='utf-8')
        (self.root / 'private-profile').mkdir()
        profile = self.root / 'private-profile/投递数据.json'
        profile.write_text('{"legacy": "keep exactly"}', encoding='utf-8')
        self.run_cli('setup.py')
        self.assertFalse((self.repo / 'offerloop.local.json').exists())
        self.assertEqual(profile.read_text(encoding='utf-8'), '{"legacy": "keep exactly"}')
        self.assertEqual(Path(self.run_cli('interview_drill.py', 'status')['ledger']),
                         self.root / 'private-data/interview-ledger.json')
        env = dict(self.env, OFFERLOOP_LOCAL=str(self.root / 'missing.json'))
        self.run_cli('setup.py', env=env, success=False)
        self.run_cli('onboard.py', 'status', env=env, success=False)

    def test_invalid_intake_does_not_change_profile_or_enable_actions(self):
        self.run_cli('setup.py')
        path = self.repo / '.local/profile/投递数据.json'
        before = path.read_bytes()
        for payload in [
            {'updates': {'name': 'fixture'}},
            {'source': 'fixture', 'updates': {'external_actions_enabled': True}},
            {'source': 'fixture', 'updates': {'work_experience': [{'company': '缺少经历类型'}]}},
            {'source': 'fixture', 'updates': {'education': 'wrong type'}}]:
            self.run_cli('onboard.py', 'apply', '--json', '-', payload=payload, success=False)
            self.assertEqual(path.read_bytes(), before)
        (path.parent / (path.name + '.pending')).write_text('unresolved write', encoding='utf-8')
        self.run_cli('onboard.py', 'apply', '--json', '-', payload={
            'source': 'fixture', 'updates': {'name': 'fixture'}}, success=False)
        self.assertEqual(path.read_bytes(), before)

    def test_generated_links_and_git_exclusion(self):
        self.run_cli('setup.py')
        for folder in ('行业线', '内容线', '笔面线', '投递线', 'memory'):
            for path in (self.repo / folder).glob('*.md'):
                content = path.read_text(encoding='utf-8')
                self.assertNotIn('{{', content)
                for link in re.findall(r'\]\(([^)]+)\)', content):
                    target = (path.parent / link.strip('<>')).resolve()
                    # The data directory is runtime-created, not a broken document link.
                    if target == self.repo / 'data':
                        continue
                    self.assertTrue(target.exists(), f'{path.name}: {link}')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, capture_output=True)
        result = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'],
                                cwd=self.repo, capture_output=True, encoding='utf-8', check=True)
        self.assertNotIn('offerloop.local.json', result.stdout)
        self.assertNotIn('.local/', result.stdout)
        self.assertNotIn('?? memory/CURRENT_STATE.md', result.stdout.splitlines())
        for folder in ('行业线', '内容线', '笔面线', '投递线'):
            check = subprocess.run(['git', 'check-ignore', folder + '/README.md'], cwd=self.repo,
                                   capture_output=True, encoding='utf-8')
            self.assertEqual(check.returncode, 0)

    def test_weekly_work_view_detects_scope_profile_and_resume_drift(self):
        import hashlib
        self.run_cli('setup.py')
        resume = self.repo / '内容线/简历.md'
        resume.write_text('Synthetic resume v1', encoding='utf-8')
        h = hashlib.sha256(resume.read_bytes()).hexdigest()
        self.run_cli('workspace.py', 'close', '--json', '-', payload={
            'source': 'synthetic user confirmed this exact resume and direction',
            'align_scope': True,
            'updates': {'direction': {'status': '已确认', 'primary': ['设备应用'], 'parallel': [], 'deferred': [],
                                      'reason': 'fixture only'},
                        'materials': [{'path': '内容线/简历.md', 'label': '当前简历', 'status': '可投',
                                       'reviewed_sha256': h, 'note': 'synthetic explicit confirmation'}],
                        'next_actions': ['准备设备岗位面试']}})
        view = self.repo / 'memory/CURRENT_STATE.md'
        self.assertIn('设备应用', view.read_text(encoding='utf-8'))
        self.assertEqual(self.run_cli('workspace.py', 'status')['materials'][0]['effective_status'], '可投')
        resume.write_text('Synthetic resume v2 - not reviewed', encoding='utf-8')
        self.assertIn('需重新审阅', self.run_cli('workspace.py', 'status')['materials'][0]['effective_status'])
        scope = self.repo / '.local/config/当前检索范围.json'
        d=self.load(scope);d['id']='changed-scope';scope.write_text(json.dumps(d),encoding='utf-8')
        self.run_cli('onboard.py', 'apply', '--json', '-', payload={
            'source':'synthetic new preference','updates':{'career_preferences':{'preferred_regions':['不限']}}})
        text=view.read_text(encoding='utf-8')
        self.assertIn('检索配置已改变', text)
        self.assertIn('个人条件已更新', text)
        self.assertIn('内容已变化', text)
        self.assertIn('准备设备岗位面试', text)
        self.run_cli('setup.py')
        self.assertEqual(view.read_text(encoding='utf-8'),text)

    def test_intake_and_training_refresh_view_without_network_or_reimport(self):
        self.run_cli('setup.py')
        self.run_cli('interview_drill.py','add','--json','-',payload={
            'qid':'Q1','date':'2026-01-01','source':'模拟','company':'fixture',
            'question':'fixture question','answer_status':'不会'})
        view=(self.repo/'memory/CURRENT_STATE.md').read_text(encoding='utf-8')
        self.assertIn('已记录 1 次作答',view)
        status=self.run_cli('workspace.py','status')
        self.assertEqual(status['ledger']['receipt_events'],0)
        # An existing hand-written memory cannot be erased by a refresh.
        p=self.repo/'memory/CURRENT_STATE.md';p.write_text('Unmigrated unique context',encoding='utf-8')
        self.run_cli('workspace.py','refresh',success=False)
        self.assertEqual(p.read_text(encoding='utf-8'),'Unmigrated unique context')
        self.run_cli('setup.py')
        self.assertEqual(p.read_text(encoding='utf-8'),'Unmigrated unique context')

    def test_material_paths_and_current_status_updates_are_bounded(self):
        self.run_cli('setup.py')
        path=self.repo/'memory/workspace.json'
        before=path.read_bytes()
        for update in [
            {'materials':[{'path':'../../another-user/resume.md'}]},
            {'materials':[{'path':'内容线/简历.md','status':'可投'}]},
            {'applications':[{'stage':'submitted'}]}]:
            self.run_cli('workspace.py','close','--json','-',success=False,
                         payload={'source':'fixture','updates':update})
            self.assertEqual(path.read_bytes(),before)
