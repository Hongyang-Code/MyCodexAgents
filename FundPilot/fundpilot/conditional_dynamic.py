"""Input-driven conditional historical replay over :mod:`fundpilot.backtest`.

This adapter performs no research, inference, strategy selection, networking, or
order submission.  It replays decisions and events that were frozen elsewhere.
``event_kernel_attested`` only means the caller accepts the typed EventSimulator
inputs for this conditional study; it is not evidence of a real fill.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
import heapq
import hashlib
import json
from pathlib import Path

from .backtest import Confirmation, EventSimulator, Order, Receipt, Rule
from .dynamic_topdown import Candidate, _weights, trend_digest
from .frozen_topdown import (
    load_complete_comparison_choice,
    load_complete_comparison_research,
    load_frozen_choice,
    load_frozen_research,
)
from .upstream_bridge import read_private, write_bytes_new

D = Decimal
ZERO = D("0")


def _time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return result


def _plain(value):
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return sorted(_plain(item) for item in value)
    return value


def _digest(value):
    raw = json.dumps(_plain(value), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _state_payload(state):
    return _plain({"cash": state.cash, "reserved_cash": state.reserved_cash,
                   "receivables": state.receivables, "shares": state.shares})


def _candidates(rows, trend):
    if not isinstance(rows, list) or not rows:
        raise ValueError("strict v2 requires the complete frozen candidate set")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("candidate_id"), str):
            raise ValueError("complete candidate identity required")
        weights = row.get("target_weights")
        available = row.get("available", True)
        if available is False:
            if weights is not None or not isinstance(row.get("unavailable_reason"), str):
                raise ValueError("unavailable candidate requires null weights and a reason")
            continue
        if weights is not None:
            if (not isinstance(weights, list) or not weights or
                    any(not isinstance(item, list) or len(item) != 2 for item in weights)):
                raise ValueError("candidate target_weights must be null or complete pairs")
            weights = tuple((str(key), D(str(value))) for key, value in weights)
        if row["candidate_id"] == "hold":
            if weights is not None:
                raise ValueError("hold candidate must preserve current state with target_weights null")
        else:
            if weights is None:
                raise ValueError("non-hold candidate requires explicit target_weights")
            _weights(weights)
        reason = row.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ValueError("candidate reason required")
        result.append(Candidate(row["candidate_id"], trend_digest(trend), weights, reason))
    ids = [candidate.candidate_id for candidate in result]
    if len(ids) != len(set(ids)) or "hold" not in ids:
        raise ValueError("unique candidates including hold required")
    return tuple(result)


def _order_intents(row):
    """Selector-visible current orders, excluding unknowable future settlements."""
    fields = ("type", "event_id", "at", "source", "instrument", "side",
              "quantity", "rule_id")
    return [{key: event[key] for key in fields if key in event}
            for event in row.get("events", []) if event.get("type") == "order"]


def _candidate_plans(rows):
    result = []
    for row in rows:
        plan = row.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("each candidate requires a frozen executable plan")
        intents = plan.get("order_intents")
        unavailable = plan.get("unavailable_reason")
        if (intents is None) == (unavailable is None):
            raise ValueError("candidate plan requires orders or unavailable reason")
        if intents is not None and (not isinstance(intents, list) or
                                    any(not isinstance(item, dict) for item in intents)):
            raise ValueError("candidate order intents must be a complete list")
        result.append({"candidate_id": row["candidate_id"],
                       "target_weights": row.get("target_weights"),
                       "reason": row["reason"], "fees": row.get("fees"),
                       "risk": row.get("risk"), "order_intents": intents,
                       "unavailable_reason": unavailable})
    return result


def _complete_case_plans(rows):
    """Validate and preserve the original readable plan table byte semantics."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("complete-comparison candidate plan table required")
    ids = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("candidate_id"), str):
            raise ValueError("complete-comparison candidate identity required")
        ids.append(row["candidate_id"])
        available = row.get("available")
        intents = row.get("order_intents")
        if available is True:
            if not isinstance(intents, list):
                raise ValueError("available candidate requires order intents")
        elif available is False:
            if intents is not None or not isinstance(row.get("unavailable_reason"), str):
                raise ValueError("unavailable candidate requires a reason and no order intents")
        else:
            raise ValueError("complete-comparison candidate availability required")
    if len(ids) != len(set(ids)) or "hold" not in ids:
        raise ValueError("unique complete-comparison candidates including hold required")
    return rows


def _strict_decision(row, state, cutoff):
    """Verify real saved research and selector artifacts; never trust supplied hashes."""
    artifacts = row.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("strict v2 requires saved research and choice artifacts")
    complete_schema = artifacts.get("schema") == "fundpilot.complete-comparison-artifacts.v1"
    if complete_schema:
        research_layout = artifacts.get("research")
        choice_layout = artifacts.get("choice")
        if not isinstance(research_layout, dict) or not isinstance(choice_layout, dict):
            raise ValueError("complete-comparison research and choice layouts required")
        research_cutoff = _time(research_layout.get("information_cutoff"))
        if research_cutoff > cutoff:
            raise ValueError("reused research cannot postdate the decision")
        reused = research_cutoff < cutoff
        if reused and row.get("research_reuse") != "explicit_frozen_reuse":
            raise ValueError("later decision requires explicit frozen research reuse marker")
        frozen = load_complete_comparison_research(research_layout, research_cutoff)
        plans = _complete_case_plans(row.get("candidate_plans"))
        candidates = _candidates(plans, frozen.trend)
    else:
        required = ("research_root", "choice_request", "choice_response")
        if any(not isinstance(artifacts.get(key), str) or not artifacts[key] for key in required):
            raise ValueError("strict v2 saved artifact paths are incomplete")
        frozen = load_frozen_research(Path(artifacts["research_root"]), cutoff)
        candidates = _candidates(row.get("candidates"), frozen.trend)
        plans = _candidate_plans(row.get("candidates"))
        reused = False
    envelope = {"cutoff": row["cutoff"], "decision_ref": row["decision_ref"],
                "candidate_plans": plans}
    if complete_schema:
        selected = load_complete_comparison_choice(
            choice_layout, frozen, candidates, state, envelope)
    else:
        selected = load_frozen_choice(
            Path(artifacts["choice_request"]), Path(artifacts["choice_response"]),
            frozen.trend, candidates, state, envelope,
            required_schema="fundpilot.final-choice-request.v2")
    if selected.choice.components != ((row["choice"], D("1")),):
        raise ValueError("saved final choice does not exactly match frozen replay choice")
    selected_plan = next(item for item in plans if item["candidate_id"] == row["choice"])
    if selected_plan.get("unavailable_reason") is not None:
        raise ValueError("saved final choice selected an unavailable candidate")
    if selected_plan["order_intents"] != _order_intents(row):
        raise ValueError("actual orders differ from the pre-choice candidate plan")
    return {
        "binding_sha256": _digest({
            "trend": trend_digest(frozen.trend),
            "research_response": frozen.provenance.response_sha256,
            "choice_response": selected.provenance.response_sha256,
            "candidates": [_plain(asdict(candidate)) for candidate in candidates],
            "state": _state_payload(state), "decision": envelope}),
        "research_response_sha256": frozen.provenance.response_sha256,
        "choice_response_sha256": selected.provenance.response_sha256,
        "research_reused": reused,
        "provider_time_unknown": frozen.provenance.provider_time_unknown,
        "semantic_contract_status": frozen.semantic_contract_status,
    }


def _rule(row):
    return Rule(row["rule_id"], row["instrument"], _time(row["effective_from"]),
                _time(row["effective_to"]), _time(row["published_at"]),
                _time(row["available_at"]), D(row["buy_rate"]),
                D(row["sell_rate"]), row["source"], True,
                row.get("buy_fee_basis", "net"))


def _event(row, cutoff):
    common = (row["event_id"], _time(row["at"]), row["source"], True)
    if row["type"] == "order":
        return Order(*common, row["instrument"], row["side"], D(row["quantity"]),
                     row["rule_id"], cutoff)
    if row["type"] == "confirmation":
        return Confirmation(*common, row["order_id"], D(row["price"]),
                            _time(row["price_determined_at"]),
                            _time(row["price_published_at"]),
                            _time(row["price_available_at"]))
    if row["type"] == "receipt":
        return Receipt(*common, row["receivable_id"])
    raise ValueError("unsupported frozen event type")


def replay(payload):
    """Replay one already-frozen conditional case, without selecting again."""
    schema = payload.get("schema")
    if schema not in ("fundpilot.conditional-dynamic-replay.v1",
                      "fundpilot.conditional-dynamic-replay.v2"):
        raise ValueError("conditional replay schema required")
    if payload.get("mode") != "conditional_historical":
        raise ValueError("explicit conditional_historical mode required")
    if payload.get("event_kernel_attested") is not True:
        raise ValueError("typed event-kernel attestation required")
    if payload.get("real_execution_verified") is not False:
        raise ValueError("conditional replay must not claim real execution")
    rules = tuple(_rule(row) for row in payload["rules"])
    rule_by_id = {rule.rule_id: rule for rule in rules}
    sim = EventSimulator(D(payload["initial_cash"]), rules,
                         {key: D(value) for key, value in payload.get("initial_shares", {}).items()})
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("at least one frozen decision required")
    end_at = _time(payload["end_at"])
    liquidation_at = _time(payload["liquidation_at"])
    if liquidation_at < end_at:
        raise ValueError("conditional liquidation cannot precede replay end")
    last = None
    trace, applied_settlements, queue, sequence = [], [], [], 0

    def enqueue(event, cutoff):
        nonlocal sequence
        if isinstance(event, Order):
            raise ValueError("settlement queue cannot inject Orders")
        if event.at <= cutoff:
            raise ValueError("frozen settlement must follow its decision cutoff")
        sequence += 1
        heapq.heappush(queue, (event.at, sequence, event))

    def advance(at):
        while queue and queue[0][0] <= at:
            _, _, event = heapq.heappop(queue)
            sim.apply(event)
            applied_settlements.append({"type": type(event).__name__,
                                        **_plain(event.__dict__)})

    for row in decisions:
        cutoff = _time(row["cutoff"])
        if last is not None and cutoff <= last:
            raise ValueError("strictly increasing decision cutoffs required")
        last = cutoff
        if not row.get("decision_ref") or not row.get("choice"):
            raise ValueError("frozen decision identity and choice required")
        events = row.get("events", [])
        if row["choice"] == "hold" and events:
            raise ValueError("hold decision cannot introduce events")
        advance(cutoff)
        before = sim.state
        binding = (_strict_decision(row, before, cutoff)
                   if schema.endswith(".v2") else None)
        orders, scheduled = [], []
        for raw in events:
            event = _event(raw, cutoff)
            if isinstance(event, Order):
                if event.at != cutoff:
                    raise ValueError("orders must bind their frozen cutoff")
                sim.apply(event)
                orders.append({"type": type(event).__name__, **_plain(event.__dict__)})
            else:
                enqueue(event, cutoff)
                scheduled.append({"type": type(event).__name__, **_plain(event.__dict__)})
        trace.append({
            "cutoff": cutoff.isoformat(), "decision_ref": row["decision_ref"],
            "choice": row["choice"], "reason": row.get("reason", ""),
            "orders": orders, "scheduled_settlements": scheduled,
            "state_before": _state_payload(before),
            "decision_context_sha256": binding["binding_sha256"] if binding else None,
            "research_response_sha256": binding["research_response_sha256"] if binding else None,
            "choice_response_sha256": binding["choice_response_sha256"] if binding else None,
            "research_reused": binding["research_reused"] if binding else False,
            "provider_time_unknown": binding["provider_time_unknown"] if binding else False,
            "semantic_contract_status": binding["semantic_contract_status"] if binding else None,
            "state_after_orders": _plain({"cash": sim.state.cash,
                                           "reserved_cash": sim.state.reserved_cash,
                                           "receivables": sim.state.receivables,
                                           "shares": sim.state.shares}),
        })
    if end_at < last:
        raise ValueError("replay end cannot precede the final cutoff")
    advance(end_at)
    marks = {key: D(value) for key, value in payload["end_marks"].items()}
    state = sim.state
    book = state.equity(marks)
    conditional = state.cash + state.reserved_cash + sum(
        (item[1] for item in state.receivables.values()), ZERO)
    liquidation = []
    for instrument, units in state.shares.items():
        if units:
            rule_id = payload["liquidation_rule_ids"][instrument]
            rule = rule_by_id[rule_id]
            if rule.instrument != instrument:
                raise ValueError("conditional liquidation rule instrument mismatch")
            if not rule.effective_from <= liquidation_at < rule.effective_to:
                raise ValueError("conditional liquidation rule not effective at liquidation time")
            if rule.available_at > liquidation_at:
                raise ValueError("conditional liquidation rule unavailable at liquidation time")
            gross = units * marks[instrument]
            fee = gross * rule.sell_rate
            conditional += gross - fee
            liquidation.append({"instrument": instrument, "units": units,
                                "mark": marks[instrument], "gross": gross,
                                "fee": fee, "conditional_net": gross - fee})
    result = {
        "schema": "fundpilot.conditional-dynamic-result.v1",
        "mode": "conditional_historical", "input_sha256": _digest(payload),
        "new_research": False, "new_model_inference": False,
        "new_strategy_evaluation": False, "real_execution_verified": False,
        "temporal_oos_qualified": False, "investment_qualified": False,
        "event_kernel_attested": True,
        "event_kernel_attestation_scope": "conditional_internal_consistency_only",
        "decision_context_bound": schema.endswith(".v2"),
        "saved_artifacts_verified": schema.endswith(".v2"),
        "legacy_unbound_decision_context": schema.endswith(".v1"),
        "end_at": end_at.isoformat(), "liquidation_at": liquidation_at.isoformat(),
        "decisions": trace, "applied_settlements": applied_settlements,
        "terminal_state": _plain(state.__dict__),
        "pending_events_after_end": [
            {"type": type(item[2]).__name__, **_plain(item[2].__dict__)}
            for item in sorted(queue)],
        "terminal_book_equity": str(book),
        "conditional_liquidation_value": str(conditional),
        "conditional_liquidation": _plain(liquidation),
        "conditional_liquidation_is_settled_cash": False,
        "limitations": list(payload.get("limitations", [])),
    }
    result["result_sha256"] = _digest(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay a frozen conditional historical case")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    source = Path(args.input); target = Path(args.output)
    payload = json.loads(read_private(source))
    result = replay(payload)
    raw = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    write_bytes_new(target, raw)
    print(json.dumps({"output": str(target), "result_sha256": result["result_sha256"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
