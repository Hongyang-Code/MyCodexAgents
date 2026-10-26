"""Synthetic settlement regression; no account data or live model/source calls."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from fundpilot.official_fees import OfficialFees
from fundpilot.conditional_value import evaluate
from test_official_fees import RAW, record
from test_conditional_value import fixture


class RedemptionTimelineTests(unittest.TestCase):
    def test_application_cannot_follow_confirmation_for_either_basis(self):
        for basis in ("confirmation_to_confirmation_exclusive_end",
                      "confirmation_to_application_exclusive_end"):
            with self.subTest(basis=basis):
                r = record()
                r["holding_basis"] = basis
                q = OfficialFees(r, RAW)
                with self.assertRaisesRegex(ValueError, "application.*confirmation"):
                    q.redemption([{"lot_id": "x", "units": "10", "confirmed_on": "2026-01-01"}],
                                 "2", redemption_application="2026-02-01",
                                 redemption_confirmation="2026-01-07")

    def test_application_cannot_precede_subscription_confirmation(self):
        q = OfficialFees(record(), RAW)
        with self.assertRaisesRegex(ValueError, "application.*subscription"):
            q.redemption([{"lot_id": "x", "units": "10", "confirmed_on": "2026-01-05"}],
                         "2", redemption_application="2026-01-04",
                         redemption_confirmation="2026-01-07")

    def test_unused_date_is_still_validated(self):
        q = OfficialFees(record(), RAW)
        with self.assertRaises(ValueError):
            q.redemption([{"lot_id": "x", "units": "10", "confirmed_on": "2026-01-01"}],
                         "2", redemption_application="not-a-date",
                         redemption_confirmation="2026-01-31")

    def test_unknown_basis_does_not_hide_known_time_conflict(self):
        r = record()
        r["holding_basis"] = None
        q = OfficialFees(r, RAW)
        with self.assertRaisesRegex(ValueError, "application.*confirmation"):
            q.redemption([{"lot_id": "x", "units": "10", "confirmed_on": "2026-01-01"}],
                         "2", redemption_application="2026-02-01",
                         redemption_confirmation="2026-01-07")

    def test_missing_dates_stay_unknown_and_keep_partial_lot_evidence(self):
        q = OfficialFees(record(), RAW)
        result = q.redemption([
            {"lot_id": "known", "units": "10", "confirmed_on": "2026-01-01"},
            {"lot_id": "unknown", "units": "10", "confirmed_on": None}],
            "2", redemption_application="2026-01-30",
            redemption_confirmation="2026-01-31")
        self.assertIsNone(result["fee"])
        self.assertEqual(Decimal(result["lots"][0]["fee"]), Decimal("0"))
        self.assertIsNone(result["lots"][1]["holding_days"])

    def test_valid_application_and_confirmation_use_reviewed_basis(self):
        lot = [{"lot_id": "x", "units": "10", "confirmed_on": "2026-01-01"}]
        for basis, days, fee in [
            ("confirmation_to_application_exclusive_end", 29, ".2"),
            ("confirmation_to_confirmation_exclusive_end", 30, "0")]:
            with self.subTest(basis=basis):
                r = record()
                r["holding_basis"] = basis
                result = OfficialFees(r, RAW).redemption(
                    lot, "2", redemption_application="2026-01-30",
                    redemption_confirmation="2026-01-31")
                self.assertEqual(result["lots"][0]["holding_days"], days)
                self.assertEqual(Decimal(result["fee"]), Decimal(fee))

    def test_application_keys_must_match_frozen_fund_set(self):
        for dates in ({}, {"A": None}, {"A": None, "B": None, "EXTRA": None}):
            with self.subTest(dates=dates):
                p, d, n, s = fixture()
                p["assumptions"]["exit_application_dates"] = dates
                with self.assertRaisesRegex(ValueError, "application.*fund"):
                    evaluate(p, d, n, s)

    def test_application_cannot_change_frozen_exit_nav_date(self):
        for day in ("2026-01-05", "2026-01-31"):
            with self.subTest(day=day):
                p, d, n, s = fixture()
                p["assumptions"]["exit_application_dates"] = {"A": day, "B": None}
                with self.assertRaisesRegex(ValueError, "application.*exit"):
                    evaluate(p, d, n, s)

    def test_application_cannot_precede_known_entry_confirmation(self):
        p, d, n, s = fixture()
        a = p["assumptions"]
        a["entry_confirmation_dates"] = {"A": "2026-01-07", "B": None}
        a["exit_confirmation_dates"] = {"A": "2026-01-08", "B": None}
        a["exit_application_dates"] = {"A": p["end_date"], "B": None}
        with self.assertRaisesRegex(ValueError, "application.*subscription"):
            evaluate(p, d, n, s)

    def test_valid_application_keeps_cash_and_input_unchanged(self):
        p, d, n, s = fixture()
        a = p["assumptions"]
        a["entry_confirmation_dates"] = {f: "2026-01-03" for f in p["funds"]}
        a["exit_confirmation_dates"] = {f: "2026-01-07" for f in p["funds"]}
        a["exit_application_dates"] = {f: p["end_date"] for f in p["funds"]}
        a["exit_receipt_date"] = "2026-01-10"
        before = deepcopy(p)
        result = evaluate(p, d, n, s)
        c = result["outcomes"]["llm_allocation"]["liquidation_scenario"]
        self.assertEqual(c["available_cash_at_window_end"], "500")
        self.assertEqual(result["conditional_holding_calendar_days"]["A"], 4)
        self.assertEqual(p, before)
        self.assertFalse(result["active_profitability_validated"])

    def test_official_application_basis_missing_then_explicit(self):
        p, d, n, s = fixture()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            root.chmod(0o700)
            raw = root / "synthetic-document"
            raw.write_bytes(RAW)
            raw.chmod(0o600)
            for f in p["funds"]:
                r = record()
                r["fund_code"] = f
                r["holding_basis"] = "confirmation_to_application_exclusive_end"
                p["assumptions"]["costs"][f] = {
                    "official_rule": r, "raw_document_path": str(raw),
                    "identity": {k: r[k] for k in ("fund_code", "share_class", "currency")}}
            a = p["assumptions"]
            a["entry_confirmation_dates"] = {f: "2026-01-03" for f in p["funds"]}
            a["exit_confirmation_dates"] = {f: "2026-01-07" for f in p["funds"]}
            result = evaluate(p, d, n, s)
            c = result["outcomes"]["llm_allocation"]
            self.assertIsNone(c["liquidation_scenario"]["hypothetical_exit_fee"])
            self.assertIsNotNone(c["pre_liquidation_nav_mark"]["book_equity"])
            a["exit_application_dates"] = {f: p["end_date"] for f in p["funds"]}
            result = evaluate(p, d, n, s)
            c = result["outcomes"]["llm_allocation"]
            self.assertEqual(c["official_fee_quotes"]["A"]["redemption"]["lots"][0]["holding_days"], 3)
            self.assertEqual(c["liquidation_scenario"]["available_cash_at_window_end"], "500")


if __name__ == "__main__":
    unittest.main()
