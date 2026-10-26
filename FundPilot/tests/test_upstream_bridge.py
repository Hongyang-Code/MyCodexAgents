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

@unittest.skipUnless(os.environ.get('FUND_PILOT_UPSTREAM') and importlib.util.find_spec('langgraph'),
                     'actual pinned native book and graph required')
class NativeComparisonWiringTests(unittest.TestCase):
    def test_full_native_flow_and_minimal_analyst_call_floor(self):
        from fundpilot.comparison_wiring import tradingagents_native
        for analysts,expected in [(('market','social','news','fundamentals'),12),(('news',),9)]:
            r=tradingagents_native(os.environ['FUND_PILOT_UPSTREAM'],analysts,synthetic_assets=50 if len(analysts)==1 else 3)
            if len(analysts)==1:self.assertIn('900049',r['calls'][-1]['prompt'])
            self.assertEqual(r['fixture_model_requests'],expected)
            self.assertEqual(r['network_attempts'],[])
            self.assertEqual(r['research_debate_turns'],2);self.assertEqual(r['risk_debate_turns'],3)

    def test_upstream_full_book_render_and_native_recovery_signature(self):
        from types import SimpleNamespace
        from fundpilot.ledger import Ledger
        from fundpilot.portfolio import PortfolioManager
        from fundpilot.comparison_wiring import native_portfolio_view
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        proof={'source':'SYNTHETIC full inventory','confidence':{'as_of':'1','positions':'1','cash':'1'}}
        for count in (10,20,50):
            ledger=Ledger(':memory:');p=PortfolioManager(ledger)
            p.import_snapshot('all',{'as_of':'2020-01-01T00:00:00Z','positions':[{'code':f'{i+1:06d}','units':'10'} for i in range(count)]},proof)
            v=native_portfolio_view(p,'000001',coverage='complete')
            self.assertEqual(len(v['native'].positions),count);self.assertIsNone(v['native'].cash)
            self.assertIn(f'{count:06d}',v['context']);self.assertNotIn('Cash available: 0',v['context'])
            wrapper=SimpleNamespace(config={'max_debate_rounds':1,'max_risk_discuss_rounds':1},selected_analysts=['news'])
            old=TradingAgentsGraph._run_signature(wrapper,'fund',v['native'])
            v['native'].positions[-1].quantity=11
            self.assertNotEqual(old,TradingAgentsGraph._run_signature(wrapper,'fund',v['native']))
            p.submit_trade('synthetic-frozen','sell','000002',units='1',evidence=proof)
            frozen=native_portfolio_view(p,'000001',coverage='complete')
            self.assertNotEqual(old,TradingAgentsGraph._run_signature(wrapper,'fund',frozen['native']))
            with self.assertRaises(ValueError):native_portfolio_view(p,'000001',coverage='partial',unresolved=[{'id':'SYNTHETIC_UNKNOWN','units':None}])
            ledger.close()

@unittest.skipUnless(os.environ.get('FUND_PILOT_UPSTREAM') and importlib.util.find_spec('langgraph'),
                     'actual pinned native graph required; no live inference')
class NativeHostBoundaryTests(unittest.TestCase):
    def command(self,*args):
        return subprocess.run([sys.executable,'-m','fundpilot.upstream_bridge',*map(str,args),
            '--upstream',os.environ['FUND_PILOT_UPSTREAM']],check=True,capture_output=True,text=True)

    def evidence(self,root):
        p=root/'evidence.json';book='SYNTHETIC full observation book: '+','.join(f'{900000+i}:unknown' for i in range(50))
        write_new(p,{'fund':'SYNTHETIC_BASKET','information_cutoff':'2020-01-01',
            'market_report':'SYNTHETIC source M1, historical only','fundamentals_report':'unknown',
            'portfolio_context':book,'context':book})
        return p

    def answer(self,root,graph,n):
        from fundpilot.upstream_bridge import now
        q=json.loads((graph/f'request-{n}.json').read_bytes());p=root/f'{graph.name}-answer-{n}.json'
        write_new(p,{'producer':'synthetic_fixture','model_ref':'SYNTHETIC_NOT_REAL_LLM',
            'prompt_sha256':q['prompt_sha256'],'generated_at':now(),'content':f'Hold\nSYNTHETIC unique answer {graph.name} {n}; unknown'})
        return p

    def test_shared_three_plus_nine_cross_process_closed_restore_and_replay(self):
        """One batch, exactly 12 charged requests, no candidate; all stages native."""
        from fundpilot.upstream_bridge import resume
        from fundpilot.native_host import ROLES
        import shutil
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);e=self.evidence(r);b=synthetic_budget(r);stable=r/'stable';native=r/'native'
            self.command('start','--evidence',e,'--output',stable,'--budget',b,'--operation-id','stable')
            for n in range(1,4):self.command('resume','--root',stable,'--response',self.answer(r,stable,n))
            self.command('start','--graph-mode','native_news','--comparison-root',stable,
                '--evidence',e,'--output',native,'--budget',b,'--operation-id','native')
            # Close processes, preserve original bytes, restore at canonical paths.
            preserved=r/'preserved';preserved.mkdir(mode=0o700)
            shutil.copytree(native,preserved/'native');shutil.copy2(b,preserved/'budget.sqlite')
            original_budget=b.read_bytes()
            shutil.rmtree(native);shutil.copytree(preserved/'native',native)
            b.unlink();shutil.copy2(preserved/'budget.sqlite',b)
            for n,role in enumerate(ROLES,1):
                q=json.loads((native/f'request-{n}.json').read_bytes())
                self.assertEqual(q['role'],role);self.assertIn('900049',q['prompt'])
                self.assertIn('native_prompt_sha256',q)
                a=self.answer(r,native,n)
                if n==2:
                    prior=native/'response-1.json';original=prior.read_bytes()
                    o=json.loads(original);o['model_ref']='TAMPER';prior.write_text(json.dumps(o))
                    with self.assertRaisesRegex(ValueError,'response chain'):resume(native,a,os.environ['FUND_PILOT_UPSTREAM'])
                    self.assertFalse((native/'response-2.json').exists());prior.write_bytes(original)
                self.command('resume','--root',native,'--response',a)
            result=json.loads((native/'result.json').read_bytes())
            self.assertEqual(result['bridge_responses'],9)
            self.assertEqual(result['response_producers'],['synthetic_fixture']*9)
            self.assertEqual(result['research_state']['risk_debate_state']['count'],3)
            self.assertEqual(result['research_state']['investment_debate_state']['count'],2)
            self.assertFalse(result['native_upstream_llm_api_called'])
            ops=DurableBudget(b).snapshot()['operations']
            self.assertEqual(sum(o['kind']=='llm' for o in ops),12)
            self.assertEqual(sum(o['kind']=='prediction_batch' for o in ops),1)
            self.assertEqual(sum(o['kind']=='comparison_arm' for o in ops),1)
            self.assertFalse(any(o['kind']=='candidate' for o in ops))
            self.assertEqual(DurableBudget(b).reserve('thirteenth','llm'),'skip_partial')
            self.assertEqual((preserved/'budget.sqlite').read_bytes(),original_budget)
            with self.assertRaises(subprocess.CalledProcessError):self.command('resume','--root',native,'--response',a)
            with self.assertRaises(subprocess.CalledProcessError):
                self.command('start','--graph-mode','native_news','--comparison-root',stable,
                    '--evidence',e,'--output',r/'again','--budget',b,'--operation-id','again')
            self.assertFalse((r/'again').exists())

    def test_native_unknown_usage_and_missing_book_fail_before_request_publication(self):
        from fundpilot.upstream_bridge import start
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);e=self.evidence(r);b=r/'unknown.sqlite';u=os.environ['FUND_PILOT_UPSTREAM']
            DurableBudget.create(b,run_id='synthetic-unknown',used=dict(source=None,retry=None,llm=None,prediction_batch=None),candidate_history=None)
            original=b.read_bytes()
            with self.assertRaisesRegex(ValueError,'unknown'):start(e,r/'absent',u,budget=b,operation_id='blocked',graph_mode='native_news')
            self.assertEqual(b.read_bytes(),original);self.assertFalse((r/'absent').exists())
            good=synthetic_budget(r);o=json.loads(e.read_bytes());del o['portfolio_context'];e.write_text(json.dumps(o))
            with self.assertRaisesRegex(ValueError,'observation book'):start(e,r/'absent',u,budget=good,operation_id='blocked',graph_mode='native_news')
            self.assertEqual(DurableBudget(good).snapshot()['operations'],[])
