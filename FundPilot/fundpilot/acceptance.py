"""Frozen historical acceptance gates; never authorizes real investment guidance.

Exact binomial bounds require independently qualified Bernoulli episodes. Input
review flags are external attestations, not evidence verified by this module.
Retrospective optimization and LLM historical-memory uncertainty remain pending.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path

CONFIDENCE = 0.95
NONLOSS_TARGET = 0.95
REAL_TARGET = 0.90
DRAWDOWN_LIMIT = Decimal("0.05")
REQUIRED_REVIEWS = (
    "frozen_protocol", "all_registered_episodes", "independent_sampling",
    "untouched_validation", "model_memory_boundary", "point_in_time_inputs",
    "fund_and_channel_rules", "costs_and_distributions", "unitized_external_flows", "cpi_precision",
)


def number(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric observation")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("finite numeric observation required") from exc
    if not result.is_finite():
        raise ValueError("finite numeric observation required")
    return result


def exact_lower(successes, trials):
    """One-sided 95% Clopper-Pearson lower bound, assuming independent trials."""
    if (type(successes) is not int or type(trials) is not int
            or not 0 <= successes <= trials <= 10000 or trials == 0):
        raise ValueError("integer counts with 0 <= successes <= trials <= 10000 required")
    if successes == 0:
        return 0.0
    alpha = 1 - CONFIDENCE
    if successes == trials:
        return alpha ** (1 / trials)

    def upper_tail(p):
        logs = [
            math.lgamma(trials + 1) - math.lgamma(j + 1) - math.lgamma(trials - j + 1)
            + j * math.log(p) + (trials - j) * math.log1p(-p)
            for j in range(successes, trials + 1)
        ]
        largest = max(logs)
        return math.exp(largest) * math.fsum(math.exp(x - largest) for x in logs)

    lower, upper = 0.0, successes / trials
    for _ in range(80):
        mid = (lower + upper) / 2
        if upper_tail(mid) < alpha:
            lower = mid
        else:
            upper = mid
    return lower


def _next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def cpi_growth(changes, start, end):
    """Compound 12 consecutive official month-on-month fractions, never YoY."""
    if type(changes) is not list or len(changes) != 12:
        raise ValueError("twelve CPI monthly observations required")
    year, month = start.year, start.month
    factor = Decimal(1)
    for row in changes:
        year, month = _next_month(year, month)
        if row.get("month") != f"{year:04d}-{month:02d}" or row.get("basis") != "month_on_month_fraction":
            raise ValueError("CPI gaps, mismatched periods or wrong basis")
        change = number(row["change"])
        if change <= -1:
            raise ValueError("CPI gross factor must be positive")
        factor *= 1 + change
    if (year, month) != (end.year, end.month):
        raise ValueError("CPI end month mismatch")
    return factor - 1


def _period(row):
    start, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
    if (end.year != start.year + 1 or end.month != start.month
            or start.day != calendar.monthrange(start.year, start.month)[1]
            or end.day != calendar.monthrange(end.year, end.month)[1]):
        raise ValueError("v1 supports month-end to month-end twelve-month episodes only")
    return start, end


def assess(payload):
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1 or type(payload.get("test_only")) is not bool:
        raise ValueError("schema_version=1 and explicit test_only required")
    role = payload.get("data_role")
    if role not in ("synthetic", "reused_development", "retrospective_diagnostic", "untouched_historical_validation"):
        raise ValueError("explicit historical data role required")
    if (role == "synthetic") != payload["test_only"]:
        raise ValueError("synthetic must be test_only; real data cannot impersonate a fixture")
    rows = payload.get("episodes")
    if type(rows) is not list or len(rows) > 10000:
        raise ValueError("bounded registered episode list required")
    ids, periods, nonloss, real, drawdowns, missing = set(), [], [], [], [], []
    for row in rows:
        if type(row) is not dict:
            raise ValueError("episode object required")
        ident = row.get("id")
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError("unique episode IDs required")
        ids.add(ident)
        periods.append(_period(row))
        refs = row.get("source_refs")
        if not refs:
            missing.append(f"{ident}:source_refs")
        elif type(refs) is not list or any(not isinstance(x, str) or not x.strip() for x in refs):
            raise ValueError("source_refs must be nonempty reference strings")
        ret = row.get("net_liquidation_return")
        draw = row.get("unitized_max_drawdown")
        if ret is None:
            missing.append(f"{ident}:net_liquidation_return")
        else:
            ret = number(ret)
            if ret < -1:
                raise ValueError("unlevered net return cannot be below -1")
            nonloss.append(ret >= 0)
        if draw is None:
            missing.append(f"{ident}:unitized_max_drawdown")
        else:
            draw = number(draw)
            if not 0 <= draw <= 1:
                raise ValueError("drawdown must be a nonnegative fraction <=1")
            drawdowns.append(draw)
        changes = row.get("cpi_monthly")
        if changes is None:
            missing.append(f"{ident}:cpi_monthly")
        else:
            inflation = cpi_growth(changes, *periods[-1])
            if ret is not None:
                real.append(ret > inflation)
    ordered = sorted(periods)
    overlap = any(current[0] < previous[1] for previous, current in zip(ordered, ordered[1:]))
    reviews = payload.get("reviews") or {}
    if type(reviews) is not dict:
        raise ValueError("reviews must be an object")
    unqualified = [
        key for key in REQUIRED_REVIEWS
        if not isinstance(reviews.get(key), dict)
        or reviews[key].get("status") != "verified"
        or not isinstance(reviews[key].get("evidence_ref"), str)
        or not reviews[key]["evidence_ref"].strip()
    ]

    def summarize(values, target):
        wins, count = sum(values), len(values)
        lower = exact_lower(wins, count) if count else None
        return {"successes": wins, "n": count, "rate": wins / count if count else None,
                "lower_bound": lower, "target": target,
                "numerical_target_met": lower is not None and lower >= target}

    a, b = summarize(nonloss, NONLOSS_TARGET), summarize(real, REAL_TARGET)
    draw_ok = bool(rows) and len(drawdowns) == len(rows) and max(drawdowns) <= DRAWDOWN_LIMIT
    eligible = (role == "untouched_historical_validation" and not missing
                and not unqualified and not overlap and bool(rows))
    numbers_met = a["numerical_target_met"] and b["numerical_target_met"] and draw_ok
    if payload["test_only"]:
        status = "synthetic_only"
    elif not eligible:
        status = "pending_evidence"
    elif numbers_met:
        status = "historical_gate_passed"
    elif not draw_ok or any(r["rate"] is not None and r["rate"] < r["target"] for r in (a, b)):
        status = "not_met"
    else:
        status = "pending_sample_size"
    return {"status": status, "registered_n": len(rows), "nonloss": a, "beat_cpi": b,
            "max_drawdown": str(max(drawdowns)) if drawdowns else None,
            "drawdown_target_met": draw_ok, "missing": missing,
            "unqualified_reviews": unqualified, "overlapping_episodes": overlap,
            "confidence": CONFIDENCE, "statistical_method": "one_sided_clopper_pearson",
            "interval_interpretation": "conditional on independent qualified sampling; ineligible bounds are descriptive only",
            "numerical_targets_met": numbers_met, "eligible": eligible,
            "test_only": payload["test_only"], "data_role": role,
            "project_complete": False, "real_guidance_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True, help="new private directory outside checkout")
    args = parser.parse_args()
    from .runner import _read_private
    from .llm_loop import private_dir
    source, target = Path(args.input).absolute(), Path(args.output).absolute()
    for candidate in (source, target):
        if any((p / ".git").exists() for p in (candidate, *candidate.parents)):
            raise ValueError("real acceptance inputs and outputs must stay outside checkout")
    result = assess(json.loads(_read_private(source)))
    destination = private_dir(target)
    import os
    fd = os.open(destination / "acceptance.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({"status": result["status"], "output": str(destination / "acceptance.json"),
                      "project_complete": False, "real_guidance_authorized": False}))


if __name__ == "__main__":
    main()
