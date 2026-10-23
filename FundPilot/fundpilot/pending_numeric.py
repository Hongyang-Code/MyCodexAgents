"""Unqualified numeric-card custody only. No calendar binding or scoring path."""
import argparse
import json
from pathlib import Path
from .llm_loop import digest, now, private_dir, write_json
from .market import timestamp
from .numeric_forecast import validate_numeric
from .iteration_control import RunBudget

STATUS = {'status':'pending_unqualified_numeric','calendar_qualification':'pending',
          'source_qualification':'pending','scoring_ready':False,'scoring_implemented':False,
          'trading_authorized':False,'calibration_proven':False,'independent_oos':False}


def object_hash(obj):
    """Hash this explicit JSON representation, never raw HTTP or unknown serialization."""
    return digest(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8'))


def validate(record, original_raw):
    json.loads(original_raw)  # Original remains uninterpreted and byte-for-byte unchanged.
    if record.get('original_sha256')!=digest(original_raw):raise ValueError('original record hash mismatch')
    if record.get('record_kind')!='pending_numeric_capture' or record.get('producer') not in ('actual_llm','synthetic_fixture'):
        raise ValueError('explicit pending numeric capture required')
    for field in ('model_ref','prompt_version','mapping_review_ref'):
        if not isinstance(record.get(field),str) or not record[field].strip():raise ValueError('required '+field)
    generated=timestamp(record['generated_at']); cutoff=timestamp(record['information_cutoff'])
    if not cutoff<=generated<=timestamp(now()):raise ValueError('real cutoff/generation time order required')
    cards=record['cards'];sources=record['sources']
    if not 1<=len(cards)<=9 or len({c['id'] for c in cards})!=len(cards):raise ValueError('one to nine unique cards')
    if len({(c['fund'],c['horizon']) for c in cards})!=len(cards):raise ValueError('duplicate fund/horizon')
    _,action=RunBudget().reserve('shape-check','prediction_batch',funds=tuple({c['fund'] for c in cards}),horizons=tuple({c['horizon'] for c in cards}))
    if action!='reserved':raise ValueError('batch shape exceeds budget')
    if not 1<=len(sources)<=12 or len({s['id'] for s in sources})!=len(sources):raise ValueError('one to twelve unique source snapshots')
    for s in sources:
        if s.get('snapshot_kind')!='captured_object' or s.get('hash_basis')!='json_sorted_compact_utf8':
            raise ValueError('explicit captured object representation required, not HTTP')
        if not isinstance(s.get('captured_object'),dict) or object_hash(s['captured_object'])!=s.get('object_sha256'):
            raise ValueError('captured object hash mismatch')
        if not timestamp(s['retrieved_at'])<=timestamp(s['known_available_at'])<=timestamp(now()):
            raise ValueError('actual source retrieval/knowledge times required')
        if 'published_at' not in s:raise ValueError('publication time explicit value or null required')
        if s['published_at'] is not None:timestamp(s['published_at'])
        # No publication/calendar eligibility inferred: storage accepts unresolved facts.
    source_ids={s['id'] for s in sources}
    for c in cards:
        validate_numeric(record,c)
        if 'numeric_forecast' not in c:raise ValueError('numeric record required')
        if any(c.get(k) is not None for k in ('D0','Dh','origin','target')):
            raise ValueError('this custody path requires unresolved dates, never binds them')
        if not c.get('source_ids') or not set(c['source_ids'])<=source_ids:raise ValueError('captured source references required')
    return True


def save(original_path, record_path, output):
    original=Path(original_path).read_bytes();raw=Path(record_path).read_bytes();record=json.loads(raw)
    validate(record,original)
    root=private_dir(output)
    for name,body in (('original.json',original),('capture-record.json',raw)):
        (root/name).write_bytes(body);(root/name).chmod(0o400)
    receipt={**STATUS,'actual_saved_at':now(),'generated_at_claim':record['generated_at'],
             'original_sha256':digest(original),'capture_record_sha256':digest(raw),
             'producer':record['producer'],'producer_attestation_not_verified':True,'card_count':len(record['cards']),
             'mapping_status':'caller_reviewed_not_independently_verified_by_program',
             'limitations':['Saved is not evidence-qualified or calibrated',
                'Object hash describes canonical captured JSON, never HTTP bytes',
                'No D0/Dh, calendar binding, labels, scoring or automatic transfer to strict score',
                'Read-only file mode and hashes are not remote WORM; preserve independent private receipt',
                'Original-to-normalized mapping needs independent review; no numerical backfill permitted']}
    write_json(root/'receipt.json',receipt);(root/'receipt.json').chmod(0o400)
    return receipt


def inspect(path):
    root=Path(path);receipt=json.loads((root/'receipt.json').read_bytes())
    if any(receipt.get(k)!=v for k,v in STATUS.items()):raise ValueError('pending status cannot be promoted by editing receipt')
    raw=(root/'capture-record.json').read_bytes();original=(root/'original.json').read_bytes()
    if digest(raw)!=receipt['capture_record_sha256'] or digest(original)!=receipt['original_sha256']:
        raise ValueError('saved bytes changed')
    validate(json.loads(raw),original)
    return {**STATUS,'hashes_verified':True,'card_count':len(json.loads(raw)['cards'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    s=sub.add_parser('save')
    for key in ('original','record','output'):s.add_argument('--'+key,required=True)
    i=sub.add_parser('inspect');i.add_argument('--pending',required=True)
    a=parser.parse_args()
    r=save(a.original,a.record,a.output) if a.command=='save' else inspect(a.pending)
    print(json.dumps(r,ensure_ascii=False))


if __name__=='__main__':main()
