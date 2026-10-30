import json
import tempfile
import unittest
import sqlite3
from pathlib import Path
from pulse.collector import Collector, FileState, antigravity_model, consume, defaults, number, stamp
from pulse.antigravity import decode_metadata, fields

TS = '2026-10-30T02:00:00Z'

def vint(n):
    out = bytearray()
    while n > 127: out.append((n & 127) | 128); n >>= 7
    return bytes(out) + bytes([n])

def wire(k, v):
    return vint(k * 8 + 2) + vint(len(v)) + v if isinstance(v, bytes) else vint(k * 8) + vint(v)

def gravity_metadata(output=90):
    created = wire(1, 1793325600)
    end = wire(1, 1793325603)
    usage = wire(2, 1000) + wire(3, output) + wire(9, 30) + wire(5, 500) + wire(11, b'response-gravity')
    # Real PLANNER_RESPONSE rows set field 32 (started_at) equal to field 7 (finished_generating_at).
    return wire(1, created) + wire(7, end) + wire(32, end) + wire(9, usage)

class ParsingTests(unittest.TestCase):
    def test_antigravity_protocol_fields_and_truncation(self):
        d = decode_metadata(gravity_metadata())
        self.assertEqual((d['input_tokens'], d['output_tokens'], d['reasoning_output_tokens'], d['cached_input_tokens']), (1000, 90, 30, 500))
        self.assertEqual(d['seconds'], 3)
        with self.assertRaises(ValueError): fields(b'\x4a\xff')
    def test_antigravity_model_aliases(self):
        self.assertEqual(antigravity_model(1401, {'1401': 'Custom'}, 'Auto Name'), 'Custom')
        self.assertEqual(antigravity_model(1401, {}, 'Claude Opus 5.5 (Medium)'), 'Claude Opus 5.5 (Medium)')
        self.assertEqual(antigravity_model(1319, {}), '未命名模型 #1319')
        self.assertEqual(antigravity_model(0, {}), '')

    def test_epoch_milliseconds_and_iso_are_equivalent(self):
        self.assertEqual(stamp(1793325600000), stamp(TS))
        self.assertEqual(stamp(1793325600), stamp(TS))

    def test_codex_dual_event_not_double_counted(self):
        s = FileState()
        consume('Codex', {'type':'token_usage_record','timestamp':TS,'payload':{'response_id':'r1','usage':{'output_tokens':100,'reasoning_output_tokens':40}}}, s)
        consume('Codex', {'type':'event_msg','timestamp':TS,'payload':{'type':'token_count','info':{'total_token_usage':{'output_tokens':100}}}}, s)
        self.assertEqual(sum(r.output for r in s.requests.values()), 100)
        self.assertEqual(sum(r.reasoning for r in s.requests.values()), 40)

    def test_codex_legacy_cumulative_delta_and_duplicate(self):
        s = FileState()
        for i, n in enumerate([100, 100, 160]):
            consume('Codex', {'type':'event_msg','timestamp':f'2026-10-30T02:00:0{i}Z','payload':{'type':'token_count','info':{'total_token_usage':{'output_tokens':n}}}}, s)
        self.assertEqual(sum(r.output for r in s.requests.values()), 160)

    def test_claude_repeated_snapshots(self):
        s = FileState()
        consume('Claude', {'type':'api-request','timestamp':'2026-10-30T02:00:00Z'}, s)
        consume('Claude', {'type':'assistant','timestamp':'2026-10-30T02:00:02Z','message':{'id':'msg1','usage':{'output_tokens':10,'input_tokens':2,'cache_read_input_tokens':10,'cache_creation_input_tokens':20}}}, s)
        # Mid-stream tool_result ('user') must not clobber msg1's start timestamp.
        consume('Claude', {'type':'user','timestamp':'2026-10-30T02:00:03.900Z'}, s)
        for n in [30, 20]:
            consume('Claude', {'type':'assistant','timestamp':'2026-10-30T02:00:04Z','message':{'id':'msg1','usage':{'output_tokens':n,'input_tokens':2,'cache_read_input_tokens':10,'cache_creation_input_tokens':20}}}, s)
        self.assertEqual(len(s.requests), 1)
        self.assertEqual(s.requests['msg1'].output, 30)
        self.assertEqual(s.requests['msg1'].input, 32)
        self.assertAlmostEqual(s.requests['msg1'].seconds, 4.0)

    def test_reasonix_no_invented_timing(self):
        s = FileState()
        consume('Reasonix', {'ts':TS,'model':'deepseek-flash-c17feb32f2d068d3bd8c9f2c779f0793/deepseek-v4-flash','completion':50,'prompt':100,'reasoning':20}, s)
        r = next(iter(s.requests.values()))
        self.assertIsNone(r.speed)
        self.assertEqual(r.output, 50)
        self.assertEqual(r.model, 'deepseek-v4-flash')

    def test_unknown_schema_ignored(self):
        s = FileState()
        consume('WorkBuddy', {'usage':{'output_tokens':100}}, s, True)
        self.assertFalse(s.requests)

    def test_workbuddy_parallel_tools_share_message_usage(self):
        s = FileState()
        consume('WorkBuddy', {'type':'message','role':'user','sessionId':'s','timestamp':'2026-10-30T01:59:58Z'}, s)
        consume('WorkBuddy', {'type':'reasoning','id':'r0','sessionId':'s','timestamp':'2026-10-30T01:59:59Z','providerData':{'messageId':'response1'}}, s)
        for ident in ['tool1', 'tool2']:
            consume('WorkBuddy', {'type':'function_call','id':ident,'sessionId':'s','timestamp':TS,'providerData':{'messageId':'response1','usage':{'inputTokens':200,'outputTokens':40,'outputTokensDetails':[{'reasoning_tokens':10}]}}}, s)
        self.assertEqual(len(s.requests), 1)
        req = next(iter(s.requests.values()))
        self.assertEqual(req.output, 40)
        self.assertAlmostEqual(req.seconds, 2.0)

    def test_generic_duration_and_nonfinite(self):
        s = FileState()
        consume('Antigravity', {'schema':'ai-pulse/v1','id':'x','timestamp':TS,'duration_ms':2000,'usage':{'output_tokens':60}}, s, True)
        self.assertEqual(s.requests['x'].speed, 30)
        for n in ['NaN', float('inf'), -2, None]: self.assertEqual(number(n), 0)

class FileTests(unittest.TestCase):
    def test_antigravity_active_wal_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            conv = Path(tmp)/'conversations'; conv.mkdir()
            p = conv/'session.db'
            con = sqlite3.connect(p)
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('CREATE TABLE steps (idx INTEGER PRIMARY KEY, metadata BLOB)')
            con.execute('INSERT INTO steps VALUES (?, ?)', (1, gravity_metadata()))
            con.commit()
            tr = Path(tmp)/'brain/session/.system_generated/logs/transcript.jsonl'
            tr.parent.mkdir(parents=True, exist_ok=True)
            tr.write_text(json.dumps({
                'step_index': 0, 'type': 'USER_INPUT',
                'content': '<USER_SETTINGS_CHANGE>\nThe user changed setting `Model Selection` from None to Claude Opus 5.5 (Medium). No need to comment'
            }) + '\n')
            cfg = defaults(); cfg['roots'] = {app:[] for app in cfg['roots']}; cfg['roots']['Antigravity']=[str(conv)]
            c = Collector(cfg)
            req = c.scan()['Antigravity']['requests'][0]
            self.assertEqual(req.output, 90)
            self.assertEqual(req.model, 'Claude Opus 5.5 (Medium)')
            con.execute('UPDATE steps SET metadata=?', (gravity_metadata(120),));con.commit()
            self.assertEqual(c.scan()['Antigravity']['requests'][0].output, 120)
            self.assertEqual(len(c.scan()['Antigravity']['requests']), 1)
            con.close()
    def test_incremental_partial_line_truncation_and_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'usage.jsonl'
            d = {'schema':'ai-pulse/v1','id':'a','timestamp':TS,'usage':{'output_tokens':10}}
            line = json.dumps(d).encode()
            p.write_bytes(line[:20])
            cfg = defaults()
            cfg['roots'] = {app:[] for app in cfg['roots']}
            cfg['imports']['WorkBuddy'] = [str(p)]
            c = Collector(cfg)
            self.assertEqual(c.scan()['WorkBuddy']['requests'], [])
            with p.open('ab') as f: f.write(line[20:]+b'\n')
            self.assertEqual(c.scan()['WorkBuddy']['requests'][0].output, 10)
            self.assertEqual(len(c.scan()['WorkBuddy']['requests']), 1)
            p.write_text('{}\n')
            self.assertEqual(c.scan()['WorkBuddy']['requests'], [])
            p.unlink()
            self.assertEqual(c.scan()['WorkBuddy']['requests'], [])
            self.assertFalse(c.files)

    def test_copied_claude_logs_deduplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = {'type':'assistant','timestamp':TS,'message':{'id':'same','usage':{'output_tokens':40}}}
            for name in ['one', 'two']:
                (Path(tmp)/(name+'.jsonl')).write_text(json.dumps(d)+'\n')
            cfg = defaults(); cfg['roots'] = {app:[] for app in cfg['roots']}; cfg['roots']['Claude']=[tmp]
            rows = Collector(cfg).scan()['Claude']['requests']
            self.assertEqual(sum(r.output for r in rows), 40)

    def test_parse_errors_persist_across_scans(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'usage.jsonl'
            p.write_text('not json\n' + json.dumps({'schema':'ai-pulse/v1','id':'a','timestamp':TS,'usage':{'output_tokens':5}}) + '\n')
            cfg = defaults(); cfg['roots'] = {app:[] for app in cfg['roots']}; cfg['imports']['Codex'] = [str(p)]
            c = Collector(cfg)
            self.assertEqual(c.scan()['Codex']['errors'], 1)
            self.assertEqual(c.scan()['Codex']['errors'], 1)

    def test_locked_file_keeps_last_rows(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'usage.jsonl'
            p.write_text(json.dumps({'schema':'ai-pulse/v1','id':'a','timestamp':TS,'usage':{'output_tokens':5}}) + '\n')
            cfg = defaults(); cfg['roots'] = {app:[] for app in cfg['roots']}; cfg['imports']['Codex'] = [str(p)]
            c = Collector(cfg)
            self.assertEqual(len(c.scan()['Codex']['requests']), 1)
            with p.open('a') as f: f.write(json.dumps({'schema':'ai-pulse/v1','id':'b','timestamp':TS,'usage':{'output_tokens':7}}) + '\n')
            with patch.object(Path, 'open', side_effect=PermissionError('locked')):
                result = c.scan()['Codex']
            self.assertEqual(len(result['requests']), 1)
            self.assertEqual(result['errors'], 1)
            self.assertEqual(len(c.scan()['Codex']['requests']), 2)

if __name__ == '__main__': unittest.main()
