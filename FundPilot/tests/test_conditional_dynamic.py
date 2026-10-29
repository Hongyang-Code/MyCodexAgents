"""Synthetic fixtures for the input-driven conditional historical adapter."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import os

from fundpilot.conditional_dynamic import _digest, replay


def fixture():
    def rule(name):
        return {"rule_id": "r-" + name, "instrument": name,
                "effective_from": "2020-01-01T00:00:00+00:00",
                "effective_to": "2021-01-01T00:00:00+00:00",
                "published_at": "2020-01-01T00:00:00+00:00",
                "available_at": "2020-01-01T00:00:00+00:00",
                "buy_rate": "0", "sell_rate": "0.01", "source": "SYNTHETIC"}
    return {"schema": "fundpilot.conditional-dynamic-replay.v1",
            "mode": "conditional_historical", "event_kernel_attested": True,
            "real_execution_verified": False, "initial_cash": "100",
            "rules": [rule("A"), rule("B")], "initial_shares": {},
            "decisions": [
                {"cutoff": "2020-01-02T00:00:00+00:00", "decision_ref": "frozen-1",
                 "choice": "target", "events": [
                     {"type": "order", "event_id": "buy-a", "at": "2020-01-02T00:00:00+00:00",
                      "source": "SYNTHETIC", "instrument": "A", "side": "buy",
                      "quantity": "100", "rule_id": "r-A"},
                     {"type": "confirmation", "event_id": "confirm-a",
                      "at": "2020-01-03T03:00:00+00:00", "source": "SYNTHETIC",
                      "order_id": "buy-a", "price": "1", "price_determined_at": "2020-01-03T01:00:00+00:00",
                      "price_published_at": "2020-01-03T02:00:00+00:00",
                      "price_available_at": "2020-01-03T03:00:00+00:00"}]},
                {"cutoff": "2020-01-10T00:00:00+00:00", "decision_ref": "frozen-2",
                 "choice": "hold", "reason": "Frozen selector retained the portfolio", "events": []}],
            "end_at": "2020-01-20T00:00:00+00:00",
            "liquidation_at": "2020-01-20T00:00:00+00:00",
            "end_marks": {"A": "1.1", "B": "2"},
            "liquidation_rule_ids": {"A": "r-A"}, "limitations": ["SYNTHETIC"]}


def bind_v2(value):
    value["schema"] = "fundpilot.conditional-dynamic-replay.v2"
    states = [
        {"cash": "100", "reserved_cash": "0", "receivables": {}, "shares": {}},
        {"cash": "0", "reserved_cash": "0", "receivables": {}, "shares": {"A": "100"}},
    ]
    for index, row in enumerate(value["decisions"]):
        context = {
            "expected_state_before": states[index],
            "research": {"target_instruments": ["A", "B"], "horizons": [1, 5, 20],
                         "response_sha256s": [str(n) * 64 for n in (1, 2, 3)]},
            "candidates": [
                {"candidate_id": "hold", "semantics": "retain_current_state"},
                {"candidate_id": "target", "semantics": "explicit_target"}],
            "selected_candidate_id": row["choice"],
            "choice_response_sha256": str(index + 4) * 64,
        }
        context["context_sha256"] = _digest(context)
        row["decision_context"] = context
    return value


class ConditionalDynamicTests(unittest.TestCase):
    def test_v2_binds_research_candidates_choice_and_actual_state(self):
        value = bind_v2(fixture())
        result = replay(value)
        self.assertTrue(result["decision_context_bound"])
        self.assertTrue(all(row["decision_context_sha256"] for row in result["decisions"]))
        value = bind_v2(fixture())
        value["decisions"][0]["decision_context"]["expected_state_before"]["cash"] = "99"
        with self.assertRaisesRegex(ValueError, "state"):
            replay(value)

    def test_v2_rejects_hold_relabel_after_choice(self):
        value = bind_v2(fixture())
        context = value["decisions"][0]["decision_context"]
        context["candidates"][0]["semantics"] = "buy_50_50"
        context["context_sha256"] = _digest(
            {key: item for key, item in context.items() if key != "context_sha256"})
        with self.assertRaisesRegex(ValueError, "retain_current_state"):
            replay(value)

    def test_two_cutoffs_hold_and_conditional_liquidation_are_distinct(self):
        result = replay(fixture())
        self.assertEqual([row["choice"] for row in result["decisions"]], ["target", "hold"])
        self.assertEqual(result["decisions"][1]["orders"], [])
        self.assertEqual(result["terminal_book_equity"], "110.0")
        self.assertEqual(result["conditional_liquidation_value"], "108.900")
        self.assertFalse(result["conditional_liquidation_is_settled_cash"])
        self.assertFalse(result["real_execution_verified"])
        self.assertTrue(result["legacy_unbound_decision_context"])

    def test_hold_cannot_hide_an_order(self):
        value = fixture(); value["decisions"][1]["events"] = value["decisions"][0]["events"][:1]
        with self.assertRaisesRegex(ValueError, "hold"):
            replay(value)

    def test_second_cutoff_before_confirmation_sees_only_reserved_cash(self):
        value = fixture()
        value["decisions"][1]["cutoff"] = "2020-01-03T01:00:00+00:00"
        result = replay(value)
        before = result["decisions"][1]["state_before"]
        self.assertEqual(before["cash"], "0")
        self.assertEqual(before["reserved_cash"], "100")
        self.assertEqual(before["shares"], {})

    def test_receipt_after_end_remains_receivable_and_pending(self):
        value = fixture()
        value["initial_cash"] = "0"; value["initial_shares"] = {"A": "100"}
        value["decisions"] = [{
            "cutoff": "2020-01-02T00:00:00+00:00", "decision_ref": "sell-1",
            "choice": "target", "events": [
                {"type": "order", "event_id": "sell-a", "at": "2020-01-02T00:00:00+00:00",
                 "source": "SYNTHETIC", "instrument": "A", "side": "sell",
                 "quantity": "100", "rule_id": "r-A"},
                {"type": "confirmation", "event_id": "sell-confirm", "at": "2020-01-03T03:00:00+00:00",
                 "source": "SYNTHETIC", "order_id": "sell-a", "price": "1.1",
                 "price_determined_at": "2020-01-03T01:00:00+00:00",
                 "price_published_at": "2020-01-03T02:00:00+00:00",
                 "price_available_at": "2020-01-03T03:00:00+00:00"},
                {"type": "receipt", "event_id": "sell-paid", "at": "2020-01-10T00:00:00+00:00",
                 "source": "SYNTHETIC", "receivable_id": "sell-confirm"}]},
            {"cutoff": "2020-01-04T00:00:00+00:00", "decision_ref": "hold-2",
             "choice": "hold", "events": []}]
        value["end_at"] = "2020-01-05T00:00:00+00:00"
        value["liquidation_at"] = value["end_at"]
        result = replay(value)
        self.assertEqual(result["terminal_state"]["cash"], "0")
        self.assertEqual(result["terminal_state"]["receivables"]["sell-confirm"][1], "108.900")
        self.assertEqual([row["type"] for row in result["pending_events_after_end"]], ["Receipt"])

    def test_unreceived_redemption_cannot_fund_a_buy(self):
        value = fixture(); second = value["decisions"][1]
        second["choice"] = "target"
        second["events"] = [
            {"type": "order", "event_id": "sell-a", "at": second["cutoff"], "source": "SYNTHETIC",
             "instrument": "A", "side": "sell", "quantity": "100", "rule_id": "r-A"},
            {"type": "confirmation", "event_id": "sell-confirm", "at": "2020-01-11T03:00:00+00:00",
             "source": "SYNTHETIC", "order_id": "sell-a", "price": "1.1",
             "price_determined_at": "2020-01-11T01:00:00+00:00",
             "price_published_at": "2020-01-11T02:00:00+00:00",
             "price_available_at": "2020-01-11T03:00:00+00:00"}]
        value["decisions"].append(
            {"cutoff": "2020-01-12T00:00:00+00:00", "decision_ref": "frozen-3",
             "choice": "target", "events": [
                 {"type": "order", "event_id": "buy-b", "at": "2020-01-12T00:00:00+00:00",
                  "source": "SYNTHETIC", "instrument": "B", "side": "buy",
                  "quantity": "1", "rule_id": "r-B"}]})
        with self.assertRaisesRegex(ValueError, "settled cash"):
            replay(value)

    def test_liquidation_rule_must_match_instrument_and_time(self):
        value = fixture(); value["liquidation_rule_ids"]["A"] = "r-B"
        with self.assertRaisesRegex(ValueError, "instrument mismatch"):
            replay(value)
        value = fixture(); value["liquidation_at"] = "2022-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "not effective"):
            replay(value)

    def test_cli_subprocess_writes_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "input.json"; output = root / "result.json"
            source.write_text(json.dumps(fixture()), encoding="utf-8")
            os.chmod(root, 0o700); os.chmod(source, 0o600)
            proc = subprocess.run([sys.executable, "-m", "fundpilot.conditional_dynamic",
                                   "--input", str(source), "--output", str(output)],
                                  text=True, capture_output=True, check=True, timeout=20)
            self.assertTrue(output.is_file())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads(output.read_text())["new_model_inference"], False)
            self.assertEqual(json.loads(proc.stdout)["output"], str(output))
            duplicate = subprocess.run([sys.executable, "-m", "fundpilot.conditional_dynamic",
                                        "--input", str(source), "--output", str(output)],
                                       text=True, capture_output=True, timeout=20)
            self.assertNotEqual(duplicate.returncode, 0)

    def test_cli_rejects_symlink_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); os.chmod(root, 0o700)
            source = root / "input.json"; source.write_text(json.dumps(fixture()), encoding="utf-8")
            os.chmod(source, 0o600)
            real = root / "real.json"; real.write_text("unchanged", encoding="utf-8"); os.chmod(real, 0o600)
            alias = root / "result.json"; alias.symlink_to(real)
            proc = subprocess.run([sys.executable, "-m", "fundpilot.conditional_dynamic",
                                   "--input", str(source), "--output", str(alias)],
                                  text=True, capture_output=True, timeout=20)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(real.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
