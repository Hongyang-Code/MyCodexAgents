"""Offline, explicitly retrospective research batch. No network or real orders.

Usage: PYTHONPATH=FundPilot python -m fundpilot.history_batch --input INPUT.json
       --protocol PROTOCOL.json --protocol-sha256 HASH --output NEW_PRIVATE_DIR
Input evidence attestations must be reviewed independently; this CLI verifies
bytes and schema, not historical publication truth, permissions or source truth.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, localcontext
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import statistics
import subprocess
import zipfile

MODELS = ('abstain', 'persistence', 'trend20')
STRATEGIES = ('buy_hold', 'installments', 'monthly_rebalance', 'trend20')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('timezone required')
    return result


def positive(value):
    if isinstance(value, bool):
        raise ValueError('boolean is not a price')
    n = Decimal(str(value))
    if not n.is_finite() or n <= 0 or n.adjusted() > 12 or n.adjusted() < -12:
        raise ValueError('finite positive bounded number required')
    return n


def safe_path(root, name):
    rel = PurePosixPath(name)
    if not name or rel.is_absolute() or '..' in rel.parts or '\\' in name:
        raise ValueError('unsafe evidence path')
    path = root / name
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('symlink forbidden')
    if not path.is_file() or path.stat().st_size > 20_000_000:
        raise ValueError('missing or oversized evidence')
    return path


def protocol_check(p):
    """Fixed model/scenario family; dates/identities may vary for synthetic tests."""
    if p.get('version') != 2 or p.get('retrospective') is not True:
        raise ValueError('frozen retrospective v2 protocol required')
    expected = {'models': list(MODELS), 'horizons': [1,5,20],
                'information_lags': [1,3,5], 'settlement_lags': [1,3], 'cost_bps': [0,20,100]}
    for k, v in expected.items():
        if p.get(k) != v:
            raise ValueError('protocol family mismatch: '+k)
    if p.get('initial_cash') != 10000 or len(p.get('installment_dates', [])) != 6:
        raise ValueError('fixed closed budget and six installments required')
    starts = [date.fromisoformat(p[k]) for k in ('analysis_start','validation_end','test_start','analysis_end')]
    if not starts[0] <= starts[1] < starts[2] <= starts[3]:
        raise ValueError('invalid chronological splits')
    dates = p['installment_dates']
    if sorted(set(dates)) != dates or any(not starts[0] <= date.fromisoformat(d) <= starts[3] for d in dates):
        raise ValueError('installments outside analysis window')
    timestamp(p['vintage_evidence_cutoff'])
    timestamp(p['original_information_cutoff'])
    timestamp(p['recorded_at'])
    if len(set(p['instruments'])) != len(p['instruments']) or not p['instruments']:
        raise ValueError('unique registered instruments required')


def load_input(path, protocol):
    path = Path(path).absolute()
    safe_path(path.parent, path.name)
    config = json.loads(path.read_bytes())
    if config.get('schema_version') != 1 or type(config.get('synthetic')) is not bool:
        raise ValueError('input version and explicit synthetic flag required')
    if config.get('calendar_mode') != 'verified_open_sessions':
        raise ValueError('verified instrument open calendars required; no weekday fallback')
    blobs, sources = {}, {}
    for ref, item in config['files'].items():
        if not ref or not isinstance(ref, str):
            raise ValueError('evidence ID required')
        data = safe_path(path.parent, item['path']).read_bytes()
        if digest(data) != item['sha256']:
            raise ValueError('evidence hash mismatch: '+ref)
        retrieved = timestamp(item['retrieved_at'])
        if timestamp(item['known_available_at']) != retrieved:
            raise ValueError('do not backdate actual known time')
        if not item['source_url'].startswith('https://') or not item.get('license_note'):
            raise ValueError('source URL and use/license boundary required')
        blobs[ref], sources[ref] = data, item
    assets = {}
    for item in config['instruments']:
        code = item['instrument']
        if code in assets or code not in protocol['instruments']:
            raise ValueError('unregistered or duplicate instrument')
        for key in ('calendar_evidence','dealing_calendar_evidence','identity_evidence','channel_evidence','rules_evidence'):
            if item[key] not in blobs:
                raise ValueError('missing reviewed evidence: '+key)
        if item.get('calendar_reviewed') is not True or item.get('dealing_calendar_reviewed') is not True or item.get('public_ant_sale_and_product_open') is not True:
            raise ValueError('calendar/eligibility review missing')
        if not item.get('share_class') or not item.get('channel_limitations'):
            raise ValueError('share class and explicit unknown channel boundaries required')
        nav_ref, cal_ref = item['nav_file'], item['calendar_file']
        nav_reader = csv.DictReader(io.StringIO(blobs[nav_ref].decode('utf-8-sig')))
        if nav_reader.fieldnames != ['date','nav']:
            raise ValueError('NAV CSV fields must be date,nav')
        nav = {}
        for row in nav_reader:
            d = date.fromisoformat(row['date'])
            if d in nav:
                raise ValueError('duplicate NAV date; revisions must be resolved explicitly')
            nav[d] = positive(row['nav'])
        cal_reader = csv.DictReader(io.StringIO(blobs[cal_ref].decode('utf-8-sig')))
        if cal_reader.fieldnames != ['date']:
            raise ValueError('calendar CSV field must be date')
        sessions = [date.fromisoformat(row['date']) for row in cal_reader]
        if not sessions or sessions != sorted(set(sessions)):
            raise ValueError('calendar must be unique and sorted')
        if not nav or not set(nav).issubset(sessions):
            raise ValueError('NAV dates must belong to verified calendar')
        dealing_reader=csv.DictReader(io.StringIO(blobs[item['dealing_calendar_file']].decode('utf-8-sig')))
        if dealing_reader.fieldnames != ['date']:
            raise ValueError('dealing calendar CSV field must be date')
        dealing=[date.fromisoformat(row['date']) for row in dealing_reader]
        if not dealing or dealing != sorted(set(dealing)) or not set(dealing).issubset(sessions):
            raise ValueError('unique reviewed dealing days within valuation calendar required')
        if max(nav) > timestamp(sources[nav_ref]['retrieved_at']).date():
            raise ValueError('NAV after actual retrieval')
        a = dict(item, nav=nav, sessions=sessions, dealing_sessions=dealing, source=sources[nav_ref])
        if item.get('distribution_status') == 'verified_none':
            if item.get('distribution_evidence') not in blobs or item.get('no_split_reviewed') is not True:
                raise ValueError('distribution/split evidence missing')
            if date.fromisoformat(item['distribution_start']) > min(nav) or date.fromisoformat(item['distribution_end']) < date.fromisoformat(protocol['analysis_end']):
                raise ValueError('distribution review does not cover used history/window')
        assets[code] = a
    if set(assets) != set(protocol['instruments']):
        raise ValueError('registered universe missing; amend before comparing outcomes')
    return config, assets, blobs


def split_for(d, p):
    if d <= date.fromisoformat(p['validation_end']):
        return 'validation'
    return 'test'


def estimates(asset, origin, lag, model, horizon):
    """Features never read origin or future NAV; scoring happens separately."""
    sessions, nav = asset['sessions'], asset['nav']
    i = sessions.index(origin)
    j = i-lag
    if j < 0 or sessions[j] not in nav:
        return None, 'missing_visible_anchor'
    anchor = nav[sessions[j]]
    growth = 1.0
    if model == 'trend20':
        if j < 20 or any(d not in nav for d in sessions[j-20:j+1]):
            return None, 'missing_20_session_history'
        growth = float(anchor/nav[sessions[j-20]]) ** (1/20)
    decision_estimate = float(anchor) * growth**lag
    target_estimate = decision_estimate * growth**horizon
    if not all(math.isfinite(x) and x > 0 for x in (decision_estimate,target_estimate)):
        return None, 'invalid_numeric_forecast'
    return {'anchor_date':sessions[j].isoformat(), 'anchor_nav':float(anchor),
            'assumed_available_at':datetime.combine(origin,time(21,30),timezone(timedelta(hours=8))).isoformat(),
            'decision_level_estimate':decision_estimate,'target_level_estimate':target_estimate,
            'predicted_return':target_estimate/decision_estimate-1}, None


def forecast_tape(assets, p):
    start, end = (date.fromisoformat(p[k]) for k in ('analysis_start','analysis_end'))
    cutoff = timestamp(p['vintage_evidence_cutoff'])
    tape = []
    for code, a in assets.items():
        sessions, nav = a['sessions'], a['nav']
        for i, origin in enumerate(sessions):
            if not start <= origin <= end:
                continue
            for lag in p['information_lags']:
                for h in p['horizons']:
                    target = sessions[i+h] if i+h < len(sessions) else None
                    for model in MODELS:
                        row = {'instrument':code,'share_class':a['share_class'], 'origin':origin.isoformat(),
                            'origin_index':i,'target':target.isoformat() if target else None,
                            'horizon':h,'information_lag':lag,'model':model,'split':split_for(origin,p),
                            'retrospective':True,'basis':'raw_nav','retrieved_at':a['source']['retrieved_at'],
                            'known_available_at':a['source']['known_available_at'],
                            'source_sha256':a['source']['sha256'],'status':'unscored','reason':None,
                            'feature_status':'abstain' if model=='abstain' else 'ready',
                            'ex_post_eligible':False,'cutoff_known_eligible':False,
                            'probability':None,'calibration':'not_applicable_no_probability'}
                        if model != 'abstain':
                            est, reason = estimates(a,origin,lag,model,h)
                            if est:
                                row.update(est)
                            else:
                                row.update(feature_status='missing',feature_reason=reason)
                        if target is None:
                            row.update(status='pending',reason='target_calendar_unavailable')
                        elif target > end:
                            row.update(status='pending',reason='target_after_observation_window')
                        elif row['split']=='validation' and target > date.fromisoformat(p['validation_end']):
                            row.update(status='purged',reason='label_crosses_split_boundary')
                        elif model == 'abstain':
                            row.update(status='abstain',reason='registered_abstention')
                        elif row['feature_status']=='missing':
                            row.update(status='missing',reason=row['feature_reason'])
                        elif origin not in nav or target not in nav:
                            row.update(status='missing',reason='missing_scoring_nav')
                        else:
                            actual = float(nav[target]/nav[origin]-1)
                            assumed_target_index = i+h+lag
                            assumed_target = sessions[assumed_target_index] if assumed_target_index < len(sessions) else None
                            row.update(status='scored',actual_origin_nav=float(nav[origin]),actual_target_nav=float(nav[target]),
                                actual_return=actual,level_error=row['target_level_estimate']-float(nav[target]),
                                return_error=row['predicted_return']-actual,ex_post_eligible=True,
                                cutoff_known_eligible=(timestamp(row['known_available_at'])<=cutoff and assumed_target is not None
                                    and assumed_target < cutoff.date()),
                                assumed_target_available_date=assumed_target.isoformat() if assumed_target else None)
                        tape.append(row)
    return tape


def metrics(tape):
    groups = {}
    for row in tape:
        key = tuple(row[k] for k in ('instrument','horizon','information_lag','model','split'))
        groups.setdefault(key,[]).append(row)
    result=[]
    sign=lambda x: (x>1e-12)-(x < -1e-12)
    for key, rows in groups.items():
        for scope in ('ex_post','cutoff_known'):
            valid=[r for r in rows if r.get(scope+'_eligible')]
            nonoverlap=[]
            next_index=-1
            for row in sorted(valid,key=lambda r:r['origin_index']):
                if row['origin_index']>=next_index:
                    nonoverlap.append(row);next_index=row['origin_index']+key[1]
            for sample, selected in (('all_overlapping',valid),('fixed_nonoverlap',nonoverlap)):
                item=dict(zip(('instrument','horizon','information_lag','model','split'),key))
                item.update(scope=scope,sample=sample,n=len(selected),total_origins=len(rows),
                    sample_origins_sha256=digest(','.join(r['origin'] for r in selected).encode()),
                    status_counts={s:sum(r['status']==s for r in rows) for s in ('scored','pending','purged','missing','abstain')},
                    level_mae=None,level_rmse=None,return_mae=None,direction_accuracy=None,
                    directional_call_count=0,directional_hit_rate=None,
                    probability_calibration=None,confidence_interval=None,
                    uncertainty='No IID CI; nonoverlap is descriptive, not proof of independence.')
                if selected:
                    calls=[r for r in selected if sign(r['predicted_return'])!=0]
                    item.update(level_mae=statistics.mean(abs(r['level_error']) for r in selected),
                        level_rmse=math.sqrt(statistics.mean(r['level_error']**2 for r in selected)),
                        return_mae=statistics.mean(abs(r['return_error']) for r in selected),
                        direction_accuracy=statistics.mean(sign(r['predicted_return'])==sign(r['actual_return']) for r in selected),
                        directional_call_count=len(calls),
                        directional_hit_rate=statistics.mean(sign(r['predicted_return'])==sign(r['actual_return']) for r in calls) if calls else None)
                result.append(item)
    return result


def simulate(assets,p,strategy,information_lag,settlement_lag,cost_bps):
    """Closed synthetic pool with future-price orders and delayed resource release."""
    if strategy not in STRATEGIES:
        raise ValueError('unknown strategy')
    if any(a.get('distribution_status')!='verified_none' for a in assets.values()):
        raise ValueError('strategies require reviewed no-distribution/no-split coverage')
    common=sorted(set.intersection(*(set(a['dealing_sessions']) for a in assets.values())))
    start,end=(date.fromisoformat(p[k]) for k in ('analysis_start','analysis_end'))
    days=[d for d in common if start<=d<=end]
    valuation_days=sorted(set.union(*(set(a['sessions']) for a in assets.values())))
    valuation_days=[d for d in valuation_days if start<=d<=end]
    if not days or common[-1]<=end:
        raise ValueError('common calendar needs analysis and future pricing/settlement coverage')
    if len(common)-common.index(days[-1])-1 < settlement_lag+1:
        raise ValueError('insufficient future settlement calendar')
    for a in assets.values():
        if any(d not in a['nav'] for d in a['sessions'] if start<=d<=end):
            raise ValueError('missing expected valuation-session NAV; no strategy forward fill')
    D=Decimal
    fee=D(cost_bps)/10000
    cash=D(str(p['initial_cash']))
    holdings={c:D(0) for c in assets}
    orders=[];pending=[];trades=[];daily=[];seq=0;fees=D(0)
    installment_days={}
    for due in p['installment_dates']:
        d=next((x for x in days if x>=date.fromisoformat(due)),None)
        if d is not None: installment_days[d]=installment_days.get(d,0)+1
    previous_month=None;previous_signals=None
    def emit(d,event,**kw):
        trades.append(dict(date=d.isoformat(),event=event,**kw))
    def state(d):
        reserved_cash=sum((o['budget'] for o in orders if o['side']=='buy'),D(0))
        reserved_units={c:sum((o['units'] for o in orders if o['side']=='sell' and o['code']==c),D(0)) for c in assets}
        pending_units={c:sum((o['units'] for o in pending if o['side']=='buy' and o['code']==c),D(0)) for c in assets}
        receivables=sum((o['receivable'] for o in pending if o['side']=='sell'),D(0))
        marks={c:max(s for s in a['sessions'] if s<=d) for c,a in assets.items()}
        values={c:(holdings[c]+reserved_units[c]+pending_units[c])*a['nav'][marks[c]] for c,a in assets.items()}
        return cash+reserved_cash+receivables+sum(values.values()),reserved_cash,receivables,values,pending_units,reserved_units
    for d in valuation_days:
        # Prior requests use today's as-yet-unknown-at-submission NAV.
        for o in list(orders):
            if o['price_date']!=d: continue
            price=assets[o['code']]['nav'][d]
            if o['side']=='buy':
                net=o['budget']/(1+fee);charged=o['budget']-net
                o=dict(o,units=net/price)
            else:
                gross=o['units']*price;charged=gross*fee
                o=dict(o,receivable=gross-charged)
            fees+=charged
            pending.append(o)
            orders=[x for x in orders if x['id']!=o['id']]
            emit(d,'priced',order_id=o['id'],instrument=o['code'],side=o['side'],nav=str(price),
                 units=str(o['units']),fee=str(charged),settle_date=o['settle_date'].isoformat())
        for o in list(pending):
            if o['settle_date']!=d: continue
            if o['side']=='buy': holdings[o['code']]+=o['units']
            else: cash+=o['receivable']
            pending.remove(o)
            emit(d,'settled',order_id=o['id'],instrument=o['code'],side=o['side'],available_cash=str(cash))
        month=(d.year,d.month)
        signals={};marks={}
        for c,a in assets.items():
            if d not in common:
                continue
            est,reason=estimates(a,d,information_lag,'trend20' if strategy=='trend20' else 'persistence',1)
            if est:
                # Allocation marks also use only visible anchor, never decision-day NAV.
                marks[c]=D(str(est['anchor_nav']))
                signals[c]=est['predicted_return']>1e-12
            else: signals[c]=None
        due=(strategy=='buy_hold' and d==days[0]) or (strategy=='installments' and d in installment_days)
        due=due or (strategy=='monthly_rebalance' and month!=previous_month)
        due=due or (strategy=='trend20' and signals!=previous_signals)
        due=due and d in common
        if due:
            if len(marks)!=len(assets) or any(v is None for v in signals.values()):
                emit(d,'decision_skipped',reason='missing_assumed_visible_history')
            elif orders or pending:
                emit(d,'decision_skipped',reason='pending_orders_or_settlement')
            else:
                known_equity=cash+sum(holdings[c]*marks[c] for c in assets)
                n=D(len(assets));buy_budgets={};sell_units={}
                for c in assets:
                    if strategy=='installments':
                        buy_budgets[c]=D(str(p['initial_cash']))/6/n*installment_days[d]
                        continue
                    target=known_equity/n
                    if strategy=='trend20' and not signals[c]: target=D(0)
                    delta=target-holdings[c]*marks[c]
                    if delta>0: buy_budgets[c]=delta
                    elif delta<0: sell_units[c]=min(holdings[c],-delta/marks[c])
                desired=sum(buy_budgets.values(),D(0));scale=min(D(1),cash/desired) if desired else D(0)
                ci=common.index(d);price_date=common[ci+1];settle_date=common[ci+1+settlement_lag]
                for c in assets:
                    for side in ('sell','buy'):
                        amount=sell_units.get(c,D(0)) if side=='sell' else buy_budgets.get(c,D(0))*scale
                        if amount<=D('0.00000001'): continue
                        seq+=1
                        o=dict(id=seq,code=c,side=side,price_date=price_date,settle_date=settle_date)
                        if side=='buy': o['budget']=amount;cash-=amount
                        else: o['units']=amount;holdings[c]-=amount
                        orders.append(o)
                        emit(d,'submitted',order_id=seq,instrument=c,side=side,
                             budget=str(amount) if side=='buy' else None,units=str(amount) if side=='sell' else None,
                             assumed_visible_mark=str(marks[c]),price_date=price_date.isoformat(),settle_date=settle_date.isoformat())
                previous_signals=signals
        if d in common: previous_month=month
        equity,reserved,receivables,values,unconfirmed,locked=state(d)
        if cash < -D('1e-18') or any(x < 0 for x in holdings.values()):
            raise AssertionError('negative spendable resource')
        daily.append(dict(date=d.isoformat(),equity=str(equity),available_cash=str(cash),reserved_cash=str(reserved),
            valuation_dates={c:max(s for s in a['sessions'] if s<=d).isoformat() for c,a in assets.items()},
            common_dealing_session=d in common,
            receivables=str(receivables),holdings={c:str(x) for c,x in holdings.items()},
            pending_units={c:str(x) for c,x in unconfirmed.items()},reserved_units={c:str(x) for c,x in locked.items()},
            values={c:str(x) for c,x in values.items()},fees_paid=str(fees),pending_orders=len(orders)+len(pending)))
    # Last common date may precede each fund's own latest session; disclose and mark separately.
    terminal_dates={c:max(s for s in a['sessions'] if s<=end) for c,a in assets.items()}
    last=daily[-1]
    terminal=cash+D(last['reserved_cash'])+D(last['receivables'])
    for c,a in assets.items():
        if terminal_dates[c] not in a['nav']: raise ValueError('missing final instrument mark')
        units=holdings[c]+D(last['pending_units'][c])+D(last['reserved_units'][c])
        terminal+=units*a['nav'][terminal_dates[c]]
    # No extra orders or settlements outside common analysis sessions are inferred.
    peak=D(str(p['initial_cash']));mdd=D(0)
    for v in [D(r['equity']) for r in daily]+[terminal]:
        peak=max(peak,v);mdd=max(mdd,1-v/peak)
    split_returns={}
    previous=D(str(p['initial_cash']))
    for name,lo,hi in (('validation',start,date.fromisoformat(p['validation_end'])),
                       ('test',date.fromisoformat(p['test_start']),end)):
        selected=[r for r in daily if lo<=date.fromisoformat(r['date'])<=hi]
        if selected:
            final=D(selected[-1]['equity'])
            split_returns[name]={'start_carried_equity':str(previous),'end_equity':str(final),
                'return':float(final/previous-1),'new_cash':0,'last_valuation_date':selected[-1]['date']}
            previous=final
    return {'strategy':strategy,'information_lag':information_lag,'settlement_lag':settlement_lag,'cost_bps':cost_bps,
            'initial_cash':p['initial_cash'],'terminal_equity':str(terminal),'available_cash':str(cash),
            'reserved_cash':last['reserved_cash'],'receivables':last['receivables'],'fees_paid':str(fees),
            'return':float(terminal/D(str(p['initial_cash']))-1),'max_drawdown':float(mdd),
            'terminal_mark_dates':{c:d.isoformat() for c,d in terminal_dates.items()},
            'last_common_session':days[-1].isoformat(),'pending_orders':orders,'pending_settlements':pending,
            'split_returns':split_returns,
            'liquidatable_return':None,'execution_claim':'hypothetical_future_NAV_and_settlement_scenario',
            'transactions':trades,'daily_assets':daily}


def serial(x):
    if isinstance(x,(date,datetime)): return x.isoformat()
    if isinstance(x,Decimal): return str(x)
    raise TypeError(type(x).__name__)


def write_json(path,value):
    data=json.dumps(value,ensure_ascii=False,indent=2,default=serial,allow_nan=False).encode()
    path.write_bytes(data);path.chmod(0o600)


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False,default=serial) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    path.chmod(0o600)


def run(input_path,protocol_path,protocol_sha,output,predictions_only=False,supplement_path=None,supplement_sha=None):
    protocol_bytes=Path(protocol_path).read_bytes()
    if digest(protocol_bytes)!=protocol_sha: raise ValueError('frozen protocol hash mismatch')
    p=json.loads(protocol_bytes);protocol_check(p)
    config,assets,blobs=load_input(input_path,p)
    supplement_bytes=None
    if supplement_path:
        supplement_bytes=Path(supplement_path).read_bytes()
        if digest(supplement_bytes)!=supplement_sha or json.loads(supplement_bytes).get('supplement_to_sha256')!=protocol_sha:
            raise ValueError('calendar supplement hash/link mismatch')
    elif not config['synthetic']:
        raise ValueError('real batch requires frozen calendar supplement')
    output=Path(output).absolute()
    repo=Path(__file__).resolve().parents[2]
    if output==repo or repo in output.parents or any(x.is_symlink() for x in (output,*output.parents)):
        raise ValueError('output must be outside checkout with no symlinks')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    # Persist immutable inputs before calculations. Failures leave auditable partial output.
    (output/'protocol.json').write_bytes(protocol_bytes);(output/'protocol.json').chmod(0o600)
    if supplement_bytes:
        (output/'protocol-calendar-supplement.json').write_bytes(supplement_bytes)
        (output/'protocol-calendar-supplement.json').chmod(0o600)
    write_json(output/'input-manifest.json',config)
    replay=json.loads(json.dumps(config))
    for item in replay['files'].values(): item['path']='evidence/'+item['sha256']
    write_json(output/'replay-input.json',replay)
    raw=output/'evidence';raw.mkdir(mode=0o700)
    for ref,data in blobs.items():
        target=raw/digest(data);target.write_bytes(data);target.chmod(0o600)
    try:
        git_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
        dirty=bool(subprocess.check_output(['git','status','--porcelain','--','FundPilot'],cwd=repo,text=True))
    except (OSError,subprocess.CalledProcessError): git_sha=None;dirty=None
    source_hashes={str(f.relative_to(repo)):digest(f.read_bytes()) for f in (repo/'FundPilot/fundpilot').glob('*.py')}
    source_root=output/'source';source_root.mkdir(mode=0o700)
    (source_root/'FundPilot').mkdir(mode=0o700)
    source_dir=source_root/'FundPilot/fundpilot';source_dir.mkdir(mode=0o700)
    for f in (repo/'FundPilot/fundpilot').glob('*.py'):
        target=source_dir/f.name;target.write_bytes(f.read_bytes());target.chmod(0o600)
    provenance={'commit':git_sha,'working_tree_dirty':dirty,'source_sha256':source_hashes,
        'protocol_sha256':protocol_sha,'supplement_sha256':supplement_sha,'created_at':datetime.now(timezone.utc).isoformat(),
        'synthetic':config['synthetic'],'retrospective':True,'production_enabled':False}
    write_json(output/'provenance.json',provenance)
    try:
        quality=[]
        for c,a in assets.items():
            missing=[d.isoformat() for d in a['sessions'] if min(a['nav'])<=d<=date.fromisoformat(p['analysis_end']) and d not in a['nav']]
            quality.append(dict(instrument=c,rows=len(a['nav']),first=min(a['nav']).isoformat(),last=max(a['nav']).isoformat(),
                missing_sessions=missing,distribution_status=a.get('distribution_status','unknown'),
                historical_publication_time='unknown',revision_history='unknown_current_vintage',
                retrieved_at=a['source']['retrieved_at'],known_available_at=a['source']['known_available_at'],
                retrieved_after_vintage_cutoff=timestamp(a['source']['retrieved_at'])>timestamp(p['vintage_evidence_cutoff']),
                channel_limitations=a['channel_limitations']))
        write_json(output/'data-quality.json',quality)
        tape=forecast_tape(assets,p)
        frozen_keys=('instrument','share_class','origin','origin_index','target','horizon','information_lag','model',
            'split','retrospective','basis','retrieved_at','known_available_at','source_sha256','feature_status',
            'feature_reason','anchor_date','anchor_nav','assumed_available_at','decision_level_estimate',
            'target_level_estimate','predicted_return','probability','calibration')
        write_json(output/'frozen-predictions.json',[{k:r[k] for k in frozen_keys if k in r} for r in tape])
        write_json(output/'predictions.json',tape);write_csv(output/'predictions.csv',tape)
        stats=metrics(tape);write_json(output/'metrics.json',stats);write_csv(output/'metrics.csv',stats)
        summaries=[]
        if not predictions_only:
            for strategy in STRATEGIES:
                for lag in p['information_lags']:
                    for settlement in p['settlement_lags']:
                        for cost in p['cost_bps']:
                            with localcontext() as ctx:
                                ctx.prec=40
                                result=simulate(assets,p,strategy,lag,settlement,cost)
                            name=f'{strategy}-lag{lag}-settle{settlement}-cost{cost}'
                            write_json(output/(name+'-transactions.json'),result.pop('transactions'))
                            write_json(output/(name+'-daily-assets.json'),result.pop('daily_assets'))
                            summaries.append(result)
        baselines={(s['information_lag'],s['settlement_lag'],s['cost_bps']):s for s in summaries if s['strategy']=='buy_hold'}
        for s in summaries:
            base=baselines[(s['information_lag'],s['settlement_lag'],s['cost_bps'])]
            s['excess_return_vs_buy_hold']=s['return']-base['return']
        write_json(output/'strategies.json',summaries);write_csv(output/'strategies.csv',summaries)
        experiences=[]
        for code in assets:
            for h in p['horizons']:
                support=[];counter=[]
                for lag in p['information_lags']:
                    pair={r['model']:r for r in stats if r['instrument']==code and r['horizon']==h and r['information_lag']==lag
                        and r['split']=='test' and r['scope']=='ex_post' and r['sample']=='fixed_nonoverlap'}
                    x,y=pair.get('trend20'),pair.get('persistence')
                    if x and y and x['n'] and x['sample_origins_sha256']==y['sample_origins_sha256']:
                        item={'lag':lag,'n_nonoverlap':x['n'],'trend_mae':x['level_mae'],'persistence_mae':y['level_mae']}
                        (support if x['level_mae']<y['level_mae'] else counter).append(item)
                experiences.append(dict(instrument=code,horizon=h,hypothesis='Fixed trend20 improves level MAE over persistence',
                    status='candidate_only',support=support,counterexamples=counter,
                    independent_sample_count=None,overlap_limit='Nonoverlapping targets remain temporally dependent; unequal eligible samples are not compared.',
                    applicability='This frozen fund/window/current vintage only; not personalized',
                    invalidation='Failure in future frozen out-of-sample data, revised source, fees or channel constraints',
                    conclusion='未证明稳定优势；禁止自动升级为交易规则'))
        for strategy in STRATEGIES[1:]:
            rows=[s for s in summaries if s['strategy']==strategy]
            experiences.append(dict(strategy=strategy,hypothesis='Exceeds buy-and-hold under the identical scenario',
                status='candidate_only',support=[{k:s[k] for k in ('information_lag','settlement_lag','cost_bps','excess_return_vs_buy_hold')}
                    for s in rows if s['excess_return_vs_buy_hold']>0],
                counterexamples=[{k:s[k] for k in ('information_lag','settlement_lag','cost_bps','excess_return_vs_buy_hold')}
                    for s in rows if s['excess_return_vs_buy_hold']<=0],
                independent_sample_count=None,overlap_limit='All scenarios share one window; 18 scenarios are not 18 independent samples.',
                applicability='Frozen universe, synthetic budget and execution assumptions only',
                invalidation='Fails in forward data, actual fees, dealing limits or longer settlement delays',
                conclusion='未证明稳定优势；禁止自动升级为交易规则'))
        write_json(output/'experience-candidates.json',experiences)
        write_json(output/'data-dictionary.json',{
            'prediction_basis':'raw_nav; no dividend-adjusted prediction claim',
            'actual_return':'target NAV / decision-day NAV - 1; scoring only',
            'predicted_return':'estimated target level / independently estimated decision level - 1',
            'ex_post':'matured within observation window, current-vintage NAV; not historical availability proof',
            'cutoff_known':'ex-post eligible AND actual retrieval <= evidence cutoff AND assumed target availability date strictly before cutoff date; deliberately excludes same-day uncertain publication',
            'assumed_available_at':'feature-view hypothetical decision timestamp; not verified source publication time',
            'no_distribution':'reviewer attestation with hashed evidence, not automatically verified',
            'strategy_equity':'book wealth, includes pending/frozen assets; not liquidatable cash',
            'strategy_scenarios':'all 72 predeclared scenarios, no selection of winner',
            'source_bytes':'evidence/{sha256}; source URL/time/license retained in input-manifest.json'})
        best=[]
        for c in assets:
            selected=[r for r in stats if r['instrument']==c and r['model']=='persistence' and r['horizon']==1 and r['information_lag']==1 and r['split']=='test' and r['scope']=='ex_post' and r['sample']=='all_overlapping']
            if selected: best.append(f"- {c}：固定水平不变模型，1日目标/1日假设延迟，测试集有效样本 {selected[0]['n']}；MAE {selected[0]['level_mae']}。")
        report=('合成验证批次，不能解释为市场研究。\n\n' if config['synthetic'] else '当前版本历史数据的回顾性研究，不是严格历史可得回测。\n\n')
        report+=f"观察窗口：{p['analysis_start']}—{p['analysis_end']}。原资料截止：{p['original_information_cutoff']}；修订取证截止：{p['vintage_evidence_cutoff']}。\n\n"
        report+='\n'.join(best)+'\n\n'
        report+=f'完整预测记录 {len(tape)} 条；固定策略情景 {len(summaries)} 个。全部结果均已保存，不按收益择优报告。\n\n'
        for strategy in STRATEGIES:
            rows=[s for s in summaries if s['strategy']==strategy]
            if rows:
                report+=f"- {strategy}：18个共同情景的账面收益范围 {min(s['return'] for s in rows):.4%} 至 {max(s['return'] for s in rows):.4%}。范围是敏感性结果，不是概率区间。\n"
        report+='\n'
        report+='信息延迟1/3/5日是假设，不能证明QDII真实披露时间；当前数据可能晚于取证截止，详见质量记录。事后评分与截止已知评分分别输出。5/20日期限存在重叠，非重叠子样本也不保证独立，不提供独立同分布置信区间或无依据概率校准。\n\n'
        report+='策略使用封闭合成初始资金、下一共同开放日未知净值计价、延迟确认/到账和双边成本压力情景。无强制期末卖出，终值包括冻结/未到账资产，现金单列。费用不是支付宝实际报价。历史渠道状态、限购、产品取整仍未知，不能声称可执行收益。\n\n'
        report+='本批次未证明稳定预测或交易优势。经验只保留候选及反例，不升级规则。缺分红证据时只允许净值水平预测诊断，策略比较失败关闭。没有真实交易、通知或正式定时任务。\n'
        (output/'report.txt').write_text(report,encoding='utf-8');(output/'report.txt').chmod(0o600)
        write_json(output/'run-status.json',{'status':'completed','market_result':not config['synthetic'],
            'predictions_only':predictions_only,'strategy_scenarios':len(summaries),'proven_efficacy':False})
    except Exception as exc:
        write_json(output/'run-status.json',{'status':'failed','error':str(exc),'proven_efficacy':False})
        raise
    members={str(f.relative_to(output)):digest(f.read_bytes()) for f in output.rglob('*') if f.is_file()}
    write_json(output/'audit-manifest.json',members)
    archive=output/'audit.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(output.rglob('*')):
            if f.is_file() and f!=archive: z.write(f,str(f.relative_to(output)))
    archive.chmod(0o600)
    with zipfile.ZipFile(archive) as z:
        for name,sha in members.items():
            if digest(z.read(name))!=sha: raise AssertionError('archive readback mismatch')
    return {'output':str(output),'archive':str(archive),'archive_sha256':digest(archive.read_bytes()),
            'predictions':len(tape),'strategy_scenarios':len(summaries),'synthetic':config['synthetic']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('input','protocol','protocol-sha256','output'): parser.add_argument('--'+arg,required=True)
    parser.add_argument('--predictions-only',action='store_true',help='raw NAV diagnostics; no strategy comparison')
    parser.add_argument('--supplement');parser.add_argument('--supplement-sha256')
    args=parser.parse_args()
    print(json.dumps(run(args.input,args.protocol,args.protocol_sha256,args.output,args.predictions_only,args.supplement,args.supplement_sha256),ensure_ascii=False))


if __name__=='__main__': main()
