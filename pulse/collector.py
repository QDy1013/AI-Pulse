"""Read local records without retaining prompts, responses, or credentials."""
from __future__ import annotations
import json
import os
import math
import time
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from .antigravity import read_database

APPS = ('Codex', 'Claude', 'Reasonix', 'Antigravity', 'WorkBuddy')

def stamp(value):
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 100_000_000_000 else value
            if not math.isfinite(seconds): return 0.0
            datetime.fromtimestamp(seconds)
            return float(seconds)
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return 0.0

def number(value):
    try:
        n = float(value or 0)
        return n if math.isfinite(n) and n >= 0 else 0
    except (ValueError, TypeError):
        return 0

@dataclass
class Request:
    key: str
    app: str
    timestamp: float
    model: str = ''
    input: int = 0
    output: int = 0
    reasoning: int = 0
    cached: int = 0
    seconds: float | None = None
    timing: str = 'unavailable'

    @property
    def speed(self):
        return self.output / self.seconds if self.seconds and self.seconds > 0 else None

    def public(self):
        d = asdict(self)
        d.pop('key')
        d['speed'] = self.speed
        return d

@dataclass
class FileState:
    offset: int = 0
    context: dict = field(default_factory=dict)
    requests: dict[str, Request] = field(default_factory=dict)
    signature: tuple = ()

def defaults():
    h = Path.home()
    a = Path(os.environ.get('APPDATA', str(h / '.config')))
    return {'roots': {
        'Codex': [str(h / '.codex/sessions')],
        'Claude': [str(h / '.claude/projects'), str(a / 'Claude/claude-code-sessions')],
        'Reasonix': [str(a / 'reasonix/stats')],
        'Antigravity': [str(h / '.gemini/antigravity/conversations')],
        'WorkBuddy': [str(h / '.workbuddy/projects')],
    }, 'imports': {app: [] for app in APPS}, 'interval': 3}

def usage_request(app, key, timestamp, usage, model='', seconds=None, timing='unavailable'):
    return Request(str(key), app, stamp(timestamp), str(model)[:160],
                   int(number(usage.get('input_tokens'))), int(number(usage.get('output_tokens'))),
                   int(number(usage.get('reasoning_output_tokens'))),
                   int(number(usage.get('cached_input_tokens'))), seconds, timing)

def consume(app, d, state, generic=False):
    """Normalize known schemas. Duplicate snapshots replace the same request."""
    c, out = state.context, state.requests
    if generic:
        if d.get('schema') != 'ai-pulse/v1' or not d.get('id') or not stamp(d.get('timestamp')):
            return
        seconds = number(d.get('duration_ms')) / 1000 or None
        r = usage_request(app, d['id'], d['timestamp'], d.get('usage', {}), d.get('model', ''), seconds,
                          'reported' if seconds else 'unavailable')
        out[r.key] = r
        return
    t = d.get('type')
    p = d.get('payload') or {}
    ts = d.get('timestamp')
    if app == 'Codex':
        if t == 'turn_context': c['model'] = p.get('model', '')
        if t == 'event_msg' and p.get('type') in ('task_started', 'turn_started'):
            c['start'] = stamp(p.get('started_at') or ts)
            c['turn'] = p.get('turn_id', str(ts))
        if t == 'token_usage_record':
            c['modern'] = True
            # Remove compatibility token_count rows if a modern record follows them.
            out.pop('legacy:' + str(ts), None)
            u = p.get('usage') or {}
            start = c.get('start', 0)
            seconds = stamp(ts) - start if start else 0
            key = p.get('response_id') or ('record:' + str(d.get('ordinal', ts)))
            r = usage_request(app, key, ts, u, c.get('model', ''), seconds if seconds > 0 else None,
                              'turn_elapsed_estimate' if seconds > 0 else 'unavailable')
            out[r.key] = r
            # Next request elapsed time starts after the previous response, includes tools/waiting.
            c['start'] = stamp(ts)
        elif t == 'event_msg' and p.get('type') == 'token_count' and not c.get('modern'):
            total = (p.get('info') or {}).get('total_token_usage')
            if not total: return
            prev = c.get('total', {})
            delta = {k: max(0, number(v) - number(prev.get(k))) for k, v in total.items()}
            c['total'] = total
            if not any(delta.values()): return
            r = usage_request(app, 'legacy:' + str(ts), ts, delta, c.get('model', ''))
            out[r.key] = r
    elif app == 'Claude':
        if t == 'user' or t == 'api-request': c['start'] = stamp(ts)
        if t != 'assistant': return
        m = d.get('message') or {}
        u = m.get('usage')
        if not isinstance(u, dict) or not m.get('id'): return
        # Claude input excludes cache read/write; normalize to inclusive input.
        u = dict(u)
        u['input_tokens'] = sum(number(u.get(k)) for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
        u['cached_input_tokens'] = u.get('cache_read_input_tokens', 0)
        u['reasoning_output_tokens'] = (u.get('output_tokens_details') or {}).get('thinking_tokens', 0)
        key = m['id']
        old = out.get(key)
        if old and old.output > number(u.get('output_tokens')): return
        seconds = stamp(ts) - c.get('start', 0) if c.get('start') else 0
        r = usage_request(app, key, ts, u, m.get('model', ''), seconds if seconds > 0 else None,
                          'turn_elapsed_estimate' if seconds > 0 else 'unavailable')
        out[r.key] = r
    elif app == 'WorkBuddy':
        pd = d.get('providerData') or {}
        usage = pd.get('usage')
        if not isinstance(usage, dict): return
        key = pd.get('messageId') or d.get('id')
        if not key: return
        key = str(d.get('sessionId', '')) + ':' + str(key)
        inp_details = usage.get('inputTokensDetails') or []
        out_details = usage.get('outputTokensDetails') or []
        u = {'input_tokens': usage.get('inputTokens'), 'output_tokens': usage.get('outputTokens'),
             'cached_input_tokens': sum(number(x.get('cached_tokens')) for x in inp_details if isinstance(x, dict)),
             'reasoning_output_tokens': sum(number(x.get('reasoning_tokens')) for x in out_details if isinstance(x, dict))}
        old = out.get(key)
        if old and old.output > number(u['output_tokens']): return
        out[key] = usage_request(app, key, ts, u, pd.get('model') or pd.get('requestModelName', ''))
    elif app == 'Reasonix':
        if 'completion' not in d or 'ts' not in d: return
        u = {'input_tokens': d.get('prompt'), 'output_tokens': d.get('completion'),
             'reasoning_output_tokens': d.get('reasoning'), 'cached_input_tokens': d.get('cache_hit')}
        key = str(d.get('id') or (str(d['ts']) + ':' + str(d.get('model', '')) + ':' + str(d.get('source', '')) + ':' + str(state.offset)))
        out[key] = usage_request(app, key, d['ts'], u, d.get('model', ''))

class Collector:
    def __init__(self, config=None):
        self.config = config or defaults()
        self.files = {}

    def scan(self):
        result, live_keys = {}, set()
        for app in APPS:
            paths, existing, errors = {}, 0, 0
            roots = self.config.get('roots', {}).get(app, [])
            for root in roots:
                p = Path(root).expanduser()
                if not p.exists(): continue
                existing += 1
                # Only documented usage sources; do not sweep caches/config/credentials.
                if app in ('Codex', 'Claude', 'Reasonix', 'WorkBuddy'):
                    for f in p.rglob('*.jsonl'):
                        paths[f] = False
                elif app == 'Antigravity':
                    for f in p.glob('*.db'):
                        paths[f] = 'sqlite'
            for raw in self.config.get('imports', {}).get(app, []):
                p = Path(raw).expanduser()
                if p.is_file(): paths[p] = True
            rows, latest = [], 0
            for path, generic in paths.items():
                key = (app, str(path), generic)
                live_keys.add(key)
                try:
                    st = path.stat()
                    state = self.files.setdefault(key, FileState())
                    if generic == 'sqlite':
                        wal = Path(str(path) + '-wal')
                        walstat = wal.stat() if wal.exists() else None
                        dbsig = (st.st_mtime_ns, st.st_size, walstat.st_mtime_ns if walstat else 0, walstat.st_size if walstat else 0)
                        if state.context.get('dbsig') != dbsig:
                            new_rows = {}
                            for d in read_database(path):
                                r = usage_request(app, d['id'], d['timestamp'], d, '模型编号 ' + str(d['model']),
                                                  d['seconds'], 'step_elapsed_estimate' if d['seconds'] else 'unavailable')
                                new_rows[r.key] = r
                            state.requests = new_rows
                            state.context['dbsig'] = dbsig
                        rows.extend(state.requests.values())
                        latest = max(latest, st.st_mtime, walstat.st_mtime if walstat else 0)
                        continue
                    sig = (st.st_dev, st.st_ino)
                    if st.st_size < state.offset or (state.signature and state.signature != sig) or (st.st_size == state.offset and state.context.get('_mtime', st.st_mtime_ns) != st.st_mtime_ns):
                        state = self.files[key] = FileState()
                    state.signature = sig
                    if st.st_size != state.offset:
                        with path.open('rb') as f:
                            f.seek(state.offset)
                            while True:
                                line = f.readline()
                                if not line or not line.endswith(b'\n'): break
                                state.offset = f.tell()
                                try:
                                    d = json.loads(line)
                                    if isinstance(d, dict): consume(app, d, state, generic)
                                except (ValueError, TypeError, AttributeError, KeyError):
                                    errors += 1
                    state.context['_mtime'] = st.st_mtime_ns
                    latest = max(latest, st.st_mtime)
                    rows.extend(state.requests.values())
                except (OSError, sqlite3.Error):
                    errors += 1
            # Same response can appear in copied Claude session logs: count it once.
            unique = {}
            for r in rows:
                if r.key not in unique or r.output >= unique[r.key].output: unique[r.key] = r
            rows = sorted(unique.values(), key=lambda r: r.timestamp)
            if rows: status = '已接入 · 本地用量记录'
            elif existing and app == 'Antigravity': status = '检测到会话 · 尚无可读取的用量记录'
            elif existing and app == 'WorkBuddy': status = '检测到目录 · 请导入标准用量记录'
            elif existing: status = '已找到目录 · 等待用量记录'
            else: status = '未找到数据 · 可设置路径或导入'
            result[app] = {'status': status, 'requests': rows, 'files': len(paths),
                           'latest': latest, 'errors': errors, 'detected': bool(existing)}
        self.files = {k: v for k, v in self.files.items() if k in live_keys}
        return result
