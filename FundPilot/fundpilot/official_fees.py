"""Reviewed document imports, not a scraper or a source-authenticity attestation.

Reuse FeeSchedule for natural-day redemption bands and its NAV fee convention.
Only external transaction fees are calculated. Unknown discounts do not change
the official standard quote; unknown dates never become an assumed free exit.
"""
from datetime import date
from hashlib import sha256
import re

from .risk import FeeBand, FeeSchedule, decimal, nonnegative


def validate_redemption_dates(subscription_confirmation, *,
                              redemption_application=None, redemption_confirmation=None):
    """Check every known date, even when the selected holding basis is unknown.

    Missing values stay None. Calendar eligibility and actual execution still
    require product/channel evidence outside this arithmetic validation.
    """
    start = None if subscription_confirmation is None else date.fromisoformat(subscription_confirmation)
    application = None if redemption_application is None else date.fromisoformat(redemption_application)
    confirmation = None if redemption_confirmation is None else date.fromisoformat(redemption_confirmation)
    if application is not None and confirmation is not None and application > confirmation:
        raise ValueError('redemption application follows redemption confirmation')
    if start is not None and application is not None and application < start:
        raise ValueError('redemption application precedes subscription confirmation')
    if start is not None and confirmation is not None and confirmation < start:
        raise ValueError('redemption confirmation precedes subscription confirmation')
    return start, application, confirmation


class OfficialFees:
    def __init__(self, record, raw_document):
        self.record = record
        for key in ('fund_code', 'share_class', 'currency', 'version', 'source_url',
                    'published_on', 'reviewed_by', 'pages', 'applicability_note'):
            if not isinstance(record.get(key), str) or not record[key].strip():
                raise ValueError('reviewed fee field required: ' + key)
        if record.get('reviewed') is not True or not record['source_url'].startswith('https://'):
            raise ValueError('reviewed public official document required')
        if not re.fullmatch('[0-9a-f]{64}', record.get('raw_sha256', '')) or sha256(raw_document).hexdigest() != record['raw_sha256']:
            raise ValueError('original fee document hash mismatch')
        self.published = date.fromisoformat(record['published_on'])
        if record.get('holding_basis') is not None and (record['holding_basis'] not in
                ('confirmation_to_confirmation_exclusive_end', 'confirmation_to_application_exclusive_end')
                or not record.get('holding_basis_evidence')):
            raise ValueError('reviewed holding-day convention evidence required')
        self.start = self._date(record.get('effective_from'))
        self.end = self._date(record.get('effective_until'))
        if self.start and self.end and self.start > self.end:
            raise ValueError('invalid fee version interval')
        if record.get('nav_includes_recurring_fees') is not True:
            raise ValueError('published NAV must include recurring expenses')
        self.bands = record['subscription_bands']
        previous = decimal('0')
        for i, band in enumerate(self.bands):
            lower = nonnegative(band['min_amount'])
            upper = None if band['max_amount'] is None else nonnegative(band['max_amount'])
            if previous is None or lower != previous or (upper is not None and upper <= lower):
                raise ValueError('subscription bands must be contiguous and nonoverlapping')
            if ('rate' in band) == ('fixed_fee' in band):
                raise ValueError('exactly one proportional or fixed fee required')
            if 'rate' in band and not 0 <= decimal(band['rate']) < 1:
                raise ValueError('invalid subscription rate')
            if 'fixed_fee' in band: nonnegative(band['fixed_fee'])
            previous = upper
        if not self.bands or previous is not None:
            raise ValueError('complete amount coverage required')
        self.schedule = FeeSchedule(record['fund_code'], record['source_url'], record['published_on'],
                                    '0', tuple(FeeBand(**b) for b in record['redemption_bands']))

    @staticmethod
    def _date(value):
        return None if value is None else date.fromisoformat(value)

    def check(self, identity, trade_date, *, document_version_scenario=False):
        r = self.record
        if identity != {k:r[k] for k in ('fund_code', 'share_class', 'currency')}:
            raise ValueError('fee identity/share/currency mismatch')
        day = date.fromisoformat(trade_date)
        if day < self.published:
            raise ValueError('document published after trade date; historical version required')
        if (self.start and day < self.start) or (self.end and day > self.end):
            raise ValueError('fee version outside effective interval')
        confirmed = self.start is not None and self.end is not None
        if not confirmed and (not document_version_scenario or day < self.published):
            raise ValueError('unverified historical applicability; explicit document-version scenario required')
        return 'verified_interval_declaration' if confirmed else 'document_version_conditional_not_historical_verification'

    def subscription(self, gross, *, discount=None, discount_evidence=None):
        gross = nonnegative(gross)
        if gross == 0:
            return {'gross':'0', 'net':'0', 'fee':'0', 'discount_status':'not_applicable'}
        b = next(b for b in self.bands if gross >= decimal(b['min_amount']) and
                 (b['max_amount'] is None or gross < decimal(b['max_amount'])))
        factor = decimal('1')
        if discount is not None:
            factor = nonnegative(discount)
            if factor > 1 or not discount_evidence:
                raise ValueError('explicit sourced channel discount required')
            if 'fixed_fee' in b and factor != 1:
                raise ValueError('fixed fee discount is not inferred')
        fee = nonnegative(b['fixed_fee']) if 'fixed_fee' in b else gross - gross / (1 + decimal(b['rate']) * factor)
        if fee > gross: raise ValueError('fixed fee exceeds gross amount')
        return {'gross':str(gross), 'net':str(gross-fee), 'fee':str(fee), 'band':b,
                'discount_status':'official_standard_channel_discount_unknown' if discount is None else 'explicit_sourced_discount',
                'discount_evidence':discount_evidence}

    def redemption(self, lots, nav, *, redemption_application=None, redemption_confirmation=None):
        """Explicit lot portions, never average ages or silently choose FIFO lots.

        Holding basis is a reviewed product rule, not a universal convention.
        Missing basis/dates returns partial lot evidence and null total fee.
        """
        nav = nonnegative(nav); basis = self.record.get('holding_basis')
        # Validate both supplied dates, not only the one used to count days.
        validate_redemption_dates(None, redemption_application=redemption_application,
                                  redemption_confirmation=redemption_confirmation)
        rows = []
        for lot in lots:
            units = nonnegative(lot['units'])
            start, application, confirmation = validate_redemption_dates(
                lot.get('confirmed_on'), redemption_application=redemption_application,
                redemption_confirmation=redemption_confirmation)
            end = {'confirmation_to_confirmation_exclusive_end':confirmation,
                   'confirmation_to_application_exclusive_end':application}.get(basis)
            days = None if start is None or end is None else (end-start).days
            rate = None if days is None else self.schedule.redemption_rate(days)
            rows.append({'lot_id':lot['lot_id'], 'units':str(units), 'holding_days':days,
                         'rate':None if rate is None else str(rate),
                         'fee':None if rate is None else str(units*nav*rate)})
        if len({r['lot_id'] for r in rows}) != len(rows): raise ValueError('duplicate redemption lot')
        total = None if any(r['fee'] is None for r in rows) else str(sum(decimal(r['fee']) for r in rows))
        return {'lots':rows, 'fee':total, 'holding_basis':basis,
                'status':'pending_holding_basis_or_dates' if total is None else 'conditional_quote'}


def load_cost(cost):
    """Import an already reviewed embedded document, rechecking raw bytes.

    The local path is used only in the private input and never copied into code.
    Private path checks are shared with the existing bridge storage contract.
    """
    from .upstream_bridge import read_private
    return OfficialFees(cost['official_rule'], read_private(cost['raw_document_path']))
