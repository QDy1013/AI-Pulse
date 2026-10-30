"""Minimal protobuf wire reader for Antigravity's local steps.metadata.

Field mappings confirmed against the application's embedded CortexStepMetadata
and ModelUsageStats protocol descriptors. Unknown fields are skipped. No
application code, proprietary descriptors, or conversation payloads are bundled.
"""
import sqlite3

def fields(data):
    values = {}
    i = 0
    def varint():
        nonlocal i
        n = 0
        for shift in range(0, 70, 7):
            if i >= len(data): raise ValueError('truncated varint')
            b = data[i]; i += 1; n |= (b & 127) << shift
            if b < 128: return n
        raise ValueError('oversized varint')
    while i < len(data):
        tag = varint(); field, wire = tag >> 3, tag & 7
        if not field: raise ValueError('invalid field')
        if wire == 0: value = varint()
        elif wire == 2:
            size = varint()
            if size > len(data) - i: raise ValueError('truncated field')
            value = data[i:i+size]; i += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if size > len(data) - i: raise ValueError('truncated scalar')
            value = data[i:i+size]; i += size
        else: raise ValueError('unsupported wire type')
        values.setdefault(field, []).append(value)
    return values

def first(message, key, default=0):
    return message.get(key, [default])[0]

def protobuf_time(raw):
    if not raw: return 0
    ts = fields(raw)
    return first(ts, 1) + first(ts, 2) / 1_000_000_000

def decode_metadata(raw):
    meta = fields(raw)
    raw_usage = first(meta, 9, b'')
    if not raw_usage: return None
    usage = fields(raw_usage)
    # ModelUsageStats fields 2/3/9/5: input/output/thinking/cache read.
    # Preserve the recorded input total; cache fields are not added again.
    start = protobuf_time(first(meta, 32, b'')) or protobuf_time(first(meta, 1, b''))
    end = protobuf_time(first(meta, 7, b'')) or protobuf_time(first(meta, 8, b''))
    return {
        'timestamp': end or start,
        'seconds': end - start if end > start > 0 else None,
        'id': first(usage, 11, b'') or first(usage, 7, b''),
        'model': first(usage, 1),
        'input_tokens': first(usage, 2), 'output_tokens': first(usage, 3),
        'reasoning_output_tokens': first(usage, 9), 'cached_input_tokens': first(usage, 5),
    }

def read_database(path):
    rows = []
    # mode=ro honors SQLite WAL. immutable=1 would miss active WAL updates.
    uri = 'file:' + path.as_posix() + '?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=0.2)
    try:
        for idx, raw in con.execute('SELECT idx, metadata FROM steps WHERE metadata IS NOT NULL'):
            try:
                d = decode_metadata(raw)
                if d:
                    ident = d['id'].decode('utf-8', errors='replace') if isinstance(d['id'], bytes) else ''
                    d['id'] = ident or (path.stem + ':' + str(idx))
                    rows.append(d)
            except (ValueError, TypeError, IndexError):
                continue
    finally: con.close()
    return rows
