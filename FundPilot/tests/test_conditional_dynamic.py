"""Synthetic fixtures for the input-driven conditional historical adapter."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import os
from decimal import Decimal

from fundpilot.backtest import State
from fundpilot.conditional_dynamic import _order_intents, replay
from fundpilot.dynamic_topdown import Candidate, trend_digest
from fundpilot.frozen_topdown import build_choice_request, load_frozen_research
from fundpilot.upstream_bridge import PIN, SCOPE, digest, write_new


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


def _research(root, cutoff):
    root.mkdir(mode=0o700)
    raw = json.dumps({"fund": "SYNTHETIC", "information_cutoff": cutoff,
                      "market_report": "SYNTHETIC", "fundamentals_report": "SYNTHETIC"}).encode()
    (root / "input.json").write_bytes(raw); (root / "input.json").chmod(0o600)
    write_new(root / "receipt.json", {"bridge_schema": 2, "graph_mode": "stable",
              "input_sha256": digest(raw), "upstream_sha": PIN, **SCOPE})
    manager = json.dumps({"forecasts": [
        {"horizon": h, "direction": "flat", "p_up": None, "rationale": "fixture",
         "counterevidence": "fixture", "invalidation": "fixture", "gaps": "fixture"}
        for h in (1, 5, 20)]})
    contents = ("bull fixture", "bear fixture", manager)
    for index, (role, content) in enumerate(zip(("bull", "bear", "manager"), contents), 1):
        prompt = "prompt-" + role; prompt_sha = digest(prompt.encode())
        write_new(root / f"request-{index}.json", {"role": role, "prompt": prompt,
                  "prompt_sha256": prompt_sha, "captured_at": "2026-10-27T00:00:00+00:00",
                  **SCOPE})
        write_new(root / f"response-{index}.json", {"producer": "synthetic_fixture",
                  "model_ref": "SYNTHETIC_NOT_LLM", "generated_at": "2026-10-27T00:00:01+00:00",
                  "prompt_sha256": prompt_sha, "content": content})
    write_new(root / "result.json", {**SCOPE, "upstream_sha": PIN,
              "completed_at": "2026-10-27T00:00:02+00:00", "bridge_responses": 3,
              "response_producers": ["synthetic_fixture"] * 3,
              "research_state": {"investment_plan": manager}})


def bind_v2(value, root):
    value["schema"] = "fundpilot.conditional-dynamic-replay.v2"
    states = [
        {"cash": "100", "reserved_cash": "0", "receivables": {}, "shares": {}},
        {"cash": "0", "reserved_cash": "0", "receivables": {}, "shares": {"A": "100"}},
    ]
    for index, row in enumerate(value["decisions"]):
        graph = root / f"graph-{index}"; _research(graph, row["cutoff"])
        frozen = load_frozen_research(graph, __import__("datetime").datetime.fromisoformat(row["cutoff"]))
        candidates = (
            Candidate("hold", trend_digest(frozen.trend), None, "retain current state"),
            Candidate("target", trend_digest(frozen.trend), (("A", Decimal("1")),), "explicit target"))
        state = State(cash=Decimal(states[index]["cash"]),
                      reserved_cash=Decimal(states[index]["reserved_cash"]),
                      shares={k: Decimal(v) for k, v in states[index]["shares"].items()})
        frozen_rows = [
            {"candidate_id": "hold", "target_weights": None, "reason": "retain current state",
             "fees": "0", "risk": "state unchanged", "plan": {"order_intents": []}},
            {"candidate_id": "target", "target_weights": [["A", "1"]],
             "reason": "explicit target", "fees": "rule based", "risk": "market",
             "plan": {"order_intents": _order_intents(row)}}]
        plans = [{"candidate_id": item["candidate_id"], "target_weights": item["target_weights"],
                  "reason": item["reason"], "fees": item["fees"], "risk": item["risk"],
                  "order_intents": item["plan"]["order_intents"], "unavailable_reason": None}
                 for item in frozen_rows]
        envelope = {"cutoff": row["cutoff"], "decision_ref": row["decision_ref"],
                    "candidate_plans": plans}
        request = root / f"choice-request-{index}.json"
        response = root / f"choice-response-{index}.json"
        request_obj = build_choice_request(frozen.trend, candidates, state, envelope,
                                           "2026-10-27T00:00:03+00:00")
        prompt = request_obj["prompt_sha256"]
        write_new(request, request_obj)
        write_new(response, {"schema": "fundpilot.final-choice-response.v2",
                  "producer": "synthetic_fixture", "model_ref": "SYNTHETIC_NOT_LLM",
                  "generated_at": "2026-10-27T00:00:04+00:00", "prompt_sha256": prompt,
                  "components": [{"candidate_id": row["choice"], "weight": "1"}],
                  "reason": "fixture"})
        row["candidates"] = frozen_rows
        row["artifacts"] = {"research_root": str(graph), "choice_request": str(request),
                            "choice_response": str(response)}
    return value


def complete_case_v2(root):
    value = fixture()
    value.update(schema="fundpilot.conditional-dynamic-replay.v2",
                 initial_cash="100", initial_shares={})
    for row in value["decisions"]:
        row["choice"] = "hold"; row["events"] = []
    bull = root / "bull.json"; bear = root / "bear.json"
    write_new(bull, {"role": "bull"}); write_new(bear, {"role": "bear"})
    cutoff = value["decisions"][0]["cutoff"]
    manager_prompt = "Directions are up|flat|down|abstain; p_up is number or null."
    manager_request = root / "manager-request.json"
    manager_response = root / "manager-response.json"
    manager_receipt = root / "manager-receipt.json"
    request_obj = {
        "schema": "fundpilot.research-request.v2", "role": "manager",
        "information_cutoff": cutoff, "captured_at": "2026-10-29T00:00:00+00:00",
        "prompt": manager_prompt, "prompt_sha256": digest(manager_prompt.encode()),
        "input_response_sha256": [digest(bull.read_bytes()), digest(bear.read_bytes())]}
    write_new(manager_request, request_obj)
    forecast = lambda h: {
        "horizon": h, "direction": "abstain", "p_up": None,
        "rationale": "fixture", "invalidation": "fixture"}
    response_obj = {
        "role": "manager", "funds": [
            {"instrument": {"code": "A"}, "forecasts": [forecast(h) for h in (1, 5, 20)]},
            {"instrument": {"code": "B"}, "forecasts": [forecast(h) for h in (1, 5, 20)]}]}
    write_new(manager_response, response_obj)
    write_new(manager_receipt, {
        "request_sha256": digest(manager_request.read_bytes()),
        "response_sha256": digest(manager_response.read_bytes()),
        "prompt_sha256": request_obj["prompt_sha256"],
        "host_captured_at": "2026-10-29T00:00:01+00:00",
        "provider_generated_at": "unknown", "model_ref": "fixture-model"})
    research = {
        "schema": "fundpilot.complete-comparison-research.v1",
        "information_cutoff": cutoff, "manager_request": str(manager_request),
        "manager_response": str(manager_response), "manager_receipt": str(manager_receipt),
        "bull_response": str(bull), "bear_response": str(bear)}
    plans = [
        {"candidate_id": "hold", "target_weights": None, "reason": "retain cash",
         "fees": "0", "risk": "opportunity cost", "available": True,
         "order_intents": []},
        {"candidate_id": "target", "target_weights": [["A", "1"]],
         "reason": "explicit build", "fees": "0", "risk": "market",
         "available": True, "order_intents": []},
        {"candidate_id": "minimum_variance", "target_weights": None,
         "available": False, "unavailable_reason": "insufficient history",
         "order_intents": None}]
    for index, row in enumerate(value["decisions"]):
        request = root / f"choice-request-{index}.json"
        response = root / f"choice-response-{index}.json"
        receipt = root / f"choice-receipt-{index}.json"
        prompt = "Select one frozen candidate from the complete plan table."
        request_obj = {
            "schema": "fundpilot.final-choice-request.v2",
            "cutoff": row["cutoff"], "decision_ref": row["decision_ref"],
            "captured_at": f"2026-10-29T00:00:0{2 + index * 2}+00:00",
            "prompt": prompt, "prompt_sha256": digest(prompt.encode()),
            "research_response_sha256": digest(manager_response.read_bytes()),
            "state": {"cash": "100", "reserved_cash": "0",
                      "receivables": {}, "shares": {}},
            "candidate_plans": plans}
        write_new(request, request_obj)
        write_new(response, {
            "schema": "fundpilot.final-choice-response.v2",
            "selected_candidate_id": "hold", "reason": "fixture hold"})
        write_new(receipt, {
            "request_sha256": digest(request.read_bytes()),
            "response_sha256": digest(response.read_bytes()),
            "prompt_sha256": request_obj["prompt_sha256"],
            "host_captured_at": f"2026-10-29T00:00:0{3 + index * 2}+00:00",
            "provider_generated_at": None, "model_ref": "fixture-model"})
        row["candidate_plans"] = plans
        row["artifacts"] = {
            "schema": "fundpilot.complete-comparison-artifacts.v1",
            "research": research,
            "choice": {"schema": "fundpilot.complete-comparison-choice.v1",
                       "request": str(request), "response": str(response),
                       "receipt": str(receipt)}}
        if index:
            row["research_reuse"] = "explicit_frozen_reuse"
    return value


class ConditionalDynamicTests(unittest.TestCase):
    def test_complete_comparison_layout_replays_same_hold_choices(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); os.chmod(root, 0o700)
            value = complete_case_v2(root)
            result = replay(value)
            self.assertEqual([row["choice"] for row in result["decisions"]],
                             ["hold", "hold"])
            self.assertTrue(result["saved_artifacts_verified"])
            self.assertFalse(result["decisions"][0]["research_reused"])
            self.assertTrue(result["decisions"][1]["research_reused"])
            self.assertTrue(result["decisions"][0]["provider_time_unknown"])
            semantic = result["decisions"][0]["semantic_contract_status"]
            self.assertFalse(semantic["complete"])
            self.assertEqual(
                semantic["missing"],
                ["flat_exact_zero_definition", "p_up_event_and_unit_definition"])

    def test_complete_comparison_layout_rejects_changed_raw_response(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); os.chmod(root, 0o700)
            value = complete_case_v2(root)
            target = Path(value["decisions"][0]["artifacts"]["choice"]["response"])
            target.write_text('{"schema":"fundpilot.final-choice-response.v2",'
                              '"selected_candidate_id":"target","reason":"changed"}')
            target.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "receipt byte binding"):
                replay(value)

    def test_v2_binds_research_candidates_choice_and_actual_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); os.chmod(root, 0o700)
            value = bind_v2(fixture(), root)
            result = replay(value)
            self.assertTrue(result["decision_context_bound"])
            self.assertTrue(result["saved_artifacts_verified"])
            self.assertTrue(all(row["decision_context_sha256"] for row in result["decisions"]))

    def test_prechoice_request_supports_hold_without_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); os.chmod(root, 0o700)
            value = bind_v2(fixture(), root)
            row = value["decisions"][0]
            request = Path(row["artifacts"]["choice_request"])
            before = request.read_bytes()
            response = Path(row["artifacts"]["choice_response"])
            obj = json.loads(response.read_text())
            obj["components"] = [{"candidate_id": "hold", "weight": "1"}]
            response.write_text(json.dumps(obj)); response.chmod(0o600)
            row["choice"] = "hold"; row["events"] = []
            value["decisions"] = [row]
            result = replay(value)
            self.assertEqual(result["decisions"][0]["choice"], "hold")
            self.assertEqual(result["decisions"][0]["orders"], [])
            self.assertEqual(request.read_bytes(), before)

    def test_v2_rejects_missing_or_forged_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); os.chmod(root, 0o700)
            value = bind_v2(fixture(), root)
            Path(value["decisions"][0]["artifacts"]["choice_response"]).unlink()
            with self.assertRaises((OSError, ValueError)):
                replay(value)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); os.chmod(root, 0o700)
            value = bind_v2(fixture(), root)
            response = Path(value["decisions"][0]["artifacts"]["choice_response"])
            obj = json.loads(response.read_text()); obj["prompt_sha256"] = "1" * 64
            response.write_text(json.dumps(obj)); response.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "prompt binding"):
                replay(value)

    def test_v2_rejects_legacy_choice_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); os.chmod(root, 0o700)
            value = bind_v2(fixture(), root); row = value["decisions"][0]
            request = Path(row["artifacts"]["choice_request"])
            response = Path(row["artifacts"]["choice_response"])
            old = json.loads(request.read_text())
            unsigned = {"schema": "fundpilot.final-choice-request.v1",
                        "trend_digest": old["trend_digest"],
                        "candidate_ids": old["candidate_ids"]}
            prompt = digest(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode())
            unsigned.update(prompt_sha256=prompt, captured_at=old["captured_at"])
            request.write_text(json.dumps(unsigned)); request.chmod(0o600)
            old_response = json.loads(response.read_text())
            old_response.update(schema="fundpilot.final-choice-response.v1",
                                prompt_sha256=prompt)
            response.write_text(json.dumps(old_response)); response.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "requires final choice v2"):
                replay(value)

    def test_v2_rejects_same_id_weight_cutoff_or_order_change(self):
        for mutation in ("weight", "cutoff", "order"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td); os.chmod(root, 0o700)
                value = bind_v2(fixture(), root)
                if mutation == "weight":
                    value["decisions"][0]["candidates"][1]["target_weights"] = [["A", ".5"], ["B", ".5"]]
                elif mutation == "cutoff":
                    value["decisions"][0]["cutoff"] = "2020-01-02T00:00:01+00:00"
                    value["decisions"][0]["events"][0]["at"] = value["decisions"][0]["cutoff"]
                else:
                    value["decisions"][0]["events"][0]["quantity"] = "99"
                with self.assertRaises(ValueError):
                    replay(value)

    def test_v2_does_not_bind_future_settlement_price_into_choice_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); os.chmod(root, 0o700)
            value = bind_v2(fixture(), root)
            value["decisions"] = value["decisions"][:1]
            first = replay(value)
            value["decisions"][0]["events"][1]["price"] = "2"
            changed = replay(value)
            self.assertEqual(first["decisions"][0]["decision_context_sha256"],
                             changed["decisions"][0]["decision_context_sha256"])
            self.assertNotEqual(first["input_sha256"], changed["input_sha256"])
            self.assertEqual(changed["terminal_state"]["shares"]["A"], "50")

    def test_v2_rejects_invalid_nonhold_candidate_weights(self):
        bad = ([['A', '-.1'], ['B', '1.1']], [['A', '.5'], ['A', '.5']],
               [['A', '.4'], ['B', '.4']], None)
        for weights in bad:
            with self.subTest(weights=weights), tempfile.TemporaryDirectory() as td:
                root = Path(td); os.chmod(root, 0o700)
                value = bind_v2(fixture(), root)
                value["decisions"][0]["candidates"][1]["target_weights"] = weights
                with self.assertRaises(ValueError):
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
