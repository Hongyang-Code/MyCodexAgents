"""One shared synthetic scenario; no market result or real LLM claim."""
from decimal import Decimal as D
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from fundpilot.decision_value import evaluate


def sample():
    return json.loads((Path(__file__).parents[1]/'examples/decision-value.synthetic.json').read_text())


class DecisionValueTests(unittest.TestCase):
    def test_one_end_to_end_cli(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'input.json').write_text(json.dumps(sample()))
            subprocess.run([sys.executable,'-m','fundpilot.decision_value','--input',str(root/'input.json'),'--output',str(root/'result')],check=True,capture_output=True)
            r=json.loads((root/'result/results.json').read_text());c=r['outcomes']['candidate']
            self.assertEqual(r['outcomes']['cash']['terminal_book_equity'],'1000')
            self.assertAlmostEqual(D(c['terminal_book_equity']),D('974.2356435643564356435643564'))
            self.assertGreater(D(r['candidate_minus_baseline_terminal_equity']['buy_hold']),0)
            self.assertLess(D(r['candidate_minus_baseline_terminal_equity']['cash']),0)
            self.assertFalse(r['synthetic_value_improvement_and_risk_pass'])
            self.assertEqual(r['promotion'],'retain_stable_pending_unseen_validation')
            self.assertEqual((root/'result/results.json').stat().st_mode&0o777,0o600)
    def test_unknown_gain_and_direction_not_orders(self):
        p=sample();p['decisions'][0]['expected_gain_bps']=None
        with self.assertRaises(ValueError):evaluate(p)
        p=sample();p['decisions'][0]['action']='up'
        with self.assertRaises(ValueError):evaluate(p)
    def test_no_fake_real_evidence(self):
        p=sample();p['mode']='real'
        with self.assertRaises(ValueError):evaluate(p)
        p=sample();p['no_distributions_or_splits']=False
        with self.assertRaises(ValueError):evaluate(p)
    def test_cost_and_risk_gate(self):
        p=sample();p['decisions'][0]['expected_gain_bps']='300'
        with self.assertRaises(ValueError):evaluate(p)
        p=sample();p['risk']['max_cash_fees']='1'
        self.assertFalse(evaluate(p)['outcomes']['candidate']['risk_gates_passed'])
    def test_leverage_exposure_and_future_evidence(self):
        p=sample();p['decisions'][0]['quantity']='1001'
        with self.assertRaises(ValueError):evaluate(p)
        p=sample();p['risk']['max_exposure']='.3'
        with self.assertRaises(ValueError):evaluate(p)
        p=sample();p['decisions'][0]['evidence_cutoff']='2026-02-01T00:00:00Z'
        with self.assertRaises(ValueError):evaluate(p)
    def test_unknown_price_and_pending_cash(self):
        p=sample();p['opportunities'][0]['determined_at']=p['opportunities'][0]['at']
        with self.assertRaises(ValueError):evaluate(p)
        r=evaluate(sample());rows=r['outcomes']['candidate']['daily_assets']
        self.assertEqual(rows[2]['receivables'],'107.800')
        self.assertEqual(rows[2]['cash'],'600')
