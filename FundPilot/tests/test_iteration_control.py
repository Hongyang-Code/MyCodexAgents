import json
from pathlib import Path
import unittest
from fundpilot.iteration_control import CAPS, RunBudget, check_config, register_candidate, review_candidate


def protocol(**changes):
    p = dict(candidate_id='synthetic-c1', stable_version='stable', candidate_version='candidate',
             hypothesis='One evidence checklist reduces missing source fields', one_change='Add one checklist',
             evidence_hash='synthetic-evidence-hash', evaluation_hash='synthetic-evaluation-hash',
             counterexample_archive='private-synthetic-archive', metric='missing_fields', direction='lower',
             frozen_at='2026-01-01T00:00:00Z', evaluation_start='2026-01-02T00:00:00Z',
             kind='process', change_area='research_workflow')
    return dict(p, **changes)


def result(**changes):
    r = dict(evidence_hash='synthetic-evidence-hash', evaluation_hash='synthetic-evaluation-hash',
             counterexample_review='All synthetic failures retained', results_ref='private-synthetic-results',
             regression_checks_passed=True, stable_metric='4', candidate_metric='2')
    return dict(r, **changes)


class IterationControlTests(unittest.TestCase):
    def test_exact_config(self):
        self.assertTrue(check_config(json.loads((Path(__file__).parents[1]/'config/research-budget.json').read_text())))
        for c in (dict(CAPS, source_attempts=13), dict(CAPS, prediction_batches=True)):
            with self.assertRaises(ValueError): check_config(c)

    def test_one_batch_and_shape(self):
        b, status = RunBudget().reserve('batch', 'prediction_batch', funds=('a','b','c'), horizons=(1,5,20))
        self.assertEqual(status, 'reserved')
        self.assertEqual(b.reserve('batch2','prediction_batch',funds=('a',),horizons=(1,))[1], 'skip_partial')
        for funds, horizons in [(('a','a'),(1,)), (('a','b','c','d'),(1,)), (('a',),(2,)), (('a',),(True,))]:
            with self.assertRaises(ValueError): RunBudget().reserve('x','prediction_batch',funds=funds,horizons=horizons)

    def test_parallel_total_and_no_recursion(self):
        b,_=RunBudget().reserve('s1','subtask');b,_=b.reserve('s2','subtask')
        self.assertEqual(b.reserve('s3','subtask')[1],'skip_partial')
        self.assertEqual(b.reserve('child','subtask',parent='s1')[1],'skip_partial')
        b=b.finish('s1');b,_=b.reserve('s3','subtask');b=b.finish('s2')
        self.assertEqual(b.reserve('s4','subtask')[1],'skip_partial')

    def test_source_budget_includes_retry(self):
        b,_=RunBudget().reserve('source','source')
        b,status=b.reserve('retry','retry',parent='source',failure='transient')
        self.assertEqual(status,'reserved')
        self.assertEqual(b.reserve('retry2','retry',parent='source',failure='transient')[1],'skip_partial')
        for n in range(10):b,_=b.reserve(str(n),'source')
        self.assertEqual(b.reserve('overflow','source')[1],'skip_partial')
        self.assertEqual(len(b.reservations),12)

    def test_no_deterministic_or_unknown_retry(self):
        b,_=RunBudget().reserve('source','source')
        for failure in ('validation','permission','unknown_outcome','platform_limit'):
            self.assertEqual(b.reserve('retry','retry',parent='source',failure=failure)[1],'skip_partial')
        self.assertEqual(b.reserve('retry','retry',parent='absent',failure='transient')[1],'skip_partial')

    def test_duplicate_reservation_never_authorizes_reexecution(self):
        b,_=RunBudget().reserve('s','source')
        same,status=b.reserve('s','source')
        self.assertEqual(same,b);self.assertEqual(status,'already_reserved_do_not_execute')

    def test_limit_and_revocation_stop_even_reserved_actions(self):
        b,_=RunBudget().reserve('s','source');b=b.stop()
        for key in ('s','new'):
            self.assertEqual(b.reserve(key,'source')[1],'stop')

    def test_usage_unknown_not_zero(self):
        b=RunBudget().record_usage('one').record_usage('two',0)
        self.assertEqual(b.usage,(('one',None),('two',0)))
        for value in (-1,True,1.5):
            with self.assertRaises(ValueError): b.record_usage('three',value)
        with self.assertRaises(ValueError): b.record_usage('one',1)

    def test_registration_boundaries(self):
        self.assertTrue(register_candidate(protocol(),[]))
        for changes in ({'change_area':'budget'}, {'kind':'investment'}, {'candidate_version':'stable'},
                        {'evaluation_start':'2026-01-01T00:00:00Z'}, {'hypothesis':''}):
            with self.assertRaises(ValueError):register_candidate(protocol(**changes),[])

    def test_rolling_week_and_complete_history(self):
        old=protocol(candidate_id='old',frozen_at='2025-12-25T00:00:01Z')
        with self.assertRaises(ValueError):register_candidate(protocol(),[old])
        old['frozen_at']='2025-12-25T00:00:00Z'
        self.assertTrue(register_candidate(protocol(),[old]))
        with self.assertRaises(ValueError):register_candidate(protocol(),[protocol()])

    def test_fairness_and_counterexamples(self):
        for changes in ({'evidence_hash':'other'},{'evaluation_hash':'changed'}, {'counterexample_review':''}, {'results_ref':''}):
            with self.assertRaises(ValueError): review_candidate(protocol(),result(**changes))
        with self.assertRaises(ValueError):review_candidate(protocol(),result(),1)

    def test_no_improvement_or_regression_retains_stable(self):
        for changes in ({'candidate_metric':'4'},{'candidate_metric':'5'},{'regression_checks_passed':False}):
            self.assertEqual(review_candidate(protocol(),result(**changes)),'retain_stable')

    def test_process_never_proves_prediction(self):
        self.assertEqual(review_candidate(protocol(),result()),'process_review_eligible_not_prediction_evidence')
        for value in ('NaN','Infinity',True,1.5):
            with self.assertRaises(ValueError):review_candidate(protocol(),result(candidate_metric=value))

    def test_prediction_not_promoted_by_few_wins_or_reuse(self):
        p=protocol(kind='prediction')
        self.assertEqual(review_candidate(p,result(data_role='reused_development',mature=True)),'pending_future_validation')
        self.assertEqual(review_candidate(p,result(data_role='future_unseen',mature=True,wins=3)),'pending_future_validation')
        r=result(data_role='future_unseen',mature=True,nonoverlap_analysis='ref',uncertainty_analysis='ref',
                 cost_risk_comparison='ref',sample_sufficiency_review='ref')
        self.assertEqual(review_candidate(p,r),'independent_review_required_no_automatic_promotion')
        r['mature']=False
        self.assertEqual(review_candidate(p,r),'pending_future_validation')
