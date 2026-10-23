"""Synthetic cadence and review regressions; no market results."""
import copy
from datetime import date
from decimal import localcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_history_batch import fixture
from fundpilot.history_batch import load_input,simulate,run,digest,CONDITIONAL_ASSUMPTION
from fundpilot.improvement import checkpoints,review_record


def protocol():
    p=dict(iteration=1,candidate='trend20_weekly',evaluation_role='reused_development',independent_oos=False,
           prior_prediction_and_strategy_outcomes_seen=True,status='frozen_for_implementation',
           budget=dict(new_candidate_count=1,new_scenario_count=18,parameter_search=False))
    for k in ('frozen_at','registration_boundary','one_change','calendar_definition','blocked_checkpoint','sign_semantics','acceptance','future_promotion'):
        p[k]='Synthetic protocol test; no market claim'
    return p


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.p,self.config,self.sha=fixture(self.root)
        _,self.assets,_=load_input(self.root/'input.json',self.p)

    def sim(self,strategy='trend20_weekly',settle=3):
        return simulate(self.assets,self.p,strategy,1,settle,20,improvement_enabled=True)

    def test_iso_year_holiday_midweek(self):
        days=[date.fromisoformat(x) for x in ('2025-12-31','2026-01-01','2026-01-06','2026-01-07','2026-01-12')]
        self.assertEqual(checkpoints(days),{days[0],days[2],days[4]})

    def test_checkpoint_pending_no_catchup_and_settlement_continues(self):
        r=self.sim();rows=r['transactions']
        self.assertTrue(any(x['event']=='decision_skipped' and x.get('reason')=='pending_orders_or_settlement' for x in rows))
        checks={x['date'] for x in rows if x['event']=='signal_checkpoint'}
        self.assertTrue(all(x['date'] in checks for x in rows if x['event']=='submitted'))
        self.assertTrue(any(x['date'] not in checks for x in rows if x['event']=='settled'))
        # Positive unchanged signal never triggers weekly rebalancing/catch-up purchases.
        self.assertEqual(sum(x['event']=='submitted' for x in rows),3)

    def test_default_rejects_candidate(self):
        with self.assertRaises(ValueError):simulate(self.assets,self.p,'trend20_weekly',1,1,0)

    def test_original72_unchanged_with_flag(self):
        for strategy in ('buy_hold','installments','monthly_rebalance','trend20'):
            for lag in (1,3,5):
                for settle in (1,3):
                    for cost in (0,20,100):
                        self.assertEqual(simulate(self.assets,self.p,strategy,lag,settle,cost),
                                         simulate(self.assets,self.p,strategy,lag,settle,cost,improvement_enabled=True))

    def test_no_future_nav_changes_prior_weekly_requests(self):
        first=self.sim()['transactions']
        for a in self.assets.values():
            for d in a['nav']:
                if d>=date(2026,5,1):a['nav'][d]*=2
        second=self.sim()['transactions']
        self.assertEqual([r for r in first if r['date']<'2026-05-01'],[r for r in second if r['date']<'2026-05-01'])

    def test_end_to_end_90_pairs_labels_and_review(self):
        self.config['conditional_unknown_evidence']=['Synthetic unresolved coverage']
        for a in self.config['instruments']:
            a.update(distribution_status='unknown',split_status='unknown',known_distribution_events=[],known_split_events=[])
        (self.root/'input.json').write_text(json.dumps(self.config))
        ip=json.dumps(protocol()).encode();(self.root/'improvement.json').write_bytes(ip)
        out=self.root/'out'
        result=run(self.root/'input.json',self.root/'protocol.json',self.sha,out,
                   conditional_nav_scenarios=True,assumptions=[CONDITIONAL_ASSUMPTION],
                   improvement_protocol=self.root/'improvement.json',improvement_protocol_sha=digest(ip))
        self.assertEqual(result['strategy_scenarios'],90)
        self.assertEqual(len(json.loads((out/'iteration-pairs.json').read_text())),18)
        for f in out.glob('*.json'):
            if f.name.startswith('protocol'):continue
            data=json.loads(f.read_text());rows=data if isinstance(data,list) else [data]
            for r in rows:
                self.assertEqual(r['evaluation_context'],'reused_development',f.name)
                self.assertTrue(r['not_executable'],f.name)
        record=json.loads((out/'improvement-experience.json').read_text())
        self.assertTrue(review_record(record))
        for field in ('counterexamples','same_sample_baseline','evaluation_context','results'):
            bad=copy.deepcopy(record);bad.pop(field)
            with self.assertRaises(ValueError):review_record(bad)
        record['status']='provisional'
        with self.assertRaises(ValueError):review_record(record)

    def test_protocol_hash_and_mode_rejected(self):
        ip=json.dumps(protocol()).encode();path=self.root/'imp.json';path.write_bytes(ip)
        with self.assertRaises(ValueError):run(self.root/'input.json',self.root/'protocol.json',self.sha,self.root/'bad',improvement_protocol=path,improvement_protocol_sha=digest(ip))
