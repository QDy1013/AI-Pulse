import json
import tempfile
import unittest
import sqlite3
from pathlib import Path
from pulse.collector import Collector, FileState, Request, antigravity_model, consume, defaults, number, stamp
from pulse.antigravity import decode_metadata, fields
from pulse.pricing import estimate_usd, format_custom_rates, parse_custom_rates, resolve_rate

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

    def test_codex_legacy_before_modern_with_different_timestamp(self):
        s = FileState()
        # Older client portion of the session: legacy-only row before the current turn.
        consume('Codex', {'type':'event_msg','timestamp':'2026-10-30T01:00:00Z','payload':{'type':'token_count','info':{'total_token_usage':{'output_tokens':50}}}}, s)
        consume('Codex', {'type':'event_msg','timestamp':'2026-10-30T02:00:00Z','payload':{'type':'task_started'}}, s)
        # Dual-written response: compatibility row a few ms before the modern record.
        consume('Codex', {'type':'event_msg','timestamp':'2026-10-30T02:00:04.998Z','payload':{'type':'token_count','info':{'total_token_usage':{'output_tokens':150}}}}, s)
        consume('Codex', {'type':'token_usage_record','timestamp':'2026-10-30T02:00:05Z','payload':{'response_id':'r1','usage':{'output_tokens':100}}}, s)
        self.assertEqual(sum(r.output for r in s.requests.values()), 150)
        self.assertIn('legacy:2026-10-30T01:00:00Z', s.requests)

    def test_claude_one_hour_cache_writes(self):
        s = FileState()
        consume('Claude', {'type':'assistant','timestamp':TS,'message':{'id':'m1','model':'claude-sonnet-4-5','usage':{
            'output_tokens':10,'input_tokens':0,'cache_creation_input_tokens':300,
            'cache_creation':{'ephemeral_5m_input_tokens':100,'ephemeral_1h_input_tokens':200}}}}, s)
        r = s.requests['m1']
        self.assertEqual((r.cache_write, r.cache_write_1h), (300, 200))
        self.assertAlmostEqual(estimate_usd(r)[0], (100 * 3.75 + 200 * 3.0 * 2 + 10 * 15.0) / 1_000_000)

    def test_pricing_prefers_most_specific_model(self):
        self.assertEqual(resolve_rate('Codex', 'o3-mini-2025-01-31'), (1.10, 0.55, 4.40, 1.10))
        self.assertEqual(resolve_rate('Codex', 'o3-2025-04-16'), (2.0, 0.50, 8.0, 2.0))
        self.assertEqual(resolve_rate('Claude', 'claude-opus-4-1-20250805')[2], 75.0)
        self.assertEqual(resolve_rate('Claude', 'claude-opus-4-5-20251101')[2], 25.0)
        self.assertEqual(resolve_rate('Claude', 'claude-haiku-4-5-20251001')[2], 5.0)
        custom = {'deepseek': [1, 0.1, 2], 'deepseek-v4': [3, 0.3, 6]}
        self.assertEqual(resolve_rate('Reasonix', 'deepseek-v4-flash', custom)[0], 3.0)

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
        self.assertEqual(s.requests['msg1'].cache_write, 20)
        self.assertAlmostEqual(s.requests['msg1'].seconds, 4.0)

    def test_reasonix_no_invented_timing(self):
        s = FileState()
        consume('Reasonix', {'id':'rx1','ts':TS,'model':'deepseek-flash-c17feb32f2d068d3bd8c9f2c779f0793/deepseek-v4-flash','completion':50,'prompt':100,'reasoning':20,'valuation_usd':'0.00125','cost_complete':True}, s)
        consume('Reasonix', {'id':'rx2','ts':TS,'model':'deepseek-v4-flash','completion':50,'prompt':100,'valuation_usd':'0','cost_complete':False}, s)
        r = s.requests['rx1']
        self.assertIsNone(r.speed)
        self.assertEqual(r.output, 50)
        self.assertEqual(r.model, 'deepseek-v4-flash')
        self.assertAlmostEqual(r.cost_usd, 0.00125)
        self.assertIsNone(s.requests['rx2'].cost_usd)

    def test_api_quota_pricing_and_custom_overrides(self):
        # Claude: input is inclusive (2 uncached + 10 cached + 20 cache_write), reasoning inside output.
        claude_req = Request('c1', 'Claude', 0, 'claude-opus-5-5', input=32, output=30, reasoning=15, cached=10, cache_write=20)
        actual, full = estimate_usd(claude_req)
        self.assertAlmostEqual(actual, (2 * 4.0 + 10 * 0.2 + 20 * 5.0 + 30 * 20.0) / 1_000_000)
        self.assertAlmostEqual(full, (32 * 4.0 + 30 * 20.0) / 1_000_000)

        # Antigravity: input (field 2) and cached (field 5) are disjoint buckets.
        ag_req = Request('a1', 'Antigravity', 0, 'Claude Opus 5.5 (Medium)', input=1000, output=90, reasoning=30, cached=500)
        ag_actual, ag_full = estimate_usd(ag_req)
        self.assertAlmostEqual(ag_actual, (1000 * 4.0 + 500 * 0.2 + 90 * 20.0) / 1_000_000)
        self.assertAlmostEqual(ag_full, (1500 * 4.0 + 90 * 20.0) / 1_000_000)

        # Reasonix: honors reported valuation_usd unless overridden by custom_rates.
        rx_req = Request('r1', 'Reasonix', 0, 'deepseek-v4-flash', input=1000, output=500, cached=500, cost_usd=0.005)
        self.assertAlmostEqual(estimate_usd(rx_req)[0], 0.005)
        custom = parse_custom_rates('deepseek-v4 = 1.0, 0.1, 2.0\ninvalid line\n')
        self.assertEqual(format_custom_rates(custom), 'deepseek-v4 = 1, 0.1, 2')
        self.assertAlmostEqual(estimate_usd(rx_req, custom)[0], (500 * 1.0 + 500 * 0.1 + 500 * 2.0) / 1_000_000)

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

    def test_invalid_timestamps_are_errors_not_1970_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = {'type':'assistant','timestamp':TS,'message':{'id':'ok','usage':{'output_tokens':40}}}
            bad = {'type':'assistant','timestamp':'not a time','message':{'id':'bad','usage':{'output_tokens':9}}}
            (Path(tmp)/'s.jsonl').write_text(json.dumps(good)+'\n'+json.dumps(bad)+'\n')
            cfg = defaults(); cfg['roots'] = {app:[] for app in cfg['roots']}; cfg['roots']['Claude']=[tmp]
            result = Collector(cfg).scan()['Claude']
            self.assertEqual([r.key for r in result['requests']], ['ok'])
            self.assertEqual(result['errors'], 1)

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

    def test_codex_quota_snapshot_and_project(self):
        def limits(used, at):
            return {'type':'event_msg','timestamp':at,'payload':{'type':'token_count','info':None,'rate_limits':{
                'limit_id':'codex','plan_type':'plus',
                'primary':{'used_percent':used,'window_minutes':300,'resets_at':1793346840},
                'secondary':{'used_percent':11.0,'window_minutes':10080,'resets_in_seconds':3600}}}}
        with tempfile.TemporaryDirectory() as tmp:
            older = [{'type':'session_meta','timestamp':TS,'payload':{'cwd':'C:\\work\\alpha'}}, limits(30.0, '2026-10-30T02:00:00Z'),
                     {'type':'token_usage_record','timestamp':TS,'payload':{'response_id':'r1','usage':{'output_tokens':10}}}]
            newer = [limits(47.0, '2026-10-30T03:00:00Z'),
                     # Other limit families (e.g. premium models) are not the Codex plan quota.
                     {'type':'event_msg','timestamp':'2026-10-30T04:00:00Z','payload':{'type':'token_count','rate_limits':{
                         'limit_id':'premium','primary':{'used_percent':99.0,'window_minutes':300}}}}]
            (Path(tmp)/'a.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in older))
            (Path(tmp)/'b.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in newer))
            cfg = defaults(); cfg['roots'] = {app:[] for app in cfg['roots']}; cfg['roots']['Codex']=[tmp]
            result = Collector(cfg).scan()
            snap = result['Codex']['limits']
            self.assertEqual(snap['plan'], 'plus')
            self.assertEqual([w['used'] for w in snap['windows']], [47.0, 11.0])
            self.assertEqual(snap['windows'][0]['resets_at'], 1793346840)
            self.assertEqual(snap['windows'][1]['resets_at'], stamp('2026-10-30T03:00:00Z') + 3600)
            self.assertEqual(result['Codex']['requests'][0].project, 'C:\\work\\alpha')
            self.assertIsNone(result['Claude']['limits'])

    def test_claude_project_from_cwd(self):
        s = FileState()
        consume('Claude', {'type':'assistant','timestamp':TS,'cwd':'/home/me/beta','message':{'id':'m','usage':{'output_tokens':5}}}, s)
        self.assertEqual(s.requests['m'].project, '/home/me/beta')
        w = FileState()
        consume('WorkBuddy', {'type':'message','role':'user','timestamp':TS,'sessionId':'s','cwd':'c:\\wb\\gamma'}, w)
        consume('WorkBuddy', {'type':'message','timestamp':TS,'sessionId':'s','providerData':{'messageId':'m','usage':{'outputTokens':3}}}, w)
        self.assertEqual(w.requests['s:m'].project, 'c:\\wb\\gamma')

if __name__ == '__main__': unittest.main()
