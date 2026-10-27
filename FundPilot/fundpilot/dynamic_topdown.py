"""Synthetic top-down dynamic orchestration over the existing EventSimulator.

One frozen trend is shared by candidate generators; a selector then chooses or
blends target portfolios. Only an explicit planner creates Orders. Settlement is
resolved AFTER selection and is never passed to research callbacks.

This is an engineering adapter, not a new forecasting/optimization framework.
It does not invoke TradingAgents, train a network, establish callback provenance,
enforce external-call budgets, verify real fund rules, or authorize investment.
Callbacks must be pure synthetic fixtures here. A future real adapter requires
separate evidence, budget, model, execution and evaluation qualification.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import heapq
import json

from .backtest import Event, EventSimulator, Order, State, amount, timestamp

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class Datum:
    key: str
    available_at: datetime
    text: str


@dataclass(frozen=True)
class Mark:
    instrument: str
    available_at: datetime
    nav: Decimal


@dataclass(frozen=True)
class View:
    at: datetime
    state: State
    facts: tuple[Datum, ...]
    marks: tuple[Mark, ...]


@dataclass(frozen=True)
class Trend:
    trend_id: str
    cutoff: datetime
    thesis: str
    evidence_refs: tuple[str, ...]
    invalidations: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    trend_digest: str
    # None means retain existing state; CASH is an explicit target component.
    target_weights: tuple[tuple[str, Decimal], ...] | None
    reason: str


@dataclass(frozen=True)
class Choice:
    components: tuple[tuple[str, Decimal], ...]
    reason: str


@dataclass(frozen=True)
class ExecutionPlan:
    orders: tuple[Order, ...]
    reason: str


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _hash(value):
    raw = json.dumps(_plain(value), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def trend_digest(trend):
    return _hash(asdict(trend))


def _weights(items):
    if not isinstance(items, tuple) or not items:
        raise ValueError("nonempty immutable weights required")
    seen = set()
    for key, weight in items:
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("unique component identities required")
        amount(weight)
        if weight > ONE:
            raise ValueError("weight above one")
        seen.add(key)
    if sum((w for _, w in items), ZERO) != ONE:
        raise ValueError("weights must sum to one")
    return dict(items)


def blend(candidates, choice):
    """Combine target weights, never historical returns or separate orders."""
    if not isinstance(choice, Choice) or not choice.reason:
        raise ValueError("explicit choice and reason required")
    parts = _weights(choice.components)
    by_id = {c.candidate_id: c for c in candidates}
    if not set(parts) <= set(by_id):
        raise ValueError("choice references an unknown candidate")
    if any(by_id[k].target_weights is None for k in parts):
        if len(parts) != 1:
            raise ValueError("hold cannot be blended without an explicit valued target")
        return None
    target = {}
    for key, share in parts.items():
        for instrument, weight in by_id[key].target_weights:
            target[instrument] = target.get(instrument, ZERO) + share * weight
    result = tuple(sorted(target.items()))
    _weights(result)
    return result


def run_dynamic(*, initial_cash, rules, cutoffs, end, facts, marks,
                predict, generators, select, plan, settle,
                initial_shares=None, initial_events=(),
                producer="synthetic_fixture"):
    """Run sequential synthetic decisions; callbacks receive only current views.

    predict(view)->Trend; generators[name](view, trend)->Candidate;
    select(view, trend, candidates)->Choice;
    plan(view, trend, target_weights)->ExecutionPlan;
    settle(orders)->future verified Event objects.

    The host remains responsible for pure callbacks and all hard risk limits.
    This adapter cannot prevent a closure/model from remembering future history.
    Fees/rounding/lot constraints remain those of the supplied kernel and planner.
    """
    if producer != "synthetic_fixture":
        raise ValueError("only synthetic fixtures authorized by this entry")
    cutoffs, facts, marks = tuple(cutoffs), tuple(facts), tuple(marks)
    timestamp(end)
    if not cutoffs:
        raise ValueError("at least one decision cutoff required")
    for at in cutoffs:
        timestamp(at)
    if list(cutoffs) != sorted(set(cutoffs)) or cutoffs[-1] > end:
        raise ValueError("strictly ordered cutoffs within end required")
    if not isinstance(generators, dict) or not generators or "hold" in generators:
        raise ValueError("named generators required; hold is reserved")
    for fact in facts:
        if not isinstance(fact, Datum) or not fact.key or not fact.text:
            raise ValueError("typed nonempty evidence required")
        timestamp(fact.available_at)
    if len({f.key for f in facts}) != len(facts):
        raise ValueError("duplicate evidence identity")
    for mark in marks:
        if not isinstance(mark, Mark) or not mark.instrument:
            raise ValueError("typed mark required")
        timestamp(mark.available_at)
        amount(mark.nav)
        if mark.nav <= ZERO:
            raise ValueError("positive mark required")
    if len({(m.instrument, m.available_at) for m in marks}) != len(marks):
        raise ValueError("ambiguous mark version")

    sim = EventSimulator(initial_cash, rules, initial_shares)
    queue, sequence, trace, events_seen = [], 0, [], []

    def enqueue(event, after=None):
        nonlocal sequence
        if not isinstance(event, Event) or isinstance(event, Order):
            raise ValueError("settlement stream must not inject Orders")
        if after is not None and event.at <= after:
            raise ValueError("settlement must follow decision")
        sequence += 1
        heapq.heappush(queue, (event.at, sequence, event))

    for event in initial_events:
        enqueue(event)

    def advance(at):
        while queue and queue[0][0] <= at:
            _, _, event = heapq.heappop(queue)
            sim.apply(event)
            events_seen.append({"type": type(event).__name__, **asdict(event)})

    def view(at):
        latest = {}
        for mark in sorted(marks, key=lambda m: m.available_at):
            if mark.available_at <= at:
                latest[mark.instrument] = mark
        return View(at, sim.state,
                    tuple(f for f in facts if f.available_at <= at),
                    tuple(latest[k] for k in sorted(latest)))

    for at in cutoffs:
        advance(at)
        before = view(at)
        trend = predict(deepcopy(before))
        if (not isinstance(trend, Trend) or not trend.trend_id or not trend.thesis
                or not isinstance(trend.evidence_refs, tuple)
                or not isinstance(trend.invalidations, tuple)
                or not trend.evidence_refs or not trend.invalidations):
            raise ValueError("explicit trend, evidence and invalidations required")
        timestamp(trend.cutoff)
        if trend.cutoff != at:
            raise ValueError("trend must bind the current cutoff")
        if not set(trend.evidence_refs) <= {f.key for f in before.facts}:
            raise ValueError("trend references unavailable evidence")
        if any(not isinstance(x, str) or not x for x in
               (*trend.evidence_refs, *trend.invalidations)):
            raise ValueError("immutable text evidence and invalidations required")
        fingerprint = trend_digest(trend)
        candidates = [Candidate("hold", fingerprint, None, "Retain current portfolio")]
        for name, generate in generators.items():
            candidate = generate(deepcopy(before), trend)
            if (not isinstance(candidate, Candidate) or candidate.candidate_id != name
                    or candidate.trend_digest != fingerprint or not candidate.reason
                    or candidate.target_weights is None):
                raise ValueError("candidate must bind the shared frozen trend")
            _weights(candidate.target_weights)
            candidates.append(candidate)
        candidates = tuple(candidates)
        choice = select(deepcopy(before), trend, candidates)
        target = blend(candidates, choice)
        execution = (ExecutionPlan((), "Retain current portfolio") if target is None
                     else plan(deepcopy(before), trend, target))
        if (not isinstance(execution, ExecutionPlan) or not execution.reason
                or not isinstance(execution.orders, tuple)):
            raise ValueError("explicit execution plan and reason required")
        orders = execution.orders
        if any(not isinstance(o, Order) or o.at != at or o.decision_cutoff != at
               for o in orders):
            raise ValueError("planner Orders must bind the current decision")
        # Validate a complete application batch without partially committing it.
        trial = deepcopy(sim)
        for order in orders:
            trial.apply(order)
        record = {
            "cutoff": at, "trend": asdict(trend), "trend_digest": fingerprint,
            "candidates": [asdict(c) for c in candidates],
            "choice": asdict(choice), "target_weights": target,
            "orders": [asdict(o) for o in orders],
            "execution_reason": execution.reason,
            "available_evidence": [f.key for f in before.facts],
            "known_marks": [asdict(m) for m in before.marks],
            "state_before": {"cash": before.state.cash,
                             "available_cash": before.state.available_cash(at),
                             "reserved_cash": before.state.reserved_cash,
                             "shares": before.state.shares,
                             "receivables": before.state.receivables},
            "previous_digest": trace[-1]["record_digest"] if trace else None,
        }
        record["record_digest"] = _hash(record)
        trace.append(_plain(record))
        future = tuple(settle(orders)) if orders else ()
        for event in future:
            if (not isinstance(event, Event) or isinstance(event, Order)
                    or event.at <= at):
                raise ValueError("settlement must be future non-Order events")
        sim = trial
        for event in future:
            enqueue(event, after=at)
    advance(end)
    final = view(end)
    terminal = final.state.equity({m.instrument: m.nav for m in final.marks})
    return {
        "scope": "synthetic_topdown_dynamic_only",
        "real_model_verified": False, "real_execution_authorized": False,
        "investment_qualified": False,
        "decisions": trace, "settlement_events": _plain(events_seen),
        "terminal_book_equity": str(terminal),
        "terminal_cash": str(final.state.cash),
        "terminal_available_cash": str(final.state.available_cash(end)),
        "terminal_reserved_cash": str(final.state.reserved_cash),
        "terminal_receivables": str(sum((r[1] for r in final.state.receivables.values()), ZERO)),
        "terminal_shares": _plain(final.state.shares),
        "cash_fees": str(final.state.fees), "scheduled_events_after_end": len(queue),
        "limitations": [
            "Synthetic fixture callbacks; no real model or optimization is verified",
            "Known marks are valuation inputs, not execution prices or cash",
            "Fees, rounding, eligibility and lot rules require separate real qualification",
            "No automatic prediction scoring, experience promotion or deployment",
            "Callback closures and model memory cannot be proven free of hindsight",
        ],
    }
