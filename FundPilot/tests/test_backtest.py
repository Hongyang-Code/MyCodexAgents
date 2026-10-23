"""Synthetic verified-event fixtures; no live funds or performance claims."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from fundpilot.backtest import (
    Rule, Order, Confirmation, Receipt, DistributionRecord, DistributionEx,
    Reinvestment, EventSimulator,
)


def t(i):
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)


def order(id="buy", when=2, side="buy", quantity="101"):
    return Order(id, t(when), "synthetic-order", True, "SYNTH-A", side, D(quantity), "v1", t(when))


def confirm(id="confirm", when=5, order_id="buy", price="1", price_time=3):
    return Confirmation(id, t(when), "synthetic-confirmation", True, order_id, D(price),
                        t(price_time), t(when-1), t(when))


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.rule = Rule("v1", "SYNTH-A", t(0), t(100), t(0), t(1),
                         D(".01"), D(".02"), "synthetic-rule", True)
        self.sim = EventSimulator(D("101"), [self.rule])

    def test_buy_reserves_cash_until_confirmation(self):
        state = self.sim.apply(order())
        self.assertEqual(state.cash, 0)
        self.assertEqual(state.reserved_cash, 101)
        self.assertEqual(state.shares, {})
        self.assertEqual(state.equity({}), 101)
        state = self.sim.apply(confirm())
        self.assertEqual(state.shares["SYNTH-A"], 100)
        self.assertEqual(state.fees, 1)
        self.assertEqual(state.reserved_cash, 0)
        self.assertEqual(state.equity({"SYNTH-A": D(1)}) + state.fees, 101)

    def test_redemption_does_not_immediately_release_cash(self):
        self.sim.replay([order(), confirm(), order("sell", 6, "sell", "100")])
        state = self.sim.state
        self.assertEqual(state.shares["SYNTH-A"], 100)
        self.assertEqual(state.frozen_shares["SYNTH-A"], 100)
        self.assertEqual(state.cash, 0)
        state = self.sim.apply(confirm("redeemed", 9, "sell", "1", 7))
        self.assertEqual(state.cash, 0)
        self.assertEqual(state.receivables["redeemed"][1], 98)
        self.assertEqual(state.equity({}) + state.fees, 101)
        with self.assertRaisesRegex(ValueError, "settled cash"):
            self.sim.apply(order("too-early", 10, quantity="98"))
        state = self.sim.apply(Receipt("paid", t(12), "synthetic-bank", True, "redeemed"))
        self.assertEqual(state.cash, 98)
        with self.assertRaises(ValueError):
            self.sim.apply(order("same-instant", 12, quantity="98"))
        self.sim.apply(order("later", 13, quantity="98"))

    def test_future_or_expired_rules_cannot_be_used(self):
        for rule in (replace(self.rule, available_at=t(3)),
                     replace(self.rule, effective_from=t(3)),
                     replace(self.rule, effective_to=t(2))):
            sim = EventSimulator(D(101), [rule])
            with self.assertRaises(ValueError):
                sim.apply(order())
        with self.assertRaises(ValueError):
            self.sim.apply(replace(order(), decision_cutoff=t(0)))

    def test_known_or_same_time_execution_price_is_rejected(self):
        self.sim.apply(order())
        for price_time in (1, 2):
            with self.assertRaises(ValueError):
                self.sim.apply(confirm(price_time=price_time))
        self.assertEqual(self.sim.state.reserved_cash, 101)

    def test_unavailable_price_rejected(self):
        for change in ({"price_available_at": t(6)}, {"price_published_at": t(6)},
                       {"price_determined_at": t(7)}, {"price": D("NaN")}):
            with self.assertRaises(ValueError):
                replace(confirm(), **change)

    def test_no_external_money_or_leverage(self):
        with self.assertRaises(ValueError):
            self.sim.apply(order(quantity="102"))
        with self.assertRaises(ValueError):
            self.sim.apply(order(side="sell", quantity="1"))
        with self.assertRaises(ValueError):
            self.sim.apply(Receipt("invented", t(2), "synthetic", True, "missing"))
        self.assertEqual(self.sim.state.cash, 101)

    def test_frozen_shares_cannot_be_sold_twice(self):
        self.sim.replay([order(), confirm(), order("sell", 6, "sell", "100")])
        with self.assertRaises(ValueError):
            self.sim.apply(order("sell-again", 7, "sell", "1"))

    def test_duplicate_confirmation_receipt_and_event_rejected(self):
        self.sim.replay([order(), confirm()])
        with self.assertRaises(ValueError):
            self.sim.apply(confirm())
        with self.assertRaises(ValueError):
            self.sim.apply(confirm("duplicate-confirmation", 6))
        self.sim.replay([order("sell", 7, "sell", "100"), confirm("redeemed", 10, "sell", "1", 8),
                         Receipt("paid", t(11), "synthetic", True, "redeemed")])
        with self.assertRaises(ValueError):
            self.sim.apply(Receipt("paid-again", t(12), "synthetic", True, "redeemed"))
        self.assertEqual(self.sim.state.cash, 98)

    def test_cash_dividend_ex_date_preserves_equity(self):
        sim = EventSimulator(D(0), [self.rule], {"SYNTH-A": D(100)})
        sim.apply(DistributionRecord("record", t(2), "synthetic", True, "SYNTH-A", D(".1"), "cash"))
        state = sim.apply(DistributionEx("ex", t(3), "synthetic", True, "record"))
        self.assertEqual(state.equity({"SYNTH-A": D(".9")}), 100)
        self.assertEqual(state.cash, 0)
        state = sim.apply(Receipt("dividend-paid", t(8), "synthetic", True, "ex"))
        self.assertEqual(state.cash, 10)
        self.assertEqual(state.income, 10)
        self.assertEqual(state.fees, 0)
        self.assertEqual(state.equity({"SYNTH-A": D(".9")}), 100)

    def test_reinvestment_keeps_income_out_of_available_cash(self):
        sim = EventSimulator(D(0), [self.rule], {"SYNTH-A": D(90)})
        sim.replay([DistributionRecord("record", t(2), "synthetic", True, "SYNTH-A", D(".1"), "reinvest"),
                    DistributionEx("ex", t(3), "synthetic", True, "record")])
        with self.assertRaises(ValueError):
            sim.apply(Receipt("wrong-mode", t(4), "synthetic", True, "ex"))
        state = sim.apply(Reinvestment("reinvested", t(6), "synthetic", True, "ex", D(".9"), t(3), t(5), t(6)))
        self.assertEqual(state.shares["SYNTH-A"], 100)
        self.assertEqual(state.cash, 0)
        self.assertEqual(state.equity({"SYNTH-A": D(".9")}), 90)
        with self.assertRaises(ValueError):
            sim.apply(Reinvestment("again", t(7), "synthetic", True, "ex", D(".9"), t(3), t(5), t(6)))

    def test_record_date_entitlement_survives_later_sale(self):
        sim = EventSimulator(D(0), [self.rule], {"SYNTH-A": D(100)})
        sim.replay([DistributionRecord("record", t(2), "synthetic", True, "SYNTH-A", D(".1"), "cash"),
                    order("sell", 3, "sell", "100"), confirm("redeemed", 6, "sell", "1", 4),
                    DistributionEx("ex", t(7), "synthetic", True, "record")])
        self.assertEqual(sim.state.receivables["ex"][1], 10)

    def test_gross_fee_basis_explicit_and_no_nav_fee_double_count(self):
        sim = EventSimulator(D(100), [replace(self.rule, buy_fee_basis="gross")])
        sim.replay([order(quantity="100"), confirm()])
        self.assertEqual(sim.state.shares["SYNTH-A"], 99)
        self.assertEqual(sim.state.fees, 1)
        # A lower NAV affects mark only; there is no ongoing-fee debit API.
        self.assertEqual(sim.state.equity({"SYNTH-A": D(".9")}), D("89.1"))
        self.assertEqual(sim.state.fees, 1)

    def test_validation_and_immutable_snapshot(self):
        for cash in (D("NaN"), D("-1"), 100.0):
            with self.assertRaises(ValueError):
                EventSimulator(cash, [self.rule])
        with self.assertRaises(ValueError):
            replace(self.rule, verified=False)
        with self.assertRaises(ValueError):
            replace(order(), verified=False)
        with self.assertRaises(ValueError):
            replace(order(), at=datetime(2026, 1, 1))
        snapshot = self.sim.state
        snapshot.cash = D(10000)
        self.assertEqual(self.sim.state.cash, 101)

    def test_out_of_order_events_and_missing_marks_fail(self):
        self.sim.replay([order(), confirm()])
        with self.assertRaises(ValueError):
            self.sim.apply(order("old", 3))
        with self.assertRaises(ValueError):
            self.sim.state.equity({})
        with self.assertRaises(ValueError):
            self.sim.state.equity({"SYNTH-A": D("NaN")})

    def test_distribution_duplicate_and_pre_ex_price_rejected_atomically(self):
        sim = EventSimulator(D(0), [self.rule], {"SYNTH-A": D(90)})
        sim.replay([DistributionRecord("record", t(2), "synthetic", True, "SYNTH-A", D(".1"), "reinvest"),
                    DistributionEx("ex", t(3), "synthetic", True, "record")])
        before = sim.state
        with self.assertRaises(ValueError):
            sim.apply(DistributionEx("duplicate-ex", t(4), "synthetic", True, "record"))
        with self.assertRaises(ValueError):
            sim.apply(Reinvestment("bad-price", t(5), "synthetic", True, "ex", D(".9"), t(2), t(4), t(5)))
        self.assertEqual(before, sim.state)

    def test_only_old_cash_can_be_spent_at_receipt_timestamp(self):
        sim = EventSimulator(D(5), [self.rule], {"SYNTH-A": D(100)})
        sim.replay([order("sell", 2, "sell", "100"), confirm("redeemed", 5, "sell", "1", 3),
                    Receipt("paid", t(6), "synthetic", True, "redeemed")])
        sim.apply(order("old-cash-only", 6, quantity="5"))
        self.assertEqual(sim.state.cash, 98)
        with self.assertRaises(ValueError):
            sim.apply(order("new-cash-too-early", 6, quantity="1"))
        sim.apply(order("new-cash-later", 7, quantity="98"))


if __name__ == "__main__":
    unittest.main()
