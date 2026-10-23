import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from fundpilot.pending_numeric import object_hash, save, inspect
from fundpilot.llm_loop import digest, score
from test_numeric_forecast import numeric


def fixture():
    original=b'{ "actual_original_shape": "synthetic test", "p_up": "0.8" }\n'
    obj={'text':'synthetic captured summary','published_at':None}
    record={'record_kind':'pending_numeric_capture','producer':'synthetic_fixture',
        'original_sha256':digest(original),'model_ref':'unknown','prompt_version':'synthetic',
        'mapping_review_ref':'synthetic mapping test; not real LLM output',
        'generated_at':'2026-01-01T02:00:00Z','information_cutoff':'2026-01-01T01:00:00Z',
        'numeric_schema':'research_numeric_v1','new_batch_no_backfill':True,
        'sources':[{'id':'s','snapshot_kind':'captured_object','hash_basis':'json_sorted_compact_utf8',
            'captured_object':obj,'object_sha256':object_hash(obj),'retrieved_at':'2026-01-01T00:00:00Z',
            'known_available_at':'2026-01-01T00:00:00Z','published_at':None}],
        'cards':[{'id':'n','fund':'SYNTH-A','horizon':1,'D0':None,'Dh':None,'source_ids':['s'],'numeric_forecast':numeric()}]}
    return original,record


class PendingNumericTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.original,self.record=fixture()
    def write(self):
        (self.root/'original').write_bytes(self.original)
        (self.root/'record').write_text(json.dumps(self.record))
    def save(self):
        self.write();return save(self.root/'original',self.root/'record',self.root/'pending')
    def test_numeric_only_unknown_dates_and_publication_cli(self):
        self.write()
        subprocess.run([sys.executable,'-m','fundpilot.pending_numeric','save','--original',str(self.root/'original'),
            '--record',str(self.root/'record'),'--output',str(self.root/'pending')],check=True,capture_output=True)
        self.assertEqual((self.root/'pending/original.json').read_bytes(),self.original)
        self.assertEqual((self.root/'pending/original.json').stat().st_mode&0o777,0o400)
        r=inspect(self.root/'pending');self.assertFalse(r['scoring_ready']);self.assertEqual(r['source_qualification'],'pending')
        self.assertEqual(r['calendar_qualification'],'pending')
    def test_original_and_object_hash_rejected(self):
        self.record['original_sha256']='0'*64
        with self.assertRaises(ValueError):self.save()
        self.original,self.record=fixture();self.record['sources'][0]['object_sha256']='0'*64
        with self.assertRaises(ValueError):self.save()
    def test_no_guessed_dates_or_future_generation(self):
        self.record['cards'][0]['D0']='2026-01-02'
        with self.assertRaises(ValueError):self.save()
        self.original,self.record=fixture();self.record['generated_at']='2099-01-01T00:00:00Z'
        with self.assertRaises(ValueError):self.save()
    def test_numeric_validation_still_required(self):
        self.record['cards'][0]['numeric_forecast']['p_up']='2'
        with self.assertRaises(ValueError):self.save()
    def test_no_overwrite_or_old_score_bypass(self):
        self.save()
        with self.assertRaises(FileExistsError):save(self.root/'original',self.root/'record',self.root/'pending')
        with self.assertRaises(FileNotFoundError):score(self.root/'pending','unused','unused','2026-01-01T00:00:00Z',self.root/'out')
        self.assertFalse((self.root/'out').exists())
    def test_saved_tamper_detected(self):
        self.save();p=self.root/'pending/capture-record.json';p.chmod(0o600);p.write_text('{}')
        with self.assertRaisesRegex(ValueError,'saved bytes changed'):inspect(self.root/'pending')
    def test_snapshot_after_cutoff_still_unqualified_not_promoted(self):
        self.record['sources'][0]['retrieved_at']='2026-01-03T00:00:00Z'
        self.record['sources'][0]['known_available_at']='2026-01-03T00:00:00Z'
        self.assertFalse(self.save()['scoring_ready'])
