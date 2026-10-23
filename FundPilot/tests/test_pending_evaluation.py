import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from fundpilot.pending_numeric import save
from fundpilot.pending_evaluation import evaluate
from fundpilot.llm_loop import digest, now
from test_pending_numeric import fixture


def review():
    return {'reviewed':True,'evidence_ref':'synthetic review','evidence_sha256':'b'*64,
            'evidence_kind':'captured_object','retrieved_at':'2026-02-01T00:00:00Z','reviewed_at':'2026-02-01T01:00:00Z'}


class PendingEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        original,record=fixture();(self.root/'original').write_bytes(original);(self.root/'record').write_text(json.dumps(record))
        self.pending=self.root/'pending';save(self.root/'original',self.root/'record',self.pending)
        self.before={p.name:p.read_bytes() for p in self.pending.iterdir()}
        self.binding={'pending_sha256':{k:digest(v) for k,v in self.before.items()},
            'original_freeze':dict(review(),frozen_at='2026-01-01T03:00:00Z',original_sha256=digest(original)),
            'source_reviews':[dict(review(),source_id='s',object_sha256=record['sources'][0]['object_sha256'],
                usable_for_frozen_prediction=True,review_scope='frozen_object_only_no_new_facts')],
            'calendars':{'SYNTH-A':dict(review(),complete_valuation_sequence=True,
                coverage_start_at='2026-01-01T00:00:00Z',coverage_end_at='2026-01-03T23:00:00Z',
                sessions=[{'date':'2026-01-01','close_at':'2026-01-01T10:00:00Z'},
                          {'date':'2026-01-03','close_at':'2026-01-03T10:00:00Z'}])},
            'nav':[dict(review(),fund='SYNTH-A',date=day,nav=value,snapshot_sha256='c'*64,
                       snapshot_kind='captured_object',known_available_at='2026-02-01T00:00:00Z')
                   for day,value in [('2026-01-01','1'),('2026-01-03','1.1')]]}
    def test_mature_uses_original_freeze_not_later_binding(self):
        r=evaluate(self.pending,self.binding,now());row=r['tape'][0]
        self.assertEqual((row['D0'],row['Dh']),('2026-01-01','2026-01-03'))
        self.assertAlmostEqual(row['numeric_scores']['brier'],.04)
        self.assertEqual(row['numeric_scores']['pinball']['q50'],'0.05')
        self.assertFalse(row['direction_added'])
        self.assertEqual(self.before,{p.name:p.read_bytes() for p in self.pending.iterdir()})
    def test_missing_qualification_calendar_and_nav(self):
        b=dict(self.binding);b['source_reviews']=[]
        r=evaluate(self.pending,b,now());self.assertIsNone(r['tape'][0]['numeric_scores']['brier'])
        self.assertEqual(r['tape'][0]['reason'],'source_qualification_missing_or_rejected')
        b=dict(self.binding);b['calendars']={}
        self.assertEqual(evaluate(self.pending,b,now())['tape'][0]['reason'],'verified_valuation_calendar_missing')
        b=dict(self.binding);b['nav']=[]
        row=evaluate(self.pending,b,now())['tape'][0]
        self.assertEqual(row['status'],'missing');self.assertIsNone(row['numeric_scores']['pinball'])
    def test_original_freeze_missing_is_pending(self):
        self.binding.pop('original_freeze')
        self.assertEqual(evaluate(self.pending,self.binding,now())['tape'][0]['reason'],'original_freeze_review_missing')
    def test_future_target_and_incomplete_calendar_pending(self):
        cal=self.binding['calendars']['SYNTH-A'];cal['sessions'][1]={'date':'2099-01-01','close_at':'2099-01-01T10:00:00Z'}
        cal['coverage_end_at']='2099-01-01T23:00:00Z'
        row=evaluate(self.pending,self.binding,now())['tape'][0]
        self.assertEqual(row['reason'],'target_not_mature');self.assertIsNone(row['numeric_scores']['brier'])
        cal['sessions']=cal['sessions'][:1]
        self.assertEqual(evaluate(self.pending,self.binding,now())['tape'][0]['reason'],'target_session_not_yet_covered')
    def test_hash_tampering_and_no_new_source_facts(self):
        self.binding['source_reviews'][0]['object_sha256']='0'*64
        with self.assertRaises(ValueError):evaluate(self.pending,self.binding,now())
        self.binding['pending_sha256']['original.json']='0'*64
        with self.assertRaises(ValueError):evaluate(self.pending,self.binding,now())
    def test_pre_close_label_and_late_review_unqualified(self):
        self.binding['nav'][1]['retrieved_at']='2026-01-02T00:00:00Z'
        self.binding['nav'][1]['known_available_at']='2026-01-02T00:00:00Z'
        row=evaluate(self.pending,self.binding,now())['tape'][0]
        self.assertEqual(row['status'],'missing');self.assertIsNone(row['numeric_scores']['brier'])
        self.binding['source_reviews'][0]['reviewed_at']='2099-01-01T00:00:00Z'
        self.assertEqual(evaluate(self.pending,self.binding,now())['tape'][0]['status'],'pending')
    def test_cli_creates_separate_hashed_attachment(self):
        raw=json.dumps(self.binding).encode();(self.root/'binding.json').write_bytes(raw)
        subprocess.run([sys.executable,'-m','fundpilot.pending_evaluation','--pending',str(self.pending),
            '--binding',str(self.root/'binding.json'),'--binding-sha256',digest(raw),'--as-of',now(),
            '--output',str(self.root/'evaluation')],check=True,capture_output=True)
        self.assertTrue((self.root/'evaluation/manifest.json').is_file())
        self.assertEqual(self.before,{p.name:p.read_bytes() for p in self.pending.iterdir()})

    def test_partial_binding_fields_remain_unready(self):
        self.binding['original_freeze'].pop('frozen_at')
        row=evaluate(self.pending,self.binding,now())['tape'][0]
        self.assertEqual(row['status'],'pending');self.assertIsNone(row['numeric_scores']['brier'])
        self.binding['original_freeze']['frozen_at']='2026-01-01T03:00:00Z'
        self.binding['source_reviews'][0].pop('object_sha256')
        self.assertEqual(evaluate(self.pending,self.binding,now())['tape'][0]['status'],'pending')

    def test_after_freeze_source_remains_blocked(self):
        # Create a separate synthetic custody record; never modify a saved real record.
        original,record=fixture();record['sources'][0]['retrieved_at']='2026-01-02T00:00:00Z'
        record['sources'][0]['known_available_at']='2026-01-02T00:00:00Z'
        (self.root/'late-record').write_text(json.dumps(record))
        late=self.root/'late-pending';save(self.root/'original',self.root/'late-record',late)
        self.binding['pending_sha256']={p.name:digest(p.read_bytes()) for p in late.iterdir()}
        row=evaluate(late,self.binding,now())['tape'][0]
        self.assertEqual(row['reason'],'captured_object_not_known_before_original_freeze')
        self.assertIsNone(row['numeric_scores']['brier'])
