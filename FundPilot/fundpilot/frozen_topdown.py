"""Fail-closed offline adapter for already completed LLM bridge artifacts.

This module performs no inference, networking, budget mutation, or order work.
It turns a completed stable research bridge into one immutable ``Trend`` and
validates a *separate* final-choice request/response pair.  In particular, an
upstream research manager's allocation discussion is never treated as the
downstream candidate choice.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from .dynamic_topdown import Candidate, Choice, Trend, run_dynamic, trend_digest
from .upstream_bridge import PIN, SCOPE, checked_time, digest, private_root, read_private


@dataclass(frozen=True)
class FrozenProvenance:
    producer: str
    model_ref: str
    generated_at: datetime
    prompt_sha256: str
    response_sha256: str
    source_file: str
    replayed_frozen_output: bool = True


@dataclass(frozen=True)
class FrozenResearch:
    trend: Trend
    provenance: FrozenProvenance
    choice: None = None
    choice_status: str = "missing_separate_final_choice"


@dataclass(frozen=True)
class FrozenChoice:
    choice: Choice
    provenance: FrozenProvenance


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _binding_digest(value):
    return digest(json.dumps(_plain(value), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode())


def choice_context(candidates, state):
    """Immutable selector inputs for v2 choice envelopes."""
    return {
        "candidate_digest": _binding_digest([asdict(candidate) for candidate in candidates]),
        "state_digest": _binding_digest({
            "cash": state.cash, "reserved_cash": state.reserved_cash,
            "receivables": state.receivables, "shares": state.shares}),
    }


def _object(raw, label):
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _scope(value, label):
    if any(value.get(key) != expected for key, expected in SCOPE.items()):
        raise ValueError(f"{label} scope mismatch")


def _response(request, response, *, role, now_limit=None):
    if request.get("role") != role:
        raise ValueError("saved request role mismatch")
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or digest(prompt.encode()) != request.get("prompt_sha256"):
        raise ValueError("saved prompt hash mismatch")
    if response.get("prompt_sha256") != request["prompt_sha256"]:
        raise ValueError("response prompt binding mismatch")
    if response.get("producer") not in ("actual_current_llm", "synthetic_fixture"):
        raise ValueError("response producer mismatch")
    if not isinstance(response.get("model_ref"), str) or not response["model_ref"].strip():
        raise ValueError("response model reference missing")
    generated = checked_time(response.get("generated_at", ""))
    captured = checked_time(request.get("captured_at", ""))
    if generated < captured or generated > (now_limit or datetime.now(timezone.utc)):
        raise ValueError("response generation time mismatch")
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("response content missing")
    return content, generated


def _cutoff(value):
    if not isinstance(value, str):
        raise ValueError("exact information cutoff required")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("exact timezone-aware information cutoff required") from exc
    if result.tzinfo is None:
        raise ValueError("exact timezone-aware information cutoff required")
    return result


def _manager_trend(content, cutoff, response_sha):
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("structured manager JSON required; frozen prose is not inference") from exc
    if not isinstance(value, dict) or not isinstance(value.get("forecasts"), list):
        raise ValueError("structured manager JSON required; frozen prose is not inference")
    forecasts = value["forecasts"]
    if {row.get("horizon") for row in forecasts if isinstance(row, dict)} != {1, 5, 20} or len(forecasts) != 3:
        raise ValueError("exact 1/5/20 forecast horizons required")
    directions = {"up", "flat", "down", "abstain"}
    by_horizon = {}
    invalidations = []
    for row in forecasts:
        required = ("rationale", "counterevidence", "invalidation")
        gaps = row.get("gaps")
        complete_gaps = ((isinstance(gaps, str) and gaps.strip()) or
                         (isinstance(gaps, list) and gaps and
                          all(isinstance(gap, str) and gap.strip() for gap in gaps)))
        if (row.get("direction") not in directions or
                any(not isinstance(row.get(key), str) or not row[key].strip() for key in required) or
                not complete_gaps or
                (row.get("p_up") is not None and not isinstance(row.get("p_up"), (int, float)))):
            raise ValueError("complete structured forecast fields required")
        if row.get("p_up") is not None and not 0 <= row["p_up"] <= 1:
            raise ValueError("forecast probability outside unit interval")
        by_horizon[row["horizon"]] = row
        invalidations.append(f"h{row['horizon']}:{row['invalidation']}")
    thesis = "; ".join(f"{h}:{by_horizon[h]['direction']} — {by_horizon[h]['rationale']}"
                       for h in (1, 5, 20))
    return Trend("frozen-bridge-" + response_sha[:16], cutoff, thesis,
                 ("response-3.json#forecasts",), tuple(invalidations))


def load_frozen_research(root, expected_cutoff):
    """Load a completed stable bridge without replaying or invoking its graph."""
    root = private_root(root)
    input_raw = read_private(root / "input.json")
    evidence = _object(input_raw, "input")
    receipt = _object(read_private(root / "receipt.json"), "receipt")
    result = _object(read_private(root / "result.json"), "result")
    if (receipt.get("bridge_schema") != 2 or receipt.get("graph_mode", "stable") != "stable" or
            receipt.get("upstream_sha") != PIN or result.get("upstream_sha") != PIN):
        raise ValueError("completed stable pinned bridge required")
    _scope(receipt, "receipt"); _scope(result, "result")
    if digest(input_raw) != receipt.get("input_sha256"):
        raise ValueError("input receipt hash mismatch")
    cutoff = _cutoff(evidence.get("information_cutoff"))
    if not isinstance(expected_cutoff, datetime) or expected_cutoff.tzinfo is None or expected_cutoff != cutoff:
        raise ValueError("expected cutoff must exactly equal frozen information cutoff")
    if result.get("bridge_responses") != 3 or result.get("response_producers") not in (
            ["actual_current_llm"] * 3, ["synthetic_fixture"] * 3):
        raise ValueError("complete homogeneous three-response bridge required")
    requests = sorted(root.glob("request-*.json"))
    responses = sorted(root.glob("response-*.json"))
    if [p.name for p in requests] != [f"request-{i}.json" for i in range(1, 4)] or [p.name for p in responses] != [f"response-{i}.json" for i in range(1, 4)]:
        raise ValueError("complete contiguous bridge evidence required")
    manager = None
    for index, role in enumerate(("bull", "bear", "manager"), 1):
        request = _object(read_private(root / f"request-{index}.json"), "request")
        response_raw = read_private(root / f"response-{index}.json")
        response = _object(response_raw, "response")
        content, generated = _response(request, response, role=role)
        if response["producer"] != result["response_producers"][index - 1]:
            raise ValueError("result producer list mismatch")
        if role == "manager":
            manager = (content, generated, response, digest(response_raw))
    if result.get("research_state", {}).get("investment_plan") != manager[0]:
        raise ValueError("completed result differs from manager response")
    completed = checked_time(result.get("completed_at", ""))
    if completed < manager[1] or completed > datetime.now(timezone.utc):
        raise ValueError("completed result time mismatch")
    trend = _manager_trend(manager[0], cutoff, manager[3])
    provenance = FrozenProvenance(manager[2]["producer"], manager[2]["model_ref"], manager[1],
                                  manager[2]["prompt_sha256"], manager[3], "response-3.json")
    return FrozenResearch(trend, provenance)


def load_frozen_choice(request_path, response_path, trend, candidates, state=None):
    """Validate a distinct final-selection envelope; never reuse manager prose."""
    request_raw = read_private(request_path); response_raw = read_private(response_path)
    request = _object(request_raw, "choice request"); response = _object(response_raw, "choice response")
    schema = request.get("schema")
    if (schema not in ("fundpilot.final-choice-request.v1", "fundpilot.final-choice-request.v2")
            or response.get("schema") != schema.replace("request", "response")):
        raise ValueError("final choice schema mismatch")
    fields = ["schema", "trend_digest", "candidate_ids"]
    if schema.endswith(".v2"):
        if state is None:
            raise ValueError("v2 final choice requires current state")
        fields += ["candidate_digest", "state_digest"]
    unsigned = {key: request[key] for key in fields if key in request}
    expected_prompt = digest(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode())
    if request.get("prompt_sha256") != expected_prompt or response.get("prompt_sha256") != expected_prompt:
        raise ValueError("final choice prompt binding mismatch")
    if request.get("trend_digest") != trend_digest(trend):
        raise ValueError("final choice trend binding mismatch")
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if request.get("candidate_ids") != candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("final choice candidate binding mismatch")
    if schema.endswith(".v2"):
        expected = choice_context(candidates, state)
        if any(request.get(key) != value for key, value in expected.items()):
            raise ValueError("final choice candidate content or state binding mismatch")
    if response.get("producer") not in ("actual_current_llm", "synthetic_fixture") or not response.get("model_ref"):
        raise ValueError("final choice producer mismatch")
    generated = checked_time(response.get("generated_at", "")); captured = checked_time(request.get("captured_at", ""))
    if not captured <= generated <= datetime.now(timezone.utc):
        raise ValueError("final choice generation time mismatch")
    if not isinstance(response.get("reason"), str) or not response["reason"].strip():
        raise ValueError("final choice reason required")
    components = response.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("final choice components required")
    parsed = []
    for item in components:
        if not isinstance(item, dict) or item.get("candidate_id") not in candidate_ids:
            raise ValueError("final choice references unknown candidate")
        try:
            weight = Decimal(item.get("weight"))
        except Exception as exc:
            raise ValueError("final choice weight invalid") from exc
        if weight < 0 or weight > 1:
            raise ValueError("final choice weight invalid")
        parsed.append((item["candidate_id"], weight))
    if len({key for key, _ in parsed}) != len(parsed) or sum((weight for _, weight in parsed), Decimal(0)) != 1:
        raise ValueError("final choice weights must be unique and sum to one")
    choice = Choice(tuple(parsed), response["reason"])
    provenance = FrozenProvenance(response["producer"], response["model_ref"], generated,
                                  expected_prompt, digest(response_raw), Path(response_path).name)
    return FrozenChoice(choice, provenance)


def run_frozen_synthetic(*, research_root, choice_request, choice_response,
                         initial_cash, rules, cutoffs, end, facts, marks,
                         generators, plan, settle, initial_shares=None,
                         initial_events=()):
    """Replay one complete synthetic frozen decision through ``run_dynamic``.

    The bridge artifacts and final choice must both be ``synthetic_fixture``.
    This function deliberately cannot run an actual model response: it is a
    recovery/integration fixture for the offline envelopes, not a live adapter.
    Historical generation is generally later than its information cutoff, so
    the returned metadata always keeps temporal/OOS qualification false.
    """
    cutoffs = tuple(cutoffs)
    if len(cutoffs) != 1:
        raise ValueError("frozen synthetic replay requires exactly one cutoff")
    research = load_frozen_research(research_root, cutoffs[0])
    if research.provenance.producer != "synthetic_fixture":
        raise ValueError("dynamic replay accepts only a synthetic fixture research producer")
    selected = []

    def predict(view):
        return research.trend

    def select(view, trend, candidates):
        frozen = load_frozen_choice(choice_request, choice_response, trend, candidates, view.state)
        if frozen.provenance.producer != "synthetic_fixture":
            raise ValueError("dynamic replay accepts only a synthetic fixture choice producer")
        selected.append(frozen)
        return frozen.choice

    result = run_dynamic(
        initial_cash=initial_cash, rules=rules, cutoffs=cutoffs, end=end,
        facts=facts, marks=marks, predict=predict, generators=generators,
        select=select, plan=plan, settle=settle,
        initial_shares=initial_shares, initial_events=initial_events,
        producer="synthetic_fixture")
    if len(selected) != 1:
        raise ValueError("exactly one frozen choice must be consumed")
    result["frozen_replay"] = {
        "schema": "fundpilot.frozen-synthetic-replay.v1",
        "replayed_frozen_output": True,
        "new_model_inference": False,
        "temporal_oos_qualified": False,
        "research": {
            "producer": research.provenance.producer,
            "model_ref": research.provenance.model_ref,
            "generated_at": research.provenance.generated_at.isoformat(),
            "prompt_sha256": research.provenance.prompt_sha256,
            "response_sha256": research.provenance.response_sha256,
            "source_file": research.provenance.source_file,
        },
        "choice": {
            "producer": selected[0].provenance.producer,
            "model_ref": selected[0].provenance.model_ref,
            "generated_at": selected[0].provenance.generated_at.isoformat(),
            "prompt_sha256": selected[0].provenance.prompt_sha256,
            "response_sha256": selected[0].provenance.response_sha256,
            "source_file": selected[0].provenance.source_file,
        },
    }
    return result
