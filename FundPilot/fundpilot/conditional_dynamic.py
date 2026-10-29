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
import hashlib
import json
from pathlib import Path

from .backtest import Confirmation, EventSimulator, Order, Receipt, Rule

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
    if payload.get("schema") != "fundpilot.conditional-dynamic-replay.v1":
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
    last = None
    trace = []
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
        before = sim.state
        applied = []
        for raw in events:
            event = _event(raw, cutoff)
            if isinstance(event, Order) and event.at != cutoff:
                raise ValueError("orders must bind their frozen cutoff")
            sim.apply(event)
            applied.append({"type": type(event).__name__, **_plain(event.__dict__)})
        trace.append({
            "cutoff": cutoff.isoformat(), "decision_ref": row["decision_ref"],
            "choice": row["choice"], "reason": row.get("reason", ""),
            "events": applied,
            "state_before": _plain({"cash": before.cash,
                                     "reserved_cash": before.reserved_cash,
                                     "receivables": before.receivables,
                                     "shares": before.shares}),
            "state_after": _plain({"cash": sim.state.cash,
                                    "reserved_cash": sim.state.reserved_cash,
                                    "receivables": sim.state.receivables,
                                    "shares": sim.state.shares}),
        })
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
        "decisions": trace, "terminal_state": _plain(state.__dict__),
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
    if target.exists():
        raise ValueError("output must not already exist")
    payload = json.loads(source.read_text(encoding="utf-8"))
    result = replay(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "result_sha256": result["result_sha256"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
