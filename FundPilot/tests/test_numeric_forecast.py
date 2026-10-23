import json
from pathlib import Path
import tempfile
import unittest
from fundpilot.numeric_forecast import score_numeric, validate_numeric, summarize_numeric
from fundpilot.llm_loop import freeze, score, now
from test_llm_loop import fixture


def numeric(**changes):
    return dict({'unit':'raw_nav_return_fraction','event':'return_gt_zero','calibration_status':'subjective_uncalibrated',
                 'horizon':1,'p_up':'.8','q10':'-.1','q50':'0','q90':'.1'},**changes)


class NumericForecastTests(unittest.TestCase):
    def test_brier_pinball_and_inclusive_coverage(self):
        r=score_numeric(numeric(),'.1',card_id='x',target='2026-01-02',as_of=now(),missing_reason=None)
        self.assertAlmostEqual(r['brier'],.04);self.assertEqual(r['constant_half_brier'],.25)
        self.assertEqual(r['pinball'],{'q10':'0.02','q50':'0.05','q90':'0.00'})
        self.assertTrue(r['interval_coverage']);self.assertEqual(r['interval_width'],'0.2')
        self.assertFalse(r['calibration_proven'])
    def test_zero_not_up_and_pending_not_zero_loss(self):
        r=score_numeric(numeric(), '0',card_id='x',target='2026-01-02',as_of=now(),missing_reason=None)
        self.assertAlmostEqual(r['brier'],.64)
        r=score_numeric(numeric(),None,card_id='x',target=None,as_of=now(),missing_reason='not_mature')
        self.assertIsNone(r['brier']);self.assertIsNone(r['pinball']);self.assertEqual(r['label_missing_reason'],'not_mature')
    def test_missing_predictions_denominator(self):
        r=score_numeric(numeric(p_up=None,q10=None,q50=None,q90=None,missing_reason='insufficient evidence'),'.1',card_id='x',target='2026-01-02',as_of=now(),missing_reason=None)
        m=summarize_numeric([{'numeric_scores':r}])
        self.assertEqual(m['mature_labels'],1);self.assertEqual(m['probability_n'],0)
        self.assertEqual(m['quantile_n'],0);self.assertIsNone(m['mean_brier']);self.assertIsNone(m['mean_pinball']['q10'])
    def test_schema_bounds_units_and_no_backfill(self):
        b={'numeric_schema':'research_numeric_v1','new_batch_no_backfill':True}
        for changes in ({'p_up':'1.1'},{'p_up':True},{'q10':'.2'},{'q90':None},{'unit':'percent'},
                        {'calibration_status':'calibrated'},{'horizon':5},{'q10':'NaN'}, {'q10':'-1.1'}):
            with self.assertRaises(ValueError):validate_numeric(b,{'horizon':1,'numeric_forecast':numeric(**changes)})
        with self.assertRaises(ValueError):validate_numeric({}, {'horizon':1,'numeric_forecast':numeric()})
        with self.assertRaises(ValueError):validate_numeric(dict(b,new_batch_no_backfill=False),{'horizon':1,'numeric_forecast':numeric()})
    def test_direction_abstention_does_not_remove_numeric_scores_and_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cards=fixture(root)
            cards.update(numeric_schema='research_numeric_v1',new_batch_no_backfill=True)
            for c in cards['cards']:c['numeric_forecast']=numeric(horizon=c['horizon'])
            (root/'cards.json').write_text(json.dumps(cards))
            freeze(root/'cards.json',root/'sources.json',root/'calendar.json',root/'frozen')
            r=score(root/'frozen',root/'nav.csv',root/'nav-manifest.json',now(),root/'output')
            self.assertEqual(r['metrics']['scored'],2);self.assertEqual(r['numeric_metrics']['probability_n'],3)
            self.assertEqual(r['tape'][1]['status'],'abstained');self.assertIsNotNone(r['tape'][1]['numeric_scores']['brier'])
            cards['cards'][0]['numeric_forecast']['p_up']='.9'
            (root/'frozen/cards.json').write_text(json.dumps(cards))
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                score(root/'frozen',root/'nav.csv',root/'nav-manifest.json',now(),root/'again')
    def test_old_cards_unchanged_and_missing_quantile_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root)
            freeze(root/'cards.json',root/'sources.json',root/'calendar.json',root/'frozen')
            r=score(root/'frozen',root/'nav.csv',root/'nav-manifest.json',now(),root/'output')
            self.assertNotIn('numeric_metrics',r);self.assertNotIn('numeric_scores',r['tape'][0])
        with self.assertRaises(ValueError):validate_numeric({'numeric_schema':'research_numeric_v1','new_batch_no_backfill':True},
            {'horizon':1,'numeric_forecast':numeric(p_up=None)})

    def test_separate_probability_quantile_samples_and_lower_tail(self):
        r=score_numeric(numeric(p_up=None,missing_reason='no probability estimate'), '-.2',
            card_id='x',target='2026-01-02',as_of=now(),missing_reason=None)
        self.assertEqual(r['pinball']['q10'],'0.09');self.assertFalse(r['interval_coverage'])
        m=summarize_numeric([{'numeric_scores':r}])
        self.assertEqual(m['probability_n'],0);self.assertEqual(m['quantile_n'],1)
        self.assertIsNone(m['same_sample_constant_half_brier'])
        self.assertIsNotNone(m['same_sample_zero_return_pinball']['q10'])
