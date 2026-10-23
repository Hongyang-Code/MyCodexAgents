"""Reviewed, point-in-time-safe public NAV ingestion (standard library only).

No execution of remote scripts, account access, inferred publication vintage or
implicit zero distributions. Raw evidence belongs outside the public repository.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

MAX_IMPORT_BYTES = 8 * 1024 * 1024


def timestamp(value: str | datetime) -> datetime:
    if not isinstance(value, (str, datetime)):
        raise ValueError('timestamp must be ISO-8601 with timezone')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError('invalid timestamp') from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('timezone required')
    return result.astimezone(timezone.utc)


def number(value, *, positive=True) -> Decimal:
    if isinstance(value, bool):
        raise ValueError('boolean is not a number')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('invalid decimal') from exc
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise ValueError('finite positive value required' if positive else 'finite nonnegative value required')
    return result


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} is required')
    return value.strip()


@dataclass(frozen=True)
class NavRecord:
    fund_code: str
    share_class: str
    nav_date: date
    unit_nav: Decimal
    source_url: str
    source_version: str
    raw_sha256: str
    retrieved_at: datetime
    available_at: datetime
    published_at: datetime | None = None
    cumulative_nav: Decimal | None = None
    distribution_per_unit: Decimal | None = None
    distribution_status: str = 'unknown'
    currency: str = 'CNY'
    reviewed_by: str = ''
    reviewed_at: datetime | None = None

    def __post_init__(self):
        # Direct construction must enforce the same contract as imported rows.
        if not isinstance(self.fund_code, str) or not re.fullmatch(r'[0-9]{6}', self.fund_code):
            raise ValueError('fund_code must retain six digits')
        for key in ('share_class', 'source_version', 'reviewed_by', 'currency'):
            object.__setattr__(self, key, _text(getattr(self, key), key))
        u = urlsplit(self.source_url)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment:
            raise ValueError('source_url requires public HTTPS provenance')
        if not isinstance(self.raw_sha256, str) or not re.fullmatch('[0-9a-f]{64}', self.raw_sha256):
            raise ValueError('raw_sha256 must be lowercase SHA-256')
        if isinstance(self.nav_date, str):
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', self.nav_date):
                raise ValueError('nav_date must be YYYY-MM-DD')
            object.__setattr__(self, 'nav_date', date.fromisoformat(self.nav_date))
        if type(self.nav_date) is not date:
            raise ValueError('nav_date must be a date')
        for key in ('retrieved_at', 'available_at', 'reviewed_at'):
            object.__setattr__(self, key, timestamp(getattr(self, key)))
        if self.published_at is not None:
            object.__setattr__(self, 'published_at', timestamp(self.published_at))
        if self.available_at < self.retrieved_at:
            raise ValueError('historical availability cannot precede observed retrieval')
        if self.reviewed_at < self.retrieved_at:
            raise ValueError('review must follow retrieval')
        if self.published_at and self.published_at > self.retrieved_at:
            raise ValueError('publication cannot follow retrieval')
        if self.nav_date > self.retrieved_at.astimezone(timezone.utc).date():
            # Compare with China date below to permit evening UTC rollover.
            from datetime import timedelta
            if self.nav_date > self.retrieved_at.astimezone(timezone(timedelta(hours=8))).date():
                raise ValueError('future NAV date')
        object.__setattr__(self, 'unit_nav', number(self.unit_nav))
        if self.cumulative_nav is not None:
            object.__setattr__(self, 'cumulative_nav', number(self.cumulative_nav))
        if self.distribution_status not in ('unknown', 'verified_none', 'verified_cash'):
            raise ValueError('invalid distribution_status')
        if self.distribution_per_unit is not None:
            object.__setattr__(self, 'distribution_per_unit', number(self.distribution_per_unit, positive=False))
        if self.distribution_status == 'unknown' and self.distribution_per_unit is not None:
            raise ValueError('unknown distribution must not invent a value')
        if self.distribution_status == 'verified_none' and self.distribution_per_unit != Decimal(0):
            raise ValueError('verified_none requires explicit zero')
        if self.distribution_status == 'verified_cash' and (self.distribution_per_unit is None or self.distribution_per_unit <= 0):
            raise ValueError('verified_cash requires positive distribution')

    @classmethod
    def from_dict(cls, row):
        if not isinstance(row, dict):
            raise ValueError('NAV row must be an object')
        clean = dict(row)
        for key in ('published_at', 'cumulative_nav', 'distribution_per_unit'):
            if clean.get(key) == '':
                clean[key] = None
        try:
            return cls(**clean)
        except TypeError as exc:
            raise ValueError('missing or unknown NAV fields') from exc

    def to_dict(self):
        return {k: v.isoformat() if isinstance(v, (date, datetime)) else str(v) if isinstance(v, Decimal) else v
                for k, v in asdict(self).items()}


def import_reviewed(path, *, reviewer, reviewed_at):
    """Import explicitly reviewed JSON array or CSV; never infer raw evidence hashes.

    Caller must check source identity, exact raw SHA, fund class and distribution
    evidence before approval. This validates structure, not external truth.
    """
    reviewer = _text(reviewer, 'reviewer')
    reviewed_at = timestamp(reviewed_at)
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError('import exceeds size limit')
    text = raw.decode('utf-8-sig')
    if path.suffix.lower() == '.json':
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError('JSON import must be an array')
    elif path.suffix.lower() == '.csv':
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('missing or duplicate CSV headers')
        rows = list(reader)
    else:
        raise ValueError('only reviewed JSON or CSV is supported')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('row must be object')
        record = NavRecord.from_dict(dict(row, reviewed_by=reviewer, reviewed_at=reviewed_at))
        key = (record.fund_code, record.share_class, record.nav_date, record.source_version)
        if key in seen:
            raise ValueError('duplicate fund/class/date/version; review revisions explicitly')
        seen.add(key)
        result.append(record)
    return sorted(result, key=lambda x: (x.fund_code, x.share_class, x.nav_date, x.available_at))


def available_as_of(records, cutoff):
    """Strict operational cutoff: import approval must also have occurred."""
    cutoff = timestamp(cutoff)
    return [r for r in records if max(r.available_at, r.retrieved_at, r.reviewed_at) <= cutoff]


def latest_known(records, cutoff):
    """One latest observation per (fund_code, share_class); no calendar fill."""
    result = {}
    for record in available_as_of(records, cutoff):
        key = (record.fund_code, record.share_class)
        previous = result.get(key)
        if previous is None or (record.nav_date, record.available_at) > (previous.nav_date, previous.available_at):
            result[key] = record
        elif (record.nav_date, record.available_at) == (previous.nav_date, previous.available_at) and record != previous:
            raise ValueError('conflicting same-time observations require review')
    return result


def verify_raw_evidence(record, raw):
    """Explicit local byte check; no arbitrary URL fetching or filesystem traversal."""
    if hashlib.sha256(raw).hexdigest() != record.raw_sha256:
        raise ValueError('raw evidence SHA-256 mismatch')
    return True
