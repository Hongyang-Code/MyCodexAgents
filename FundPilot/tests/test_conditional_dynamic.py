"""Synthetic fixtures for the input-driven conditional historical adapter."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fundpilot.conditional_dynamic import replay


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
            "end_marks": {"A": "1.1", "B": "2"},
            "liquidation_rule_ids": {"A": "r-A"}, "limitations": ["SYNTHETIC"]}


class ConditionalDynamicTests(unittest.TestCase):
    def test_two_cutoffs_hold_and_conditional_liquidation_are_distinct(self):
        result = replay(fixture())
        self.assertEqual([row["choice"] for row in result["decisions"]], ["target", "hold"])
        self.assertEqual(result["decisions"][1]["events"], [])
        self.assertEqual(result["terminal_book_equity"], "110.0")
        self.assertEqual(result["conditional_liquidation_value"], "108.900")
        self.assertFalse(result["conditional_liquidation_is_settled_cash"])
        self.assertFalse(result["real_execution_verified"])

    def test_hold_cannot_hide_an_order(self):
        value = fixture(); value["decisions"][1]["events"] = value["decisions"][0]["events"][:1]
        with self.assertRaisesRegex(ValueError, "hold"):
            replay(value)

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

    def test_cli_subprocess_writes_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "input.json"; output = root / "result.json"
            source.write_text(json.dumps(fixture()), encoding="utf-8")
            proc = subprocess.run([sys.executable, "-m", "fundpilot.conditional_dynamic",
                                   "--input", str(source), "--output", str(output)],
                                  text=True, capture_output=True, check=True, timeout=20)
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(output.read_text())["new_model_inference"], False)
            self.assertEqual(json.loads(proc.stdout)["output"], str(output))


if __name__ == "__main__":
    unittest.main()
