import json
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request as HttpRequest, urlopen
from pulse.collector import APPS, Request
from pulse.remote import QUICK_URL, RemoteService, summary

def sample():
    now = time.time()
    data = {a: {'requests': [], 'errors': 0, 'status': 'x'} for a in APPS}
    data['Claude']['requests'] = [
        Request('c1', 'Claude', now - 60, 'claude-sonnet-4-5', input=1000, output=100, cached=400, seconds=4),
        Request('c2', 'Claude', now - 30, 'claude-haiku-4-5', input=500, output=50),
    ]
    data['Codex']['requests'] = [Request('x1', 'Codex', now - 10 * 86400, 'gpt-5.5', output=999, seconds=9)]
    return data

class SummaryTests(unittest.TestCase):
    def test_period_and_app_filters(self):
        d = summary(sample(), 'all', 'today')
        self.assertEqual((d['count'], d['output'], d['input'], d['cached']), (2, 150, 1500, 400))
        self.assertEqual(d['recent_speed'], 25)
        self.assertEqual([r['model'] for r in d['recent']], ['claude-haiku-4-5', 'claude-sonnet-4-5'])
        self.assertEqual({s['app']: s['output'] for s in d['split']}['Claude'], 150)
        self.assertEqual(summary(sample(), 'all', 'all')['output'], 1149)
        models = summary(sample(), 'Claude', 'all')['split']
        self.assertEqual([m['name'] for m in models], ['claude-sonnet-4-5', 'claude-haiku-4-5'])
        self.assertAlmostEqual(d['cny'], d['usd'] * d['fx'])

    def test_limits_history_and_projects(self):
        data = sample()
        data['Claude']['requests'][0].project = 'C:\\Users\\me\\secret\\alpha'
        data['Codex']['limits'] = {'t': time.time(), 'plan': '', 'windows': [
            {'minutes': 300, 'used': 20.0, 'resets_at': time.time() + 600}]}
        d = summary(data, 'all', 'today', budget={'daily_cny': 1000})
        self.assertEqual(d['quota'][0]['left'], 80.0)
        self.assertEqual(d['budget'][0]['name'], '今日预算')
        self.assertEqual(len(d['daily']), 30)
        self.assertEqual(d['daily'][-1]['count'], 2)
        self.assertEqual(sum(x['count'] for x in summary(data, 'Claude', 'today')['daily']), 2)
        self.assertEqual(d['projects'][0]['name'], 'alpha')
        # Only folder names are served to the phone, never full local paths.
        self.assertNotIn('secret', json.dumps(d['projects']))

    def test_quick_tunnel_url_detection(self):
        line = '2026-10-30T06:00:00Z INF |  https://brave-lion-fox.trycloudflare.com  |'
        self.assertEqual(QUICK_URL.search(line).group(0), 'https://brave-lion-fox.trycloudflare.com')

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.service = RemoteService()
        self.service.apply({'enabled': True, 'tunnel': False, 'port': 0, 'token': 'secret-key'})
        self.service.set_data(sample())
        self.base = f'http://127.0.0.1:{self.service.port}'

    def tearDown(self):
        self.service.stop()

    def get(self, path, headers=None):
        try:
            with urlopen(HttpRequest(self.base + path, headers=headers or {}), timeout=5) as r:
                return r.status, r.read().decode('utf-8'), r.headers
        except HTTPError as e:
            return e.code, e.read().decode('utf-8'), e.headers

    def test_requires_key(self):
        self.assertEqual(self.get('/')[0], 401)
        self.assertEqual(self.get('/api/summary')[0], 401)
        self.assertEqual(self.get('/?k=wrong')[0], 401)
        self.assertEqual(self.get('/api/summary', {'Authorization': 'Bearer wrong'})[0], 401)
        self.assertEqual(self.get('/settings.json')[0], 404)
        self.assertNotIn('secret-key', self.get('/manifest.webmanifest')[1])

    def test_page_and_api_with_key(self):
        status, body, headers = self.get('/?k=secret-key')
        self.assertEqual(status, 200)
        self.assertIn("var KEY = 'secret-key'", body)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertEqual(self.get('/', {'Cookie': 'pulse_key=secret-key'})[0], 200)
        status, body, _ = self.get('/api/summary?app=Claude&period=all', {'Authorization': 'Bearer secret-key'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['output'], 150)
        manifest = json.loads(self.get('/manifest.webmanifest', {'Cookie': 'pulse_key=secret-key'})[1])
        self.assertEqual(manifest['start_url'], '/?k=secret-key')

    def test_home_screen_icons_are_public_pngs(self):
        # iOS fetches the touch icon without the page's key, and ignores SVG icons.
        for path in ('/apple-touch-icon.png', '/icon-192.png', '/icon-512.png'):
            with urlopen(self.base + path, timeout=5) as r:
                self.assertEqual(r.headers['Content-Type'], 'image/png')
                self.assertEqual(r.read(8), b'\x89PNG\r\n\x1a\n')
        manifest = json.loads(self.get('/manifest.webmanifest')[1])
        self.assertIn('/icon-512.png', [i['src'] for i in manifest['icons']])
        self.assertIn('apple-touch-icon.png', self.get('/?k=secret-key')[1])

    def test_unchanged_summary_answers_304(self):
        auth = {'Authorization': 'Bearer secret-key'}
        status, body, headers = self.get('/api/summary?app=all&period=all', auth)
        etag = headers['ETag']
        self.assertEqual(status, 200)
        self.assertEqual(self.get('/api/summary?app=all&period=all', dict(auth, **{'If-None-Match': etag}))[0], 304)
        # Cloudflare may hand the client a weakened tag.
        self.assertEqual(self.get('/api/summary?app=all&period=all', dict(auth, **{'If-None-Match': 'W/' + etag}))[0], 304)
        # A different filter, or new data, is a different body.
        self.assertEqual(self.get('/api/summary?app=Claude&period=all', dict(auth, **{'If-None-Match': etag}))[0], 200)
        data = sample()
        data['Claude']['requests'].append(Request('c3', 'Claude', time.time(), 'claude-haiku-4-5', output=7))
        self.service.set_data(data)
        status, body, _ = self.get('/api/summary?app=all&period=all', dict(auth, **{'If-None-Match': etag}))
        self.assertEqual((status, json.loads(body)['output']), (200, 1156))

    def test_disable_stops_server(self):
        port = self.service.port
        self.service.apply({'enabled': False})
        self.assertFalse(self.service.running)
        with self.assertRaises(OSError):
            urlopen(f'http://127.0.0.1:{port}/', timeout=2)

if __name__ == '__main__': unittest.main()
