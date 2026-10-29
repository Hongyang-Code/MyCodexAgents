"""Read-only audit for an already registered trend-diagnostic scope.

This command never creates a registry, grant, ledger, reservation, or request.
It distinguishes an executable frozen input from an older claimed scope whose
immutable bindings contain only a protocol or batch manifest.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .durable_budget import DurableBudget, encoded
from .trend_diagnostic_grant import CUTOFF, FUNDS, HORIZONS, SCOPE, USED, _legacy
from .upstream_bridge import checked_time, digest, private_parent, read_private


def _executable_binding(approval):
    executable = False
    for item in approval["bindings"]:
        raw = read_private(item["path"])
        if digest(raw) != item["sha256"]:
            raise ValueError("frozen trend diagnostic binding changed")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        required = ("fund", "information_cutoff", "market_report",
                    "fundamentals_report")
        if (isinstance(value, dict)
                and value.get("fund") in FUNDS
                and value.get("information_cutoff") == CUTOFF
                and all(isinstance(value.get(key), str)
                        and value[key].strip() for key in required)):
            executable = True
    return executable


def audit(legacy_path, approval_path):
    legacy, legacy_raw, old = _legacy(legacy_path)
    approval = json.loads(read_private(approval_path))
    if approval.get("authority_legacy_path") != str(legacy.path):
        raise ValueError("canonical legacy authority required")
    exact = (
        approval.get("approval_id")
        and approval.get("answer") == "批准这一批趋势诊断"
        and approval.get("source")
        and approval.get("question")
        and approval.get("scope") == SCOPE
        and approval.get("used") == USED
        and approval.get("funds") == FUNDS
        and approval.get("horizons") == HORIZONS
        and approval.get("information_cutoff") == CUTOFF
    )
    if not exact:
        raise ValueError("explicit trend-diagnostic approval and exact scope required")
    if checked_time(approval["approved_at"]) > datetime.now(timezone.utc):
        raise ValueError("future approval rejected")
    if (approval.get("legacy_sha256") != digest(legacy_raw)
            or old["seed"]["candidate_history"] is None):
        raise ValueError("complete unchanged legacy binding required")
    bindings = approval.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("frozen protocol/input bindings required")
    executable = _executable_binding(approval)
    binding = {
        **approval,
        "grant_kind": "trend_diagnostic",
        "legacy_seed": old["seed"],
        "legacy_cumulative_used": old["seed"]["used"],
        "cross_scope_tokens": "unknown",
    }
    binding_hash = digest(encoded(binding).encode())
    key = digest(approval["approval_id"].encode())
    registry = legacy.path.parent / "diagnostic-grants.sqlite"
    target = legacy.path.parent / ("trend-diagnostic-" + key + ".sqlite")
    read_private(registry)
    with private_parent(registry) as (parent, name):
        uri = f"file:/proc/self/fd/{parent}/{quote(name, safe='')}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            prior = connection.execute(
                "SELECT binding,status FROM grants WHERE id=?", (key,)
            ).fetchone()
    if prior != (binding_hash, "ready"):
        raise ValueError("registered scope identity is not ready and unchanged")
    budget = DurableBudget(target)
    snapshot = budget.snapshot()
    if snapshot["seed"].get("diagnostic_grant") != binding:
        raise ValueError("grant ledger identity mismatch")
    from .trend_scope_evidence import registered_evidence
    derived = registered_evidence(binding)
    status = ("ready" if executable else
              "ready_registered_evidence" if derived else
              "blocked_non_executable_binding")
    return {
        "status": status,
        "budget": str(target),
        "ledger_id": snapshot["seed"]["ledger_id"],
        "operations": len(snapshot["operations"]),
        "used": snapshot["seed"]["used"],
        "bridge_start_allowed": executable or bool(derived),
        "derived_evidence_count": len(derived),
        "derived_evidence_sha256": [item["sha256"] for item in derived],
        "audit_mutations": 0,
        "actual_tokens": "unknown",
        "legacy_cumulative_usage": "unknown",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", required=True)
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.legacy, args.approval), sort_keys=True))


if __name__ == "__main__":
    main()
