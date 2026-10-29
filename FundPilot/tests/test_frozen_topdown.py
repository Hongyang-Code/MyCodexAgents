"""Offline adaptation of completed bridge evidence into top-down objects."""
from datetime import datetime, timezone
from decimal import Decimal as D
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from fundpilot.dynamic_topdown import Candidate, Datum, ExecutionPlan, Mark, trend_digest
from fundpilot.frozen_topdown import (
    build_choice_request, choice_context, load_frozen_research, load_frozen_choice,
    run_frozen_synthetic,
)
from fundpilot.backtest import State
from fundpilot.upstream_bridge import PIN, SCOPE, digest, write_new


UTC = timezone.utc


def _manager_json():
    return json.dumps({
        "forecasts": [
            {"horizon": 1, "direction": "flat", "p_up": None,
             "rationale": "r1", "counterevidence": "c1",
             "invalidation": "i1", "gaps": "g1"},
            {"horizon": 5, "direction": "up", "p_up": None,
             "rationale": "r5", "counterevidence": "c5",
             "invalidation": "i5", "gaps": "g5"},
            {"horizon": 20, "direction": "abstain", "p_up": None,
             "rationale": "r20", "counterevidence": "c20",
             "invalidation": "i20", "gaps": "g20"},
        ],
        "simulation_allocation_fraction": None,
        "simulation_rationale": "insufficient execution evidence",
        "no_action_counterfactual": "hold",
        "cost_coverage_assessment": "unknown",
    }, ensure_ascii=False)


def _fixture(root):
    graph = root / "graph"
    graph.mkdir(mode=0o700)
    cutoff = "2020-01-02T15:00:00+00:00"
    raw = json.dumps({"fund": "SYNTHETIC:001", "information_cutoff": cutoff,
                      "market_report": "source:S1", "fundamentals_report": "source:S2"}).encode()
    (graph / "input.json").write_bytes(raw)
    (graph / "input.json").chmod(0o600)
    receipt = {"bridge_schema": 2, "graph_mode": "stable", "input_sha256": digest(raw),
               "upstream_sha": PIN, "max_responses": 3, **SCOPE}
    write_new(graph / "receipt.json", receipt)
    contents = ("bull", "bear", _manager_json())
    producers = []
    for index, (role, content) in enumerate(zip(("bull", "bear", "manager"), contents), 1):
        prompt = "prompt-" + role
        prompt_sha = digest(prompt.encode())
        write_new(graph / f"request-{index}.json", {"role": role, "prompt": prompt,
                  "prompt_sha256": prompt_sha, "captured_at": "2026-10-27T00:00:00+00:00",
                  "checkpoint_id": str(index), "bridge": "current_conversation_llm", **SCOPE})
        write_new(graph / f"response-{index}.json", {"producer": "synthetic_fixture",
                  "model_ref": "SYNTHETIC_NOT_LLM", "generated_at": "2026-10-27T00:00:01+00:00",
                  "prompt_sha256": prompt_sha, "content": content})
        producers.append("synthetic_fixture")
    write_new(graph / "result.json", {**SCOPE, "upstream_sha": PIN,
              "completed_at": "2026-10-27T00:00:02+00:00", "bridge_responses": 3,
              "response_producers": producers,
              "research_state": {"investment_plan": contents[-1]}})
    return graph, datetime.fromisoformat(cutoff)


def _choice_fixture(root, trend, candidate_ids=("hold", "conditional")):
    prompt = {"schema": "fundpilot.final-choice-request.v1",
              "trend_digest": trend_digest(trend), "candidate_ids": list(candidate_ids)}
    raw = json.dumps(prompt, sort_keys=True, separators=(",", ":")).encode()
    request = root / "choice-request.json"; response = root / "choice-response.json"
    write_new(request, {**prompt, "prompt_sha256": hashlib.sha256(raw).hexdigest(),
                        "captured_at": "2026-10-27T00:00:03+00:00"})
    write_new(response, {"schema": "fundpilot.final-choice-response.v1",
              "producer": "synthetic_fixture", "model_ref": "SYNTHETIC_NOT_LLM",
              "generated_at": "2026-10-27T00:00:04+00:00",
              "prompt_sha256": hashlib.sha256(raw).hexdigest(),
              "components": [{"candidate_id": "conditional", "weight": "1"}],
              "reason": "fixture"})
    return request, response


class FrozenResearchTests(unittest.TestCase):
    def test_completed_manager_json_becomes_one_provenanced_trend_not_choice(self):
        with tempfile.TemporaryDirectory() as td:
            graph, cutoff = _fixture(Path(td))
            frozen = load_frozen_research(graph, cutoff)
            self.assertEqual(frozen.trend.cutoff, cutoff)
            self.assertIn("1:flat", frozen.trend.thesis)
            self.assertIn("20:abstain", frozen.trend.thesis)
            self.assertEqual(frozen.provenance.producer, "synthetic_fixture")
            self.assertEqual(frozen.provenance.source_file, "response-3.json")
            self.assertIsNone(frozen.choice)
            self.assertEqual(frozen.choice_status, "missing_separate_final_choice")

    def test_unstructured_manager_or_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            graph, cutoff = _fixture(Path(td))
            response = graph / "response-3.json"
            obj = json.loads(response.read_bytes()); obj["content"] = "BUY"
            response.write_text(json.dumps(obj)); response.chmod(0o600)
            result = graph / "result.json"; robj = json.loads(result.read_bytes())
            robj["research_state"]["investment_plan"] = "BUY"
            result.write_text(json.dumps(robj)); result.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "structured manager JSON"):
                load_frozen_research(graph, cutoff)
        with tempfile.TemporaryDirectory() as td:
            graph, cutoff = _fixture(Path(td))
            result = graph / "result.json"
            obj = json.loads(result.read_bytes()); obj["research_state"]["investment_plan"] = "tampered"
            result.write_text(json.dumps(obj)); result.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "completed result"):
                load_frozen_research(graph, cutoff)

    def test_exact_cutoff_and_complete_forecasts_required(self):
        with tempfile.TemporaryDirectory() as td:
            graph, cutoff = _fixture(Path(td))
            with self.assertRaisesRegex(ValueError, "cutoff"):
                load_frozen_research(graph, cutoff.replace(day=3))
            response = graph / "response-3.json"
            obj = json.loads(response.read_bytes()); parsed = json.loads(obj["content"])
            parsed["forecasts"].pop(); obj["content"] = json.dumps(parsed)
            response.write_text(json.dumps(obj)); response.chmod(0o600)
            result = graph / "result.json"; robj = json.loads(result.read_bytes())
            robj["research_state"]["investment_plan"] = obj["content"]
            result.write_text(json.dumps(robj)); result.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "horizons"):
                load_frozen_research(graph, cutoff)

    def test_separate_choice_envelope_binds_prompt_trend_and_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); graph, cutoff = _fixture(root)
            frozen = load_frozen_research(graph, cutoff)
            candidates = (Candidate("hold", trend_digest(frozen.trend), None, "hold"),
                          Candidate("low", trend_digest(frozen.trend), (("CASH", 1),), "low"))
            prompt = {"schema": "fundpilot.final-choice-request.v1",
                      "trend_digest": trend_digest(frozen.trend),
                      "candidate_ids": ["hold", "low"]}
            request = root / "choice-request.json"; response = root / "choice-response.json"
            prompt_raw = json.dumps(prompt, sort_keys=True, separators=(",", ":")).encode()
            write_new(request, {**prompt, "prompt_sha256": hashlib.sha256(prompt_raw).hexdigest(),
                                "captured_at": "2026-10-27T00:00:03+00:00"})
            write_new(response, {"schema": "fundpilot.final-choice-response.v1",
                      "producer": "synthetic_fixture", "model_ref": "SYNTHETIC_NOT_LLM",
                      "generated_at": "2026-10-27T00:00:04+00:00",
                      "prompt_sha256": hashlib.sha256(prompt_raw).hexdigest(),
                      "components": [{"candidate_id": "low", "weight": "1"}], "reason": "fixture"})
            choice = load_frozen_choice(request, response, frozen.trend, candidates)
            self.assertEqual(choice.choice.components, (("low", 1),))
            self.assertEqual(choice.provenance.producer, "synthetic_fixture")
            bad = json.loads(response.read_bytes()); bad["components"][0]["candidate_id"] = "other"
            response.write_text(json.dumps(bad)); response.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "candidate"):
                load_frozen_choice(request, response, frozen.trend, candidates)

    def test_v2_choice_rejects_same_id_with_changed_weight_or_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); graph, cutoff = _fixture(root)
            frozen = load_frozen_research(graph, cutoff)
            state = State(cash=D("100"))
            candidates = (Candidate("hold", trend_digest(frozen.trend), None, "hold"),
                          Candidate("low", trend_digest(frozen.trend),
                                    (("CASH", D(1)),), "low"))
            plans = [
                {"candidate_id": "hold", "target_weights": None, "reason": "hold",
                 "fees": "0", "risk": "unchanged", "order_intents": [],
                 "unavailable_reason": None},
                {"candidate_id": "low", "target_weights": [["CASH", "1"]],
                 "reason": "low", "fees": "0", "risk": "cash",
                 "order_intents": [], "unavailable_reason": None}]
            envelope = {"cutoff": cutoff.isoformat(), "decision_ref": "fixture-choice",
                        "candidate_plans": plans}
            request_obj = build_choice_request(frozen.trend, candidates, state, envelope,
                                               "2026-10-27T00:00:03+00:00")
            prompt = request_obj["prompt_sha256"]
            request = root / "choice-request.json"; response = root / "choice-response.json"
            write_new(request, request_obj)
            write_new(response, {"schema": "fundpilot.final-choice-response.v2",
                      "producer": "synthetic_fixture", "model_ref": "SYNTHETIC_NOT_LLM",
                      "generated_at": "2026-10-27T00:00:04+00:00",
                      "prompt_sha256": prompt,
                      "components": [{"candidate_id": "low", "weight": "1"}],
                      "reason": "fixture"})
            load_frozen_choice(request, response, frozen.trend, candidates, state, envelope)
            changed = (candidates[0], Candidate("low", trend_digest(frozen.trend),
                                               (("CASH", D(".5")), ("SYNTH", D(".5"))), "low"))
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                load_frozen_choice(request, response, frozen.trend, changed, state, envelope)
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                load_frozen_choice(request, response, frozen.trend, candidates,
                                   State(cash=D("99")), envelope)
            changed_envelope = dict(envelope, decision_ref="changed-choice")
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                load_frozen_choice(request, response, frozen.trend, candidates, state,
                                   changed_envelope)

    def test_completed_synthetic_envelopes_drive_one_dynamic_decision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); graph, cutoff = _fixture(root)
            frozen = load_frozen_research(graph, cutoff)
            request, response = _choice_fixture(root, frozen.trend)
            def generate(view, trend):
                return Candidate("conditional", trend_digest(trend), (("SYNTH", D(1)),), "fixture")
            result = run_frozen_synthetic(
                research_root=graph, choice_request=request, choice_response=response,
                initial_cash=D(100), rules=(), cutoffs=(cutoff,), end=cutoff,
                facts=(Datum("response-3.json#forecasts", cutoff, "SYNTHETIC replay evidence"),),
                marks=(Mark("SYNTH", cutoff, D(1)),), generators={"conditional": generate},
                plan=lambda view, trend, target: ExecutionPlan((), "fixture no order"),
                settle=lambda orders: ())
            self.assertEqual(result["decisions"][0]["choice"]["components"], [["conditional", "1"]])
            self.assertTrue(result["frozen_replay"]["replayed_frozen_output"])
            self.assertFalse(result["frozen_replay"]["temporal_oos_qualified"])
            self.assertFalse(result["frozen_replay"]["new_model_inference"])

    def test_dynamic_replay_rejects_actual_producer_and_multiple_cutoffs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); graph, cutoff = _fixture(root)
            frozen = load_frozen_research(graph, cutoff)
            request, response = _choice_fixture(root, frozen.trend)
            response_obj = json.loads(response.read_bytes()); response_obj["producer"] = "actual_current_llm"
            response.write_text(json.dumps(response_obj)); response.chmod(0o600)
            base = dict(research_root=graph, choice_request=request, choice_response=response,
                        initial_cash=D(100), rules=(), cutoffs=(cutoff,), end=cutoff,
                        facts=(Datum("response-3.json#forecasts", cutoff, "SYNTHETIC"),), marks=(),
                        generators={"conditional": lambda v, t: Candidate(
                            "conditional", trend_digest(t), (("CASH", D(1)),), "fixture")},
                        plan=lambda v, t, w: ExecutionPlan((), "fixture"), settle=lambda o: ())
            with self.assertRaisesRegex(ValueError, "synthetic fixture"):
                run_frozen_synthetic(**base)
            response_obj["producer"] = "synthetic_fixture"
            response.write_text(json.dumps(response_obj)); response.chmod(0o600)
            base["cutoffs"] = (cutoff, cutoff.replace(minute=1)); base["end"] = cutoff.replace(minute=1)
            with self.assertRaisesRegex(ValueError, "exactly one"):
                run_frozen_synthetic(**base)

    def test_private_copy_recovers_identically_in_a_separate_process(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); graph, cutoff = _fixture(root)
            frozen = load_frozen_research(graph, cutoff)
            request, response = _choice_fixture(root, frozen.trend)
            def generate(view, trend):
                return Candidate("conditional", trend_digest(trend), (("SYNTH", D(1)),), "fixture")
            expected = run_frozen_synthetic(
                research_root=graph, choice_request=request, choice_response=response,
                initial_cash=D(100), rules=(), cutoffs=(cutoff,), end=cutoff,
                facts=(Datum("response-3.json#forecasts", cutoff, "SYNTHETIC"),),
                marks=(Mark("SYNTH", cutoff, D(1)),), generators={"conditional": generate},
                plan=lambda v, t, w: ExecutionPlan((), "fixture"), settle=lambda o: ())
            recovered_root = root / "recovered-root"; recovered_root.mkdir(mode=0o700)
            recovered = recovered_root / "graph"; recovered.mkdir(mode=0o700)
            for source in graph.iterdir():
                target = recovered / source.name
                shutil.copyfile(source, target); target.chmod(0o600)
            for source in (request, response):
                target = recovered_root / source.name
                shutil.copyfile(source, target); target.chmod(0o600)
            code = """
from datetime import datetime
from decimal import Decimal as D
import json, sys
from fundpilot.dynamic_topdown import Candidate, Datum, ExecutionPlan, Mark, trend_digest
from fundpilot.frozen_topdown import run_frozen_synthetic
root=sys.argv[1]; cutoff=datetime.fromisoformat(sys.argv[2])
def generate(view, trend):
    return Candidate('conditional',trend_digest(trend),(('SYNTH',D(1)),),'fixture')
x=run_frozen_synthetic(research_root=root+'/graph',choice_request=root+'/choice-request.json',
    choice_response=root+'/choice-response.json',initial_cash=D(100),rules=(),cutoffs=(cutoff,),
    end=cutoff,facts=(Datum('response-3.json#forecasts',cutoff,'SYNTHETIC'),),
    marks=(Mark('SYNTH',cutoff,D(1)),),generators={'conditional':generate},
    plan=lambda v,t,w:ExecutionPlan((),'fixture'),settle=lambda o:())
print(json.dumps({'record':x['decisions'][0]['record_digest'],'replay':x['frozen_replay']}))
"""
            env = dict(os.environ); env["PYTHONPATH"] = str(Path(__file__).parents[1])
            run = subprocess.run([sys.executable, "-c", code, str(recovered_root), cutoff.isoformat()],
                                 check=True, capture_output=True, text=True, env=env)
            restored = json.loads(run.stdout)
            self.assertEqual(restored["record"], expected["decisions"][0]["record_digest"])
            self.assertEqual(restored["replay"], expected["frozen_replay"])


if __name__ == "__main__":
    unittest.main()
