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
            e.write_bytes(raw);call('start','--evidence',str(e),'--output',str(out))
            self.assertEqual((out/'input.json').read_bytes(),raw)
            self.assertEqual(json.loads((out/'receipt.json').read_text())['input_sha256'],hashlib.sha256(raw).hexdigest())
            for i,role in enumerate(('bull','bear','manager'),1):
                q=json.loads((out/f'request-{i}.json').read_text());self.assertEqual(q['role'],role)
                r=root/f'answer{i}.json';r.write_text(json.dumps({'producer':'synthetic_fixture',
                    'model_ref':'SYNTHETIC_NOT_LLM','generated_at':datetime.now(timezone.utc).isoformat(),
                    'prompt_sha256':q['prompt_sha256'],'content':'SYNTHETIC response only'}))
                if i==1:
                    bad=root/'bad.json';bad.write_text(r.read_text().replace(q['prompt_sha256'],'0'*64))
                    with self.assertRaises(subprocess.CalledProcessError):call('resume','--root',str(out),'--response',str(bad))
                    self.assertFalse((out/'response-1.json').exists())
                call('resume','--root',str(out),'--response',str(r))
            result=json.loads((out/'result.json').read_text())
            self.assertEqual(result['bridge_responses'],3)
            self.assertEqual(result['response_producers'],['synthetic_fixture']*3)
            self.assertEqual(result['research_state']['investment_debate_state']['count'],2)
            self.assertFalse(result['native_upstream_llm_api_called'])
            with self.assertRaises(subprocess.CalledProcessError):call('resume','--root',str(out),'--response',str(r))
