"""Optional phone dashboard: token-protected HTTP server plus a Cloudflare tunnel.

Only statistics leave the process (token counts, model names, times, estimated
cost). Prompts and responses are never held by the collector, so they cannot be
served. Every data route requires the access token.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import insights
from .collector import APPS
from .pricing import DEFAULT_USD_TO_CNY, estimate_usd

COOKIE = 'pulse_key'
PAGE = Path(__file__).with_name('mobile.html')
PERIODS = {'today', '7d', 'all'}
TREND_LIMIT = 40
RECENT_LIMIT = 30
QUICK_URL = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')

ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
        '<rect x="6" y="6" width="116" height="116" rx="28" fill="#0f221b" stroke="#2a5242" stroke-width="3"/>'
        '<path d="M22 67H43L54 34L73 93L85 57H106" fill="none" stroke="#6fdcaa" stroke-width="7.5" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>')
MANIFEST = json.dumps({
    'name': 'AI Pulse', 'short_name': 'AI Pulse', 'start_url': '/', 'display': 'standalone',
    'background_color': '#0b0c0e', 'theme_color': '#0b0c0e',
    'icons': [{'src': '/icon.svg', 'sizes': 'any', 'type': 'image/svg+xml'}],
})


def new_token():
    return secrets.token_urlsafe(24)


def start_of_today(now):
    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def summary(data, app='all', period='today', rates=None, fx=DEFAULT_USD_TO_CNY, now=None, budget=None):
    """Aggregate scan results into the JSON the phone page renders."""
    now = now or time.time()
    cutoff = {'today': start_of_today(now), '7d': now - 7 * 86400}.get(period, 0)
    apps = [app] if app in APPS else list(APPS)
    rows = sorted((r for a in apps for r in data.get(a, {}).get('requests', []) if r.timestamp >= cutoff),
                  key=lambda r: r.timestamp)
    costs = [estimate_usd(r, rates) for r in rows]
    usd = sum(c[0] for c in costs)
    full = sum(c[1] for c in costs)
    timed = [r for r in rows if r.speed is not None]
    seconds = sum(r.seconds for r in timed)

    if app in APPS:
        groups = {}
        for r, (cost, _) in zip(rows, costs):
            g = groups.setdefault(r.model or '未记录', [0, 0.0])
            g[0] += r.output
            g[1] += cost
        split = [{'name': k, 'output': v[0], 'usd': v[1]}
                 for k, v in sorted(groups.items(), key=lambda kv: kv[1][0], reverse=True)[:8]]
    else:
        split = [{'name': a, 'app': a,
                  'output': sum(r.output for r in rows if r.app == a),
                  'usd': sum(c[0] for r, c in zip(rows, costs) if r.app == a)} for a in APPS]

    def item(r, cost):
        return {'t': r.timestamp, 'app': r.app, 'model': r.model, 'output': r.output, 'input': r.input,
                'reasoning': r.reasoning, 'cached': r.cached, 'speed': r.speed, 'usd': cost}

    pairs = list(zip(rows, costs))
    return {
        'updated': now, 'app': app if app in APPS else 'all', 'period': period if period in PERIODS else 'all',
        'fx': fx, 'count': len(rows), 'timed': len(timed),
        'output': sum(r.output for r in rows), 'input': sum(r.input for r in rows),
        'reasoning': sum(r.reasoning for r in rows), 'cached': sum(r.cached for r in rows),
        'usd': usd, 'cny': usd * fx, 'saved_usd': max(0.0, full - usd),
        'recent_speed': timed[-1].speed if timed else None,
        'avg_speed': sum(r.output for r in timed) / seconds if seconds else None,
        'trend': [{'t': r.timestamp, 'speed': r.speed, 'app': r.app, 'model': r.model} for r in timed[-TREND_LIMIT:]],
        'split': split,
        'recent': [item(r, c[0]) for r, c in reversed(pairs[-RECENT_LIMIT:])],
        'sources': {a: {'status': d.get('status', ''), 'connected': bool(d.get('requests'))}
                    for a, d in data.items()},
        # Limits are global (all apps); history follows the app filter; projects follow both filters.
        'quota': insights.quota(data, now),
        'budget': insights.budget(data, budget, rates, fx, now),
        'daily': insights.history(data, apps, rates, now),
        # Only the folder name leaves the computer, not the full path.
        'projects': [{k: g[k] for k in ('name', 'output', 'usd', 'count')} for g in insights.projects(rows, rates)],
    }


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))  # No packet is sent for UDP connect.
            return s.getsockname()[0]
    except OSError:
        return ''


def find_cloudflared(configured=''):
    candidates = [configured] if configured else []
    found = shutil.which('cloudflared')
    if found:
        candidates.append(found)
    local = os.environ.get('LOCALAPPDATA', '')
    for base in (os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', '')):
        if base:
            candidates.append(str(Path(base) / 'cloudflared/cloudflared.exe'))
    if local:
        candidates.append(str(Path(local) / 'Microsoft/WinGet/Links/cloudflared.exe'))
    candidates.append(str(Path(sys.executable).with_name('cloudflared.exe')))
    return next((c for c in candidates if c and Path(c).is_file()), '')


class Handler(BaseHTTPRequestHandler):
    server_version = 'AIPulse'
    sys_version = ''

    def log_message(self, *args):
        pass

    def authorized(self, query):
        token = self.server.owner.token
        cookie = ''
        for part in (self.headers.get('Cookie') or '').split(';'):
            name, _, value = part.strip().partition('=')
            if name == COOKIE:
                cookie = value
        supplied = [cookie, (query.get('k') or [''])[0],
                    (self.headers.get('Authorization') or '').removeprefix('Bearer ').strip()]
        return bool(token) and any(s and hmac.compare_digest(s.encode(), token.encode()) for s in supplied)

    def send(self, status, body, ctype, extra=None):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; manifest-src 'self'; frame-ancestors 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == '/icon.svg':
            return self.send(200, ICON, 'image/svg+xml')
        token = self.server.owner.token
        if url.path == '/manifest.webmanifest':
            # Home-screen apps (notably iOS) keep a separate cookie jar, so an authorized
            # manifest launches with the key in the start URL.
            manifest = json.loads(MANIFEST)
            if self.authorized(query):
                manifest['start_url'] = f'/?k={token}'
            return self.send(200, json.dumps(manifest), 'application/manifest+json')
        if url.path not in ('/', '/api/summary'):
            return self.send(404, 'Not found', 'text/plain; charset=utf-8')
        if not self.authorized(query):
            if url.path == '/':
                return self.send(401, LOCKED, 'text/html; charset=utf-8')
            return self.send(401, '{"error":"unauthorized"}', 'application/json')
        if url.path == '/':
            try:
                page = PAGE.read_text(encoding='utf-8').replace('__PULSE_KEY__', token)
            except OSError:
                return self.send(500, 'Page missing', 'text/plain; charset=utf-8')
            https = 'https' in (self.headers.get('X-Forwarded-Proto') or '') or \
                    'https' in (self.headers.get('Cf-Visitor') or '')
            cookie = f'{COOKIE}={token}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax'
            return self.send(200, page, 'text/html; charset=utf-8',
                             {'Set-Cookie': cookie + ('; Secure' if https else '')})
        app = (query.get('app') or ['all'])[0]
        period = (query.get('period') or ['today'])[0]
        body, etag = self.server.owner.summary_json(app, period)
        # Cloudflare weakens ETags when it compresses responses (W/"..."), so compare the opaque part.
        if (self.headers.get('If-None-Match') or '').removeprefix('W/') == etag:
            # Nothing changed since the phone's last render: no body, no re-render.
            return self.send(304, b'', 'application/json; charset=utf-8', {'ETag': etag})
        return self.send(200, body, 'application/json; charset=utf-8', {'ETag': etag})


LOCKED = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Pulse</title></head>
<body style="background:#0b0c0e;color:#eceef1;font-family:system-ui,sans-serif;padding:40px 20px;text-align:center">
<h2>需要访问密钥</h2><p style="color:#767c86">请在电脑上的 AI Pulse「手机查看」中重新扫码或复制链接。</p></body></html>'''


class Tunnel:
    """Run cloudflared and report the public URL. Restarts if the process exits."""

    def __init__(self, exe, port, on_change, tunnel_token='', public_url=''):
        self.exe, self.port, self.on_change = exe, port, on_change
        self.tunnel_token, self.public_url = tunnel_token, public_url.rstrip('/')
        self.url = ''
        self.error = ''
        self.proc = None
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def start(self):
        self.thread.start()

    def command(self):
        if self.tunnel_token:
            return [self.exe, 'tunnel', '--no-autoupdate', 'run']
        return [self.exe, 'tunnel', '--no-autoupdate', '--url', f'http://127.0.0.1:{self.port}']

    def set(self, url, error=''):
        self.url, self.error = url, error
        self.on_change()

    def loop(self):
        delay = 3
        while not self.stopped.is_set():
            env = dict(os.environ)
            if self.tunnel_token:
                env['TUNNEL_TOKEN'] = self.tunnel_token  # Keep the secret out of the command line.
            try:
                self.proc = subprocess.Popen(
                    self.command(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                    env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except OSError as e:
                self.set('', f'无法启动 cloudflared：{e}')
                return
            started = time.time()
            for raw in self.proc.stderr:
                line = raw.decode('utf-8', 'replace')
                if self.tunnel_token:
                    if 'Registered tunnel connection' in line and not self.url:
                        self.set(self.public_url)
                else:
                    m = QUICK_URL.search(line)
                    if m and m.group(0) != self.url:
                        self.set(m.group(0))
            self.proc.wait()
            if self.stopped.is_set():
                break
            self.set('', '外网通道已断开，正在重连…')
            delay = 3 if time.time() - started > 60 else min(delay * 2, 60)
            self.stopped.wait(delay)

    def stop(self):
        self.stopped.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class RemoteService:
    """Owns the HTTP server and tunnel; fed with scan results from the UI thread."""

    def __init__(self, on_change=lambda: None):
        self.on_change = on_change
        self.lock = threading.Lock()
        self.data, self.version = {}, 0
        self.rates, self.fx, self.budget = None, DEFAULT_USD_TO_CNY, {}
        self.cache = {}
        self.token = ''
        self.httpd = None
        self.tunnel = None
        self.port = 0
        self.lan = False
        self.error = ''

    # ---- data
    def set_data(self, data, rates=None, fx=DEFAULT_USD_TO_CNY, budget=None):
        with self.lock:
            self.data, self.rates, self.fx, self.budget = data, rates, fx, budget or {}
            self.version += 1
            self.cache = {}

    def summary(self, app, period):
        return json.loads(self.summary_json(app, period)[0])

    def summary_json(self, app, period):
        """(body, etag) for the phone API, cached per data version and 30-second window."""
        with self.lock:
            data, rates, fx, budget, version = self.data, self.rates, self.fx, self.budget, self.version
            window = (version, datetime.now().date(), int(time.time() // 30))
            hit = self.cache.get(window + (app, period))
        if hit is None:
            body = json.dumps(summary(data, app, period, rates, fx, budget=budget), ensure_ascii=False)
            hit = (body, '"' + hashlib.sha1(body.encode('utf-8')).hexdigest()[:20] + '"')
            with self.lock:
                if self.version == version:
                    # Only the current window is ever requested again.
                    self.cache = {k: v for k, v in self.cache.items() if k[:3] == window}
                    self.cache[window + (app, period)] = hit
        return hit

    # ---- lifecycle
    @property
    def running(self):
        return self.httpd is not None

    def apply(self, cfg):
        """Start, stop or restart according to the 'remote' config section."""
        self.stop()
        self.error = ''
        if not cfg.get('enabled') or not cfg.get('token'):
            self.on_change()
            return
        self.token = cfg['token']
        self.lan = bool(cfg.get('lan'))
        try:
            self.httpd = ThreadingHTTPServer(('0.0.0.0' if self.lan else '127.0.0.1', int(cfg.get('port') or 0)), Handler)
        except OSError as e:
            self.httpd = None
            self.error = f'端口 {cfg.get("port")} 无法使用：{e.strerror or e}'
            self.on_change()
            return
        self.httpd.daemon_threads = True
        self.httpd.owner = self
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        if cfg.get('tunnel'):
            exe = find_cloudflared(cfg.get('cloudflared', ''))
            if not exe:
                self.error = '未找到 cloudflared，外网访问不可用'
            elif cfg.get('tunnel_token') and not cfg.get('public_url'):
                self.error = '使用固定通道时需要填写外网地址'
            else:
                self.tunnel = Tunnel(exe, self.port, self.on_change,
                                     cfg.get('tunnel_token', ''), cfg.get('public_url', ''))
                self.tunnel.start()
        self.on_change()

    def stop(self):
        if self.tunnel:
            self.tunnel.stop()
            self.tunnel = None
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    # ---- addresses
    def local_url(self):
        if not self.running:
            return ''
        host = (lan_address() or '127.0.0.1') if self.lan else '127.0.0.1'
        return f'http://{host}:{self.port}/?k={self.token}'

    def public_url(self):
        if self.tunnel and self.tunnel.url:
            return f'{self.tunnel.url}/?k={self.token}'
        return ''

    def state(self):
        """(headline, detail) describing the current status for the UI."""
        if not self.running:
            return ('未开启', self.error)
        if self.tunnel:
            if self.tunnel.url:
                return ('外网可访问', '')
            return ('正在建立外网通道…', self.tunnel.error)
        return ('仅本机 / 局域网', self.error)
