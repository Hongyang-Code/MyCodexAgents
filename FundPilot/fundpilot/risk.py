"""Fail-closed advisory gate; never places orders. All examples must be synthetic.

RiskAdvisor.evaluate(context, proposal=None) returns action, amount (decimal string
or None), reasons, requested_fields, advisory_only. Context is explicitly supplied
private account evidence; no account defaults or recurring income are assumed.
Synthetic actionable shape (private real values must be supplied by caller)::

    context = dict(confirmed=True, horizon_months="24", max_loss_fraction="0.1",
      risk_preference="conservative", other_restrictions_confirmed=True,
      holdings=[dict(fund_id="SYNTHETIC", share_class="A", units="10",
        confirmed=True, as_of="2026-01-02")], as_of="2026-01-02",
      evaluation_date="2026-01-02", cash_confirmed=True, available_cash="20",
      trading_rules_confirmed=True, validation_passed=True)
    proposal = dict(action="buy", fund_id="SYNTHETIC", amount="5",
      estimated_fee="0.01", conservative_expected_benefit="0.02",
      fund_identity_confirmed=True, rules_current=True, validated=True,
      risk_within_limits=True, fees_confirmed=True, timing_confirmed=True,
      restrictions_satisfied=True, market_calendar_confirmed=True,
      evidence=["synthetic-test"], valid_until="2026-01-03",
      rules_effective_from="2026-01-01", rules_effective_until="2026-01-03",
      rules_source="synthetic-test", trading_timing="synthetic confirmed calendar",
      uncertainties=["future NAV unknown"])

These booleans are upstream verification attestations, not an implemented risk
model. Safe production caller must never set them merely to unlock advice.
Without such a verified proposal this gate returns hold. Sell additionally needs
sellable_value_confirmed=True and sellable_value; holdings units remain unchanged.
FeeSchedule is an observation, not a universal rule. Inclusive holding-day edges
are explicit; unknown/ambiguous edges raise rather than invent a fee.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


def decimal(value):
    if isinstance(value, (bool, float)):
        raise ValueError('use decimal strings, integers or Decimal')
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('invalid decimal') from None
    if not result.is_finite():
        raise ValueError('non-finite decimal')
    return result


def nonnegative(value):
    result = decimal(value)
    if result < 0:
        raise ValueError('negative value')
    return result


@dataclass(frozen=True)
class FeeBand:
    min_days: int
    max_days: int | None
    rate: str

    def __post_init__(self):
        if type(self.min_days) is not int or self.min_days < 0:
            raise ValueError('invalid lower holding-day edge')
        if self.max_days is not None and (type(self.max_days) is not int or self.max_days < self.min_days):
            raise ValueError('invalid upper holding-day edge')
        if not 0 <= decimal(self.rate) <= 1:
            raise ValueError('invalid fee rate')


@dataclass(frozen=True)
class FeeSchedule:
    fund_id: str
    source: str
    observed_on: str
    subscription_rate: str
    redemption_bands: tuple[FeeBand, ...]
    # This model consumes published NAV. Embedded expenses are not charged again.
    nav_includes_recurring_fees: bool = True
    effective_from: str | None = None
    effective_until: str | None = None

    def __post_init__(self):
        if not self.fund_id or not self.source or self.nav_includes_recurring_fees is not True:
            raise ValueError('verified identity/source and published NAV fee convention required')
        date.fromisoformat(self.observed_on)
        if self.effective_from is not None:
            date.fromisoformat(self.effective_from)
        if self.effective_until is not None:
            date.fromisoformat(self.effective_until)
        if self.effective_from and self.effective_until and self.effective_until < self.effective_from:
            raise ValueError('invalid effective interval')
        if not 0 <= decimal(self.subscription_rate) <= 1:
            raise ValueError('invalid subscription rate')
        previous = -1
        for band in sorted(self.redemption_bands, key=lambda b: b.min_days):
            if previous is None or band.min_days <= previous:
                raise ValueError('overlapping fee bands')
            previous = band.max_days

    def redemption_rate(self, held_days):
        if type(held_days) is not int or held_days < 0:
            raise ValueError('confirmed holding duration required')
        for band in self.redemption_bands:
            if held_days >= band.min_days and (band.max_days is None or held_days <= band.max_days):
                return decimal(band.rate)
        raise ValueError('holding period not covered by observed schedule')

    def estimate_cost(self, action, gross_amount, held_days=None, *, trade_date=None):
        """Buy: front-end external rate, gross/(1+rate). Sell: gross*rate.

        No fixed fees, conversion fees, discounts or unknown channels are assumed.
        Caller must confirm this fee convention applies to the particular fund.
        """
        if trade_date is not None:
            day = date.fromisoformat(trade_date)
            if self.effective_from is None or day < date.fromisoformat(self.effective_from):
                raise ValueError('fee not confirmed effective on trade date')
            if self.effective_until is None or day > date.fromisoformat(self.effective_until):
                raise ValueError('fee not confirmed effective on trade date')
        gross = nonnegative(gross_amount)
        if action == 'buy':
            rate = decimal(self.subscription_rate)
            return gross - gross / (1 + rate)
        if action == 'sell':
            return gross * self.redemption_rate(held_days)
        raise ValueError('unsupported action')


class RiskAdvisor:
    """Strict context contract, no implicit attestations from truthy strings.

    Required context: confirmed=True; horizon_months; max_loss_fraction;
    risk_preference; other_restrictions_confirmed=True; holdings (nonempty list
    of {fund_id, share_class, units, confirmed=True, as_of}); as_of; cash_confirmed;
    available_cash (already net of pending reservations); trading_rules_confirmed;
    validation_passed. No potential_extra_cash or pending proceeds are consumed.
    An actionable proposal additionally requires rule/validation attestations,
    fee and risk bounds, and is never auto-executed.
    """
    def evaluate(self, context, proposal=None):
        p = proposal or {}
        if p.get('action', 'hold') in ('hold', 'watch', 'retain_cash'):
            return self._result('hold', ['No actionable validated proposal.'])
        missing = []
        try:
            evaluated_on = date.fromisoformat(context.get('evaluation_date', date.today().isoformat()))
        except (TypeError, ValueError):
            return self._result('calibration', ['Invalid evaluation date.'], ['evaluation_date'])
        for key in ('confirmed', 'other_restrictions_confirmed', 'cash_confirmed',
                    'trading_rules_confirmed', 'validation_passed'):
            if context.get(key) is not True:
                missing.append(key)
        for key in ('horizon_months', 'max_loss_fraction'):
            try:
                n = decimal(context.get(key))
                if n <= 0 or (key == 'max_loss_fraction' and n > 1):
                    raise ValueError()
            except ValueError:
                missing.append(key)
        if not isinstance(context.get('risk_preference'), str) or not context['risk_preference'].strip():
            missing.append('risk_preference')
        try:
            if date.fromisoformat(context.get('as_of', '')) > evaluated_on:
                raise ValueError()
        except (TypeError, ValueError):
            missing.append('as_of')
        try:
            cash = nonnegative(context.get('available_cash'))
        except ValueError:
            cash = Decimal(0)
            missing.append('available_cash')
        holdings = context.get('holdings')
        if not isinstance(holdings, list) or not holdings:
            missing.append('holdings')
            holdings = []
        for i, holding in enumerate(holdings):
            try:
                if not isinstance(holding, dict) or holding.get('confirmed') is not True or not holding.get('fund_id') or not holding.get('share_class'):
                    raise ValueError()
                nonnegative(holding.get('units'))
                if date.fromisoformat(holding.get('as_of', '')) > evaluated_on:
                    raise ValueError()
            except (TypeError, ValueError):
                missing.append(f'holdings[{i}].identity_units_date')
        if context.get('data_stale') is True or context.get('data_conflict') is True:
            missing.append('current_reconciled_snapshot')
        if missing:
            return self._result('calibration', ['Consolidated account/risk calibration required; no amount inferred.'], missing)
        action = p.get('action')
        if action not in ('buy', 'sell'):
            return self._result('watch', ['Unsupported proposal; manual research required.'])
        required = ('fund_identity_confirmed', 'rules_current', 'validated', 'risk_within_limits',
                    'fees_confirmed', 'timing_confirmed', 'restrictions_satisfied',
                    'market_calendar_confirmed')
        missing = [f'proposal.{key}' for key in required if p.get(key) is not True]
        for key in ('fund_id', 'evidence', 'valid_until', 'trading_timing', 'uncertainties'):
            if not p.get(key):
                missing.append(f'proposal.{key}')
        try:
            if date.fromisoformat(p.get('valid_until', '')) < evaluated_on:
                raise ValueError()
            if date.fromisoformat(p.get('rules_effective_from', '')) > evaluated_on:
                raise ValueError()
            if date.fromisoformat(p.get('rules_effective_until', '')) < evaluated_on:
                raise ValueError()
            if not p.get('rules_source'):
                raise ValueError()
        except (TypeError, ValueError):
            missing.append('proposal.current_sourced_trading_rules_and_expiry')
        try:
            amount = nonnegative(p.get('amount'))
            cost = nonnegative(p.get('estimated_fee'))
            benefit = decimal(p.get('conservative_expected_benefit'))
            if amount <= 0 or cost > amount or benefit <= cost:
                raise ValueError()
        except ValueError:
            missing.append('proposal.positive_net_value_after_costs')
            amount = Decimal(0)
        if action == 'buy' and amount > cash:
            missing.append('confirmed_available_cash_sufficient')
        if action == 'sell':
            # Gross estimated proceeds never become cash here. Confirmed lot value
            # and duration are separate from unrealized gains or future NAV.
            if p.get('sellable_value_confirmed') is not True:
                missing.append('confirmed_sellable_value')
            try:
                if amount > nonnegative(p.get('sellable_value')):
                    raise ValueError()
                if not any(h.get('fund_id') == p.get('fund_id') for h in holdings):
                    raise ValueError()
            except ValueError:
                missing.append('sufficient_identified_sellable_holding')
        if missing:
            return self._result('calibration', ['Proposal blocked; consolidate missing evidence before advice.'], missing)
        result = self._result(action, ['Validated advisory proposal; user decides and executes manually.'])
        result.update(amount=str(amount), fund_id=p['fund_id'], estimated_fee=str(cost),
                      evidence=p['evidence'], valid_until=p['valid_until'],
                      trading_timing=p['trading_timing'], uncertainties=p['uncertainties'])
        return result

    @staticmethod
    def _result(action, reasons, requested_fields=None):
        return dict(action=action, amount=None, reasons=reasons,
                    requested_fields=sorted(set(requested_fields or [])), advisory_only=True,
                    auto_trade=False)
