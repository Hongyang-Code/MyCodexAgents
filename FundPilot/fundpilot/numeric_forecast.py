"""Subjective research measurement only; no calibrated probability or trading claim."""
from datetime import date
from decimal import Decimal, InvalidOperation
from .research import Settlement, evaluate
from .market import timestamp

SCHEMA='research_numeric_v1'


def decimal(value):
    if isinstance(value,bool):raise ValueError('boolean is not a forecast')
    try:x=Decimal(str(value))
    except InvalidOperation as exc:raise ValueError('finite numeric forecast required') from exc
    if not x.is_finite():raise ValueError('finite numeric forecast required')
    return x


def validate_numeric(batch, card):
    schema=batch.get('numeric_schema')
    if schema is None:
        if 'numeric_forecast' in card:raise ValueError('numeric forecast requires new frozen batch schema')
        return
    if schema!=SCHEMA or batch.get('new_batch_no_backfill') is not True:
        raise ValueError('explicit new numeric batch required; never backfill old cards')
    n=card.get('numeric_forecast')
    if not isinstance(n,dict):raise ValueError('numeric record required, including explicit missing values')
    required={'unit':'raw_nav_return_fraction','event':'return_gt_zero','calibration_status':'subjective_uncalibrated','horizon':card['horizon']}
    if any(n.get(k)!=v for k,v in required.items()):raise ValueError('numeric unit/event/horizon/calibration mismatch')
    for k in ('p_up','q10','q50','q90'):
        if k not in n:raise ValueError('explicit numeric value or null required: '+k)
    if n['p_up'] is not None and not 0<=decimal(n['p_up'])<=1:raise ValueError('p_up outside [0,1]')
    qs=[n[k] for k in ('q10','q50','q90')]
    if any(v is None for v in qs) and not all(v is None for v in qs):raise ValueError('all three quantiles or all missing required')
    if qs[0] is not None:
        qs=list(map(decimal,qs))
        if qs!=sorted(qs) or qs[0]<-1:raise ValueError('ordered return quantiles >=-1 required')
    if (n['p_up'] is None or qs[0] is None) and not n.get('missing_reason'):
        raise ValueError('missing prediction reason required')


def score_numeric(n, actual_return, *, card_id, target, as_of, missing_reason):
    r={'forecast':n,'status':'pending_or_missing_label' if actual_return is None else 'mature',
       'label_missing_reason':missing_reason if actual_return is None else None,
       'brier':None,'constant_half_brier':None,'pinball':None,'zero_return_pinball':None,
       'interval_coverage':None,'zero_return_interval_coverage':None,'interval_width':None,
       'nominal_interval_coverage':'0.8','calibration_proven':False,'trading_authorized':False}
    if actual_return is None:return r
    y=decimal(actual_return)
    if n['p_up'] is not None:
        # Reuse existing scoring semantics: strictly positive NAV return, zero is not up.
        settled=Settlement(card_id,timestamp(as_of),'mature-nav-label',float(y),None,float(decimal(n['p_up'])),date.fromisoformat(target))
        r['brier']=evaluate([settled])['brier_score']
        baseline=Settlement(card_id,timestamp(as_of),'mature-nav-label',float(y),None,.5,date.fromisoformat(target))
        r['constant_half_brier']=evaluate([baseline])['brier_score']
    if n['q10'] is not None:
        def pinball(q,tau):
            error=y-q
            return str(tau*error if error>=0 else (tau-1)*error)
        qs=[decimal(n[k]) for k in ('q10','q50','q90')]
        r['pinball']={k:pinball(q,Decimal(t)) for k,q,t in zip(('q10','q50','q90'),qs,('.1','.5','.9'))}
        r['zero_return_pinball']={k:pinball(Decimal(0),Decimal(t)) for k,t in zip(('q10','q50','q90'),('.1','.5','.9'))}
        r['interval_coverage']=qs[0]<=y<=qs[2];r['zero_return_interval_coverage']=y==0
        r['interval_width']=str(qs[2]-qs[0])
    return r


def summarize_numeric(rows):
    values=[r['numeric_scores'] for r in rows]
    p=[v for v in values if v['brier'] is not None];q=[v for v in values if v['pinball'] is not None]
    mean=lambda xs: str(sum((decimal(x) for x in xs),Decimal(0))/len(xs)) if xs else None
    mature=[v for v in values if v['status']=='mature']
    return {'total':len(values),'mature_labels':len(mature),'probability_n':len(p),'quantile_n':len(q),
            'missing_probability_on_mature':sum(v['forecast']['p_up'] is None for v in mature),
            'missing_quantiles_on_mature':sum(v['forecast']['q10'] is None for v in mature),
            'pending_or_missing_labels':len(values)-len(mature),
            'probability_coverage':len(p)/len(mature) if mature else None,
            'quantile_coverage':len(q)/len(mature) if mature else None,
            'mean_brier':mean([v['brier'] for v in p]),
            'same_sample_constant_half_brier':mean([v['constant_half_brier'] for v in p]),
            'mean_pinball':{k:mean([v['pinball'][k] for v in q]) for k in ('q10','q50','q90')},
            'same_sample_zero_return_pinball':{k:mean([v['zero_return_pinball'][k] for v in q]) for k in ('q10','q50','q90')},
            'empirical_interval_coverage':sum(v['interval_coverage'] for v in q)/len(q) if q else None,
            'same_sample_zero_return_interval_coverage':sum(v['zero_return_interval_coverage'] for v in q)/len(q) if q else None,
            'mean_interval_width':mean([v['interval_width'] for v in q]),
            'baseline_definition':'Fixed p_up=0.5 and separate degenerate zero-return quantiles; no fitting or future inputs',
            'calibration_proven':False,'profitability_improved':False,'trading_authorized':False}
