"""Explicit current-vintage research view, never a production availability claim.

No conversion to market.NavRecord or research.Observation is provided. Raw NAV
diagnostics are not total returns. Calendars must be supplied and checked by the
caller; missing observations remain missing rather than compressing horizons.
"""
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Literal


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')


@dataclass(frozen=True)
class RetrospectivePoint:
    instrument: str
    session: date
    value: float
    retrieved_at: datetime
    known_available_at: datetime
    assumed_available_at: datetime
    source_url: str
    raw_sha256: str
    assumption: str
    basis: Literal['raw_nav', 'total_return'] = 'raw_nav'
    distribution_evidence: str | None = None
    retrospective: bool = True

    def __post_init__(self):
        for value in (self.retrieved_at, self.known_available_at, self.assumed_available_at):
            aware(value)
        if self.retrospective is not True or self.known_available_at != self.retrieved_at:
            raise ValueError('current-vintage knowledge time must equal actual retrieval')
        if type(self.session) is not date or self.session > self.retrieved_at.date():
            raise ValueError('invalid observation date')
        if self.assumed_available_at.date() <= self.session:
            raise ValueError('retrospective availability requires a later session')
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not isfinite(self.value) or self.value <= 0:
            raise ValueError('finite positive value required')
        if not self.instrument or not self.assumption or not self.source_url.startswith('https://'):
            raise ValueError('identity, source and explicit assumption required')
        if len(self.raw_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.raw_sha256):
            raise ValueError('raw evidence hash required')
        if self.basis not in ('raw_nav', 'total_return'):
            raise ValueError('unknown measurement basis')
        if self.basis == 'total_return' and not self.distribution_evidence:
            raise ValueError('total return requires reviewed distribution/adjustment evidence')


def assumed_view(points, decision_at):
    """Select on an explicit assumption, while retaining real acquisition dates."""
    aware(decision_at)
    seen = set()
    result = []
    for point in points:
        if not isinstance(point, RetrospectivePoint):
            raise TypeError('retrospective points required')
        key = (point.instrument, point.session)
        if key in seen:
            raise ValueError('duplicate current-vintage observation')
        seen.add(key)
        if point.assumed_available_at <= decision_at:
            result.append(point)
    return tuple(sorted(result, key=lambda p: (p.instrument, p.session)))


def predict(points, sessions, decision_at, horizon, model):
    """Fixed level forecasts; target is h calendar sessions after decision date.

    Trend uses exactly 20 observed calendar intervals, extrapolated from the
    latest assumed-visible observation to target (including availability lag).
    Returns None for missing history; never fills calendar gaps.
    """
    if type(horizon) is not int or horizon not in (1, 5, 20) or model not in ('abstain', 'persistence', 'trend20'):
        raise ValueError('unregistered model or horizon')
    points = tuple(points)
    sessions = tuple(sessions)
    if not sessions or any(type(s) is not date for s in sessions) or tuple(sorted(set(sessions))) != sessions:
        raise ValueError('unique sorted calendar required')
    visible = assumed_view(points, decision_at)
    if len({p.instrument for p in points}) != 1 or len({p.basis for p in points}) != 1:
        raise ValueError('one instrument and measurement basis required')
    i = sessions.index(decision_at.date())
    if i + horizon >= len(sessions):
        return None
    target = sessions[i + horizon]
    if model == 'abstain' or not visible:
        return dict(target=target, prediction=None, retrospective=True, basis=points[0].basis)
    last = visible[-1]
    j = sessions.index(last.session)
    value = last.value
    if model == 'trend20':
        by_date = {p.session: p for p in visible}
        if j < 20 or any(s not in by_date for s in sessions[j-20:j+1]):
            return None
        value *= (last.value / by_date[sessions[j-20]].value) ** ((i + horizon - j) / 20)
    if not isfinite(value):
        raise ValueError('nonfinite forecast')
    return dict(target=target, prediction=value, retrospective=True, basis=last.basis,
                last_observation=last.session, assumed_available_at=last.assumed_available_at,
                known_available_at=last.known_available_at, retrieved_at=last.retrieved_at)
