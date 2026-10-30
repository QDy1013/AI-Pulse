"""Read local records without retaining prompts, responses, or credentials."""
from __future__ import annotations
import json
import os
import re
import math
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from .antigravity import read_database, transcript_path

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

def optional_usd(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (ValueError, TypeError):
        return None

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
    cache_write: int = 0
    cost_usd: float | None = None

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
    }, 'imports': {app: [] for app in APPS}, 'interval': 3,
       'antigravity_models': {}, 'usd_to_cny': 7.15, 'model_rates': {}}

def antigravity_model(number, aliases, detected=''):
    """Resolve Antigravity's placeholder enum (e.g. 1401 = MODEL_PLACEHOLDER_M401)
    using user aliases first, then names extracted from companion transcript logs."""
    if not number and not detected: return ''
    return aliases.get(str(number)) or detected or f'未命名模型 #{number}'

def usage_request(app, key, timestamp, usage, model='', seconds=None, timing='unavailable',
                  cache_write=0, cost_usd=None):
    return Request(str(key), app, stamp(timestamp), str(model)[:160],
                   int(number(usage.get('input_tokens'))), int(number(usage.get('output_tokens'))),
                   int(number(usage.get('reasoning_output_tokens'))),
                   int(number(usage.get('cached_input_tokens'))), seconds, timing,
                   int(number(cache_write)), cost_usd)

def consume(app, d, state, generic=False):
    """Normalize known schemas. Duplicate snapshots replace the same request."""
    c, out = state.context, state.requests
    if generic:
        if d.get('schema') != 'ai-pulse/v1' or not d.get('id') or not stamp(d.get('timestamp')):
            return
        seconds = number(d.get('duration_ms')) / 1000 or None
        u = d.get('usage') or {}
        r = usage_request(app, d['id'], d['timestamp'], u, d.get('model', ''), seconds,
                          'reported' if seconds else 'unavailable',
                          u.get('cache_write_input_tokens', 0), optional_usd(d.get('cost_usd')))
        out[r.key] = r
        return
    t = d.get('type')
    p = d.get('payload') or {}
    ts = d.get('timestamp')
    if app == 'Codex':
        if t == 'session_meta' and not c.get('start'):
            c['start'] = stamp(p.get('timestamp') or ts)
        if t == 'turn_context': c['model'] = p.get('model', '')
        if t == 'event_msg' and p.get('type') in ('task_started', 'turn_started'):
            c['start'] = stamp(p.get('started_at') or ts)
            c['turn'] = p.get('turn_id', str(ts))
        if t == 'response_item' and (p.get('type') in ('function_call_output', 'custom_tool_call_output') or p.get('role') == 'user'):
            c['start'] = max(c.get('start', 0), stamp(ts))
        if t == 'token_usage_record':
            c['modern'] = True
            # Remove compatibility token_count rows if a modern record follows them.
            out.pop('legacy:' + str(ts), None)
            u = p.get('usage') or {}
            start = c.get('start', 0)
            seconds = stamp(ts) - start if start else 0
            key = p.get('response_id') or ('record:' + str(d.get('ordinal', ts)))
            r = usage_request(app, key, ts, u, c.get('model', ''), seconds if seconds > 0 else None,
                              'turn_elapsed_estimate' if seconds > 0 else 'unavailable',
                              u.get('cache_write_input_tokens', 0))
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
            r = usage_request(app, 'legacy:' + str(ts), ts, delta, c.get('model', ''),
                              cache_write=delta.get('cache_write_input_tokens', 0))
            out[r.key] = r
    elif app == 'Claude':
        if t == 'user' or t == 'api-request': c['start'] = stamp(ts)
        if t != 'assistant': return
        m = d.get('message') or {}
        u = m.get('usage')
        if not isinstance(u, dict) or not m.get('id'): return
        # Claude input excludes cache read/write; normalize to inclusive input.
        raw_cw = int(number(u.get('cache_creation_input_tokens')))
        u = dict(u)
        u['input_tokens'] = sum(number(u.get(k)) for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
        u['cached_input_tokens'] = u.get('cache_read_input_tokens', 0)
        u['reasoning_output_tokens'] = (u.get('output_tokens_details') or {}).get('thinking_tokens', 0)
        if m.get('model') == '<synthetic>' and not u['input_tokens'] and not number(u.get('output_tokens')):
            return
        key = m['id']
        # Pin request start when message.id first appears so mid-stream tool_result ('user')
        # events cannot overwrite the start time of later blocks in the same response.
        start = c.setdefault('starts', {}).setdefault(key, c.get('start', 0))
        old = out.get(key)
        if old and old.output > number(u.get('output_tokens')): return
        seconds = stamp(ts) - start if start else 0
        r = usage_request(app, key, ts, u, m.get('model', ''), seconds if seconds > 0 else None,
                          'turn_elapsed_estimate' if seconds > 0 else 'unavailable', raw_cw)
        out[r.key] = r
    elif app == 'WorkBuddy':
        pd = d.get('providerData') or {}
        now = stamp(ts)
        raw_id = pd.get('messageId') or (d.get('id') if isinstance(pd.get('usage'), dict) else None)
        if raw_id:
            key = str(d.get('sessionId', '')) + ':' + str(raw_id)
            c.setdefault('starts', {}).setdefault(key, c.get('start', 0))
        if (t == 'message' and d.get('role') == 'user') or t == 'function_call_result':
            if now > 0: c['start'] = now
        usage = pd.get('usage')
        if not isinstance(usage, dict) or not raw_id: return
        inp_details = usage.get('inputTokensDetails') or []
        out_details = usage.get('outputTokensDetails') or []
        u = {'input_tokens': usage.get('inputTokens'), 'output_tokens': usage.get('outputTokens'),
             'cached_input_tokens': sum(number(x.get('cached_tokens')) for x in inp_details if isinstance(x, dict)),
             'reasoning_output_tokens': sum(number(x.get('reasoning_tokens')) for x in out_details if isinstance(x, dict))}
        old = out.get(key)
        if old and old.output > number(u['output_tokens']): return
        start = c.get('starts', {}).get(key, 0)
        seconds = now - start if start and now > start else 0
        out[key] = usage_request(app, key, ts, u, pd.get('model') or pd.get('requestModelName', ''),
                                 seconds if seconds > 0 else None,
                                 'turn_elapsed_estimate' if seconds > 0 else 'unavailable')
        if now > c.get('start', 0): c['start'] = now
    elif app == 'Reasonix':
        if 'completion' not in d or 'ts' not in d: return
        prompt = d['prompt'] if 'prompt' in d else (number(d.get('cache_hit')) + number(d.get('cache_miss')))
        u = {'input_tokens': prompt, 'output_tokens': d.get('completion'),
             'reasoning_output_tokens': d.get('reasoning'), 'cached_input_tokens': d.get('cache_hit')}
        model = re.sub(r'^[^/]*-[0-9a-f]{16,}/', '', str(d.get('model') or ''))
        raw_cost = d.get('valuation_usd') if d.get('valuation_usd') is not None else (
            d.get('cost_amount') if d.get('cost_currency') == 'USD' else None)
        parsed_cost = optional_usd(raw_cost) if d.get('cost_complete', True) is not False else None
        cost_usd = parsed_cost if (parsed_cost and parsed_cost > 0) else None
        key = str(d.get('id') or (str(d['ts']) + ':' + str(d.get('model', '')) + ':' + str(d.get('source', '')) + ':' + str(state.offset)))
        out[key] = usage_request(app, key, d['ts'], u, model, cost_usd=cost_usd)

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
                state = self.files.setdefault(key, FileState())
                try:
                    st = path.stat()
                    if generic == 'sqlite':
                        wal = Path(str(path) + '-wal')
                        walstat = wal.stat() if wal.exists() else None
                        tr = transcript_path(path)
                        trstat = tr.stat() if tr.exists() else None
                        dbsig = (st.st_mtime_ns, st.st_size,
                                 walstat.st_mtime_ns if walstat else 0, walstat.st_size if walstat else 0,
                                 trstat.st_mtime_ns if trstat else 0, trstat.st_size if trstat else 0)
                        if state.context.get('dbsig') != dbsig:
                            new_rows = {}
                            aliases = self.config.get('antigravity_models') or {}
                            learned = self.files.setdefault(('antigravity_names',), {})
                            for d in read_database(path):
                                if d.get('model') and d.get('model_name'):
                                    learned[str(d['model'])] = d['model_name']
                                detected = d.get('model_name') or learned.get(str(d.get('model')), '')
                                r = usage_request(app, d['id'], d['timestamp'], d,
                                                  antigravity_model(d['model'], aliases, detected),
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
                                    # Each line is read only once; keep the count so it persists across scans.
                                    state.context['_errors'] = state.context.get('_errors', 0) + 1
                    state.context['_mtime'] = st.st_mtime_ns
                    latest = max(latest, st.st_mtime)
                    errors += state.context.get('_errors', 0)
                    rows.extend(state.requests.values())
                except (OSError, sqlite3.Error):
                    # Busy/locked file (Windows share locks, active SQLite writer): keep the
                    # last known rows so totals do not flicker down for one refresh.
                    errors += 1
                    rows.extend(self.files[key].requests.values())
            # Same response can appear in copied Claude session logs: count it once.
            unique = {}
            for r in rows:
                if r.key not in unique or r.output >= unique[r.key].output: unique[r.key] = r
            rows = sorted(unique.values(), key=lambda r: r.timestamp)
            if rows: status = '已接入 · 本地用量记录'
            elif existing and app == 'Antigravity': status = '检测到会话 · 尚无可读取的用量记录'
            elif existing: status = '已找到目录 · 等待用量记录'
            else: status = '未找到数据 · 可设置路径或导入'
            result[app] = {'status': status, 'requests': rows, 'files': len(paths),
                           'latest': latest, 'errors': errors, 'detected': bool(existing)}
        self.files = {k: v for k, v in self.files.items() if k in live_keys or k == ('antigravity_names',)}
        return result
