"""Point-in-time research primitives. No trading, learned alpha, or LLM replay.

Dates in TradingCalendar must come from a verified instrument-specific calendar.
Values must be comparable total-return levels (not unadjusted dividend NAVs).
The caller persists frozen dataclasses in its append-only private ledger. Metrics
are forecast diagnostics, never executable fund returns or evidence of profit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from statistics import mean
from typing import Iterable, Literal

HORIZONS = (1, 5, 20)


def _time(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")


def _number(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("finite number required")


@dataclass(frozen=True)
class Observation:
    observation_id: str
    instrument: str
    session: date
    value: float
    published_at: datetime
    available_at: datetime
    source: str
    revision: int = 0
    basis: str = "total_return"

    def __post_init__(self) -> None:
        _time(self.published_at)
        _time(self.available_at)
        _number(self.value)
        if not self.observation_id or not self.instrument or not self.source:
            raise ValueError("identity and source required")
        if type(self.session) is not date or self.session > self.published_at.date():
            raise ValueError("invalid observation session")
        if self.available_at < self.published_at or self.value <= 0:
            raise ValueError("invalid availability or level")
        if type(self.revision) is not int or self.revision < 0 or self.basis != "total_return":
            raise ValueError("nonnegative revision and total_return basis required")


def as_of(observations: Iterable[Observation], cutoff: datetime) -> tuple[Observation, ...]:
    """Select the latest *available* vintage, never a future revision."""
    _time(cutoff)
    selected: dict[tuple[str, date], Observation] = {}
    ids: dict[str, Observation] = {}
    vintages: dict[tuple[str, date, int], Observation] = {}
    for obs in observations:
        if obs.observation_id in ids and ids[obs.observation_id] != obs:
            raise ValueError("conflicting observation ID")
        ids[obs.observation_id] = obs
        vintage = (obs.instrument, obs.session, obs.revision)
        if vintage in vintages and vintages[vintage] != obs:
            raise ValueError("conflicting observation vintage")
        vintages[vintage] = obs
        if max(obs.published_at, obs.available_at) > cutoff:
            continue
        key = (obs.instrument, obs.session)
        if key not in selected or obs.revision > selected[key].revision:
            selected[key] = obs
    return tuple(sorted(selected.values(), key=lambda o: (o.instrument, o.session)))


@dataclass(frozen=True)
class TradingCalendar:
    sessions: tuple[date, ...]
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sessions", tuple(self.sessions))
        if not self.source or not self.sessions or any(type(d) is not date for d in self.sessions):
            raise ValueError("dated calendar with source required")
        if tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("sessions must be unique and sorted")

    def advance(self, session: date, horizon: int) -> date:
        if type(horizon) is not int or horizon not in HORIZONS:
            raise ValueError("supported horizons: 1, 5, 20 trading sessions")
        index = self.sessions.index(session) + horizon
        if index >= len(self.sessions):
            raise ValueError("insufficient calendar coverage")
        return self.sessions[index]


@dataclass(frozen=True)
class FrozenForecast:
    forecast_id: str
    instrument: str
    created_at: datetime
    data_cutoff: datetime
    anchor_session: date
    anchor_value: float
    target_session: date
    horizon: int
    model: str
    model_version: str
    predicted_return: float | None
    probability_up: float | None
    evidence_ids: tuple[str, ...]
    calendar_source: str
    experience_ids: tuple[str, ...] = ()
    invalidation: str = "Missing/revised input, incompatible total-return basis, or calendar error requires review."
    estimated_verification_at: datetime | None = None

    def __post_init__(self) -> None:
        _time(self.created_at)
        _time(self.data_cutoff)
        _number(self.anchor_value)
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "experience_ids", tuple(self.experience_ids))
        if self.data_cutoff > self.created_at or self.anchor_session > self.data_cutoff.date():
            raise ValueError("future forecast input")
        if (type(self.anchor_session) is not date or type(self.target_session) is not date
                or self.anchor_value <= 0 or self.target_session <= self.anchor_session
                or type(self.horizon) is not int or self.horizon not in HORIZONS):
            raise ValueError("invalid forecast target")
        if not all((self.forecast_id, self.instrument, self.model, self.model_version, self.evidence_ids, self.calendar_source, self.invalidation)):
            raise ValueError("forecast audit fields required")
        if self.predicted_return is not None:
            _number(self.predicted_return)
            if self.predicted_return <= -1:
                raise ValueError("invalid predicted return")
        if self.probability_up is not None:
            _number(self.probability_up)
            if not 0 <= self.probability_up <= 1:
                raise ValueError("invalid probability")
        if self.estimated_verification_at is not None:
            _time(self.estimated_verification_at)
            if self.estimated_verification_at < self.created_at:
                raise ValueError("verification estimate precedes forecast")


class ForecastEngine:
    """Three fixed baselines; no fitting, tuning or calibrated probability claims."""

    def predict(self, forecast_id: str, instrument: str, observations: Iterable[Observation],
                calendar: TradingCalendar, cutoff: datetime, horizon: int,
                model: Literal["no_direction", "persistence", "trend"] = "no_direction") -> FrozenForecast:
        available = [o for o in as_of(observations, cutoff) if o.instrument == instrument]
        if not available:
            raise ValueError("insufficient observations")
        anchor = available[-1]
        target = calendar.advance(anchor.session, horizon)
        # A delayed NAV cannot be used to issue an already elapsed target forecast.
        if target <= cutoff.date():
            raise ValueError("target session already elapsed at issue time")
        predicted: float | None = None
        used = [anchor]
        if model == "persistence":
            predicted = 0.0  # persistence of the level, NOT last return extrapolation
        elif model == "trend":
            index = calendar.sessions.index(anchor.session)
            if index < 5:
                raise ValueError("trend requires five prior trading sessions")
            required = calendar.sessions[index - 5:index + 1]
            by_date = {o.session: o for o in available}
            if any(d not in by_date for d in required):
                raise ValueError("missing trading-session observation")
            used = [by_date[d] for d in required]
            predicted = (anchor.value / used[0].value) ** (horizon / 5) - 1
        elif model != "no_direction":
            raise ValueError("unknown baseline")
        return FrozenForecast(forecast_id, instrument, cutoff, cutoff, anchor.session,
                              anchor.value, target, horizon, model, "baseline-v1", predicted,
                              None, tuple(o.observation_id for o in used), calendar.source)

    def walk_forward(self, instrument: str, observations: Iterable[Observation], calendar: TradingCalendar,
                     cutoffs: Iterable[datetime], horizon: int, model: str = "no_direction") -> tuple[FrozenForecast, ...]:
        observations = tuple(observations)
        cutoffs = tuple(cutoffs)
        if tuple(sorted(set(cutoffs))) != cutoffs:
            raise ValueError("walk-forward cutoffs must be unique and increasing")
        # Fail closed on insufficiency; never silently drop failed dates and bias results.
        return tuple(self.predict(f"{instrument}:{model}:{horizon}:{t.isoformat()}", instrument,
                                  observations, calendar, t, horizon, model) for t in cutoffs)


@dataclass(frozen=True)
class Settlement:
    forecast_id: str
    settled_at: datetime
    outcome_observation_id: str
    actual_return: float
    predicted_return: float | None
    probability_up: float | None
    target_session: date

    def __post_init__(self) -> None:
        _time(self.settled_at)
        _number(self.actual_return)
        if self.actual_return <= -1 or not self.forecast_id or not self.outcome_observation_id:
            raise ValueError("invalid settlement")
        if self.predicted_return is not None:
            _number(self.predicted_return)
        if self.probability_up is not None:
            _number(self.probability_up)
            if not 0 <= self.probability_up <= 1:
                raise ValueError("invalid probability")


def settle_forecast(forecast: FrozenForecast, observations: Iterable[Observation], now: datetime,
                    existing: Iterable[Settlement] = ()) -> Settlement | None:
    """Idempotent: return original settlement; revisions require separate audit events.

    None means not due/available. Never substitute the next observed date for a
    missing target session. Frozen anchor is preserved across later revisions.
    """
    _time(now)
    prior = [s for s in existing if s.forecast_id == forecast.forecast_id]
    if len(prior) > 1:
        raise ValueError("duplicate settlement records")
    if prior:
        previous = prior[0]
        if (previous.target_session != forecast.target_session
                or previous.predicted_return != forecast.predicted_return
                or previous.probability_up != forecast.probability_up
                or previous.settled_at < forecast.created_at):
            raise ValueError("existing settlement conflicts with forecast")
        return previous
    if now < forecast.created_at:
        raise ValueError("settlement precedes forecast")
    candidates = [o for o in as_of(observations, now)
                  if o.instrument == forecast.instrument and o.session == forecast.target_session]
    if not candidates:
        return None
    outcome = candidates[0]
    return Settlement(forecast.forecast_id, now, outcome.observation_id,
                      outcome.value / forecast.anchor_value - 1, forecast.predicted_return,
                      forecast.probability_up, forecast.target_session)


def evaluate(settlements: Iterable[Settlement]) -> dict[str, float | int | None]:
    """MAE, three-way direction and Brier score; abstentions have no accuracy."""
    rows = tuple(settlements)
    if len({s.forecast_id for s in rows}) != len(rows):
        raise ValueError("duplicate settlements would bias metrics")
    numeric = [s for s in rows if s.predicted_return is not None]
    probabilistic = [s for s in rows if s.probability_up is not None]
    sign = lambda x: (x > 0) - (x < 0)
    return {"n": len(rows), "numeric_n": len(numeric), "probability_n": len(probabilistic),
            "mae": mean(abs(s.actual_return - s.predicted_return) for s in numeric) if numeric else None,
            "direction_accuracy": mean(sign(s.actual_return) == sign(s.predicted_return) for s in numeric) if numeric else None,
            "brier_score": mean((s.probability_up - int(s.actual_return > 0)) ** 2 for s in probabilistic) if probabilistic else None}


def maximum_drawdown(equity: Iterable[float]) -> float | None:
    """For supplied positive marked portfolio equity; does not simulate execution."""
    values = tuple(equity)
    if not values:
        return None
    peak, worst = 0.0, 0.0
    for value in values:
        _number(value)
        if value <= 0:
            raise ValueError("positive equity required")
        peak = max(peak, value)
        worst = max(worst, 1 - value / peak)
    return worst


@dataclass(frozen=True)
class LabelWindow:
    sample_id: str
    start: date
    end: date
    available_at: datetime

    def __post_init__(self) -> None:
        _time(self.available_at)
        if not self.sample_id or self.start >= self.end or self.end > self.available_at.date():
            raise ValueError("invalid label window")


def purged_split(windows: Iterable[LabelWindow], validation_at: datetime,
                 test_at: datetime) -> dict[str, tuple[LabelWindow, ...]]:
    """Chronological train/validation/test; purge boundary overlap and late labels.

    Test is an untouched holdout. This primitive does not authorize selecting
    models on test metrics or prove statistical independence of overlapping rows.
    """
    _time(validation_at)
    _time(test_at)
    if validation_at >= test_at:
        raise ValueError("validation must precede test")
    rows = tuple(windows)
    if len({r.sample_id for r in rows}) != len(rows):
        raise ValueError("duplicate samples")
    groups: dict[str, list[LabelWindow]] = {"train": [], "validation": [], "test": [], "purged": []}
    for row in sorted(rows, key=lambda r: (r.start, r.sample_id)):
        if row.start < validation_at.date():
            key = "train" if row.end < validation_at.date() and row.available_at < validation_at else "purged"
        elif row.start < test_at.date():
            key = "validation" if row.end < test_at.date() and row.available_at < test_at else "purged"
        else:
            key = "test"
        groups[key].append(row)
    return {key: tuple(value) for key, value in groups.items()}


EXPERIENCE_STATES = ("candidate", "validating", "provisional", "invalid", "disabled", "archive")


@dataclass(frozen=True)
class Experience:
    experience_id: str
    rule: str
    created_at: datetime
    state: str = "candidate"
    weight: float = 0.0
    review_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _time(self.created_at)
        _number(self.weight)
        object.__setattr__(self, "review_ids", tuple(self.review_ids))
        if not self.experience_id or not self.rule or self.state not in EXPERIENCE_STATES or not 0 <= self.weight <= 1:
            raise ValueError("invalid experience")
        if self.state != "provisional" and self.weight != 0:
            raise ValueError("unvalidated/disabled experience has zero decision weight")


@dataclass(frozen=True)
class ExperienceReview:
    review_id: str
    experience_id: str
    reviewed_at: datetime
    strategy_version: str
    evidence_ids: tuple[str, ...]
    previous_state: str
    next_state: str
    rationale: str

    def __post_init__(self) -> None:
        _time(self.reviewed_at)
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        if (not all((self.review_id, self.experience_id, self.strategy_version, self.evidence_ids, self.rationale))
                or self.previous_state not in EXPERIENCE_STATES or self.next_state not in EXPERIENCE_STATES):
            raise ValueError("invalid experience review")


class ExperienceManager:
    """Explicit review trace, no automatic promotion from win counts.

    This foundation deliberately cannot confer provisional validity: independent
    multi-regime OOS methodology review remains required before enabling weight.
    """
    def review(self, experience: Experience, review_id: str, now: datetime,
               strategy_version: str, evidence_ids: Iterable[str], rationale: str,
               next_state: str = "validating") -> tuple[Experience, ExperienceReview]:
        _time(now)
        evidence = tuple(evidence_ids)
        if (now < experience.created_at or not review_id or review_id in experience.review_ids
                or not strategy_version or not evidence or not rationale):
            raise ValueError("new traceable review with evidence required")
        if next_state not in EXPERIENCE_STATES or next_state == "provisional":
            raise ValueError("provisional promotion requires independent validation not implemented here")
        if experience.state == "archive" and next_state != "archive":
            raise ValueError("archived experience cannot be silently reactivated")
        updated = Experience(experience.experience_id, experience.rule, experience.created_at,
                             next_state, 0.0, experience.review_ids + (review_id,))
        review = ExperienceReview(review_id, experience.experience_id, now, strategy_version,
                                  evidence, experience.state, next_state, rationale)
        return updated, review

    @staticmethod
    def monthly_review_due(experience: Experience, reviews: Iterable[ExperienceReview], now: datetime) -> bool:
        _time(now)
        if now < experience.created_at:
            raise ValueError("review time precedes experience")
        if experience.state == "archive":
            return False
        relevant = [r for r in reviews if r.experience_id == experience.experience_id and r.review_id in experience.review_ids]
        if any(r.reviewed_at > now for r in relevant):
            raise ValueError("future review")
        return not any((r.reviewed_at.year, r.reviewed_at.month) == (now.year, now.month) for r in relevant)


def calibration_bins(settlements: Iterable[Settlement], bins: int = 5) -> tuple[dict, ...]:
    """Descriptive reliability table; small bin counts confer no calibration claim."""
    if type(bins) is not int or not 1 <= bins <= 100:
        raise ValueError("bins must be between 1 and 100")
    rows = tuple(settlements)
    evaluate(rows)  # reject duplicates before binning
    groups: list[list[Settlement]] = [[] for _ in range(bins)]
    for row in rows:
        if row.probability_up is not None:
            groups[min(int(row.probability_up * bins), bins - 1)].append(row)
    return tuple({"lower": i / bins, "upper": (i + 1) / bins, "n": len(group),
                  "mean_probability": mean(r.probability_up for r in group) if group else None,
                  "observed_up_rate": mean(r.actual_return > 0 for r in group) if group else None}
                 for i, group in enumerate(groups))


def compare_holdout(candidate_forecasts: Iterable[FrozenForecast], candidate_results: Iterable[Settlement],
                    baseline_forecasts: Iterable[FrozenForecast], baseline_results: Iterable[Settlement],
                    test_at: datetime) -> dict:
    """Require identical OOS targets, anchors and outcome vintages for paired MAE.

    Caller must freeze test_at and model selection *before* test observations.
    This API can check timestamps/pairing, not prove unseen-human-data discipline.
    Overlapping labels remain correlated; no significance or alpha claim follows.
    """
    _time(test_at)

    def paired(forecasts, results):
        forecasts, results = tuple(forecasts), tuple(results)
        by_id = {f.forecast_id: f for f in forecasts}
        if len(by_id) != len(forecasts) or len({r.forecast_id for r in results}) != len(results):
            raise ValueError("duplicate forecasts or results")
        if set(by_id) != {r.forecast_id for r in results}:
            raise ValueError("every holdout forecast needs exactly one result")
        pairs = {}
        for result in results:
            f = by_id[result.forecast_id]
            if f.created_at < test_at or f.data_cutoff < test_at:
                raise ValueError("non-holdout forecast")
            if (result.target_session != f.target_session or result.settled_at < f.created_at
                    or result.predicted_return != f.predicted_return or result.probability_up != f.probability_up):
                raise ValueError("settlement does not match frozen forecast")
            key = (f.instrument, f.anchor_session, f.target_session, f.horizon, f.data_cutoff)
            if key in pairs:
                raise ValueError("duplicate evaluation target")
            pairs[key] = (f, result)
        return pairs

    candidates = paired(candidate_forecasts, candidate_results)
    baselines = paired(baseline_forecasts, baseline_results)
    if candidates.keys() != baselines.keys():
        raise ValueError("unmatched holdout targets")
    for key, (f, result) in candidates.items():
        b, reference = baselines[key]
        if (f.anchor_value != b.anchor_value or result.actual_return != reference.actual_return
                or result.outcome_observation_id != reference.outcome_observation_id):
            raise ValueError("different anchors or outcome vintages")
    candidate_metrics = evaluate(r for _, r in candidates.values())
    baseline_metrics = evaluate(r for _, r in baselines.values())
    c, b = candidate_metrics["mae"], baseline_metrics["mae"]
    return {"candidate": candidate_metrics, "baseline": baseline_metrics,
            "mae_improvement": b - c if b is not None and c is not None else None,
            "evidence_scope": "paired holdout diagnostics; no profitability or significance claim"}
