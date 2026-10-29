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
from .upstream_bridge import read_private, write_bytes_new

D = Decimal
ZERO = D("0")
HEX = set("0123456789abcdef")


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


def _sha(value, label):
    if not isinstance(value, str) or len(value) != 64 or set(value) - HEX:
        raise ValueError(f"{label} must be a lowercase SHA256")
    return value


def _decision_context(row, state, instruments):
    """Bind research, candidates, choice and the state actually seen."""
    context = row.get("decision_context")
    if not isinstance(context, dict):
        raise ValueError("v2 decision_context required")
    expected = context.get("expected_state_before")
    actual = _state_payload(state)
    if expected != actual:
        raise ValueError("decision context state does not match replay state")
    research = context.get("research")
    if not isinstance(research, dict):
        raise ValueError("decision research binding required")
    targets = research.get("target_instruments")
    if (not isinstance(targets, list) or not targets or len(targets) != len(set(targets))
            or not set(targets) <= instruments):
        raise ValueError("decision research instruments must match replay instruments")
    if research.get("horizons") != [1, 5, 20]:
        raise ValueError("decision research must preserve 1/5/20 targets")
    responses = research.get("response_sha256s")
    if not isinstance(responses, list) or len(responses) != 3:
        raise ValueError("exactly three frozen research response hashes required")
    for value in responses:
        _sha(value, "research response")
    candidates = context.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("frozen candidate set required")
    ids = [item.get("candidate_id") for item in candidates if isinstance(item, dict)]
    if len(ids) != len(candidates) or any(not isinstance(x, str) or not x for x in ids):
        raise ValueError("candidate identities required")
    if len(ids) != len(set(ids)) or "hold" not in ids:
        raise ValueError("unique candidates including hold required")
    hold = candidates[ids.index("hold")]
    if hold.get("semantics") != "retain_current_state":
        raise ValueError("hold must mean retain_current_state")
    selected = context.get("selected_candidate_id")
    if selected not in ids or selected != row.get("choice"):
        raise ValueError("selected candidate must bind the frozen choice")
    _sha(context.get("choice_response_sha256"), "choice response")
    supplied = _sha(context.get("context_sha256"), "decision context")
    body = {key: value for key, value in context.items() if key != "context_sha256"}
    if supplied != _digest(body):
        raise ValueError("decision context hash mismatch")
    return supplied


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
    instruments = {rule.instrument for rule in rules}
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
        context_sha = (_decision_context(row, before, instruments)
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
            "decision_context_sha256": context_sha,
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
