"""Synthetic numeric checks only; real historical LLM study runs privately elsewhere."""
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from fundpilot.conditional_value import evaluate, run


def fixture():
    a={'no_cash_distributions_and_no_splits':True,'entry_price_rule':'entry_date_nav_hypothesis',
       'exit_price_rule':'end_nav_same_price_hypothesis',
       'costs':{f:{'buy_rate':'.1','exit_rate':'.1','buy_fee_basis':'net','holding_period_condition':'synthetic fixed rate, not actual tier'} for f in ('A','B')},
       'entry_confirmation_dates':{'A':None,'B':None},'exit_confirmation_dates':{'A':None,'B':None},'exit_receipt_date':None}
    p={'mode':'retrospective_conditional','frozen_at':'2026-03-02T00:00:00Z','funds':['A','B'],
       'valuation_dates':['2026-01-02','2026-01-03','2026-01-06'],'entry_date':'2026-01-02','end_date':'2026-01-06',
       'valuation_dates_evidence_ref':'synthetic irregular dates, not an exchange calendar','initial_cash':'1000',
       'risk':{'max_exposure':'1','max_drawdown':'.5','max_cash_fees':'300','no_leverage':True},
       'assumptions':a,'known_distribution_events':[],'known_split_events':[],
       'unknown_evidence':{k:'synthetic limitation, no actual evidence' for k in ('fees','distributions','confirmation','receipt','channel')}}
    d={'decision_kind':'explicit_llm_allocation','producer':'synthetic_fixture','rationale':'synthetic allocation',
       'no_action_counterfactual':'cash zero interest','cost_coverage_assessment':'unproven, test fixed assumptions',
       'model_ref':'synthetic-not-LLM','prompt_version':'fixture','frozen_at':'2026-03-01T00:00:00Z',
       'entry_date':'2026-01-02','end_date':'2026-01-06','information_cutoff':'2026-01-01T21:30:00+08:00','evidence_refs':['synthetic snapshot'],
       'initial_cash':'1000','cash_amount':'500','allocations':{'A':'500','B':'0'}}
    s=[{'id':'source','url':'https://example.org/synthetic','snapshot_sha256':'a'*64,'snapshot_kind':'structured_summary',
        'retrieved_at':'2026-02-01T00:00:00Z','known_available_at':'2026-02-01T00:00:00Z','reviewed':True}]
    lines=['fund,date,nav,source_id,retrieved_at,known_available_at']
    for f,values in [('A',['10','9','12']),('B',['20','21','18'])]:
        for day,value in zip(p['valuation_dates'],values):
            lines.append(f'{f},{day},{value},source,2026-02-01T00:00:00Z,2026-02-01T00:00:00Z')
    return p,d,('\n'.join(lines)+'\n').encode(),s


class ConditionalValueTests(unittest.TestCase):
    def test_fixed_conditional_math_and_cash_not_receipt(self):
        p,d,n,s=fixture();r=evaluate(p,d,n,s);c=r['outcomes']['llm_allocation']
        self.assertAlmostEqual(D(c['pre_liquidation_nav_mark']['book_equity']),D('1045.454545454545454545454545'))
        self.assertAlmostEqual(D(c['liquidation_scenario']['conditional_equity_after_exit_fee']),D('990.9090909090909090909090909'))
        self.assertEqual(c['liquidation_scenario']['available_cash_at_window_end'],'500')
        self.assertIsNone(c['liquidation_scenario']['conditional_cash_if_assumed_receipt_occurs'])
        self.assertGreater(D(c['pre_liquidation_nav_mark']['modeled_units_pending_confirmation_value']),0)
        self.assertEqual(r['outcomes']['cash']['pre_liquidation_nav_mark']['book_equity'],'1000')
        self.assertEqual(r['outcomes']['cash']['liquidation_scenario']['conditional_liquidation_status'],
                         'not_applicable_no_risky_units')
        self.assertEqual(r['promotion'],'retain_stable');self.assertFalse(r['independent_oos'])
        self.assertTrue(all(row['not_actual_fund_total_return'] for row in c['daily_curve']))
    def test_costs_and_time_shared_with_equal_weight(self):
        p,d,n,s=fixture();d['allocations']={'A':'500','B':'500'};d['cash_amount']='0'
        r=evaluate(p,d,n,s)
        self.assertEqual(r['outcomes']['llm_allocation'],r['outcomes']['equal_weight_buy_hold'])
    def test_missing_rates_and_unknown_receipt_not_zero(self):
        p,d,n,s=fixture();del p['assumptions']['costs']['A']['exit_rate']
        with self.assertRaises((KeyError,ValueError)):evaluate(p,d,n,s)
        p,d,n,s=fixture();del p['assumptions']['exit_receipt_date']
        with self.assertRaises(ValueError):evaluate(p,d,n,s)
    def test_known_dividend_and_missing_nav_rejected(self):
        p,d,n,s=fixture();p['known_distribution_events']=['known dividend']
        with self.assertRaises(ValueError):evaluate(p,d,n,s)
        p,d,n,s=fixture();n=b'\n'.join(n.splitlines()[:-1])+b'\n'
        with self.assertRaisesRegex(ValueError,'missing NAV'):evaluate(p,d,n,s)
    def test_no_direction_conversion_or_leverage(self):
        p,d,n,s=fixture();d['decision_kind']='direction_card'
        with self.assertRaises(ValueError):evaluate(p,d,n,s)
        p,d,n,s=fixture();d['allocations']['A']='501'
        with self.assertRaises(ValueError):evaluate(p,d,n,s)
        p,d,n,s=fixture();p['mode']='prospective'
        with self.assertRaises(ValueError):evaluate(p,d,n,s)
    def test_holding_calendar_days_and_assumed_receipt(self):
        p,d,n,s=fixture();a=p['assumptions'];a['entry_confirmation_dates']={'A':'2026-01-03','B':'2026-01-03'}
        a['exit_confirmation_dates']={'A':'2026-01-07','B':'2026-01-07'};a['exit_receipt_date']='2026-01-10'
        r=evaluate(p,d,n,s);self.assertEqual(r['conditional_holding_calendar_days']['A'],4)
        c=r['outcomes']['llm_allocation']['liquidation_scenario']
        self.assertEqual(c['available_cash_at_window_end'],'500')
        self.assertIsNotNone(c['conditional_cash_if_assumed_receipt_occurs'])
        a['exit_receipt_date']='2026-01-06'
        with self.assertRaises(ValueError):evaluate(p,d,n,s)
    def test_hashes_and_cli(self):
        p,d,n,s=fixture()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);raw={'decision':json.dumps(d).encode(),'nav':n,'sources':json.dumps(s).encode()}
            p['input_sha256']={k:hashlib.sha256(v).hexdigest() for k,v in raw.items()}
            raw['protocol']=json.dumps(p).encode()
            for k,v in raw.items():(root/k).write_bytes(v)
            sha=hashlib.sha256(raw['protocol']).hexdigest()
            subprocess.run([sys.executable,'-m','fundpilot.conditional_value','--protocol',str(root/'protocol'),
                '--protocol-sha256',sha,'--decision',str(root/'decision'),'--nav',str(root/'nav'),
                '--sources',str(root/'sources'),'--output',str(root/'output')],check=True,capture_output=True)
            self.assertTrue((root/'output/manifest.json').is_file())
            self.assertEqual((root/'output/results.json').stat().st_mode&0o777,0o600)
            (root/'decision').write_text('{}')
            with self.assertRaisesRegex(ValueError,'decision hash'):
                run(root/'protocol',sha,root/'decision',root/'nav',root/'sources',root/'other')
    def test_duplicate_nav_and_bad_actual_time(self):
        p,d,n,s=fixture();n+=n.splitlines()[1]+b'\n'
        with self.assertRaisesRegex(ValueError,'duplicate NAV'):evaluate(p,d,n,s)
        p,d,n,s=fixture();s[0]['known_available_at']='2026-01-01T00:00:00Z'
        with self.assertRaises(ValueError):evaluate(p,d,n,s)

    def test_all_cash_never_claims_active_profit(self):
        p,d,n,s=fixture();d['allocations']={'A':'0','B':'0'};d['cash_amount']='1000'
        r=evaluate(p,d,n,s)
        self.assertEqual(r['outcomes']['llm_allocation'],r['outcomes']['cash'])
        self.assertEqual(r['same_scenario_comparisons']['against_cash']['pre_liquidation_difference'],'0')
        self.assertGreater(D(r['same_scenario_comparisons']['against_equal_weight']['pre_liquidation_difference']),0)
        self.assertEqual(r['risky_allocation_fraction'],'0');self.assertTrue(r['cash_equivalent_allocation'])
        self.assertFalse(r['active_profitability_validated']);self.assertEqual(r['promotion'],'retain_stable')
        self.assertEqual(r['outcomes']['llm_allocation']['liquidation_scenario']['conditional_liquidation_status'],
                         'not_applicable_no_risky_units')

    def test_frozen_window_cannot_be_changed(self):
        p,d,n,s=fixture();d['end_date']='2026-01-03'
        with self.assertRaisesRegex(ValueError,'holding window'):evaluate(p,d,n,s)
        p,d,n,s=fixture();p['frozen_at']='2026-03-02T00:00:00Z';s[0]['known_available_at']='2026-03-03T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'protocol freeze'):evaluate(p,d,n,s)
