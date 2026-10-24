"""Synthetic acceptance tests; no investment or sample independence claim."""
import copy
from datetime import date
from decimal import Decimal
import unittest

from fundpilot.acceptance import assess, cpi_growth, exact_lower, REQUIRED_REVIEWS


def episode(year, ident=None, ret="0.02", draw="0.03"):
    return {
        "id": ident or f"synthetic-{year}",
        "start": f"{year}-12-31", "end": f"{year+1}-12-31",
        "net_liquidation_return": ret, "unitized_max_drawdown": draw,
        "source_refs": ["synthetic-fixture-not-market-data"],
        "cpi_monthly": [
            {"month": f"{year+1}-{month:02d}", "basis": "month_on_month_fraction", "change": "0.001"}
            for month in range(1, 13)
        ],
    }


def fixture(n=1):
    return {"schema_version": 1, "test_only": True, "data_role": "synthetic",
            "episodes": [episode(1900+i) for i in range(n)],
            "reviews": {key: {"status": "verified", "evidence_ref": "synthetic-only"}
                        for key in REQUIRED_REVIEWS}}


class ExactBoundTests(unittest.TestCase):
    def test_all_success_closed_form_and_sample_boundary(self):
        self.assertAlmostEqual(exact_lower(1, 1), .05)
        self.assertLess(exact_lower(58, 58), .95)
        self.assertGreater(exact_lower(59, 59), .95)
        self.assertLess(exact_lower(28, 28), .9)
        self.assertGreater(exact_lower(29, 29), .9)

    def test_nontrivial_binomial_polynomial(self):
        # P(X>=1 | n=2) = 1-(1-p)^2, independently invert this polynomial.
        self.assertAlmostEqual(exact_lower(1, 2), 1-(.95**.5), places=12)
        p = exact_lower(2, 3)
        self.assertAlmostEqual(3*p*p-2*p*p*p, .05, places=12)
        self.assertEqual(exact_lower(0, 25), 0)

    def test_counts_are_strict_and_bounded(self):
        for args in [(True, 3), (1, False), (1, 1.0), (4, 3), (-1, 3), (0, 0), (1, 10001)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                exact_lower(*args)

    def test_one_loss_widens_the_bound(self):
        self.assertLess(exact_lower(58, 59), exact_lower(59, 59))


class GateTests(unittest.TestCase):
    def test_synthetic_cannot_become_real_guidance(self):
        r = assess(fixture(59))
        self.assertTrue(r["numerical_targets_met"])
        self.assertFalse(r["eligible"])
        self.assertEqual(r["status"], "synthetic_only")
        self.assertFalse(r["real_guidance_authorized"])
        self.assertFalse(r["project_complete"])

    def test_development_cannot_qualify_despite_perfect_numbers(self):
        p = fixture(59)
        p.update(test_only=False, data_role="reused_development")
        r = assess(p)
        self.assertTrue(r["numerical_targets_met"])
        self.assertEqual(r["status"], "pending_evidence")
        self.assertFalse(r["eligible"])

    def test_conditional_pass_does_not_complete_project(self):
        # Simulates external qualification; does not certify real evidence.
        p = fixture(59)
        p.update(test_only=False, data_role="untouched_historical_validation")
        r = assess(p)
        self.assertEqual(r["status"], "historical_gate_passed")
        self.assertFalse(r["real_guidance_authorized"])
        self.assertFalse(r["project_complete"])

    def test_small_perfect_sample_is_pending(self):
        p = fixture(2)
        p.update(test_only=False, data_role="untouched_historical_validation")
        self.assertEqual(assess(p)["status"], "pending_sample_size")

    def test_source_or_outcome_missing_is_not_dropped(self):
        p = fixture(3)
        p["episodes"][1]["net_liquidation_return"] = None
        p["episodes"][2]["source_refs"] = []
        r = assess(p)
        self.assertEqual(r["registered_n"], 3)
        self.assertEqual(r["nonloss"]["n"], 2)
        self.assertEqual(r["beat_cpi"]["n"], 2)
        self.assertTrue(r["missing"])

    def test_reused_market_window_across_funds_is_overlap(self):
        p = fixture(2)
        p["episodes"][1] = episode(1900, ident="different-fund-same-period")
        p.update(test_only=False, data_role="untouched_historical_validation")
        r = assess(p)
        self.assertTrue(r["overlapping_episodes"])
        self.assertEqual(r["status"], "pending_evidence")

    def test_review_requires_evidence_not_boolean(self):
        p = fixture()
        p["reviews"]["independent_sampling"] = True
        self.assertIn("independent_sampling", assess(p)["unqualified_reviews"])
        p["reviews"]["independent_sampling"] = {"status": "verified", "evidence_ref": ""}
        self.assertIn("independent_sampling", assess(p)["unqualified_reviews"])

    def test_cpi_is_compounded_not_added_or_yoy(self):
        e = episode(2020)
        self.assertAlmostEqual(cpi_growth(e["cpi_monthly"], date(2020,12,31), date(2021,12,31)),
                               Decimal("1.001")**12-1, delta=Decimal("1e-24"))
        e["cpi_monthly"][0]["basis"] = "year_on_year_fraction"
        with self.assertRaises(ValueError):
            cpi_growth(e["cpi_monthly"], date(2020,12,31), date(2021,12,31))

    def test_cpi_gap_and_partial_horizon_rejected(self):
        p = fixture()
        p["episodes"][0]["cpi_monthly"][4]["month"] = "1901-07"
        with self.assertRaises(ValueError):
            assess(p)
        p = fixture()
        p["episodes"][0]["end"] = "1901-06-30"
        with self.assertRaises(ValueError):
            assess(p)

    def test_zero_counts_as_nonloss_but_cpi_tie_is_not_a_win(self):
        p = fixture()
        e = p["episodes"][0]
        e["net_liquidation_return"] = "0"
        for row in e["cpi_monthly"]:
            row["change"] = "0"
        r = assess(p)
        self.assertEqual(r["nonloss"]["successes"], 1)
        self.assertEqual(r["beat_cpi"]["successes"], 0)

    def test_observed_drawdown_breach_fails(self):
        p = fixture(59)
        p.update(test_only=False, data_role="untouched_historical_validation")
        p["episodes"][0]["unitized_max_drawdown"] = "0.0501"
        r = assess(p)
        self.assertEqual(r["status"], "not_met")
        self.assertFalse(r["drawdown_target_met"])

    def test_invalid_values_and_duplicate_ids_rejected(self):
        for field, value in [("net_liquidation_return","NaN"), ("net_liquidation_return",True),
                             ("unitized_max_drawdown","-0.01"), ("unitized_max_drawdown","Infinity")]:
            p = fixture()
            p["episodes"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                assess(p)
        p = fixture(2)
        p["episodes"][1]["id"] = p["episodes"][0]["id"]
        with self.assertRaises(ValueError):
            assess(p)

    def test_missing_cpi_and_memory_review_remain_pending(self):
        p = fixture(59)
        p.update(test_only=False, data_role="untouched_historical_validation")
        p["episodes"][0]["cpi_monthly"] = None
        del p["reviews"]["model_memory_boundary"]
        r = assess(p)
        self.assertEqual(r["status"], "pending_evidence")
        self.assertEqual(r["beat_cpi"]["n"], 58)
        self.assertIn("model_memory_boundary", r["unqualified_reviews"])

    def test_no_observations_is_not_success(self):
        r = assess(fixture(0))
        self.assertIsNone(r["nonloss"]["rate"])
        self.assertFalse(r["numerical_targets_met"])

    def test_leap_year_month_end(self):
        p = fixture()
        e = p["episodes"][0]
        e.update(start="2020-02-29", end="2021-02-28")
        e["cpi_monthly"] = [
            {"month": m, "basis":"month_on_month_fraction", "change":"0"}
            for m in ["2020-03","2020-04","2020-05","2020-06","2020-07","2020-08",
                      "2020-09","2020-10","2020-11","2020-12","2021-01","2021-02"]]
        self.assertEqual(assess(p)["registered_n"], 1)


if __name__ == "__main__":
    unittest.main()
