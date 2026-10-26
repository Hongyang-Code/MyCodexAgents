"""Evidence-backed closed-pool bookkeeping; no broker connection or OCR.

All monetary/quantity inputs are Decimal, int or decimal strings, never float.
Trading methods record user-reported facts, not instructions to place orders.
Risk suitability, platform rules and screenshot transcription require separate
verified inputs before any personalized recommendation is permitted.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
import re
from .ledger import ConflictError, canonical, timestamp


def number(value, *, positive=False):
    """Finite, nonnegative bounded Decimal; avoid float and context overflow."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("use a decimal string, Decimal or integer")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError("invalid number") from None
    if not result.is_finite() or result < 0 or result > Decimal("1e15") or (positive and result == 0):
        raise ValueError("number out of range")
    if result.as_tuple().exponent < -10:
        raise ValueError("at most ten decimal places")
    return result


def code(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{6}", value, flags=re.ASCII):
        raise ValueError("full six-digit fund code required")
    return value


def evidence(value):
    """Require explicit provenance and field confidence; no claim of OCR accuracy."""
    if not isinstance(value, dict) or not isinstance(value.get("source"), str) or not value["source"].strip():
        raise ValueError("evidence source required")
    confidence = value.get("confidence")
    if not isinstance(confidence, dict) or not confidence:
        raise ValueError("field confidence mapping required")
    for key, item in confidence.items():
        if not isinstance(key, str) or number(item) > 1:
            raise ValueError("confidence must lie in [0,1]")
    return {"source": value["source"], "confidence": {k: str(number(v)) for k, v in confidence.items()}}


class PortfolioManager:
    """Project confirmed holdings, reserved cash and receivables from Ledger.

    state() returns Decimal values; persisted event payloads use strings.
    A snapshot accepts {as_of, positions:[{code,units,...}], cash?: decimal}.
    Missing cash means UNKNOWN, not zero. It is a full confirmed-position
    replacement; omitted funds leave the current projection but never history.
    Pending trades block snapshot reconciliation until resolved explicitly.
    Extra supplied position fields are retained as evidence, never inferred.
    """
    def __init__(self, ledger):
        self.ledger = ledger

    def state(self):
        state = {"version": 0, "cash": None, "positions": {}, "pending": {}, "receivables": {}, "snapshot_as_of": None, "latest_asset_at": None}
        for event in self.ledger.events():
            state["version"] = event["version"]
            p, kind = event["payload"], event["kind"]
            if kind.startswith("portfolio."):
                state["latest_asset_at"] = event["occurred_at"]
            if kind == "portfolio.snapshot":
                state["cash"] = None if p["snapshot"].get("cash") is None else Decimal(p["snapshot"]["cash"])
                state["positions"] = {x["code"]: Decimal(x["units"]) for x in p["snapshot"]["positions"]}
                state["snapshot_as_of"] = p["snapshot"]["as_of"]
            elif kind == "portfolio.submitted":
                state["pending"][p["trade_id"]] = p
                if p["side"] == "buy":
                    state["cash"] -= Decimal(p["amount"])
            elif kind == "portfolio.canceled":
                trade = state["pending"].pop(p["trade_id"])
                if trade["side"] == "buy" and state["cash"] is not None:
                    state["cash"] += Decimal(trade["amount"])
            elif kind == "portfolio.confirmed":
                trade = state["pending"].pop(p["trade_id"])
                fund = trade["code"]
                if trade["side"] == "buy":
                    state["positions"][fund] = state["positions"].get(fund, Decimal(0)) + Decimal(p["units"])
                else:
                    state["positions"][fund] -= Decimal(p["units"])
                    state["receivables"][p["trade_id"]] = Decimal(p["net_cash"])
            elif kind == "portfolio.settled":
                amount = state["receivables"].pop(p["trade_id"])
                if state["cash"] is not None:
                    state["cash"] += amount
            elif kind == "portfolio.dividend":
                if p["mode"] == "reinvest":
                    state["positions"][p["code"]] += Decimal(p["units"])
                elif state["cash"] is not None:
                    state["cash"] += Decimal(p["amount"])
        return state

    def _record(self, event_id, kind, payload, validate, expected_version=None, occurred_at=None):
        old = self.ledger.get(event_id)
        if old:
            return self.ledger.append(event_id, kind, payload, occurred_at=occurred_at)
        state = self.state()
        if expected_version is not None and state["version"] != expected_version:
            raise ConflictError("stale portfolio version")
        at = timestamp(occurred_at)
        if state["latest_asset_at"] and datetime.fromisoformat(at) < datetime.fromisoformat(state["latest_asset_at"]):
            raise ValueError("asset event predates latest recorded asset event")
        validate(state)
        return self.ledger.append(event_id, kind, payload, expected_version=state["version"], occurred_at=at)

    def import_snapshot(self, snapshot_id, snapshot, evidence, *, expected_version=None, reconcile=False):
        """Import explicitly transcribed fields; reject unresolved trade reconciliation.

        evidence.confidence must cover as_of, positions and cash when supplied.
        as_of must not predate any asset event. Subsequent changed balances need
        reconcile=True after reviewing the rejection's before/after diff; the
        accepted event retains that diff and confirmation. For historical trade
        imports supply occurred_at explicitly and replay in chronological order.
        Low-confidence fields (<1) are retained but must be user-confirmed before
        they can alter holdings (this foundation requires confidence exactly 1).
        """
        if type(reconcile) is not bool:
            raise ValueError("reconcile must be an explicit boolean")
        proof = globals()["evidence"](evidence)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("positions"), list):
            raise ValueError("structured snapshot positions required")
        fields = {"as_of", "positions"} | ({"cash"} if snapshot.get("cash") is not None else set())
        if any(f not in proof["confidence"] or Decimal(proof["confidence"][f]) != 1 for f in fields):
            raise ValueError("confirm as_of, positions and supplied cash before importing")
        normalized = dict(snapshot)
        normalized["as_of"] = timestamp(snapshot["as_of"])
        normalized["cash"] = None if snapshot.get("cash") is None else str(number(snapshot["cash"]))
        positions, seen = [], set()
        for position in snapshot["positions"]:
            item = dict(position)
            item["code"] = code(item["code"])
            if item["code"] in seen:
                raise ValueError("duplicate fund code")
            seen.add(item["code"])
            item["units"] = str(number(item["units"]))
            for field in ("market_value", "cost"):
                if field in item:
                    item[field] = str(number(item[field]))
            positions.append(item)
        normalized["positions"] = positions
        payload = {"snapshot": normalized, "evidence": proof, "reconcile_confirmed": reconcile}
        canonical(payload)
        previous = self.ledger.get(snapshot_id)
        if previous:
            original = dict(previous["payload"])
            original.pop("reconciliation", None)
            if previous["kind"] != "portfolio.snapshot" or original != payload:
                raise ConflictError("snapshot ID reused with different content")
            return previous
        def validate(s):
            if s["pending"] or s["receivables"]:
                raise ValueError("unresolved trades: reconcile explicitly before importing")
            if s["snapshot_as_of"] and datetime.fromisoformat(normalized["as_of"]) < datetime.fromisoformat(s["snapshot_as_of"]):
                raise ValueError("snapshot older than current calibration")
            before = {"cash": None if s["cash"] is None else str(s["cash"]),
                      "positions": {k: str(v) for k, v in s["positions"].items()}}
            after = {"cash": normalized["cash"], "positions": {x["code"]: x["units"] for x in positions}}
            changed = s["cash"] != (None if normalized["cash"] is None else Decimal(normalized["cash"])) or s["positions"] != {x["code"]: Decimal(x["units"]) for x in positions}
            if s["snapshot_as_of"] and changed and not reconcile:
                raise ValueError("snapshot differs from ledger; review before/after and explicitly set reconcile=True: " + canonical({"before": before, "after": after}))
            payload["reconciliation"] = {"before": before, "after": after, "changed": changed, "previous_version": s["version"]}
        return self._record(snapshot_id, "portfolio.snapshot", payload, validate, expected_version, normalized["as_of"])

    def submit_trade(self, trade_id, side, fund_code, *, amount=None, units=None, evidence, occurred_at=None):
        """Record an application. Buy amount includes ALL fees and reserves cash.

        Sell reserves units (no cash credited). No confirmed units change yet.
        """
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        p = {"trade_id": trade_id, "side": side, "code": code(fund_code), "evidence": globals()["evidence"](evidence)}
        field = "amount" if side == "buy" else "units"
        p[field] = str(number(amount if side == "buy" else units, positive=True))
        def validate(s):
            if side == "buy":
                if s["cash"] is None or s["cash"] < Decimal(p["amount"]):
                    raise ValueError("known sufficient cash required")
            else:
                reserved = sum((Decimal(t["units"]) for t in s["pending"].values() if t["side"] == "sell" and t["code"] == fund_code), Decimal(0))
                if s["positions"].get(fund_code, Decimal(0)) - reserved < Decimal(p["units"]):
                    raise ValueError("insufficient unreserved confirmed units")
        return self._record("submit:" + trade_id, "portfolio.submitted", p, validate, occurred_at=occurred_at)

    def cancel_trade(self, trade_id, *, evidence, reason, outcome="canceled",
                     occurred_at=None, expected_version=None):
        """Record verified cancellation/rejection of an UNCONFIRMED application.

        A cancellation request alone is insufficient evidence. Caller must supply
        the platform's confirmed terminal result. This releases the entire gross
        buy reservation or sell-unit reservation; partial refund/fees/partial
        fills are unsupported and require explicit reconciliation. No real order
        is canceled by this method. Identical retries do not release funds twice.
        """
        if outcome not in ("canceled", "rejected"):
            raise ValueError("verified canceled or rejected outcome required")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("cancellation/rejection reason required")
        p = {"trade_id": trade_id, "outcome": outcome, "reason": reason,
             "evidence": globals()["evidence"](evidence)}
        def validate(s):
            if trade_id not in s["pending"]:
                raise ValueError("only pending unconfirmed trades can be canceled/rejected")
        return self._record("cancel:" + trade_id, "portfolio.canceled", p, validate,
                            expected_version=expected_version, occurred_at=occurred_at)

    def confirm_trade(self, trade_id, *, units, fee="0", net_cash=None, evidence, occurred_at=None):
        """Record externally confirmed units and explicit fee, never deduct fee twice.

        Buys consume the already reserved gross amount; fee is informational.
        Sells require net_cash AFTER all explicit redemption fees; money remains
        a receivable until settle_redemption. Partial fills need reconciliation.
        """
        p = {"trade_id": trade_id, "units": str(number(units, positive=True)), "fee": str(number(fee)), "net_cash": None if net_cash is None else str(number(net_cash)), "evidence": globals()["evidence"](evidence)}
        def validate(s):
            t = s["pending"].get(trade_id)
            if not t:
                raise ValueError("pending trade required")
            if t["side"] == "sell":
                if Decimal(p["units"]) != Decimal(t["units"]) or p["net_cash"] is None:
                    raise ValueError("full confirmed units and net proceeds required")
            elif net_cash is not None or Decimal(p["fee"]) > Decimal(t["amount"]):
                raise ValueError("invalid buy confirmation")
        return self._record("confirm:" + trade_id, "portfolio.confirmed", p, validate, occurred_at=occurred_at)

    def settle_redemption(self, trade_id, *, evidence, occurred_at=None):
        """Record verified actual availability; unknown total cash stays unknown."""
        p = {"trade_id": trade_id, "evidence": globals()["evidence"](evidence)}
        def validate(s):
            if trade_id not in s["receivables"]:
                raise ValueError("confirmed redemption receivable required")
        return self._record("settle:" + trade_id, "portfolio.settled", p, validate, occurred_at=occurred_at)

    def record_dividend(self, event_id, fund_code, mode, *, amount=None, units=None, evidence, occurred_at=None):
        """Record paid cash or confirmed reinvested units, with no NAV fee deduction."""
        if mode not in ("cash", "reinvest"):
            raise ValueError("invalid dividend mode")
        p = {"code": code(fund_code), "mode": mode, "evidence": globals()["evidence"](evidence)}
        field = "amount" if mode == "cash" else "units"
        p[field] = str(number(amount if mode == "cash" else units, positive=True))
        def validate(s):
            if fund_code not in s["positions"]:
                raise ValueError("confirmed holding required")
        return self._record(event_id, "portfolio.dividend", p, validate, occurred_at=occurred_at)

    def estimate(self, navs, *, estimated_at):
        """navs={code:{nav,nav_date}}. Return dated MODEL estimates, not balances.

        Missing/stale NAVs remain explicit; caller must enforce freshness policy.
        No fees already included in unit NAV are subtracted here.
        """
        at = timestamp(estimated_at)
        s = self.state()
        values, missing = {}, []
        for fund, units in s["positions"].items():
            if fund not in navs:
                missing.append(fund)
                continue
            item = navs[fund]
            day = date.fromisoformat(item["nav_date"])
            if day > date.fromisoformat(at[:10]):
                raise ValueError("future NAV")
            with localcontext() as context:
                context.prec = 60
                values[fund] = {"value": units * number(item["nav"], positive=True), "nav_date": day.isoformat()}
        return {"kind": "model_estimate_not_account_balance", "estimated_at": at, "values": values, "missing_navs": missing, "cash": s["cash"]}

    @staticmethod
    def recommendation_gates():
        return ["confirmed screenshot transcription", "investment horizon and loss tolerance", "verified fund/platform trading rules and fees", "validated out-of-sample evidence"]
