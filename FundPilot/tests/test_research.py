"""Synthetic fixtures only. Passing tests do not validate investment efficacy."""
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone

from fundpilot.research import (
    Experience, ExperienceManager, ForecastEngine, LabelWindow, Observation,
    TradingCalendar, as_of, evaluate, maximum_drawdown, purged_split, settle_forecast,
    calibration_bins, compare_holdout,
)


def at(day, hour=18):
    return datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=hour)


class ResearchTests(unittest.TestCase):
    def setUp(self):
        start = date(2026, 1, 1)
        self.days = tuple(start + timedelta(days=i) for i in range(70)
                          if (start + timedelta(days=i)).weekday() < 5)
        self.calendar = TradingCalendar(self.days, "synthetic-test-calendar")
        self.rows = tuple(Observation(f"synthetic-{i}", "SYNTH", day, 100 + i,
                                     at(day), at(day), "synthetic-fixture")
                          for i, day in enumerate(self.days))
        self.engine = ForecastEngine()

    def forecast(self, horizon=1, model="persistence"):
        return self.engine.predict("f1", "SYNTH", self.rows, self.calendar,
                                   at(self.days[6]), horizon, model)

    def test_timestamp_validation(self):
        for kw in ({"available_at": at(self.days[0], 17)},
                   {"published_at": datetime(2026, 1, 1)},
                   {"session": self.days[1]}, {"value": float("nan")},
                   {"value": float("inf")}, {"value": 0},
                   {"revision": -1}, {"basis": "raw_nav"}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                replace(self.rows[0], **kw)

    def test_future_data_and_revised_vintages(self):
        revision = replace(self.rows[0], observation_id="revision", value=999,
                           revision=1, published_at=at(self.days[10]), available_at=at(self.days[11]))
        data = self.rows + (revision,)
        old = as_of(data, at(self.days[5]))
        self.assertEqual(old[0].value, 100)
        self.assertEqual(len(old), 6)
        self.assertEqual(as_of(data, at(self.days[10]))[0].value, 100)
        self.assertEqual(as_of(data, at(self.days[11]))[0].value, 999)

    def test_conflicting_ids_and_vintages_rejected(self):
        for change in ({"value": 200}, {"value": 200, "observation_id": "other"}):
            with self.assertRaises(ValueError):
                as_of(self.rows + (replace(self.rows[0], **change),), at(self.days[6]))

    def test_horizons_are_trading_sessions(self):
        for h in (1, 5, 20):
            self.assertEqual(self.forecast(h).target_session, self.days[6 + h])
        self.assertGreater((self.forecast(5).target_session - self.days[6]).days, 5)
        with self.assertRaises(ValueError):
            self.forecast(2)

    def test_frozen_predict_and_abstain(self):
        f = self.forecast(model="no_direction")
        self.assertIsNone(f.predicted_return)
        self.assertIsNone(f.probability_up)
        with self.assertRaises(FrozenInstanceError):
            f.anchor_value = 200
        self.assertEqual(self.forecast().predicted_return, 0)

    def test_trend_uses_only_pre_cutoff_data(self):
        f = self.forecast(5, "trend")
        self.assertAlmostEqual(f.predicted_return, 106 / 101 - 1)
        altered = tuple(replace(o, value=999) if o.session > self.days[6] else o for o in self.rows)
        other = self.engine.predict("f1", "SYNTH", altered, self.calendar, at(self.days[6]), 5, "trend")
        self.assertEqual(f, other)

    def test_missing_trading_day_fails_trend(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            self.engine.predict("f", "SYNTH", self.rows[:3] + self.rows[4:], self.calendar,
                                at(self.days[6]), 5, "trend")

    def test_insufficient_data_and_calendar(self):
        with self.assertRaises(ValueError):
            self.engine.predict("f", "SYNTH", (), self.calendar, at(self.days[0]), 1)
        with self.assertRaises(ValueError):
            self.engine.predict("f", "SYNTH", self.rows, self.calendar, at(self.days[2]), 1, "trend")
        with self.assertRaises(ValueError):
            self.engine.predict("f", "SYNTH", self.rows, self.calendar, at(self.days[-1]), 20)

    def test_delayed_anchor_cannot_predict_elapsed_target(self):
        with self.assertRaisesRegex(ValueError, "elapsed"):
            self.engine.predict("f", "SYNTH", self.rows[:1], self.calendar, at(self.days[5]), 1)

    def test_settlement_waits_for_actual_publication(self):
        f = self.forecast()
        outcome = replace(self.rows[7], published_at=at(self.days[9]), available_at=at(self.days[10]))
        self.assertIsNone(settle_forecast(f, [outcome], at(self.days[8])))
        self.assertIsNone(settle_forecast(f, [outcome], at(self.days[9])))
        self.assertIsNotNone(settle_forecast(f, [outcome], at(self.days[10])))

    def test_missing_target_does_not_skip(self):
        self.assertIsNone(settle_forecast(self.forecast(), self.rows[:7] + self.rows[8:], at(self.days[20])))

    def test_settlement_keeps_frozen_anchor_and_is_idempotent(self):
        f = self.forecast()
        s = settle_forecast(f, self.rows, at(self.days[7]))
        self.assertAlmostEqual(s.actual_return, 107 / 106 - 1)
        revised = replace(self.rows[7], observation_id="revised", revision=1, value=200,
                          published_at=at(self.days[8]), available_at=at(self.days[8]))
        self.assertEqual(settle_forecast(f, self.rows + (revised,), at(self.days[9]), [s]), s)
        with self.assertRaises(ValueError):
            settle_forecast(f, self.rows, at(self.days[9]), [s, s])
        with self.assertRaises(ValueError):
            evaluate([s, s])

    def test_walk_forward_is_point_in_time(self):
        cuts = [at(self.days[6]), at(self.days[7])]
        forecasts = self.engine.walk_forward("SYNTH", self.rows, self.calendar, cuts, 5, "trend")
        self.assertEqual([f.anchor_value for f in forecasts], [106, 107])
        with self.assertRaises(ValueError):
            self.engine.walk_forward("SYNTH", self.rows, self.calendar, cuts[::-1], 1)

    def test_metrics_abstentions_and_probability(self):
        s = settle_forecast(self.forecast(model="no_direction"), self.rows, at(self.days[7]))
        self.assertIsNone(evaluate([s])["mae"])
        self.assertIsNone(evaluate([])["direction_accuracy"])
        s = replace(s, predicted_return=.01, probability_up=.75)
        m = evaluate([s])
        self.assertEqual(m["direction_accuracy"], 1)
        self.assertAlmostEqual(m["brier_score"], .0625)
        self.assertAlmostEqual(maximum_drawdown([100, 120, 90, 110]), .25)
        self.assertIsNone(maximum_drawdown([]))
        with self.assertRaises(ValueError):
            maximum_drawdown([100, float("nan")])

    def test_purge_overlapping_and_unavailable_labels(self):
        ds = self.days
        rows = [LabelWindow("train", ds[0], ds[2], at(ds[2])),
                LabelWindow("overlap", ds[3], ds[7], at(ds[7])),
                LabelWindow("late", ds[0], ds[1], at(ds[10])),
                LabelWindow("val", ds[6], ds[7], at(ds[7])),
                LabelWindow("val-overlap", ds[7], ds[10], at(ds[10])),
                LabelWindow("holdout", ds[10], ds[15], at(ds[15]))]
        split = purged_split(rows, at(ds[6], 0), at(ds[10], 0))
        self.assertEqual([r.sample_id for r in split["train"]], ["train"])
        self.assertEqual([r.sample_id for r in split["validation"]], ["val"])
        self.assertEqual([r.sample_id for r in split["test"]], ["holdout"])
        self.assertEqual(len(split["purged"]), 3)

    def test_experience_is_traceable_and_never_promoted_by_win(self):
        e = Experience("e1", "synthetic rule", at(self.days[0]))
        manager = ExperienceManager()
        with self.assertRaises(ValueError):
            manager.review(e, "r1", at(self.days[1]), "v1", ["one-win"], "one win", "provisional")
        updated, review = manager.review(e, "r1", at(self.days[1]), "v1", ["case1"], "needs validation")
        self.assertEqual(e.state, "candidate")
        self.assertEqual(updated.state, "validating")
        self.assertEqual(updated.weight, 0)
        self.assertFalse(manager.monthly_review_due(updated, [review], at(self.days[2])))
        self.assertTrue(manager.monthly_review_due(updated, [review], at(date(2026, 2, 1))))
        with self.assertRaises(ValueError):
            manager.review(updated, "r1", at(self.days[2]), "v1", ["case1"], "duplicate")
        archived, _ = manager.review(updated, "r2", at(self.days[2]), "v2", ["case1"], "archive", "archive")
        self.assertFalse(manager.monthly_review_due(archived, [], at(self.days[3])))
        with self.assertRaises(ValueError):
            manager.review(archived, "r3", at(self.days[3]), "v2", ["case1"], "revive")

    def test_holdout_comparison_matches_targets_and_vintages(self):
        c = self.forecast(5, "trend")
        b = replace(self.forecast(5), forecast_id="baseline")
        cr = settle_forecast(c, self.rows, at(self.days[11]))
        br = settle_forecast(b, self.rows, at(self.days[11]))
        result = compare_holdout([c], [cr], [b], [br], at(self.days[6]))
        self.assertEqual(result["candidate"]["n"], 1)
        self.assertGreater(result["mae_improvement"], 0)
        with self.assertRaises(ValueError):
            compare_holdout([c], [cr], [b], [br], at(self.days[7]))
        with self.assertRaises(ValueError):
            compare_holdout([c], [cr], [b], [replace(br, outcome_observation_id="revision")], at(self.days[6]))
        with self.assertRaises(ValueError):
            compare_holdout([c], [cr], [], [], at(self.days[6]))

    def test_calibration_empty_and_boundaries(self):
        s = settle_forecast(self.forecast(), self.rows, at(self.days[7]))
        self.assertEqual(sum(b["n"] for b in calibration_bins([s])), 0)
        rows = [replace(s, forecast_id="zero", probability_up=0),
                replace(s, forecast_id="one", probability_up=1)]
        bins = calibration_bins(rows)
        self.assertEqual(bins[0]["n"], 1)
        self.assertEqual(bins[-1]["n"], 1)
        self.assertEqual(bins[-1]["observed_up_rate"], 1)
        with self.assertRaises(ValueError):
            calibration_bins(rows, 0)


if __name__ == "__main__":
    unittest.main()
