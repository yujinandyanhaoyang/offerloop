import tempfile
import unittest
from pathlib import Path
from execution import prepare, registry, read, ROOT


class ExecutionTests(unittest.TestCase):
    def test_input_source_overrides_legacy_example(self):
        mapping = {'fields': {'name': {'source_field': 'name', 'selector': '#name', 'fill_type': 'text', 'value': 'wrong'}}}
        result = prepare('test', {'name': 'actual'}, mapping, Path('.'))
        self.assertEqual(result['steps'][0]['value'], 'actual')

    def test_file_is_hashed_and_missing_file_is_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'resume.pdf').write_bytes(b'fixture')
            mapping = {'fields': {'resume': {'source_field': 'resume_pdf', 'selector': '#file', 'fill_type': 'file_upload', 'accept': ['.pdf']}}}
            result = prepare('test', {'resume_pdf': 'resume.pdf'}, mapping, root)
            self.assertEqual(len(result['steps'][0]['sha256']), 64)
            result = prepare('test', {'resume_pdf': 'missing.pdf'}, mapping, root)
            self.assertEqual(result['steps'][0]['reason'], 'file_missing')

    def test_no_submission_or_login_overwrite_in_fill(self):
        mapping = {'fields': {'submit': {'fill_type': 'submit'}, 'phone': {'fill_type': 'follow_login'}}}
        steps = prepare('test', {}, mapping, Path('.'))['steps']
        self.assertEqual([s['status'] for s in steps], ['separate_submission', 'observe_only'])
        self.assertTrue(all('value' not in s for s in steps))

    def test_unverified_portfolio_and_repeated_work_mapping_blocked(self):
        mapping = read(ROOT / 'field_mapping.json')['meituan']
        steps = {s['field']: s for s in prepare('meituan', {}, mapping, Path('.'))['steps']}
        self.assertEqual(steps['portfolio']['status'], 'blocked')
        self.assertEqual(steps['work_type']['status'], 'blocked')

    def test_routes_do_not_claim_logged_in(self):
        routes = registry()
        self.assertEqual(set(routes), {'boss', 'zhaopin', 'nowcoder', 'meituan'})
        self.assertTrue(all(r['authentication'] == 'not_checked' for r in routes.values()))


if __name__ == '__main__':
    unittest.main()
