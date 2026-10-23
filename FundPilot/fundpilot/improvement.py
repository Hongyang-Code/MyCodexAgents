"""Explicit retrospective candidate review; never grants production promotion."""
from datetime import date
from decimal import Decimal
import hashlib
import json

CANDIDATE = 'trend20_weekly'
CONTEXT = 'reused_development'


def load_protocol(path, sha):
    from pathlib import Path
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('improvement protocol hash mismatch')
    p = json.loads(raw)
    expected = {'iteration': 1, 'candidate': CANDIDATE, 'evaluation_role': CONTEXT,
                'independent_oos': False, 'prior_prediction_and_strategy_outcomes_seen': True,
                'status': 'frozen_for_implementation',
                'budget': {'new_candidate_count': 1, 'new_scenario_count': 18, 'parameter_search': False}}
    if any(p.get(k) != v for k, v in expected.items()):
        raise ValueError('unsupported improvement protocol or evaluation context')
    for k in ('frozen_at', 'registration_boundary', 'one_change', 'calendar_definition',
              'blocked_checkpoint', 'sign_semantics', 'acceptance', 'future_promotion'):
        if not isinstance(p.get(k), str) or not p[k].strip():
            raise ValueError('missing improvement protocol field: '+k)
    return raw


def checkpoints(days):
    """First supplied common dealing date per ISO year/week, including midweek start."""
    seen = set(); result = set()
    for d in sorted(days):
        week = d.isocalendar()[:2]
        if week not in seen:
            result.add(d); seen.add(week)
    return result


def mechanism(result):
    trades = result['transactions']; daily = result['daily_assets']
    if isinstance(trades, dict): trades = trades['records']
    priced = [r for r in trades if r['event'] == 'priced']
    turnover = sum((abs(Decimal(r['units'])*Decimal(r['nav'])) for r in priced), Decimal(0))
    exposure = [sum(Decimal(v) for v in r['values'].values()) / Decimal(r['equity']) for r in daily]
    nonrisk = [(Decimal(r['available_cash'])+Decimal(r['reserved_cash'])+Decimal(r['receivables']))/Decimal(r['equity']) for r in daily]
    return dict(priced_buy_count=sum(r['side']=='buy' for r in priced),
                priced_sell_count=sum(r['side']=='sell' for r in priced),
                gross_absolute_priced_turnover=str(turnover),
                turnover_over_initial_cash=str(turnover/Decimal(str(result['initial_cash']))),
                mean_risky_exposure=str(sum(exposure)/len(exposure)),
                risky_exposure_day_count=sum(x>0 for x in exposure),
                mean_nonrisk_fraction=str(sum(nonrisk)/len(nonrisk)))


def paired_results(summaries):
    keys = ('information_lag','settlement_lag','cost_bps')
    daily = {tuple(r[k] for k in keys):r for r in summaries if r['strategy']=='trend20'}
    fields = ('priced_buy_count','priced_sell_count','gross_absolute_priced_turnover','fees_paid',
              'terminal_equity','max_drawdown','available_cash','reserved_cash','receivables',
              'mean_risky_exposure','risky_exposure_day_count','mean_nonrisk_fraction','return')
    pairs=[]
    for w in summaries:
        if w['strategy']!=CANDIDATE: continue
        d=daily[tuple(w[k] for k in keys)]
        pairs.append(dict(**{k:w[k] for k in keys}, comparator='trend20',candidate=CANDIDATE,
            daily={k:d[k] for k in fields},weekly={k:w[k] for k in fields},
            weekly_minus_daily={k:str(Decimal(str(w[k]))-Decimal(str(d[k]))) for k in fields},
            pending_states={'daily':{k:d[k] for k in ('pending_orders','pending_settlements')},
                            'weekly':{k:w[k] for k in ('pending_orders','pending_settlements')}},
            split_values_for_descriptive_diagnostics_only={'daily':d['split_returns'],'weekly':w['split_returns']}))
    if len(pairs)!=18: raise ValueError('expected all 18 paired scenarios')
    counts={k:{label:sum((Decimal(r['weekly_minus_daily'][k])>0)-(Decimal(r['weekly_minus_daily'][k])<0)==sign for r in pairs)
                  for label,sign in (('decreased',-1),('equal',0),('increased',1))}
            for k in fields}
    return pairs,counts


def review_record(record):
    required=('issue_id','fact_evidence_refs','confirmed_causes','hypotheses','support','counterexamples',
              'counterexample_review','candidate_version','before_config','after_config','protocol_sha256',
              'data_role','acceptance_items','results','uncertainty','next_validation','same_sample_baseline')
    for k in required:
        if k not in record or record[k] is None:
            raise ValueError('missing experience field: '+k)
    for k in ('issue_id','fact_evidence_refs','counterexample_review','same_sample_baseline','next_validation'):
        if not record[k]: raise ValueError('empty experience field: '+k)
    if record.get('status')!='candidate_only' or record.get('evaluation_context')!=CONTEXT or record['data_role']!=CONTEXT:
        raise ValueError('reused development cannot promote experience or claim holdout')
    return True
