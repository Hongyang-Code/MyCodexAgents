"""Synthetic bridge transport and actual optional upstream graph tests."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from fundpilot.upstream_bridge import fund_prompt, write_new
from fundpilot.durable_budget import DurableBudget

def synthetic_budget(root):
    p=Path(root)/"budget.sqlite"
    DurableBudget.create(p,run_id="synthetic-run",used=dict(source=0,retry=0,llm=0,prediction_batch=0),candidate_history=[])
    return p


class BridgeContractTests(unittest.TestCase):
    def test_stock_prompt_is_replaced_but_evidence_retained(self):
        text=fund_prompt('bull','stock growth potential\nResources available: SYNTHETIC_EVIDENCE\nUse this information to deliver an argument')
        self.assertIn('SYNTHETIC_EVIDENCE',text)
        self.assertNotIn('stock growth potential',text)
        self.assertIn('NAV-internal',text)
        self.assertIn('unknown-price',text)

    def test_upstream_prompt_drift_fails_closed(self):
        with self.assertRaises(ValueError):fund_prompt('bull','unexpected prompt')
        with self.assertRaises(ValueError):fund_prompt('manager','unexpected prompt')

    def test_new_artifacts_never_overwrite_and_are_private(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'artifact.json';sha=write_new(p,{'synthetic':True})
            self.assertEqual(sha,hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):write_new(p,{})

@unittest.skipUnless(os.environ.get('FUND_PILOT_UPSTREAM') and importlib.util.find_spec('langgraph'),
                     'optional pinned upstream integration; no fake dependency substitute')
class ActualUpstreamGraphTests(unittest.TestCase):
    def test_separate_process_checkpoint_resume_and_input_bytes(self):
        upstream=os.environ['FUND_PILOT_UPSTREAM']
        def call(*args):
            return subprocess.run([sys.executable,'-m','fundpilot.upstream_bridge',*args,
                                   '--upstream',upstream],check=True,capture_output=True,text=True)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e=root/'evidence.json';out=root/'graph'
            raw=b'{ "fund":"SYNTHETIC:unknown", "information_cutoff":"2020-01-01", "market_report":"SYNTHETIC DATA ONLY", "fundamentals_report":"unknown" }\n'
            e.write_bytes(raw);e.chmod(0o600);budget=synthetic_budget(root)
            call('start','--evidence',str(e),'--output',str(out),'--budget',str(budget),'--operation-id','synthetic-graph')
            self.assertEqual((out/'input.json').read_bytes(),raw)
            self.assertEqual(json.loads((out/'receipt.json').read_text())['input_sha256'],hashlib.sha256(raw).hexdigest())
            for i,role in enumerate(('bull','bear','manager'),1):
                q=json.loads((out/f'request-{i}.json').read_text());self.assertEqual(q['role'],role)
                r=root/f'answer{i}.json';r.write_text(json.dumps({'producer':'synthetic_fixture',
                    'model_ref':'SYNTHETIC_NOT_LLM','generated_at':datetime.now(timezone.utc).isoformat(),
                    'prompt_sha256':q['prompt_sha256'],'content':'SYNTHETIC response only'}))
                r.chmod(0o600)
                if i==1:
                    bad=root/'bad.json';bad.write_text(r.read_text().replace(q['prompt_sha256'],'0'*64))
                    bad.chmod(0o600)
                    with self.assertRaises(subprocess.CalledProcessError):call('resume','--root',str(out),'--response',str(bad))
                    self.assertFalse((out/'response-1.json').exists())
                call('resume','--root',str(out),'--response',str(r))
            result=json.loads((out/'result.json').read_text())
            self.assertEqual(result['bridge_responses'],3)
            self.assertEqual(result['response_producers'],['synthetic_fixture']*3)
            self.assertEqual(result['research_state']['investment_debate_state']['count'],2)
            self.assertFalse(result['native_upstream_llm_api_called'])
            with self.assertRaises(subprocess.CalledProcessError):call('resume','--root',str(out),'--response',str(r))

class PrivateBoundaryTests(unittest.TestCase):
    def test_checkout_inputs_and_outputs_rejected(self):
        from fundpilot.upstream_bridge import read_private
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);repo=root/'repo';repo.mkdir(mode=0o700);(repo/'.git').mkdir()
            inp=repo/'private.json';inp.write_bytes(b'{}');inp.chmod(0o600)
            with self.assertRaisesRegex(ValueError,'checkout'):read_private(inp)
            with self.assertRaisesRegex(ValueError,'checkout'):write_new(repo/'new.json',{})
            self.assertFalse((repo/'new.json').exists())

    def test_symbolic_parent_and_leaf_rejected(self):
        from fundpilot.upstream_bridge import read_private
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);real=root/'real';real.mkdir(mode=0o700)
            f=real/'data';f.write_bytes(b'{}');f.chmod(0o600)
            (root/'alias').symlink_to(real,target_is_directory=True)
            (real/'link').symlink_to(f)
            for path in (root/'alias/data',real/'link'):
                with self.assertRaises((OSError,ValueError)):read_private(path)
            with self.assertRaises((OSError,ValueError)):write_new(root/'alias/new',{})

    def test_nonprivate_parent_file_and_hardlink_rejected(self):
        from fundpilot.upstream_bridge import read_private
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);f=root/'data';f.write_bytes(b'{}');f.chmod(0o600)
            root.chmod(0o755)
            with self.assertRaises(ValueError):read_private(f)
            with self.assertRaises(ValueError):write_new(root/'new',{})
            root.chmod(0o700);f.chmod(0o644)
            with self.assertRaises(ValueError):read_private(f)
            f.chmod(0o600);os.link(f,root/'hardlink')
            with self.assertRaises(ValueError):read_private(f)

    def test_nonregular_input_rejected_without_blocking(self):
        from fundpilot.upstream_bridge import read_private
        with tempfile.TemporaryDirectory() as td:
            fifo=Path(td)/'fifo';os.mkfifo(fifo,0o600)
            with self.assertRaises(ValueError):read_private(fifo)


@unittest.skipUnless(os.environ.get('FUND_PILOT_UPSTREAM') and importlib.util.find_spec('langgraph'),
                     'requires real pinned graph, no model requests')
class RecoveryEvidenceTests(unittest.TestCase):
    def test_tampering_rejected_before_consuming_response_and_original_time_survives_replay(self):
        from fundpilot.upstream_bridge import start,resume,opened,config
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e=root/'evidence';out=root/'graph';upstream=os.environ['FUND_PILOT_UPSTREAM']
            e.write_text(json.dumps({'fund':'SYNTHETIC','information_cutoff':'2020-01-01',
                'market_report':'SYNTHETIC original','fundamentals_report':'unknown'}));e.chmod(0o600)
            start(e,out,upstream,budget=synthetic_budget(root),operation_id="synthetic-graph")
            q=json.loads((out/'request-1.json').read_text());answer=root/'answer'
            response={'producer':'synthetic_fixture','model_ref':'SYNTHETIC',
                'generated_at':q['captured_at'],'prompt_sha256':q['prompt_sha256'],'content':'SYNTHETIC response'}
            def save():answer.write_text(json.dumps(response));answer.chmod(0o600)
            save()
            for name,change in [('input.json',lambda o:{**o,'market_report':'TAMPER'}),
                                ('receipt.json',lambda o:{**o,'actual_started_at':'2000-01-01T00:00:00Z'}),
                                ('request-1.json',lambda o:{**o,'captured_at':'2000-01-01T00:00:00Z'}),
                                ('request-1.json',lambda o:{**o,'prompt':'TAMPER'}),
                                ('request-1.json',lambda o:{**o,'checkpoint_id':'wrong'})]:
                f=out/name;original=f.read_bytes();f.write_text(json.dumps(change(json.loads(original))))
                with self.assertRaises(ValueError,msg=name):resume(out,answer,upstream)
                self.assertFalse((out/'response-1.json').exists());f.write_bytes(original)
            # Changing input and receipt together still differs from checkpoint metadata.
            inp=out/'input.json';rec=out/'receipt.json';old_input=inp.read_bytes();old_receipt=rec.read_bytes()
            inp.write_bytes(old_input+b' ');r=json.loads(old_receipt);r['input_sha256']=hashlib.sha256(inp.read_bytes()).hexdigest();rec.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'checkpoint metadata'):resume(out,answer,upstream)
            inp.write_bytes(old_input);rec.write_bytes(old_receipt)
            response['generated_at']='2000-01-01T00:00:00Z';save()
            with self.assertRaisesRegex(ValueError,'persisted request capture'):resume(out,answer,upstream)
            self.assertFalse((out/'response-1.json').exists())
            # Exact original capture time is legitimate even though replay is later.
            response['generated_at']=q['captured_at'];save();resume(out,answer,upstream)
            self.assertTrue((out/'response-1.json').exists());self.assertTrue((out/'request-2.json').exists())
            # Earlier requests and responses are rechecked, not just the active file.
            for filename, field in [('request-1.json','prompt'),('response-1.json','content')]:
                f=out/filename;original=f.read_bytes();obj=json.loads(original);obj[field]='TAMPER';f.write_text(json.dumps(obj))
                with self.assertRaises(ValueError):resume(out,answer,upstream)
                self.assertFalse((out/'response-2.json').exists());f.write_bytes(original)
            # Modify the next active checkpoint; no unsafe SQLite file-copy rollback.
            with opened(out,upstream) as graph:graph.update_state(config(out),{'market_report':'TAMPER'})
            with self.assertRaisesRegex(ValueError,'checkpoint input evidence'):resume(out,answer,upstream)

    def test_unsafe_checkpoint_and_response_links_rejected(self):
        from fundpilot.upstream_bridge import start,resume
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e=root/'e';out=root/'graph';u=os.environ['FUND_PILOT_UPSTREAM']
            e.write_text(json.dumps({'fund':'SYNTHETIC','information_cutoff':'2020-01-01',
                'market_report':'SYNTHETIC','fundamentals_report':'unknown'}));e.chmod(0o600);start(e,out,u,budget=synthetic_budget(root),operation_id="synthetic-graph")
            q=json.loads((out/'request-1.json').read_text());a=root/'answer';a.write_text(json.dumps({
                'producer':'synthetic_fixture','model_ref':'SYNTHETIC','content':'SYNTHETIC',
                'prompt_sha256':q['prompt_sha256'],'generated_at':q['captured_at']}));a.chmod(0o600)
            alias=root/'alias';alias.symlink_to(a)
            with self.assertRaises((OSError,ValueError)):resume(out,alias,u)
            os.link(a,root/'hard-answer')
            with self.assertRaises(ValueError):resume(out,a,u)
            (root/'hard-answer').unlink()
            db=out/'graph.sqlite';os.link(db,root/'hard-db')
            with self.assertRaises(ValueError):resume(out,a,u)
            self.assertFalse((out/'response-1.json').exists())

@unittest.skipUnless(os.environ.get('FUND_PILOT_UPSTREAM') and importlib.util.find_spec('langgraph'),
                     'requires actual pinned graph; synthetic responses only')
class AtomicBridgeBudgetTests(unittest.TestCase):
    def fixture(self,root):
        evidence=root/'evidence';evidence.write_text(json.dumps({'fund':'SYNTHETIC',
            'information_cutoff':'2020-01-01','market_report':'SYNTHETIC','fundamentals_report':'unknown'}))
        evidence.chmod(0o600)
        return evidence,synthetic_budget(root),os.environ['FUND_PILOT_UPSTREAM']

    def test_unknown_usage_and_missing_budget_reject_before_graph_creation(self):
        from fundpilot.upstream_bridge import start
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e,b,u=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'shared budget'):start(e,root/'absent',u)
            self.assertFalse((root/'absent').exists())
            unknown=root/'unknown.sqlite'
            DurableBudget.create(unknown,run_id='synthetic-unknown',used=dict(source=None,retry=None,llm=None,prediction_batch=None),candidate_history=None)
            with self.assertRaisesRegex(ValueError,'unknown'):start(e,root/'absent',u,budget=unknown,operation_id='one')
            self.assertFalse((root/'absent').exists())

    def test_thirteen_competing_starts_share_one_batch_and_resume_replay_is_consumed_once(self):
        from fundpilot.upstream_bridge import resume
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e,b,u=self.fixture(root);out=root/'graph'
            cmd=[sys.executable,'-m','fundpilot.upstream_bridge','start','--evidence',str(e),
                 '--output',str(out),'--upstream',u,'--budget',str(b),'--operation-id','same-start']
            ps=[subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(13)]
            results=[(p.communicate(timeout=60),p.returncode) for p in ps]
            self.assertEqual(sum(rc==0 for _,rc in results),1,results)
            state=DurableBudget(b).snapshot()
            self.assertEqual(sum(o['kind']=='prediction_batch' for o in state['operations']),1)
            self.assertEqual(sum(o['kind']=='llm' for o in state['operations']),1)
            q=json.loads((out/'request-1.json').read_bytes());a=root/'answer'
            a.write_text(json.dumps({'producer':'synthetic_fixture','model_ref':'SYNTHETIC',
                'generated_at':q['captured_at'],'prompt_sha256':q['prompt_sha256'],'content':'SYNTHETIC'}));a.chmod(0o600)
            cmd=[sys.executable,'-m','fundpilot.upstream_bridge','resume','--root',str(out),'--response',str(a),'--upstream',u]
            ps=[subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(3)]
            results=[(p.communicate(timeout=60),p.returncode) for p in ps]
            self.assertEqual(sum(rc==0 for _,rc in results),1,results)
            state=DurableBudget(b).snapshot()
            self.assertEqual(sum(o['kind']=='checkpoint_resume' for o in state['operations']),1)
            self.assertEqual(sum(o['kind']=='llm' for o in state['operations']),2)
            with self.assertRaises(ValueError):resume(out,a,u)
            before=(out/'response-1.json').read_bytes()
            DurableBudget(b).stop('synthetic platform warning')
            q=json.loads((out/'request-2.json').read_bytes());a.write_text(json.dumps({'producer':'synthetic_fixture',
                'model_ref':'SYNTHETIC','generated_at':q['captured_at'],'prompt_sha256':q['prompt_sha256'],'content':'SYNTHETIC'}))
            with self.assertRaisesRegex(ValueError,'stop'):resume(out,a,u)
            self.assertFalse((out/'response-2.json').exists());self.assertEqual((out/'response-1.json').read_bytes(),before)

    def test_crash_after_resume_claim_is_not_automatically_reexecuted(self):
        from fundpilot.upstream_bridge import start,resume,digest
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e,b,u=self.fixture(root);out=root/'graph'
            start(e,out,u,budget=b,operation_id='synthetic-start')
            q=json.loads((out/'request-1.json').read_bytes());a=root/'answer'
            a.write_text(json.dumps({'producer':'synthetic_fixture','model_ref':'SYNTHETIC','content':'SYNTHETIC',
                'generated_at':q['captured_at'],'prompt_sha256':q['prompt_sha256']}));a.chmod(0o600)
            # Same durable state a process leaves if it crashes after commit, before graph/file writes.
            DurableBudget(b).require('synthetic-start/response/1','checkpoint_resume',
                parent='synthetic-start/request/1',payload={'response_sha256':digest(a.read_bytes())})
            with self.assertRaisesRegex(ValueError,'already_reserved'):resume(out,a,u)
            self.assertFalse((out/'response-1.json').exists());self.assertFalse((out/'request-2.json').exists())

    def test_recreated_budget_cannot_replace_checkpoint_binding(self):
        from fundpilot.upstream_bridge import start,resume
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e,b,u=self.fixture(root);out=root/'graph'
            start(e,out,u,budget=b,operation_id='synthetic-start')
            q=json.loads((out/'request-1.json').read_bytes());a=root/'answer'
            a.write_text(json.dumps({'producer':'synthetic_fixture','model_ref':'SYNTHETIC','content':'SYNTHETIC',
                'generated_at':q['captured_at'],'prompt_sha256':q['prompt_sha256']}));a.chmod(0o600)
            b.rename(root/'preserved-original-budget.sqlite')
            # Even a replacement with the same declared run ID gets another ledger identity.
            synthetic_budget(root)
            with self.assertRaisesRegex(ValueError,'budget identity mismatch'):resume(out,a,u)
            self.assertFalse((out/'response-1.json').exists())

    def test_closed_private_snapshot_restored_at_same_paths_then_three_process_resumes(self):
        """Restore a pending graph and its charged ledger, never a fresh zero seed."""
        import zipfile
        from fundpilot.upstream_bridge import start
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e,b,u=self.fixture(root);out=root/'graph'
            start(e,out,u,budget=b,operation_id='synthetic-custody')
            original={p.name:p.read_bytes() for p in out.iterdir()}
            ledger_raw=b.read_bytes();archive=root/'closed-private-checkpoint.zip'
            with zipfile.ZipFile(archive,'w') as z:
                for name,raw in original.items():z.writestr('graph/'+name,raw)
                z.writestr('budget.sqlite',ledger_raw)
            out.rename(root/'preserved-original-graph');b.rename(root/'preserved-original-budget.sqlite')
            out.mkdir(mode=0o700)
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                for name,raw in original.items():
                    self.assertEqual(z.read('graph/'+name),raw)
                    f=out/name;f.write_bytes(z.read('graph/'+name));f.chmod(0o600)
                b.write_bytes(z.read('budget.sqlite'));b.chmod(0o600)
            self.assertEqual(b.read_bytes(),ledger_raw)
            self.assertEqual(len(DurableBudget(b).snapshot()['operations']),2)
            for n in (1,2,3):
                q=json.loads((out/f'request-{n}.json').read_bytes());answer=root/f'answer-{n}.json'
                answer.write_text(json.dumps({'producer':'synthetic_fixture','model_ref':'SYNTHETIC_NOT_LLM',
                    'prompt_sha256':q['prompt_sha256'],'generated_at':datetime.now(timezone.utc).isoformat(),
                    'content':'SYNTHETIC restored checkpoint response'}));answer.chmod(0o600)
                subprocess.run([sys.executable,'-m','fundpilot.upstream_bridge','resume','--root',str(out),
                    '--response',str(answer),'--upstream',u],check=True,capture_output=True,text=True)
            result=json.loads((out/'result.json').read_bytes())
            self.assertEqual(result['response_producers'],['synthetic_fixture']*3)
            self.assertEqual(result['bridge_responses'],3)
            self.assertEqual((root/'preserved-original-budget.sqlite').read_bytes(),ledger_raw)
            for name,raw in original.items():self.assertEqual((root/'preserved-original-graph'/name).read_bytes(),raw)
