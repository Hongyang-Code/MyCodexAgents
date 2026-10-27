"""Synthetic dynamic decisions; no real funds, models, or performance evidence."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from fundpilot.backtest import Rule, Order, Confirmation, Receipt
from fundpilot.dynamic_topdown import (
    Candidate, Choice, Datum, ExecutionPlan, Mark, Trend, blend,
    run_dynamic, trend_digest,
)


def t(hour):
    return datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour)


def rules():
    return tuple(Rule("rule-" + name, name, t(0), t(100), t(0), t(0),
                      D(".01") if name == "SYNTH-A" else D("0"),
                      D(".02"), "SYNTHETIC rules only", True)
                 for name in ("SYNTH-A", "SYNTH-B"))


def prediction(view):
    return Trend("synthetic-trend-" + str(view.at.hour), view.at,
                 "SYNTH-A" if view.at == t(2) else "SYNTH-B",
                 ("fact-known",), ("Synthetic thesis may be wrong",))


def candidate(view, trend):
    return Candidate("conditional", trend_digest(trend),
                     ((trend.thesis, D(1)),), "Apply shared synthetic trend")


def selector(view, trend, candidates):
    return Choice((("conditional", D(1)),), "Synthetic selection fixture")


def planner(view, trend, target):
    held_a = view.state.shares.get("SYNTH-A", D(0))
    if held_a and trend.thesis == "SYNTH-B":
        units = held_a - view.state.frozen_shares.get("SYNTH-A", D(0))
        if units:
            return ExecutionPlan((Order("sell-A", view.at, "SYNTHETIC plan", True,
                                        "SYNTH-A", "sell", units, "rule-SYNTH-A", view.at),),
                                 "Redeem A before funding B")
    cash = view.state.available_cash(view.at)
    if cash > 0:
        name = trend.thesis
        return ExecutionPlan((Order("buy-" + name, view.at, "SYNTHETIC plan", True,
                                    name, "buy", cash, "rule-" + name, view.at),),
                             "Use only settled cash")
    return ExecutionPlan((), "Wait for confirmation or settlement; no available cash")


def settlements(orders):
    result = []
    for order in orders:
        if order.event_id == "sell-A":
            result.extend((Confirmation("sell-confirm", t(13), "SYNTHETIC", True,
                                        "sell-A", D("1.10"), t(11), t(12), t(13)),
                           Receipt("sale-paid", t(15), "SYNTHETIC", True, "sell-confirm")))
        else:
            offset = 3
            price = D(1) if order.instrument == "SYNTH-A" else D(2)
            result.append(Confirmation("confirm-" + order.event_id,
                                       order.at + timedelta(hours=offset),
                                       "SYNTHETIC", True, order.event_id, price,
                                       order.at + timedelta(hours=1),
                                       order.at + timedelta(hours=2),
                                       order.at + timedelta(hours=3)))
    return tuple(result)


class DynamicTopdownTests(unittest.TestCase):
    def arguments(self):
        return dict(initial_cash=D(101), rules=rules(),
                    cutoffs=(t(2), t(10), t(14), t(16)), end=t(22),
                    facts=(Datum("fact-known", t(1), "Synthetic current evidence"),
                           Datum("future-fact", t(30), "Must not enter callbacks")),
                    marks=(Mark("SYNTH-A", t(1), D(1)),
                           Mark("SYNTH-A", t(9), D("1.05")),
                           Mark("SYNTH-B", t(1), D("1.9")),
                           Mark("SYNTH-B", t(21), D("2.1")),
                           Mark("SYNTH-B", t(30), D("999"))),
                    predict=prediction, generators={"conditional": candidate},
                    select=selector, plan=planner, settle=settlements)

    def test_dynamic_rotation_waits_for_receipt_and_reuses_kernel_fees(self):
        result = run_dynamic(**self.arguments())
        decisions = result["decisions"]
        self.assertEqual([len(d["orders"]) for d in decisions], [1, 1, 0, 1])
        self.assertEqual(decisions[2]["state_before"]["available_cash"], "0")
        self.assertTrue(decisions[2]["state_before"]["receivables"])
        self.assertEqual(D(decisions[3]["state_before"]["available_cash"]), D("107.8"))
        self.assertEqual(D(result["terminal_shares"]["SYNTH-A"]), 0)
        self.assertEqual(D(result["terminal_shares"]["SYNTH-B"]), D("53.9"))
        self.assertEqual(D(result["terminal_book_equity"]), D("113.19"))
        self.assertEqual(D(result["cash_fees"]), D("3.2"))
        self.assertFalse(result["real_execution_authorized"])
        self.assertFalse(result["investment_qualified"])
        self.assertEqual(decisions[1]["previous_digest"], decisions[0]["record_digest"])

    def test_ordered_total_split_total_calls_share_exact_trend(self):
        args = self.arguments()
        calls, fingerprints = [], []

        def predict(view):
            calls.append(("predict", view.at))
            return prediction(view)

        def generate(view, trend):
            calls.append(("generate", view.at))
            fingerprints.append(trend_digest(trend))
            return candidate(view, trend)

        def choose(view, trend, proposals):
            calls.append(("select", view.at))
            self.assertTrue(all(c.trend_digest == trend_digest(trend) for c in proposals))
            return selector(view, trend, proposals)

        args.update(predict=predict, generators={"conditional": generate}, select=choose)
        result = run_dynamic(**args)
        self.assertEqual([x[0] for x in calls], ["predict", "generate", "select"] * 4)
        self.assertEqual(fingerprints, [d["trend_digest"] for d in result["decisions"]])

    def test_all_callbacks_receive_only_available_facts_and_marks(self):
        args = self.arguments()
        observed = []

        def predict(view):
            self.assertEqual([f.key for f in view.facts], ["fact-known"])
            self.assertTrue(all(m.available_at <= view.at for m in view.marks))
            self.assertNotIn(D(999), [m.nav for m in view.marks])
            observed.append(view.at)
            return prediction(view)

        args["predict"] = predict
        result = run_dynamic(**args)
        self.assertEqual(len(observed), 4)
        self.assertTrue(all("future-fact" not in d["available_evidence"]
                            for d in result["decisions"]))

    def test_changed_trend_candidate_is_rejected_before_selection(self):
        args = self.arguments()
        args["generators"] = {"conditional": lambda v, tr: replace(candidate(v, tr),
                                                                  trend_digest="wrong")}
        with self.assertRaisesRegex(ValueError, "shared frozen trend"):
            run_dynamic(**args)

    def test_future_evidence_reference_and_wrong_cutoff_rejected(self):
        for change in ({"evidence_refs": ("future-fact",)}, {"cutoff": t(30)}):
            args = self.arguments()
            args["predict"] = lambda v: replace(prediction(v), **change)
            with self.assertRaises(ValueError):
                run_dynamic(**args)

    def test_fusion_combines_targets_before_single_plan(self):
        args = self.arguments()
        args.update(cutoffs=(t(2),), end=t(3), settle=lambda orders: ())
        seen = []

        def alternate(view, trend):
            return Candidate("alternate", trend_digest(trend),
                             (("SYNTH-B", D(1)),), "Synthetic alternative allocation")

        def plan(view, trend, weights):
            seen.append(dict(weights))
            return ExecutionPlan((), "Inspect fused target without inventing fills")

        args.update(generators={"conditional": candidate, "alternate": alternate},
                    select=lambda v, tr, cs: Choice(
                        (("conditional", D(".4")), ("alternate", D(".6"))), "Synthetic blend"),
                    plan=plan)
        result = run_dynamic(**args)
        self.assertEqual(seen, [{"SYNTH-A": D(".4"), "SYNTH-B": D(".6")}])
        self.assertEqual(result["terminal_book_equity"], "101")
        self.assertEqual(len(result["decisions"]), 1)

    def test_hold_never_calls_planner_or_settlement(self):
        args = self.arguments()

        def forbidden(*_):
            self.fail("hold must not invent a trade")

        args.update(select=lambda v, tr, cs: Choice((("hold", D(1)),), "No useful change"),
                    plan=forbidden, settle=forbidden)
        result = run_dynamic(**args)
        self.assertEqual(result["terminal_cash"], "101")
        self.assertTrue(all(d["orders"] == [] for d in result["decisions"]))

    def test_overspending_or_spending_receivables_is_rejected(self):
        args = self.arguments()
        original = planner

        def bad_plan(view, trend, weights):
            if view.at == t(14):
                return ExecutionPlan((Order("too-early", view.at, "SYNTHETIC", True,
                                            "SYNTH-B", "buy", D(1), "rule-SYNTH-B", view.at),),
                                     "Intentionally invalid early spend")
            return original(view, trend, weights)

        args["plan"] = bad_plan
        with self.assertRaisesRegex(ValueError, "settled cash"):
            run_dynamic(**args)

    def test_receipt_same_instant_cannot_fund_replacement_purchase(self):
        args = self.arguments()
        args["cutoffs"] = (t(2), t(10), t(15), t(16))
        result = run_dynamic(**args)
        self.assertEqual(D(result["decisions"][2]["state_before"]["cash"]), D("107.8"))
        self.assertEqual(D(result["decisions"][2]["state_before"]["available_cash"]), D(0))
        self.assertEqual(result["decisions"][2]["orders"], [])
        self.assertEqual(len(result["decisions"][3]["orders"]), 1)

    def test_callback_mutation_cannot_change_account_or_other_callback_view(self):
        args = self.arguments()

        def malicious(view, trend):
            view.state.cash = D("99999")
            view.state.shares.clear()
            return candidate(view, trend)

        args["generators"] = {"conditional": malicious}
        result = run_dynamic(**args)
        self.assertEqual(D(result["terminal_book_equity"]), D("113.19"))

    def test_orders_cannot_be_backdated_and_settlement_cannot_inject_orders(self):
        args = self.arguments()
        args["plan"] = lambda v, tr, w: ExecutionPlan(
            (replace(planner(v, tr, w).orders[0], at=t(1), decision_cutoff=t(1)),), "Invalid")
        with self.assertRaisesRegex(ValueError, "current decision"):
            run_dynamic(**args)
        args = self.arguments()
        args["settle"] = lambda orders: orders
        with self.assertRaisesRegex(ValueError, "future non-Order"):
            run_dynamic(**args)

    def test_unfinished_orders_remain_reserved_at_end(self):
        args = self.arguments()
        args.update(cutoffs=(t(2),), end=t(3))
        result = run_dynamic(**args)
        self.assertEqual(result["terminal_book_equity"], "101")
        self.assertEqual(result["terminal_reserved_cash"], "101")
        self.assertEqual(result["scheduled_events_after_end"], 1)
        self.assertEqual(result["terminal_available_cash"], "0")

    def test_invalid_weights_unknown_choices_and_implicit_hold_fusion_rejected(self):
        args = self.arguments()
        for weights in ((("conditional", D(".9")),),
                        (("missing", D(1)),),
                        (("hold", D(".5")), ("conditional", D(".5"))),
                        (("conditional", D("NaN")),)):
            with self.subTest(weights=weights):
                args["select"] = lambda v, tr, cs: Choice(weights, "Invalid fixture")
                with self.assertRaises(ValueError):
                    run_dynamic(**args)

    def test_entry_rejects_live_producer_and_out_of_order_cutoffs(self):
        args = self.arguments()
        args["producer"] = "actual_current_llm"
        with self.assertRaisesRegex(ValueError, "synthetic"):
            run_dynamic(**args)
        args = self.arguments()
        args["cutoffs"] = (t(10), t(2))
        with self.assertRaisesRegex(ValueError, "ordered cutoffs"):
            run_dynamic(**args)


if __name__ == "__main__":
    unittest.main()
