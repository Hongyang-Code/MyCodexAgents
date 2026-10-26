"""Only synthetic approvals and usage, no model or market requests."""
import tempfile,json,hashlib,subprocess,sys,unittest,shutil
from pathlib import Path
from fundpilot.durable_budget import DurableBudget
from fundpilot.diagnostic_grant import grant
from fundpilot.upstream_bridge import write_new,now

class DiagnosticGrantTests(unittest.TestCase):
    def fixture(self,r):
        old=r/'old.sqlite';hist=[{'attempted_at':now(),'counts_toward_next_7_day_change_budget':True}]*2
        DurableBudget.create(old,run_id='SYNTHETIC_OLD',used=dict(source=None,retry=None,llm=None,prediction_batch=None),candidate_history=hist)
        f=r/'protocol';write_new(f,{'synthetic':True})
        a=r/'approval';write_new(a,{'approval_id':'SYNTHETIC_ONE','authority_legacy_path':str(old),'answer':'批准这一次历史对照','question':'SYNTHETIC scope only','source':'SYNTHETIC fixture, not user authorization','approved_at':now(),'legacy_sha256':hashlib.sha256(old.read_bytes()).hexdigest(),'bindings':[{'path':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}],'scope':{'llm':12,'source':0,'evaluations':1,'candidate':0}})
        return old,a

    def test_thirteen_processes_return_same_scope_no_reissue_or_legacy_change(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);old,a=self.fixture(r);original=old.read_bytes()
            cmd=[sys.executable,'-m','fundpilot.diagnostic_grant','--legacy',str(old),'--approval',str(a)]
            ps=[subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(13)]
            results=[(p.communicate(timeout=30),p.returncode) for p in ps]
            successes=[json.loads(o[0])['budget'] for o,rc in results if rc==0]
            self.assertGreaterEqual(len(successes),1);self.assertEqual(len(set(successes)),1)
            old.chmod(0o400);b=grant(old,a);b.require('one','llm');self.assertEqual(grant(old,a).path,b.path)
            self.assertEqual(sum(o['kind']=='llm' for o in grant(old,a).snapshot()['operations']),1)
            self.assertEqual(b.reserve('candidate','candidate'),'skip_partial');self.assertEqual(b.reserve('source','source'),'skip_partial')
            self.assertTrue(all(v is None for v in b.snapshot()['seed']['diagnostic_grant']['legacy_cumulative_used'].values()))
            self.assertEqual(old.read_bytes(),original)
            copied=r/'copied';copied.mkdir(mode=0o700);shutil.copy2(old,copied/'old.sqlite')
            with self.assertRaisesRegex(ValueError,'canonical'):grant(copied/'old.sqlite',a)

    def test_changed_binding_missing_ledger_or_claimed_crash_never_regrants(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);old,a=self.fixture(r);b=grant(old,a);b.path.unlink()
            with self.assertRaises((OSError,ValueError)):grant(old,a)
            self.assertFalse(b.path.exists())
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);old,a=self.fixture(r);b=grant(old,a);(r/'protocol').write_text('tampered')
            with self.assertRaisesRegex(ValueError,'binding'):grant(old,a)

    def test_frozen_input_binding_is_enforced(self):
        from fundpilot.diagnostic_grant import verify_bindings
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);old,a=self.fixture(r);b=grant(old,a);seed=b.snapshot()['seed']
            good=r/'protocol';sha=hashlib.sha256(good.read_bytes()).hexdigest()
            verify_bindings(seed,evidence_path=good,input_sha256=sha)
            with self.assertRaisesRegex(ValueError,'outside'):verify_bindings(seed,evidence_path=r/'other',input_sha256=sha)
            good.write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed'):verify_bindings(seed,input_sha256=sha)

    def test_scope_cap_one_evaluation_and_no_candidate_source_or_retry(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);old,a=self.fixture(r);original=old.read_bytes();b=grant(old,a)
            b.require('batch','prediction_batch')
            for n in range(12):
                b.require(f'q{n}','llm');b.require(f'a{n}','checkpoint_resume',parent=f'q{n}')
            self.assertEqual(b.reserve('q13','llm'),'skip_partial')
            b.require('evaluation','diagnostic_evaluation',parent='batch')
            self.assertEqual(b.reserve('evaluation2','diagnostic_evaluation',parent='batch'),'skip_partial')
            for kind in ('candidate','source','retry','evaluation'):
                self.assertEqual(b.reserve('blocked-'+kind,kind),'skip_partial')
            self.assertEqual(old.read_bytes(),original)

    def test_claimed_crash_does_not_reissue(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);old,a=self.fixture(r);b=grant(old,a);b.path.unlink()
            with sqlite3.connect(r/'diagnostic-grants.sqlite') as c:c.execute("UPDATE grants SET status='claimed'")
            with self.assertRaisesRegex(ValueError,'pending'):grant(old,a)
            self.assertFalse(b.path.exists())
