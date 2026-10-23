"""Offline frozen LLM-card scoring; does not generate LLM text or execute agents."""
import argparse
import csv
from datetime import date, datetime, timezone, timedelta
import hashlib
import io
import json
import re
from pathlib import Path

from .market import timestamp, number
from .iteration_control import RunBudget


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)


def private_dir(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    return path


def diagnostic_source_bound(source, cutoff, known):
    """Conservative date qualification, NOT historical availability or vintage proof."""
    if source.get('snapshot_kind') not in ('structured_summary', 'tool_extracted_text'):
        raise ValueError('diagnostic captured snapshot kind required')
    content = source.get('snapshot_content')
    if not isinstance(content, str) or not content.strip() or digest(content.encode('utf-8')) != source.get('snapshot_sha256'):
        raise ValueError('captured UTF-8 snapshot hash mismatch')
    if source.get('raw_sha256') is not None:
        raise ValueError('summary snapshot must not be called raw HTTP')
    if source.get('revision_status') != 'unknown':
        raise ValueError('diagnostic adapter preserves unverified revision status as unknown')
    if source.get('published_precision') == 'day' and source.get('timezone') == 'unknown':
        day = date.fromisoformat(source['published_date'])
        # Latest possible end of the given local day, using UTC-12.
        bound = datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc) + timedelta(hours=12)
        if bound >= cutoff or bound > known:
            raise ValueError('whole publication day not safely before cutoff/known time')
        return bound
    raise ValueError('diagnostic day precision/unknown timezone required; unknown publication is ineligible')


def diagnostic_labels(mode):
    if mode != 'retrospective_diagnostic':
        return {}
    return dict(source_time_qualification='limited', non_blind=True, non_oos=True,
                current_vintage=True, historical_revision_status='unknown',
                snapshot_hash_basis='captured_content_utf8_not_raw_http')


def validate(cards, sources, calendar):
    mode = cards['mode']
    if mode not in ('retrospective', 'retrospective_diagnostic', 'prospective', 'synthetic'):
        raise ValueError('explicit research mode required')
    if cards['producer'] != ('synthetic_fixture' if mode == 'synthetic' else 'actual_llm'):
        raise ValueError('real LLM attestation required; synthetic cannot impersonate LLM')
    cutoff = timestamp(cards['cutoff'])
    generated = timestamp(cards['generated_at'])
    if generated < cutoff or generated > timestamp(now()):
        raise ValueError('invalid actual generation time')
    if not cards.get('model_ref') or not cards.get('prompt_version'):
        raise ValueError('LLM/model and prompt reference required; unknown details explicit')
    if calendar.get('reviewed') is not True or not calendar.get('evidence_ref'):
        raise ValueError('verified valuation calendar required; no weekday inference')
    if len(sources) > 12 or len({s['id'] for s in sources}) != len(sources):
        raise ValueError('source cap or duplicate source')
    source_map = {}
    for s in sources:
        if s.get('reviewed') is not True or not s.get('url','').startswith('https://'):
            raise ValueError('reviewed public source required')
        if mode != 'retrospective_diagnostic' and not re.fullmatch('[0-9a-f]{64}',s.get('raw_sha256','')):
            raise ValueError('source hash required')
        known = timestamp(s['known_available_at'])
        if known < timestamp(s['retrieved_at']):
            raise ValueError('knowledge cannot predate retrieval')
        if mode == 'retrospective_diagnostic':
            source_map[s['id']] = diagnostic_source_bound(s, cutoff, known)
            continue
        published = timestamp(s['published_at'])
        if published > known:
            raise ValueError('publication after known availability')
        available = known
        if mode == 'retrospective':
            available = timestamp(s['assumed_available_at'])
            if available < published:
                raise ValueError('assumed availability precedes publication')
        if available > cutoff:
            raise ValueError('future evidence anywhere in shared source snapshot')
        source_map[s['id']] = available
    rows = cards['cards']
    if not 1 <= len(rows) <= 9 or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('one to nine unique cards required')
    funds = tuple(sorted({r['fund'] for r in rows}))
    horizons = tuple(sorted({r['horizon'] for r in rows}))
    _, status = RunBudget().reserve('shape-check', 'prediction_batch', funds=funds, horizons=horizons)
    if status != 'reserved':
        raise ValueError('batch shape exceeds research budget')
    seen = set()
    for c in rows:
        key = (c['fund'], c['origin'], c['horizon'])
        if key in seen:
            raise ValueError('duplicate fund/origin/horizon')
        seen.add(key)
        if c['direction'] not in ('up','flat','down','abstain'):
            raise ValueError('invalid unconditional direction')
        for field in ('reasoning','counterevidence','invalidation','gaps','scenarios'):
            if field not in c:
                raise ValueError('missing card field: '+field)
        if c['direction'] == 'abstain' and not c.get('abstention_reason'):
            raise ValueError('abstention reason required')
        if not c.get('source_ids'):
            raise ValueError('explicit source references required')
        if any(s not in source_map or source_map[s] > cutoff for s in c['source_ids']):
            raise ValueError('unknown or future card evidence')
        days = calendar['dates'][c['fund']]
        if days != sorted(set(days)):
            raise ValueError('calendar must be sorted and unique')
        for d in days: date.fromisoformat(d)
        local_cutoff_date = datetime.fromisoformat(cards['cutoff'].replace('Z', '+00:00')).date()
        following = [d for d in days if date.fromisoformat(d) > local_cutoff_date]
        if not following or c['origin'] != following[0]:
            raise ValueError('D0 must be first verified valuation date after local cutoff date')
    if len({c['origin'] for c in rows}) != 1:
        raise ValueError('single historical origin per batch')


def freeze(cards_path, sources_path, calendar_path, output):
    raw = {name: Path(path).read_bytes() for name,path in
           (('cards.json',cards_path),('sources.json',sources_path),('calendar.json',calendar_path))}
    cards,sources,calendar = [json.loads(raw[k]) for k in ('cards.json','sources.json','calendar.json')]
    validate(cards,sources,calendar)
    root = private_dir(output)
    for name,body in raw.items():
        (root/name).write_bytes(body); (root/name).chmod(0o600)
    receipt = {'frozen_at':now(),'hashes':{k:digest(v) for k,v in raw.items()},
               'truth_loaded_by_freeze':False,'producer_attestation_not_independently_verified':True, **diagnostic_labels(cards['mode'])}
    write_json(root/'receipt.json',receipt)
    return receipt


def score(frozen, nav_path, manifest_path, as_of, output):
    root = Path(frozen)
    receipt_raw = (root/'receipt.json').read_bytes()
    receipt = json.loads(receipt_raw)
    raw = {name:(root/name).read_bytes() for name in ('cards.json','sources.json','calendar.json')}
    if receipt['hashes'] != {k:digest(v) for k,v in raw.items()}:
        raise ValueError('frozen input hash mismatch')
    cards,sources,calendar = [json.loads(raw[k]) for k in ('cards.json','sources.json','calendar.json')]
    validate(cards,sources,calendar)
    asof = timestamp(as_of)
    if not timestamp(receipt['frozen_at']) <= asof <= timestamp(now()):
        raise ValueError('score time must follow actual freeze and not be future')
    if cards['mode']=='prospective' and any(date.fromisoformat(c['origin']) < timestamp(receipt['frozen_at']).date() for c in cards['cards']):
        raise ValueError('late freeze cannot claim prospective')
    nav_raw = Path(nav_path).read_bytes(); manifest_raw = Path(manifest_path).read_bytes()
    manifest = json.loads(manifest_raw)
    if (manifest.get('sha256') != digest(nav_raw) or manifest.get('reviewed') is not True
            or not manifest.get('reviewed_by') or not manifest.get('evidence_refs')):
        raise ValueError('reviewed NAV manifest and exact file hash required')
    nav = {}
    for r in csv.DictReader(io.StringIO(nav_raw.decode('utf-8-sig'))):
        key = (r['fund'],r['date'])
        date.fromisoformat(r['date'])
        if key in nav: raise ValueError('duplicate NAV')
        known = timestamp(r['known_available_at']); retrieved = timestamp(r['retrieved_at'])
        if known < retrieved: raise ValueError('NAV knowledge precedes retrieval')
        available = timestamp(r['assumed_available_at']) if cards['mode'] in ('retrospective','retrospective_diagnostic') else known
        if available.date() < date.fromisoformat(r['date']):
            raise ValueError('NAV feature availability precedes valuation date')
        nav[key] = dict(value=number(r['nav']) if r['nav'].strip() else None,known=known,available=available)
    cutoff=timestamp(cards['cutoff']); tape=[]
    direction=lambda change:'up' if change>0 else 'down' if change<0 else 'flat'
    for c in cards['cards']:
        days=calendar['dates'][c['fund']]; idx=days.index(c['origin']); end=idx+c['horizon']
        target=days[end] if end<len(days) else None
        row=dict(card_id=c['id'],fund=c['fund'],origin=c['origin'],horizon=c['horizon'],target=target,
                 llm_direction=c['direction'],status='pending',missing_reason=None,actual_direction=None,
                 nav_price_change=None,llm_hit=None,persistence_direction='flat',persistence_hit=None,
                 trend20_direction=None,trend20_hit=None,trend20_missing_reason=None,
                 scenario_status='not_scored_requires_separate_frozen_trigger_observations',
                 attribution={'status':'candidate_only','cause':'unknown','support':[],
                              'counterevidence':c['counterevidence']})
        # Baseline uses only qualified historical inputs; target/decision NAV never enters features.
        visible=[(d,nav[(c['fund'],d)]['value']) for d in days if d<=c['origin'] and (c['fund'],d) in nav
                 and nav[(c['fund'],d)]['value'] is not None and nav[(c['fund'],d)]['available']<=cutoff]
        baseline_days = days[max(0,days.index(visible[-1][0])-20):days.index(visible[-1][0])+1] if visible else []
        qualified = dict(visible)
        if len(baseline_days)==21 and all(d in qualified for d in baseline_days):
            row['trend20_direction']=direction(qualified[baseline_days[-1]]/qualified[baseline_days[0]]-1)
        else:row['trend20_missing_reason']='unsupported_missing_21_consecutive_qualified_valuation_observations'
        if target is None:row['missing_reason']='target_calendar_missing'
        elif date.fromisoformat(target)>asof.date():row['missing_reason']='target_not_mature'
        else:
            anchor=nav.get((c['fund'],c['origin'])); truth=nav.get((c['fund'],target))
            if any(r is None or r['value'] is None for r in (anchor,truth)):
                row.update(status='missing',missing_reason='origin_or_target_nav_missing')
            elif any(r['known']>asof for r in (anchor,truth)):
                row.update(status='missing',missing_reason='truth_not_known_at_scoring')
            else:
                actual=direction(truth['value']/anchor['value']-1)
                row.update(status='abstained' if c['direction']=='abstain' else 'scored',actual_direction=actual,
                           nav_price_change=str(truth['value']/anchor['value']-1),
                           llm_hit=None if c['direction']=='abstain' else c['direction']==actual,
                           persistence_hit=actual=='flat',trend20_hit=None if row['trend20_direction'] is None else row['trend20_direction']==actual)
                if row['llm_hit'] is False:
                    row['attribution']['support']=['frozen unconditional direction differs from observed NAV direction']
                    row['attribution']['possible_classes']=['source','timing','reasoning','unobserved_shock','normal_noise']
        row.update(diagnostic_labels(cards['mode']))
        tape.append(row)
    def metrics(rows):
        mature=[r for r in rows if r['actual_direction'] is not None]
        scored=[r for r in rows if r['status']=='scored']
        paired=[r for r in scored if r['trend20_hit'] is not None]
        return dict(total=len(rows),mature=len(mature),abstained=sum(r['status']=='abstained' for r in rows),
                    pending=sum(r['status']=='pending' for r in rows),missing=sum(r['status']=='missing' for r in rows),
                    scored=len(scored),coverage=len(scored)/len(mature) if mature else None,
                    abstention_rate=sum(r['status']=='abstained' for r in rows)/len(mature) if mature else None,
                    persistence_hits_same_llm_sample=sum(r['persistence_hit'] for r in scored),
                    llm_accuracy=sum(r['llm_hit'] for r in scored)/len(scored) if scored else None,
                    paired_ids=[r['card_id'] for r in paired],paired_n=len(paired),
                    paired_hits={k:sum(r[k] for r in paired) for k in ('llm_hit','persistence_hit','trend20_hit')},
                    actual_counts={d:sum(r['actual_direction']==d for r in mature) for d in ('up','flat','down')})
    result={'scope':'raw_nav_direction_research_not_total_return','mode':cards['mode'],
            'retrospective':cards['mode'] in ('retrospective','retrospective_diagnostic'),'llm_memory_contamination_possible':True,
            'returns_seen_by_broader_project':cards['mode'] in ('retrospective','retrospective_diagnostic'),'independent_oos':False,
            'investment_efficacy_proven':False,'scored_at':now(),'as_of':as_of,
            'metrics':metrics(tape),'by_fund_horizon':{r['card_id']:metrics([r]) for r in tape},'tape':tape,
            'improvement_proposals':[], 'limitations':['Source, calendar and LLM attestations require independent inspection',
                'Same-origin funds share market shocks; no independent-sample CI',
                'Historical assumed availability is not verified point-in-time knowledge',
                'No automatic promotion, trading or notification; conditional scenarios not counted as direction hits']}
    result.update(diagnostic_labels(cards['mode']))
    if any(r['llm_hit'] is False for r in tape):
        result['improvement_proposals']=[{'status':'candidate_only_not_registered_or_evaluated',
            'change_area':'research_prompt','one_change':'Add a pre-freeze opposing-evidence checklist',
            'hypothesis':'May expose unsupported directional reasoning; effect unproven',
            'support_ids':[r['card_id'] for r in tape if r['llm_hit'] is False],
            'counterexample_ids':[r['card_id'] for r in tape if r['llm_hit'] is True],
            'next_validation':'Separate frozen future comparison under controlled-iteration budget; retain stable version'}]
    for proposal in result['improvement_proposals']:
        proposal.update(diagnostic_labels(cards['mode']))
    out=private_dir(output)
    write_json(out/'results.json',result)
    write_json(out/'manifest.json',{'frozen_receipt_sha256':digest(receipt_raw),'frozen_inputs':receipt['hashes'],
        'nav_sha256':digest(nav_raw),'nav_manifest_sha256':digest(manifest_raw),
        'results_sha256':digest((out/'results.json').read_bytes()),'created_at':now(), **diagnostic_labels(cards['mode'])})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    f=sub.add_parser('freeze')
    for key in ('cards','sources','calendar','output'): f.add_argument('--'+key,required=True)
    s=sub.add_parser('score')
    for key in ('frozen','nav','nav-manifest','as-of','output'):s.add_argument('--'+key,required=True)
    a=p.parse_args()
    if a.command=='freeze':freeze(a.cards,a.sources,a.calendar,a.output)
    else:score(a.frozen,a.nav,a.nav_manifest,a.as_of,a.output)
    print('Private output written; no LLM generation, notification or trading performed.')


if __name__=='__main__':main()
