"""Verified historical event replay, NOT an autonomous strategy backtester.

All fixtures are synthetic. Callers must independently verify product/share class,
channel, historical rule versions, lot-specific redemption fee applicability,
trading eligibility and each timestamp. `verified=True` records that attestation;
it does not establish source truth. No network, order submission or external cash.

An Order contains no execution price. Future prices arrive only in Confirmation
and cannot be exposed by this kernel to an order-decision callback (none exists).
This cannot prove that an externally supplied order was chosen without hindsight.
No 15:00 cutoff, calendar, settlement lag, fills, rounding or discount is guessed.
Fee amounts are exact Decimal arithmetic; product-specific rounding must be
verified by the caller before using this research kernel for an executable study.
NAV already includes ongoing fees: only explicit subscription/redemption charges
are applied. No extra management/custody/sales-service fee is subtracted.

Cash is reserved at buy application; redemption units remain invested but frozen
until confirmation; redemption cash becomes spendable strictly AFTER its receipt
timestamp. Income is not an external contribution. Distribution entitlements are
recorded separately from ex-date and payout/reinvestment. The engine exposes
positions, cash, reservations and receivables; it does not turn stale NAV marks
into purported realized profits. Failures leave the prior state untouched.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable

ZERO = Decimal("0")


def amount(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError("nonnegative finite Decimal required")


def timestamp(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    instrument: str
    effective_from: datetime
    effective_to: datetime
    published_at: datetime
    available_at: datetime
    buy_rate: Decimal
    sell_rate: Decimal
    source: str
    verified: bool
    buy_fee_basis: str = "net"  # gross/(1+rate), or explicitly gross*rate

    def __post_init__(self):
        for t in (self.effective_from, self.effective_to, self.published_at, self.available_at):
            timestamp(t)
        for rate in (self.buy_rate, self.sell_rate):
            amount(rate)
            if rate >= 1:
                raise ValueError("fee rate must be below one")
        if (not all((self.rule_id, self.instrument, self.source)) or self.verified is not True
                or self.effective_from >= self.effective_to or self.published_at > self.available_at
                or self.buy_fee_basis not in ("net", "gross")):
            raise ValueError("verified valid historical rule required")


@dataclass(frozen=True)
class Event:
    event_id: str
    at: datetime
    source: str
    verified: bool

    def __post_init__(self):
        timestamp(self.at)
        if not self.event_id or not self.source or self.verified is not True:
            raise ValueError("verified event with evidence required")


@dataclass(frozen=True)
class Order(Event):
    instrument: str
    side: str
    quantity: Decimal  # gross cash for buy; units for sell
    rule_id: str
    decision_cutoff: datetime

    def __post_init__(self):
        super().__post_init__()
        amount(self.quantity)
        timestamp(self.decision_cutoff)
        if (not self.instrument or not self.rule_id or self.side not in ("buy", "sell")
                or self.quantity <= 0 or self.decision_cutoff > self.at):
            raise ValueError("invalid order")


@dataclass(frozen=True)
class Confirmation(Event):
    order_id: str
    price: Decimal
    price_determined_at: datetime
    price_published_at: datetime
    price_available_at: datetime

    def __post_init__(self):
        super().__post_init__()
        amount(self.price)
        for t in (self.price_determined_at, self.price_published_at, self.price_available_at):
            timestamp(t)
        if (not self.order_id or self.price <= 0
                or not self.price_determined_at <= self.price_published_at <= self.price_available_at <= self.at):
            raise ValueError("unavailable or invalid confirmation price")


@dataclass(frozen=True)
class Receipt(Event):
    receivable_id: str


@dataclass(frozen=True)
class DistributionRecord(Event):
    instrument: str
    per_unit: Decimal
    mode: str  # cash or reinvest

    def __post_init__(self):
        super().__post_init__()
        amount(self.per_unit)
        if not self.instrument or self.per_unit <= 0 or self.mode not in ("cash", "reinvest"):
            raise ValueError("invalid distribution record")


@dataclass(frozen=True)
class DistributionEx(Event):
    record_id: str


@dataclass(frozen=True)
class Reinvestment(Event):
    receivable_id: str
    price: Decimal
    price_determined_at: datetime
    price_published_at: datetime
    price_available_at: datetime

    def __post_init__(self):
        super().__post_init__()
        amount(self.price)
        for t in (self.price_determined_at, self.price_published_at, self.price_available_at):
            timestamp(t)
        if (not self.receivable_id or self.price <= 0
                or not self.price_determined_at <= self.price_published_at <= self.price_available_at <= self.at):
            raise ValueError("invalid reinvestment price")


@dataclass
class State:
    cash: Decimal
    shares: dict[str, Decimal] = field(default_factory=dict)
    reserved_cash: Decimal = ZERO
    frozen_shares: dict[str, Decimal] = field(default_factory=dict)
    receivables: dict[str, tuple[str, Decimal, str, datetime]] = field(default_factory=dict)
    fees: Decimal = ZERO
    income: Decimal = ZERO
    orders: dict[str, Order] = field(default_factory=dict)
    confirmed: set[str] = field(default_factory=set)
    records: dict[str, tuple[DistributionRecord, Decimal]] = field(default_factory=dict)
    distributions_ex: set[str] = field(default_factory=set)
    received_at: dict[datetime, Decimal] = field(default_factory=dict)
    event_ids: set[str] = field(default_factory=set)
    last_at: datetime | None = None

    def available_cash(self, now: datetime) -> Decimal:
        """Same-timestamp receipts cannot fund orders, irrespective of event order."""
        timestamp(now)
        return self.cash - sum((v for t, v in self.received_at.items() if t >= now), ZERO)

    def equity(self, marks: dict[str, Decimal]) -> Decimal:
        """Caller-supplied marks; values may be stale and are not execution prices."""
        for instrument, units in self.shares.items():
            if units and instrument not in marks:
                raise ValueError("missing position mark")
        for value in marks.values():
            amount(value)
            if value <= 0:
                raise ValueError("positive mark required")
        return (self.cash + self.reserved_cash + sum((r[1] for r in self.receivables.values()), ZERO)
                + sum((units * marks[instrument] for instrument, units in self.shares.items() if units), ZERO))


class EventSimulator:
    def __init__(self, initial_cash: Decimal, rules: Iterable[Rule],
                 initial_shares: dict[str, Decimal] | None = None):
        amount(initial_cash)
        shares = dict(initial_shares or {})
        for instrument, units in shares.items():
            if not instrument:
                raise ValueError("instrument identity required")
            amount(units)
        rules = tuple(rules)
        self._rules = {r.rule_id: r for r in rules}
        if len(self._rules) != len(rules):
            raise ValueError("duplicate rule ID")
        self._state = State(initial_cash, shares)

    @property
    def state(self) -> State:
        return deepcopy(self._state)

    def apply(self, event: Event) -> State:
        if not isinstance(event, Event):
            raise ValueError("typed verified event required")
        s = deepcopy(self._state)
        if event.event_id in s.event_ids:
            raise ValueError("duplicate event; replay must not double-credit")
        if s.last_at is not None and event.at < s.last_at:
            raise ValueError("events must be chronological")
        if isinstance(event, Order):
            rule = self._rules.get(event.rule_id)
            if (rule is None or rule.instrument != event.instrument
                    or not rule.effective_from <= event.at < rule.effective_to
                    or rule.available_at > event.decision_cutoff):
                raise ValueError("rule not applicable or unavailable at decision time")
            if event.side == "buy":
                if event.quantity > s.available_cash(event.at):
                    raise ValueError("insufficient settled cash")
                s.cash -= event.quantity
                s.reserved_cash += event.quantity
            else:
                available = s.shares.get(event.instrument, ZERO) - s.frozen_shares.get(event.instrument, ZERO)
                if event.quantity > available:
                    raise ValueError("insufficient confirmed unfrozen units")
                s.frozen_shares[event.instrument] = s.frozen_shares.get(event.instrument, ZERO) + event.quantity
            s.orders[event.event_id] = event
        elif isinstance(event, Confirmation):
            order = s.orders.get(event.order_id)
            if order is None or event.order_id in s.confirmed:
                raise ValueError("unknown or already confirmed order")
            if event.price_determined_at <= order.at or event.at <= order.at:
                raise ValueError("unknown-price order must precede price determination and confirmation")
            rule = self._rules[order.rule_id]
            if order.side == "buy":
                net = (order.quantity / (1 + rule.buy_rate) if rule.buy_fee_basis == "net"
                       else order.quantity * (1 - rule.buy_rate))
                s.reserved_cash -= order.quantity
                s.fees += order.quantity - net
                s.shares[order.instrument] = s.shares.get(order.instrument, ZERO) + net / event.price
            else:
                gross = order.quantity * event.price
                fee = gross * rule.sell_rate
                s.shares[order.instrument] -= order.quantity
                s.frozen_shares[order.instrument] -= order.quantity
                s.fees += fee
                s.receivables[event.event_id] = (order.instrument, gross - fee, "redemption", event.at)
            s.confirmed.add(event.order_id)
        elif isinstance(event, DistributionRecord):
            # Captures actual record-time entitlement before later sales/ex-date.
            units = s.shares.get(event.instrument, ZERO)
            if units <= 0:
                raise ValueError("no confirmed distribution entitlement")
            s.records[event.event_id] = (event, units * event.per_unit)
        elif isinstance(event, DistributionEx):
            record = s.records.get(event.record_id)
            if record is None or event.record_id in s.distributions_ex:
                raise ValueError("unknown or duplicate distribution ex-date")
            declaration, income = record
            if event.at < declaration.at:
                raise ValueError("ex-date precedes record")
            s.receivables[event.event_id] = (declaration.instrument, income, declaration.mode, event.at)
            s.income += income
            s.distributions_ex.add(event.record_id)
        elif isinstance(event, Receipt):
            receivable = s.receivables.get(event.receivable_id)
            if receivable is None or receivable[2] == "reinvest":
                raise ValueError("unknown, paid or noncash receivable")
            if event.at < receivable[3]:
                raise ValueError("receipt precedes confirmation")
            s.cash += receivable[1]
            s.received_at[event.at] = s.received_at.get(event.at, ZERO) + receivable[1]
            del s.receivables[event.receivable_id]
        elif isinstance(event, Reinvestment):
            receivable = s.receivables.get(event.receivable_id)
            if receivable is None or receivable[2] != "reinvest":
                raise ValueError("unknown or non-reinvestment receivable")
            instrument, cash, _, ex_at = receivable
            if event.price_determined_at < ex_at:
                raise ValueError("reinvestment price precedes ex-date")
            s.shares[instrument] = s.shares.get(instrument, ZERO) + cash / event.price
            del s.receivables[event.receivable_id]
        else:
            raise ValueError("unsupported event")
        s.event_ids.add(event.event_id)
        s.last_at = event.at
        self._state = s
        return self.state

    def replay(self, events: Iterable[Event]) -> tuple[State, ...]:
        """Preserve supplied order, fail closed; no silent sorting or skipped fills."""
        return tuple(self.apply(event) for event in events)
