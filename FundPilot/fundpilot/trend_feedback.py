"""Bridge frozen research into existing direction scoring and case experience.

No inference, market requests, numerical backfill, strategy search or promotion.
Existing llm_loop.freeze/score and research.Experience retain their semantics.
"""
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import tempfile

from . import llm_loop
from .frozen_topdown import load_frozen_research
from .market import timestamp
from .research import Experience
from .upstream_bridge import private_parent, private_root, read_private, write_new, write_bytes_new


def _json(path):
    return json.loads(read_private(Path(path)))


def _claim_rows(raw):
    rows = json.loads(json.loads(raw)["content"])["forecasts"]
    if (len(rows) != 3 or any(not isinstance(r, dict) or type(r.get("horizon")) is not int
                             for r in rows)
            or {r["horizon"] for r in rows} != {1, 5, 20}):
        raise ValueError("exact integer 1/5/20 claims required")
    for row in rows:
        p = row.get("p_up")
        if p is not None and (type(p) not in (int, float) or not 0 <= p <= 1):
            raise ValueError("probability must be finite and numeric, never boolean")
    return {row["horizon"]: row for row in rows}


def freeze_bridge_cards(*, research_root, binding_path, sources_path,
                        calendar_path, output):
    """Map original claims to new scoreable cards; never read outcome NAV.

    Binding is an explicit external review of identity, dates and citations.
    It cannot establish source truth, historical availability, or new-run rights.
    Numeric probabilities are preserved in original claims but NOT scored until
    their event/unit and numeric-schema qualification is independently supplied.
    """
    root = private_root(research_root)
    binding_raw = read_private(Path(binding_path))
    binding = json.loads(binding_raw)
    cutoff = timestamp(binding["cutoff"])
    research = load_frozen_research(root, cutoff)
    input_raw = read_private(root / "input.json")
    manager_raw = read_private(root / "response-3.json")
    if (binding.get("reviewed") is not True or not binding.get("review_ref")
            or binding.get("bridge_input_sha256") != llm_loop.digest(input_raw)
            or binding.get("manager_response_sha256") != research.provenance.response_sha256
            or llm_loop.digest(manager_raw) != research.provenance.response_sha256):
        raise ValueError("reviewed binding to exact frozen bridge bytes required")
    original = json.loads(input_raw)
    if binding.get("fund") != original.get("fund"):
        raise ValueError("binding must preserve exact frozen fund identity")
    mode = binding.get("mode")
    synthetic = research.provenance.producer == "synthetic_fixture"
    if mode != ("synthetic" if synthetic else "retrospective"):
        raise ValueError("only same-producer synthetic or retrospective mapping allowed")
    rows = _claim_rows(manager_raw)
    calendar_raw = read_private(Path(calendar_path))
    sources_raw = read_private(Path(sources_path))
    calendar, sources = json.loads(calendar_raw), json.loads(sources_raw)
    origin = binding["origin"]
    date.fromisoformat(origin)
    source_map = binding.get("source_ids_by_horizon")
    if not isinstance(source_map, dict) or set(source_map) != {"1", "5", "20"}:
        raise ValueError("explicit citation mapping for every horizon required")
    cards = {
        "mode": mode, "producer": "synthetic_fixture" if synthetic else "actual_llm",
        "cutoff": binding["cutoff"],
        "generated_at": research.provenance.generated_at.isoformat(),
        "model_ref": research.provenance.model_ref,
        "prompt_version": "frozen-manager:" + research.provenance.prompt_sha256,
        "replayed_frozen_output": True, "new_model_inference": False,
        "independent_oos": False, "cards": [],
    }
    for h in (1, 5, 20):
        row = rows[h]
        refs = source_map[str(h)]
        if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or not x for x in refs):
            raise ValueError("nonempty source identities required")
        card = {
            "id": research.trend.trend_id + ":h" + str(h), "fund": binding["fund"],
            "origin": origin, "horizon": h, "direction": row["direction"],
            "source_ids": refs, "reasoning": row["rationale"],
            "counterevidence": row["counterevidence"], "invalidation": row["invalidation"],
            "gaps": row["gaps"], "scenarios": row.get("scenarios", []),
            "scenarios_not_reported_upstream": "scenarios" not in row,
            "bridge_forecast": row,
            "numeric_mapping_status": "pending_event_unit_and_numeric_schema_review",
        }
        if row["direction"] == "abstain":
            card["abstention_reason"] = row["gaps"]
        cards["cards"].append(card)
    # Existing calendar, citation and point-in-time checks remain authoritative.
    llm_loop.validate(cards, sources, calendar)
    output = Path(output)
    with private_parent(output):
        pass
    with tempfile.TemporaryDirectory(prefix=".bridge-cards-", dir=output.parent) as td:
        temp = Path(td)
        write_new(temp / "cards.json", cards)
        write_bytes_new(temp / "sources.json", sources_raw)
        write_bytes_new(temp / "calendar.json", calendar_raw)
        receipt = llm_loop.freeze(temp / "cards.json", temp / "sources.json",
                                  temp / "calendar.json", output)
    write_bytes_new(output / "bridge-input.json", input_raw)
    write_bytes_new(output / "bridge-manager.json", manager_raw)
    write_bytes_new(output / "bridge-binding.json", binding_raw)
    hashes = {name: llm_loop.digest(read_private(output / name)) for name in (
        "bridge-input.json", "bridge-manager.json", "bridge-binding.json",
        "cards.json", "sources.json", "calendar.json", "receipt.json")}
    write_new(output / "bridge-export.json", {
        "schema": "fundpilot.bridge-cards.v1", "hashes": hashes,
        "original_generation_preserved": True, "new_model_inference": False,
        "numeric_backfill": False, "independent_oos": False,
    })
    return receipt


def feedback_from_scores(*, frozen_root, scored_root, output):
    """Attach correct AND incorrect observations to candidate experience records.

    Reads already computed results; does not rescore real history or infer causes.
    Pending/missing/abstained rows remain cases without success/failure experience.
    All outputs are new private files. Callers retain previous versions.
    """
    frozen, scored = private_root(frozen_root), private_root(scored_root)
    export = _json(frozen / "bridge-export.json")
    if export.get("schema") != "fundpilot.bridge-cards.v1":
        raise ValueError("bridge export required")
    expected_names = {
        "bridge-input.json", "bridge-manager.json", "bridge-binding.json",
        "cards.json", "sources.json", "calendar.json", "receipt.json"}
    if set(export.get("hashes", {})) != expected_names:
        raise ValueError("complete bridge export hashes required")
    for name, expected in export["hashes"].items():
        if llm_loop.digest(read_private(frozen / name)) != expected:
            raise ValueError("bridge export hash mismatch: " + name)
    cards = _json(frozen / "cards.json")
    frozen_receipt = _json(frozen / "receipt.json")
    llm_loop.validate(cards, _json(frozen / "sources.json"), _json(frozen / "calendar.json"))
    raw_result = read_private(scored / "results.json")
    manifest = _json(scored / "manifest.json")
    if (manifest.get("results_sha256") != llm_loop.digest(raw_result)
            or manifest.get("frozen_receipt_sha256") != export["hashes"]["receipt.json"]
            or manifest.get("frozen_inputs") != frozen_receipt["hashes"]):
        raise ValueError("score manifest must bind the exact frozen cards and results")
    result = json.loads(raw_result)
    if result.get("mode") != cards["mode"] or result.get("independent_oos") is not False:
        raise ValueError("score research scope mismatch")
    tape = result["tape"]
    by_id = {c["id"]: c for c in cards["cards"]}
    if len(tape) != len(by_id) or {r["card_id"] for r in tape} != set(by_id):
        raise ValueError("all frozen cards must appear exactly once in feedback")
    reviewed_at = timestamp(llm_loop.now())
    cases, experiences = [], []
    counts = {key: 0 for key in ("correct", "incorrect", "abstained", "pending", "missing")}
    original_rows = _claim_rows(read_private(frozen / "bridge-manager.json"))
    for row in tape:
        card = by_id[row["card_id"]]
        if (any(row.get(k) != card[k] for k in ("fund", "origin", "horizon"))
                or row.get("llm_direction") != card["direction"]
                or card["bridge_forecast"] != original_rows[card["horizon"]]):
            raise ValueError("score or mapped claim differs from original frozen prediction")
        status = row["status"]
        if status == "scored":
            actual = row.get("actual_direction")
            if (actual not in ("up", "flat", "down") or card["direction"] == "abstain"
                    or type(row.get("llm_hit")) is not bool
                    or row["llm_hit"] != (actual == card["direction"])):
                raise ValueError("inconsistent direction outcome")
            label = "correct" if row["llm_hit"] else "incorrect"
        elif status in ("abstained", "pending", "missing"):
            if row.get("llm_hit") is not None:
                raise ValueError("unscored case must not claim success or failure")
            if status == "abstained":
                if card["direction"] != "abstain" or row.get("actual_direction") not in ("up", "flat", "down"):
                    raise ValueError("abstention must preserve the original abstained mature claim")
            elif row.get("actual_direction") is not None:
                raise ValueError("pending or missing case cannot contain a mature direction")
            label = status
        else:
            raise ValueError("unsupported score status")
        counts[label] += 1
        case = {
            "card_id": card["id"], "outcome": label,
            "original_claim": card["bridge_forecast"],
            "source_ids": card["source_ids"], "target": row["target"],
            "actual_direction": row.get("actual_direction"),
            "actual_nav_change": row.get("nav_price_change"),
            "missing_reason": row.get("missing_reason"),
            "baseline": {k: row.get(k) for k in (
                "persistence_direction", "persistence_hit", "trend20_direction",
                "trend20_hit", "trend20_missing_reason")},
            "attribution": {"cause": "unknown", "status": "not_established",
                            "original_counterevidence": card["counterevidence"],
                            "notice": "Agreement or disagreement alone does not establish a cause"},
            "score_result_sha256": llm_loop.digest(raw_result),
        }
        cases.append(case)
        if label in ("correct", "incorrect"):
            experience = Experience(
                "trend-case:" + card["id"],
                "Review frozen claim: " + card["reasoning"], reviewed_at)
            experiences.append({
                "experience": {**asdict(experience), "created_at": reviewed_at.isoformat()},
                "outcome": label, "support_case_id": card["id"],
                "source_ids": card["source_ids"],
                "counterevidence": card["counterevidence"],
                "invalidation": card["invalidation"],
                "score_result_sha256": llm_loop.digest(raw_result),
                "qualification": "single_case_candidate_only_no_causal_or_oos_claim",
            })
    feedback = {
        "scope": "frozen_trend_direction_feedback_not_investment_return",
        "mode": cards["mode"], "counts": counts, "cases": cases,
        "experience_candidates": experiences,
        "new_model_inference": False, "new_score_computation": False,
        "independent_oos": False, "forecasting_skill_proven": False,
        "investment_efficacy_proven": False, "automatic_promotion": False,
        "real_guidance_authorized": False,
        "limitations": [
            "Raw NAV direction is not dividend-adjusted or fee-net investment performance",
            "Correct cases do not prove reasoning; incorrect cases do not identify causes",
            "Unknown probabilities/quantiles are not supplied or backfilled",
            "Evidence, hashes and reviews require external inspection; not a signature",
            "All previous cases and scores must be retained; no automatic experience reuse",
        ],
    }
    output = Path(output)
    with private_parent(output):
        pass
    llm_loop.private_dir(output)
    write_new(output / "feedback.json", feedback)
    write_new(output / "manifest.json", {
        "bridge_export_sha256": llm_loop.digest(read_private(frozen / "bridge-export.json")),
        "score_manifest_sha256": llm_loop.digest(read_private(scored / "manifest.json")),
        "feedback_sha256": llm_loop.digest(read_private(output / "feedback.json")),
        "created_at": reviewed_at.isoformat(),
    })
    return feedback
