"""One explicitly approved diagnostic scope; legacy cumulative use stays unknown.

Same-host authority registry is fixed beside the preserved legacy ledger. It is
not a distributed lock, identity verifier, or account token meter.
"""
import argparse
import hashlib
import json
import sqlite3
from urllib.parse import quote
from pathlib import Path
from datetime import datetime,timezone
from contextlib import closing
from .upstream_bridge import read_private,write_bytes_new,private_parent,checked_time,digest
from .durable_budget import DurableBudget,encoded


def grant(legacy_path, approval_path):
    legacy=DurableBudget(legacy_path);raw=read_private(legacy.path)
    with private_parent(legacy.path) as (parent,name):
        quoted=quote(name,safe='');uri=f'file:/proc/self/fd/{parent}/{quoted}?mode=ro'
        with closing(sqlite3.connect(uri,uri=True)) as ro:old=legacy._read(ro)
    if old['stopped']:raise ValueError('legacy stopped; explicit warning reconciliation required')
    a=json.loads(read_private(approval_path))
    if a.get('authority_legacy_path')!=str(legacy.path):raise ValueError('canonical legacy authority required; no copied-directory reissue')
    if (not a.get('approval_id') or a.get('answer')!='批准这一次历史对照' or
        not a.get('source') or not a.get('question') or a.get('scope')!={'llm':12,'source':0,'evaluations':1,'candidate':0}):
        raise ValueError('explicit one-time diagnostic approval and exact scope required')
    if checked_time(a['approved_at'])>datetime.now(timezone.utc):raise ValueError('future approval rejected')
    if a['legacy_sha256']!=digest(raw) or old['seed']['candidate_history'] is None:raise ValueError('complete unchanged legacy binding required')
    for item in a['bindings']:
        if digest(read_private(item['path']))!=item['sha256']:raise ValueError('frozen binding mismatch')
    if not a['bindings']:raise ValueError('frozen protocol/input bindings required')
    binding={**a,'legacy_seed':old['seed'],'legacy_cumulative_used':old['seed']['used'],'cross_scope_tokens':'unknown'}
    ph=digest(encoded(binding).encode());key=digest(a['approval_id'].encode())
    registry=legacy.path.parent/'diagnostic-grants.sqlite';target=legacy.path.parent/('diagnostic-'+key+'.sqlite')
    try:write_bytes_new(registry,b'')
    except FileExistsError:read_private(registry)
    with DurableBudget(registry).connection() as c:
        c.execute('CREATE TABLE IF NOT EXISTS grants (id TEXT PRIMARY KEY, binding TEXT NOT NULL, status TEXT NOT NULL)')
        c.commit();c.execute('BEGIN IMMEDIATE')
        prior=c.execute('SELECT binding,status FROM grants WHERE id=?',(key,)).fetchone()
        if prior:
            if prior!=(ph,'ready'):raise ValueError('grant pending/changed; no automatic reissue')
            b=DurableBudget(target)
            if b.snapshot()['seed'].get('diagnostic_grant')!=binding:raise ValueError('grant ledger identity mismatch')
            return b
        c.execute('INSERT INTO grants VALUES(?,?,?)',(key,ph,'claimed'));c.commit()
        # A crash after claim remains claimed, never yields another twelve.
        b=DurableBudget.create(target,run_id=a['approval_id'],used=dict(source=0,retry=0,llm=0,prediction_batch=0),candidate_history=old['seed']['candidate_history'])
        with b.connection() as db:
            db.execute('BEGIN IMMEDIATE');state=b._read(db);state['seed']['diagnostic_grant']=binding;b._write(db,state)
        c.execute('UPDATE grants SET status=? WHERE id=?',('ready',key));c.commit()
    if read_private(legacy.path)!=raw:raise ValueError('legacy changed during grant')
    return b


def verify_bindings(seed, *, evidence_path=None, input_sha256=None):
    binding=seed.get('diagnostic_grant')
    if not binding:return
    if digest(read_private(binding['authority_legacy_path']))!=binding['legacy_sha256']:
        raise ValueError('legacy authority changed')
    for item in binding['bindings']:
        if digest(read_private(item['path']))!=item['sha256']:raise ValueError('frozen diagnostic binding changed')
    frozen = any(
        item['path'] == str(Path(evidence_path).absolute())
        and item['sha256'] == input_sha256 for item in binding['bindings']
    ) if evidence_path is not None else any(
        item['sha256'] == input_sha256 for item in binding['bindings']
    )
    if not frozen and binding.get('grant_kind') == 'trend_diagnostic':
        from .trend_scope_evidence import verify_registered_evidence
        frozen = verify_registered_evidence(
            binding, evidence_path=evidence_path, input_sha256=input_sha256)
    if not frozen:
        raise ValueError('input outside approved diagnostic bindings'
                         if evidence_path is not None else
                         'checkpoint outside approved diagnostic bindings')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--legacy',required=True);p.add_argument('--approval',required=True)
    a=p.parse_args();b=grant(a.legacy,a.approval);print(json.dumps({'budget':str(b.path),'legacy_cumulative_usage':'unknown','actual_tokens':'unknown'}))

if __name__=='__main__':main()
