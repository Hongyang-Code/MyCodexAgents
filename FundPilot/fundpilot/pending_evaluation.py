"""Append-only evaluation attachment for pending numeric cards; never edits forecasts."""
import argparse
from datetime import date
import json
from pathlib import Path
import re
from .pending_numeric import inspect
from .llm_loop import digest, now, private_dir, write_json
from .market import timestamp, number
from .numeric_forecast import score_numeric, summarize_numeric


def reviewed(obj, asof):
    if (not isinstance(obj,dict) or obj.get('reviewed') is not True or not obj.get('evidence_ref')
            or not re.fullmatch('[0-9a-f]{64}',obj.get('evidence_sha256',''))
            or obj.get('evidence_kind') not in ('raw_http','tool_extracted_text','structured_summary','captured_object')):
        return False
    try:
        return timestamp(obj['retrieved_at'])<=timestamp(obj['reviewed_at'])<=asof
    except (KeyError,ValueError,TypeError):
        return False


def evaluate(pending, binding, as_of):
    root=Path(pending);inspect(root)
    raw={name:(root/name).read_bytes() for name in ('original.json','capture-record.json','receipt.json')}
    record=json.loads(raw['capture-record.json']);receipt=json.loads(raw['receipt.json'])
    for name,body in raw.items():
        if binding['pending_sha256'].get(name)!=digest(body):raise ValueError('pending attachment hash mismatch: '+name)
    asof=timestamp(as_of)
    if not timestamp(receipt['actual_saved_at'])<=asof<=timestamp(now()):raise ValueError('evaluation must follow capture and not be future')
    freeze=binding.get('original_freeze'); frozen=None
    if reviewed(freeze,asof) and freeze.get('frozen_at') and freeze.get('original_sha256'):
        if freeze.get('original_sha256')!=receipt['original_sha256']:raise ValueError('freeze evidence refers to different original')
        frozen=timestamp(freeze['frozen_at'])
        if not timestamp(record['generated_at'])<=frozen<=timestamp(receipt['actual_saved_at']):
            raise ValueError('original freeze must be between generation and custody save; never binding time')
    source_map={s['id']:s for s in record['sources']}
    reviews=binding.get('source_reviews',[])
    if len({s['source_id'] for s in reviews})!=len(reviews):raise ValueError('duplicate source review')
    source_reviews={s['source_id']:s for s in reviews}
    calendars=binding.get('calendars',{})
    nav={}
    for r in binding.get('nav',[]):
        key=(r['fund'],r['date']);date.fromisoformat(r['date'])
        if key in nav:raise ValueError('duplicate NAV attachment')
        nav[key]=r
    tape=[]
    for c in record['cards']:
        row={'card_id':c['id'],'fund':c['fund'],'horizon':c['horizon'],'D0':None,'Dh':None,
             'status':'pending','reason':None,'actual_return':None,'original_freeze_at':frozen.isoformat() if frozen else None,
             'direction_added':False,'source_qualification':'pending','calendar_qualification':'pending'}
        reason=None
        if frozen is None:reason='original_freeze_review_missing'
        if reason is None:
            for sid in c['source_ids']:
                s=source_map[sid];r=source_reviews.get(sid)
                if r is not None and r.get('object_sha256') is not None and r.get('object_sha256')!=s['object_sha256']:
                    raise ValueError('review changed frozen object hash')
                if (not reviewed(r,asof) or r.get('object_sha256')!=s['object_sha256'] or r.get('usable_for_frozen_prediction') is not True
                        or r.get('review_scope')!='frozen_object_only_no_new_facts'):
                    reason='source_qualification_missing_or_rejected';break
                if timestamp(s['known_available_at'])>frozen:
                    reason='captured_object_not_known_before_original_freeze';break
            if reason is None:row['source_qualification']='external_review_of_frozen_object_known_before_freeze'
        cal=calendars.get(c['fund'])
        sessions=[]
        if reason is None:
            if (not reviewed(cal,asof) or cal.get('complete_valuation_sequence') is not True
                    or not cal.get('coverage_start_at') or not cal.get('coverage_end_at')):
                reason='verified_valuation_calendar_missing'
            else:
                sessions=cal.get('sessions',[])
                closes=[timestamp(s['close_at']) for s in sessions]
                dates=[s['date'] for s in sessions]
                for day in dates:date.fromisoformat(day)
                if closes!=sorted(set(closes)) or dates!=sorted(set(dates)):
                    raise ValueError('valuation sequence must be ordered and unique')
                # Completeness is an external attestation, not inferred from NAV rows/weekdays.
                start=timestamp(cal['coverage_start_at']);end=timestamp(cal['coverage_end_at'])
                if any(not start<=x<=end for x in closes):raise ValueError('session outside declared calendar coverage')
                if not start<=frozen<end:reason='calendar_does_not_cover_original_freeze'
                else:
                    candidates=[i for i,t in enumerate(closes) if t>frozen]
                    if not candidates:reason='first_close_after_freeze_not_yet_covered'
                    else:
                        origin=candidates[0];row['D0']=dates[origin]
                        if origin+c['horizon']>=len(sessions):reason='target_session_not_yet_covered'
                        else:
                            target=origin+c['horizon'];row['Dh']=dates[target]
                            row['calendar_qualification']='externally_reviewed_valuation_sequence'
                            if closes[target]>asof:reason='target_not_mature'
        if reason is None:
            labels=[nav.get((c['fund'],row[k])) for k in ('D0','Dh')]
            if any(r is None or r.get('nav') is None or r.get('nav')=='' for r in labels):
                reason='origin_or_target_nav_missing';row['status']='missing'
            else:
                eligible=True
                for r,close in zip(labels,(closes[origin],closes[target])):
                    if (not reviewed(r,asof) or not r.get('known_available_at') or not re.fullmatch('[0-9a-f]{64}',r.get('snapshot_sha256',''))
                            or r.get('snapshot_kind') not in ('raw_http','tool_extracted_text','structured_summary','captured_object')):
                        eligible=False;break
                    if not max(timestamp(r['retrieved_at']),close)<=timestamp(r['known_available_at'])<=timestamp(r['reviewed_at']):
                        eligible=False;break
                if not eligible:reason='nav_evidence_or_actual_availability_unqualified';row['status']='missing'
                else:
                    row['actual_return']=str(number(labels[1]['nav'])/number(labels[0]['nav'])-1)
                    row['status']='mature_missing_prediction' if c['numeric_forecast']['p_up'] is None and c['numeric_forecast']['q10'] is None else 'scored'
        row['reason']=reason
        row['numeric_scores']=score_numeric(c['numeric_forecast'],row['actual_return'],card_id=c['id'],
            target=row['Dh'],as_of=as_of,missing_reason=reason)
        tape.append(row)
    return {'status':'evaluation_attachment','as_of':as_of,'actual_evaluated_at':now(),
        'original_pending_record_unchanged':True,'original_freeze_rule':'first externally verified valuation close strictly after original freeze; Dh is h subsequent valuation sessions',
        'source_scope':'external review of already captured object; no historical publication time inferred',
        'information_cutoff_qualification':'not established by this binding; known-before-freeze is a separate scope',
        'review_flags_are_external_attestations':True,'independent_oos':False,'trading_authorized':False,
        'profitability_improved':False,'tape':tape,'numeric_metrics':summarize_numeric(tape),
        'numeric_metrics_by_card':{r['card_id']:summarize_numeric([r]) for r in tape},
        'limitations':['No network verification or publication-time reconstruction',
            'Original freeze attestation and sequence completeness require independent review',
            'Appended NAV labels never feed back into frozen numerical forecasts',
            'This attachment does not change pending custody receipt or old strict score eligibility',
            'Repeated maturity checks do not create new forecasts or reset candidate budgets']}


def run(pending,binding_path,binding_sha256,as_of,output):
    raw=Path(binding_path).read_bytes()
    if digest(raw)!=binding_sha256:raise ValueError('evaluation attachment hash mismatch')
    binding=json.loads(raw);result=evaluate(pending,binding,as_of)
    out=private_dir(output)
    (out/'binding.json').write_bytes(raw);(out/'binding.json').chmod(0o400)
    write_json(out/'results.json',result)
    write_json(out/'manifest.json',{'pending_sha256':binding['pending_sha256'],'binding_sha256':digest(raw),
        'results_sha256':digest((out/'results.json').read_bytes()),'actual_created_at':now(),
        'original_pending_record_unchanged':True,'trading_authorized':False})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('pending','binding','binding-sha256','as-of','output'):parser.add_argument('--'+key,required=True)
    a=parser.parse_args();run(a.pending,a.binding,a.binding_sha256,a.as_of,a.output)
    print('Separate evaluation attachment saved; unready cards retain null losses.')


if __name__=='__main__':main()
