"""Append-only evidence registration for an approved trend diagnostic.

The original approval, immutable bindings, legacy ledger, and derived budget
remain unchanged. A row only freezes exact executable evidence bytes and ties
them to source attempts already present in the approved manifest or scope.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .trend_diagnostic_grant import CUTOFF, FUNDS
from .upstream_bridge import digest, private_parent, read_private


def _manifest_source_ids(approval):
    source_ids, authority_parents = set(), set()
    for item in approval['bindings']:
        path = Path(item['path']).absolute()
        authority_parents.add(path.parent)
        raw = read_private(path)
        if digest(raw) != item['sha256']:
            raise ValueError('frozen trend diagnostic binding changed')
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        reservations = value.get('reservations') if isinstance(value, dict) else None
        if not isinstance(reservations, list):
            continue
        ids = [entry.get('id') for entry in reservations
               if isinstance(entry, dict) and entry.get('kind') == 'source']
        if (not ids or len(ids) != len(set(ids))
                or value.get('used', {}).get('source') != approval['used']['source']
                or len(ids) != approval['used']['source']):
            raise ValueError('frozen source-attempt manifest is inconsistent')
        source_ids.update(ids)
    return source_ids, authority_parents


def _registry_path(binding):
    return Path(binding['authority_legacy_path']).absolute().parent / 'diagnostic-grants.sqlite'


def _open_registry_readonly(path):
    context = private_parent(path)
    parent, name = context.__enter__()
    uri = f"file:/proc/self/fd/{parent}/{quote(name, safe='')}?mode=ro"
    return context, sqlite3.connect(uri, uri=True)


def verify_registered_evidence(binding, *, evidence_path=None, input_sha256=None):
    if not input_sha256:
        return False
    context, connection = _open_registry_readonly(_registry_path(binding))
    try:
        with closing(connection):
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trend_evidence'"
            ).fetchone():
                return False
            if evidence_path is None:
                row = connection.execute(
                    'SELECT path FROM trend_evidence WHERE scope_id=? AND sha256=?',
                    (binding['approval_id'], input_sha256)).fetchone()
            else:
                row = connection.execute(
                    'SELECT path FROM trend_evidence WHERE scope_id=? AND path=? AND sha256=?',
                    (binding['approval_id'], str(Path(evidence_path).absolute()),
                     input_sha256)).fetchone()
    finally:
        context.__exit__(None, None, None)
    return bool(row and digest(read_private(row[0])) == input_sha256)


def registered_evidence(binding):
    context, connection = _open_registry_readonly(_registry_path(binding))
    try:
        with closing(connection):
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trend_evidence'"
            ).fetchone():
                return []
            rows = connection.execute(
                'SELECT fund,path,sha256,source_ids,registered_at FROM trend_evidence '
                'WHERE scope_id=? ORDER BY fund', (binding['approval_id'],)).fetchall()
    finally:
        context.__exit__(None, None, None)
    result = []
    for fund, path, sha256, source_ids, registered_at in rows:
        if digest(read_private(path)) != sha256:
            raise ValueError('registered trend evidence changed')
        result.append({'fund': fund, 'path': path, 'sha256': sha256,
                       'source_operation_ids': json.loads(source_ids),
                       'registered_at': registered_at})
    return result


def register(legacy_path, approval_path, evidence_path, source_operation_ids):
    from .durable_budget import DurableBudget
    from .trend_scope_audit import audit
    audit_result = audit(legacy_path, approval_path)
    approval = json.loads(read_private(approval_path))
    evidence_path = Path(evidence_path).absolute()
    raw = read_private(evidence_path)
    value = json.loads(raw)
    required = ('fund', 'information_cutoff', 'market_report', 'fundamentals_report')
    if (not isinstance(value, dict) or value.get('fund') not in FUNDS
            or value.get('information_cutoff') != CUTOFF
            or any(not isinstance(value.get(key), str) or not value[key].strip()
                   for key in required)):
        raise ValueError('derived evidence outside approved fund/cutoff/schema')
    manifest_ids, authority_parents = _manifest_source_ids(approval)
    if evidence_path.parent not in authority_parents:
        raise ValueError('derived evidence must stay in canonical authority directory')
    budget = DurableBudget(audit_result['budget'])
    snapshot = budget.snapshot()
    scope_ids = {op['id'] for op in snapshot['operations']
                 if op['kind'] in ('source', 'retry')}
    supplied = list(source_operation_ids)
    if (not supplied or len(supplied) != len(set(supplied))
            or not set(supplied) <= (manifest_ids | scope_ids)):
        raise ValueError('every evidence source must be charged to this scope')
    binding = snapshot['seed']['diagnostic_grant']
    registry, sha256 = _registry_path(binding), digest(raw)
    exact = (str(evidence_path), sha256,
             json.dumps(supplied, separators=(',', ':'), sort_keys=True))
    with sqlite3.connect(registry) as connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute(
            'CREATE TABLE IF NOT EXISTS trend_evidence '
            '(scope_id TEXT NOT NULL, fund TEXT NOT NULL, path TEXT NOT NULL, '
            'sha256 TEXT NOT NULL, source_ids TEXT NOT NULL, registered_at TEXT NOT NULL, '
            'PRIMARY KEY(scope_id,fund), UNIQUE(scope_id,path), UNIQUE(scope_id,sha256))')
        connection.execute(
            "CREATE TRIGGER IF NOT EXISTS trend_evidence_no_update BEFORE UPDATE "
            "ON trend_evidence BEGIN SELECT RAISE(ABORT,'append only'); END")
        connection.execute(
            "CREATE TRIGGER IF NOT EXISTS trend_evidence_no_delete BEFORE DELETE "
            "ON trend_evidence BEGIN SELECT RAISE(ABORT,'append only'); END")
        prior = connection.execute(
            'SELECT path,sha256,source_ids FROM trend_evidence WHERE scope_id=? AND fund=?',
            (approval['approval_id'], value['fund'])).fetchone()
        if prior and prior != exact:
            raise ValueError('conflicting evidence already registered for fund')
        if not prior:
            connection.execute('INSERT INTO trend_evidence VALUES(?,?,?,?,?,?)',
                               (approval['approval_id'], value['fund'], *exact,
                                datetime.now(timezone.utc).isoformat()))
        connection.commit()
    if not verify_registered_evidence(
            binding, evidence_path=evidence_path, input_sha256=sha256):
        raise ValueError('registered evidence readback failed')
    return {'status': 'registered_append_only', 'scope_id': approval['approval_id'],
            'fund': value['fund'], 'path': str(evidence_path), 'sha256': sha256,
            'source_operation_ids': supplied, 'new_source_attempts': 0,
            'new_model_requests': 0, 'new_evaluations': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy', required=True)
    parser.add_argument('--approval', required=True)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--source-operation-id', action='append', required=True)
    args = parser.parse_args()
    print(json.dumps(register(args.legacy, args.approval, args.evidence,
                              args.source_operation_id), sort_keys=True))


if __name__ == '__main__':
    main()
