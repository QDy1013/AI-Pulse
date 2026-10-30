import sys
import unittest
from datetime import datetime
from pulse import autostart
from pulse.collector import APPS, Request
from pulse.insights import alerts, budget, history, project_name, projects, quota
from pulse.pricing import estimate_usd

NOW = datetime(2026, 10, 30, 15, 0).timestamp()
DAY = 86400

def data():
    d = {a: {'requests': [], 'errors': 0, 'status': 'x', 'limits': None} for a in APPS}
    # Sorted by time, as Collector.scan returns them.
    d['Claude']['requests'] = [
        Request('c2', 'Claude', NOW - 2 * DAY, 'claude-sonnet-4-5', input=1_000_000, output=10, project='/srv/beta/'),
        Request('c1', 'Claude', NOW - 60, 'claude-sonnet-4-5', input=1_000_000, output=100_000, project='C:\\code\\alpha'),
    ]
    d['Codex']['requests'] = [Request('x1', 'Codex', NOW - 120, 'gpt-5.5', output=50_000, project='C:\\code\\alpha')]
    d['Codex']['limits'] = {'t': NOW - 600, 'plan': 'plus', 'windows': [
        {'minutes': 300, 'used': 93.0, 'resets_at': NOW + 3600},
        {'minutes': 10080, 'used': 40.0, 'resets_at': NOW - 1}]}
    return d

class InsightTests(unittest.TestCase):
    def test_quota_windows_and_expired_reset(self):
        q = quota(data(), NOW)
        self.assertEqual([x['name'] for x in q], ['Codex 5 小时', 'Codex 每周'])
        self.assertEqual((q[0]['left'], q[0]['resets_at']), (7.0, NOW + 3600))
        # Reset time passed since the last snapshot: the window is available again.
        self.assertEqual((q[1]['used'], q[1]['left'], q[1]['resets_at']), (0.0, 100.0, 0.0))
        self.assertEqual(quota({}, NOW), [])

    def test_budget_and_once_per_window_alerts(self):
        d = data()
        today = sum(estimate_usd(r, None)[0] for r in d['Claude']['requests'][1:] + d['Codex']['requests'])
        b = budget(d, {'daily_cny': today * 7 / 2, 'monthly_cny': 0}, None, 7.0, NOW)
        self.assertEqual(len(b), 1)
        self.assertAlmostEqual(b[0]['spent'], today * 7)
        self.assertAlmostEqual(b[0]['pct'], 200)
        keys = [k for k, _, _ in alerts(quota(d, NOW), b)]
        self.assertEqual(keys, ['daily_cny:2026-10-30:over', f'quota:300:{NOW + 3600:.0f}'])
        self.assertEqual(budget(d, {}, None, 7.0, NOW), [])

    def test_history_buckets_by_local_day(self):
        days = history(data(), APPS, None, NOW, days=3)
        self.assertEqual([x['date'] for x in days], ['2026-10-28', '2026-10-29', '2026-10-30'])
        self.assertEqual([x['count'] for x in days], [1, 0, 2])
        self.assertEqual(set(days[2]['apps']), {'Claude', 'Codex'})
        self.assertEqual(history(data(), ['Codex'], None, NOW, days=3)[2]['output'], 50_000)

    def test_projects_group_by_directory(self):
        rows = [r for a in APPS for r in data()[a]['requests']] + [Request('r', 'Reasonix', NOW, 'm', output=1)]
        groups = projects(rows)
        self.assertEqual([(g['name'], g['output'], g['count']) for g in groups],
                         [('alpha', 150_000, 2), ('beta', 10, 1), ('未记录目录', 1, 1)])
        self.assertEqual(project_name('C:\\Users\\me\\'), 'me')

    def test_cost_memo_follows_the_rates_object(self):
        r = Request('m', 'Claude', NOW, 'claude-sonnet-4-5', input=1_000_000, output=1_000_000)
        default = estimate_usd(r, None)[0]
        self.assertEqual(estimate_usd(r, None)[0], default)
        custom = {'sonnet': [1.0, 0.1, 1.0]}
        self.assertAlmostEqual(estimate_usd(r, custom)[0], 2.0)
        # Saving settings installs a new dict; the memo must not leak across it.
        self.assertAlmostEqual(estimate_usd(r, {'sonnet': [2.0, 0.1, 2.0]})[0], 4.0)
        self.assertEqual(estimate_usd(r, None)[0], default)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows registry')
    def test_autostart_round_trip_on_scratch_key(self):
        import winreg
        key = r'Software\AI-Pulse-Test\Run'
        try:
            self.assertFalse(autostart.enabled(key))
            autostart.set_enabled(True, key)
            self.assertTrue(autostart.enabled(key))
            self.assertTrue(autostart.command().endswith(autostart.MINIMIZED))
            autostart.set_enabled(False, key)
            self.assertFalse(autostart.enabled(key))
        finally:
            for k in (key, r'Software\AI-Pulse-Test'):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k)
                except OSError:
                    pass

if __name__ == '__main__': unittest.main()
