import _bootstrap  # noqa: F401
import unittest
from datetime import datetime, timezone
from browser_health import assess, parse_line, latch


class BrowserHealthTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 24, 12, 0, 30, tzinfo=timezone.utc)

    def event(self, second, text):
        return parse_line(f'2026-10-24T12:00:{second:02d}.000Z info {text}', second)

    def test_repeated_ready_blocks_even_temporary_conversation_alias(self):
        events = [self.event(s, 'browser sidebar dom-ready conversationId=client-new-thread:x url=https://www.zhipin.com/hangzhou/?token=secret') for s in [1, 5, 10]]
        r = assess(events, 'www.zhipin.com', 'ours', self.now)
        self.assertEqual(r['status'], 'blocked')
        self.assertNotIn('secret', str(r))
        self.assertNotIn('token', str(r))

    def test_errors_are_scoped_to_current_conversation(self):
        events = [self.event(s, 'No ChatGPT browser route is available conversationId=other') for s in [1, 2]]
        self.assertEqual(assess(events, 'www.zhipin.com', 'ours', self.now)['status'], 'no_recent_loop_detected')
        for e in events:
            e['conversation'] = 'ours'
        self.assertEqual(assess(events, 'www.zhipin.com', 'ours', self.now)['status'], 'blocked')

    def test_different_pages_and_old_errors_do_not_form_loop(self):
        events = [self.event(s, f'browser sidebar dom-ready conversationId=ours url=https://www.zhipin.com/page{s}') for s in [1, 5, 10]]
        events.append({'at': '2026-10-24T11:00:00+00:00', 'kind': 'interception_invalid', 'conversation': 'ours'})
        self.assertEqual(assess(events, 'www.zhipin.com', 'ours', self.now)['status'], 'no_recent_loop_detected')

    def test_interception_error_blocks_and_unrelated_lines_ignored(self):
        e = self.event(20, 'Invalid InterceptionId conversationId=ours')
        self.assertEqual(assess([e], 'www.zhipin.com', 'ours', self.now)['status'], 'blocked')
        self.assertIsNone(parse_line('not a log line', 1))
        self.assertIsNone(self.event(1, 'unrelated message'))

    def test_quiet_window_does_not_clear_incident_or_allow_another_retry(self):
        state = {'incidents': {}}
        failed = assess([self.event(20, 'Invalid InterceptionId conversationId=ours')], 'www.zhipin.com', 'ours', self.now)
        latch(failed, state, 'iab')
        quiet = assess([], 'www.zhipin.com', 'ours', self.now)
        self.assertEqual(latch(quiet, state, 'iab')['status'], 'blocked')
        # A different browser is not falsely called broken by an IAB-only incident.
        other = assess([], 'www.zhipin.com', 'ours', self.now)
        self.assertEqual(latch(other, state, 'chrome')['status'], 'no_recent_loop_detected')

    def test_user_report_can_latch_incident_without_logging_support(self):
        state = {'incidents': {}}
        quiet = assess([], 'www.zhipin.com', 'ours', self.now)
        r = latch(quiet, state, 'iab', 'user confirmed flicker recurred after login')
        self.assertEqual(r['status'], 'blocked')
        self.assertIn('persistent_incident', r['reasons'])

    def test_iab_route_failure_does_not_block_chrome(self):
        events = [self.event(s, '[browser-use-iab-api] No ChatGPT browser route is available conversationId=ours') for s in [1, 2]]
        self.assertEqual(assess(events, 'www.zhipin.com', 'ours', self.now, backend='chrome')['status'], 'no_recent_loop_detected')
        self.assertEqual(assess(events, 'www.zhipin.com', 'ours', self.now, backend='iab')['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
