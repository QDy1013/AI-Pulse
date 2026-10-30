"""Supplement Reasonix stats with committed v5 session work-duration records.

RX4F frames contain big-endian compressed/raw lengths and Zstandard JSON.
Payloads are base64 JSON. Only numeric timing/usage metadata is retained.
workDurationMs is cumulative within a turn, so it must be differenced inside
that turn, never across stats timestamps or across turn boundaries.
"""
from __future__ import annotations
import base64
import json
import math
import re
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import zstandard

ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
MAX_FRAME = 64 * 1024 * 1024

def model_name(value):
    return re.sub(r'^[^/]*-[0-9a-f]{16,}/', '', str(value or ''))

def positive(value):
    try:
        v = float(value)
        return v if math.isfinite(v) and v >= 0 else None
    except (TypeError, ValueError, OverflowError): return None

def id_time(value):
    """ULID's time portion is only a matching bound, never a duration source."""
    if not isinstance(value, str) or len(value) != 26: return None
    try:
        if any(c not in ALPHABET for c in value.upper()): return None
        milliseconds = 0
        for ch in value[:10].upper(): milliseconds = milliseconds * 32 + ALPHABET.index(ch)
        if not 946684800000 <= milliseconds < 4102444800000: return None
        return milliseconds / 1000
    except ValueError: return None

def metadata(event):
    kind = event.get('kind')
    if kind not in ('turn/start', 'message/complete', 'diagnostic/response'): return None
    # Large historical messages may live in an external payloadRef. Do not read
    # arbitrary blobs or bridge a cumulative duration across an unknown message.
    if 'payload' not in event:
        return ('gap', None, None) if kind == 'message/complete' else None
    payload = json.loads(base64.b64decode(event['payload'], validate=True))
    if kind == 'turn/start': return ('turn', event.get('seq'), None)
    if kind == 'message/complete':
        msg = payload.get('message') or {}
        if msg.get('role') != 'assistant' or not msg.get('id'): return None
        duration = positive(msg.get('workDurationMs'))
        return ('message', str(msg['id']), duration)
    response = payload.get('response') or {}
    usage = response.get('usage') or {}
    if usage.get('estimated') or usage.get('unknown') or not payload.get('messageId'): return None
    counts = [positive(usage.get(k)) for k in ('inputTokens', 'outputTokens', 'reasoningTokens')]
    if any(v is None for v in counts): return None
    return ('usage', str(payload['messageId']), (model_name(response.get('modelRef')), *map(int, counts)))

@dataclass
class Session:
    offset: int = 0
    identity: tuple = ()
    turn: int | None = None
    messages: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    pending: dict | None = None
    errors: int = 0
    gaps: set = field(default_factory=set)

    def apply(self, item):
        if item is None: return
        kind, key, value = item
        if kind == 'turn': self.turn = key
        elif kind == 'gap': self.gaps.add(self.turn)
        elif kind == 'message':
            old = self.messages.get(key)
            # Repeated snapshots replace one message, preserving its original turn/order.
            turn, order = (old[0], old[1]) if old else (self.turn, len(self.messages))
            self.messages[key] = (turn, order, value)
        elif kind == 'usage': self.usage[key] = value

    def measurements(self):
        invalid = set(self.gaps)
        last_total = {}
        ordered = sorted(self.messages.items(), key=lambda x: x[1][1])
        for _, (turn, _, cumulative) in ordered:
            if cumulative is None or cumulative < last_total.get(turn, 0): invalid.add(turn)
            if cumulative is not None: last_total[turn] = cumulative
        previous = {}
        for ident, (turn, order, cumulative) in ordered:
            if turn is None or turn in invalid: continue
            last = previous.get(turn, 0)
            previous[turn] = cumulative
            seconds = (cumulative - last) / 1000
            usage, anchor = self.usage.get(ident), id_time(ident)
            if seconds > 0 and usage and anchor is not None:
                yield ident, usage, anchor, seconds

class Timings:
    def __init__(self):
        self.sessions = {}
        self.decoder = zstandard.ZstdDecompressor()

    def read(self, path):
        st = path.stat()
        state = self.sessions.setdefault(path, Session())
        identity = (st.st_dev, st.st_ino)
        if state.identity and (state.identity != identity or st.st_size < state.offset):
            state = self.sessions[path] = Session()
        state.identity = identity
        with path.open('rb') as stream:
            stream.seek(state.offset)
            while True:
                header = stream.read(12)
                if len(header) != 12: break  # Wait for a complete header on the next scan.
                magic, compressed, raw = struct.unpack('>4sII', header)
                if magic != b'RX4F' or not 0 < compressed <= MAX_FRAME or not 0 < raw <= MAX_FRAME:
                    state.errors = max(1, state.errors); break
                data = stream.read(compressed)
                if len(data) != compressed: break  # Partial frame is normal during append.
                state.offset = stream.tell()
                try:
                    unpacked = self.decoder.decompress(data, max_output_size=raw)
                    if len(unpacked) != raw: raise ValueError('frame size mismatch')
                    record = json.loads(unpacked)
                    kind = record.get('recordType')
                    if kind == 'batch/begin':
                        state.pending = {'id': record.get('commitId'), 'first': record.get('firstSeq'),
                                         'count': record.get('eventCount'), 'items': [], 'seq': []}
                    elif kind == 'batch/event' and state.pending:
                        event = record.get('event') or {}
                        state.pending['seq'].append(event.get('seq'))
                        state.pending['items'].append(metadata(event))
                    elif kind == 'batch/end' and state.pending:
                        pending, state.pending = state.pending, None
                        first, count = pending['first'], pending['count']
                        valid = (isinstance(first, int) and isinstance(count, int)
                                 and record.get('commitId') == pending['id']
                                 and record.get('firstSeq') == first and record.get('eventCount') == count
                                 and pending['seq'] == list(range(first, first + count)))
                        if not valid: raise ValueError('incomplete batch')
                        for item in pending['items']: state.apply(item)
                except (ValueError, TypeError, KeyError, AttributeError, zstandard.ZstdError):
                    state.errors += 1; state.pending = None
        return state

    def annotate(self, rows, roots):
        paths = set()
        for root in roots:
            p = Path(root).expanduser()
            if p.name == 'stats':
                sessions = p.parent / 'desktop-sessions-v5/by-id'
                if sessions.is_dir(): paths.update(sessions.glob('*/events.frames'))
        errors = 0
        candidates = defaultdict(dict)
        for path in sorted(paths):
            try: state = self.read(path)
            except OSError:
                errors += 1; state = self.sessions.get(path)
            if state is None: continue
            errors += state.errors
            for ident, usage, anchor, seconds in state.measurements():
                candidates[usage][ident] = (anchor, seconds)
        self.sessions = {p:s for p,s in self.sessions.items() if p in paths}
        proposals = defaultdict(list)
        for row in rows:
            if row.timing == 'reasonix_work_duration': row.seconds, row.timing = None, 'unavailable'
            if row.seconds is not None: continue
            signature = (row.model, row.input, row.output, row.reasoning)
            matches = [(ident, seconds) for ident, (anchor, seconds) in candidates.get(signature, {}).items()
                       if anchor - 1 <= row.timestamp <= anchor + seconds + 5]
            if len(matches) == 1:
                ident, seconds = matches[0]; proposals[ident].append((row, seconds))
        for matches in proposals.values():
            if len(matches) == 1:
                row, seconds = matches[0]; row.seconds, row.timing = seconds, 'reasonix_work_duration'
        return errors
