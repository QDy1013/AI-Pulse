import base64
import json
import struct
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import zstandard
from pulse.collector import Collector, defaults, Request
from pulse.reasonix import Timings, ALPHABET

NOW = 1793360000

def ident(seconds, suffix=0):
    value = (int(seconds * 1000) << 80) + suffix
    out = ''
    for _ in range(26): out = ALPHABET[value & 31] + out; value >>= 5
    return out

def frame(record):
    raw = json.dumps(record).encode()
    data = zstandard.ZstdCompressor().compress(raw)
    return struct.pack('>4sII', b'RX4F', len(data), len(raw)) + data

def batch(events, start=1):
    common = {'commitId':str(start), 'firstSeq':start, 'eventCount':len(events)}
    result = frame(dict(common, recordType='batch/begin'))
    for seq, (kind, payload) in enumerate(events, start):
        event = {'kind':kind, 'seq':seq, 'payload':base64.b64encode(json.dumps(payload).encode()).decode()}
        result += frame({'recordType':'batch/event', 'event':event})
    return result + frame(dict(common, recordType='batch/end'))

def response(key, output, cumulative):
    return [('message/complete', {'message':{'role':'assistant', 'id':key, 'workDurationMs':cumulative}}),
            ('diagnostic/response', {'messageId':key, 'response':{'modelRef':'deepseek-v4-flash',
             'usage':{'inputTokens':1000, 'outputTokens':output, 'reasoningTokens':20,
                      'estimated':False, 'unknown':False}}})]

class ReasonixTimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.stats=self.root/'stats';self.stats.mkdir()
        self.path=self.root/'desktop-sessions-v5/by-id/session/events.frames'
        self.path.parent.mkdir(parents=True)
    def tearDown(self):self.tmp.cleanup()
    def row(self, output=100, when=NOW+4, key='r1'):
        return Request(key,'Reasonix',when,'deepseek-v4-flash',input=1000,output=output,reasoning=20)
    def test_cumulative_work_is_differenced_and_turns_reset(self):
        events=[('turn/start',{})]+response(ident(NOW),100,4000)+response(ident(NOW+6),200,10000)
        events += [('turn/start',{})]+response(ident(NOW+20),300,2000)
        self.path.write_bytes(batch(events))
        rows=[self.row(),self.row(200,NOW+10,'r2'),self.row(300,NOW+22,'r3')]
        timing=Timings();self.assertEqual(timing.annotate(rows,[str(self.stats)]),0)
        self.assertEqual([r.seconds for r in rows],[4,6,2])
        self.assertEqual(rows[0].speed,25)
        self.assertEqual([r.output for r in rows],[100,200,300])
        timing.annotate(rows,[str(self.stats)])
        self.assertEqual([r.seconds for r in rows],[4,6,2])
    def test_partial_frame_and_uncommitted_batch_wait_for_completion(self):
        data=batch([('turn/start',{})]+response(ident(NOW),100,4000))
        self.path.write_bytes(data[:-4]);row=self.row();timing=Timings()
        self.assertEqual(timing.annotate([row],[str(self.stats)]),0)
        self.assertIsNone(row.seconds)
        with self.path.open('ab') as f:f.write(data[-4:])
        self.assertEqual(timing.annotate([row],[str(self.stats)]),0)
        self.assertEqual(row.seconds,4)
    def test_ambiguous_usage_never_gets_a_guessed_duration(self):
        self.path.write_bytes(batch([('turn/start',{})]+response(ident(NOW),100,4000)))
        rows=[self.row(),self.row(key='duplicate')]
        Timings().annotate(rows,[str(self.stats)])
        self.assertTrue(all(r.seconds is None for r in rows))
    def test_decreasing_cumulative_time_is_rejected(self):
        self.path.write_bytes(batch([('turn/start',{})]+response(ident(NOW),100,4000)+response(ident(NOW+5),200,2000)))
        rows=[self.row(),self.row(200,NOW+7)]
        Timings().annotate(rows,[str(self.stats)])
        self.assertTrue(all(r.seconds is None for r in rows))
    def test_stats_totals_are_preserved_and_late_timing_is_added(self):
        config=defaults();config['roots']={a:[] for a in config['roots']};config['roots']['Reasonix']=[str(self.stats)]
        d={'ts':datetime.fromtimestamp(NOW+4,timezone.utc).isoformat(),'model':'deepseek-v4-flash',
           'prompt':1000,'completion':100,'reasoning':20}
        (self.stats/'day.jsonl').write_text(json.dumps(d)+'\n')
        collector=Collector(config)
        before=collector.scan()['Reasonix'];self.assertIsNone(before['requests'][0].seconds)
        self.path.write_bytes(batch([('turn/start',{})]+response(ident(NOW),100,4000)))
        after=collector.scan()['Reasonix']
        self.assertEqual((len(after['requests']),sum(r.output for r in after['requests'])),(1,100))
        self.assertEqual(after['requests'][0].seconds,4)
        self.path.unlink();after=collector.scan()['Reasonix']
        self.assertIsNone(after['requests'][0].seconds)

if __name__=='__main__':unittest.main()
