"""One bounded trend-diagnostic grant without resetting legacy history.

The canonical legacy ledger anchors a same-host registry.  The grant preserves
the three source attempts already used by the approved scope and cannot be
reissued by copying the ledger or choosing another output directory.  This is
not a distributed lock, identity proof, model caller, or token meter.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .durable_budget import DurableBudget, encoded
from .upstream_bridge import (checked_time, digest, private_parent, read_private,
                              write_bytes_new)


SCOPE = {
    "funds": 3,
    "llm": 12,
    "source": 12,
    "evaluations": 1,
    "candidate": 0,
    "trades": 0,
}
USED = {
    "source": 3,
    "retry": 0,
    "llm": 0,
    "prediction_batch": 0,
    "evaluations": 0,
}
FUNDS = ["000051/A/CNY", "004042/A/CNY", "000071/A/CNY"]
HORIZONS = [1, 5, 20]
CUTOFF = "2026-07-31T21:30:00+08:00"


def _legacy(path):
    ledger = DurableBudget(path)
    raw = read_private(ledger.path)
    with private_parent(ledger.path) as (parent, name):
        uri = f"file:/proc/self/fd/{parent}/{quote(name, safe='')}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            state = ledger._read(connection)
    return ledger, raw, state


def grant(legacy_path, approval_path):
    legacy, legacy_raw, old = _legacy(legacy_path)
    if old["stopped"]:
        raise ValueError("legacy stopped; explicit warning reconciliation required")
    approval = json.loads(read_private(approval_path))
    if approval.get("authority_legacy_path") != str(legacy.path):
        raise ValueError("canonical legacy authority required; no copied-directory reissue")
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
    executable_input = False
    for item in bindings:
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
            executable_input = True
    if not executable_input:
        raise ValueError("at least one executable frozen evidence input required")

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
    try:
        write_bytes_new(registry, b"")
    except FileExistsError:
        read_private(registry)
    with DurableBudget(registry).connection() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS grants "
            "(id TEXT PRIMARY KEY, binding TEXT NOT NULL, status TEXT NOT NULL)"
        )
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        prior = connection.execute(
            "SELECT binding,status FROM grants WHERE id=?", (key,)
        ).fetchone()
        if prior:
            if prior != (binding_hash, "ready"):
                raise ValueError("grant pending/changed; no automatic reissue")
            budget = DurableBudget(target)
            if budget.snapshot()["seed"].get("diagnostic_grant") != binding:
                raise ValueError("grant ledger identity mismatch")
            return budget
        connection.execute(
            "INSERT INTO grants VALUES(?,?,?)", (key, binding_hash, "claimed")
        )
        connection.commit()
        # A crash after this claim stays claimed.  It never creates fresh quota.
        budget = DurableBudget.create(
            target,
            run_id=approval["approval_id"],
            used={key: USED[key] for key in
                  ("source", "retry", "llm", "prediction_batch")},
            candidate_history=old["seed"]["candidate_history"],
        )
        with budget.connection() as database:
            database.execute("BEGIN IMMEDIATE")
            state = budget._read(database)
            state["seed"]["diagnostic_grant"] = binding
            budget._write(database, state)
        connection.execute(
            "UPDATE grants SET status=? WHERE id=?", ("ready", key)
        )
        connection.commit()
    if read_private(legacy.path) != legacy_raw:
        raise ValueError("legacy changed during grant")
    return budget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", required=True)
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    budget = grant(args.legacy, args.approval)
    print(json.dumps({
        "budget": str(budget.path),
        "scope": "trend_diagnostic",
        "source_attempts_already_used": 3,
        "legacy_cumulative_usage": "unknown",
        "actual_tokens": "unknown",
    }))


if __name__ == "__main__":
    main()
