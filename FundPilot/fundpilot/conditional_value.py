"""Read-only fixed-allocation retrospective NAV scenario, never event verification.

Separated from EventSimulator: unverified real rules must not become verified=True.
No orders, LLM generation, strategy search, account state or automatic promotion.
"""
import argparse
import csv
from datetime import date, datetime, timezone
from decimal import Decimal as D
import io
import json
from pathlib import Path
import re

from .market import number, timestamp
from .official_fees import validate_redemption_dates
from .llm_loop import digest, private_dir, write_json

SCOPE = {'mode':'retrospective_conditional', 'not_executable':True,
         'not_actual_fund_total_return':True, 'independent_oos':False,
         'current_vintage':True, 'llm_memory_contamination_possible':True,
         'returns_seen_by_broader_project':True, 'promotion':'retain_stable'}
ZERO = D(0)


def required_text(obj, key):
    if not isinstance(obj.get(key), str) or not obj[key].strip():
        raise ValueError('explicit text required: '+key)
    return obj[key]


def evaluate(protocol, decision, nav_raw, sources):
    p=protocol; a=p['assumptions']
    if p.get('mode')!='retrospective_conditional':
        raise ValueError('explicit retrospective_conditional mode required')
    if decision.get('decision_kind')!='explicit_llm_allocation' or decision.get('producer') not in ('actual_llm','synthetic_fixture'):
        raise ValueError('explicit LLM allocation required, not forecast directions')
    for key in ('rationale','no_action_counterfactual','cost_coverage_assessment','model_ref','prompt_version'):
        required_text(decision,key)
    frozen=timestamp(decision['frozen_at']); protocol_frozen=timestamp(p['frozen_at'])
    if frozen>protocol_frozen or protocol_frozen>datetime.now(timezone.utc):
        raise ValueError('actual decision freeze <= protocol freeze <= execution time required')
    cutoff=timestamp(decision['information_cutoff'])
    if cutoff>frozen:raise ValueError('information cutoff cannot follow actual freeze')
    if not decision.get('evidence_refs'):raise ValueError('decision evidence references required')
    funds=p['funds']
    if not isinstance(funds,list) or not 1<=len(funds)<=3 or len(set(funds))!=len(funds):
        raise ValueError('one to three unique fund/share-class identities required')
    dates=p['valuation_dates']
    if not dates or dates!=sorted(set(dates)) or len(dates)<2:
        raise ValueError('explicit ordered common valuation dates required')
    for day in dates:date.fromisoformat(day)
    if dates[0]!=p['entry_date'] or dates[-1]!=p['end_date']:
        raise ValueError('valuation dates must span exactly entry through end')
    if decision.get('entry_date')!=p['entry_date'] or decision.get('end_date')!=p['end_date']:
        raise ValueError('frozen decision and protocol holding window must match')
    local_cutoff=datetime.fromisoformat(decision['information_cutoff'].replace('Z','+00:00')).date()
    if date.fromisoformat(p['entry_date'])<=local_cutoff:
        raise ValueError('entry valuation date must follow information cutoff local date')
    required_text(p,'valuation_dates_evidence_ref')
    initial=number(p['initial_cash']); risk=p['risk']
    cap=number(risk['max_exposure']); max_dd=number(risk['max_drawdown'],positive=False)
    max_fees=number(risk['max_cash_fees'],positive=False)
    if cap>1 or max_dd>1 or risk.get('no_leverage') is not True:
        raise ValueError('fixed bounded risk limits and no leverage required')
    if set(decision['allocations'])!=set(funds):raise ValueError('all fund allocations explicit, including zero')
    alloc={f:number(decision['allocations'][f],positive=False) for f in funds}
    cash=number(decision['cash_amount'],positive=False)
    if sum(alloc.values(),cash)!=initial or sum(alloc.values())>initial*cap:
        raise ValueError('closed budget and initial exposure cap required; no normalization')
    if decision.get('initial_cash')!=p['initial_cash']:
        raise ValueError('decision and protocol initial cash must match exactly')
    if a.get('no_cash_distributions_and_no_splits') is not True:
        raise ValueError('explicit no-distribution/no-split scenario required')
    if a.get('entry_price_rule')!='entry_date_nav_hypothesis' or a.get('exit_price_rule')!='end_nav_same_price_hypothesis':
        raise ValueError('fixed price hypotheses required, not real execution prices')
    for key in ('fees','distributions','confirmation','receipt','channel'):
        if not p.get('unknown_evidence',{}).get(key):
            raise ValueError('explicit evidence limitation required: '+key)
    if p.get('known_distribution_events')!=[] or p.get('known_split_events')!=[]:
        raise ValueError('known events conflict with this scenario or event check missing')
    if set(a['costs'])!=set(funds) or set(a['entry_confirmation_dates'])!=set(funds) or set(a['exit_confirmation_dates'])!=set(funds):
        raise ValueError('cost and confirmation assumptions required for each fund')
    # Optional for compatibility: omission preserves unknown dates, never end_date.
    applications=a.get('exit_application_dates', {f:None for f in funds})
    if not isinstance(applications,dict) or set(applications)!=set(funds):
        raise ValueError('exit application dates required for exactly the frozen funds')
    rates={}; official={}; fee_coverage={}
    for f in funds:
        cost=a['costs'][f]
        if 'official_rule' in cost:
            from .official_fees import load_cost
            rule=load_cost(cost)
            ident=cost['identity']
            if f not in (ident['fund_code'], ident['fund_code']+':'+ident['share_class'],
                         ident['fund_code']+':'+ident['share_class']+':'+ident['currency']):
                raise ValueError('official fee assigned to a different fund')
            status=rule.check(cost['identity'],p['entry_date'],document_version_scenario=cost.get('document_version_scenario') is True)
            rule.check(cost['identity'],p['end_date'],document_version_scenario=cost.get('document_version_scenario') is True)
            official[f]=rule
            fee_coverage[f]={'version_status':status,'rule_sha256':rule.record['raw_sha256'],
                             'version':rule.record['version'],'published_on':rule.record['published_on'],
                             'effective_from':rule.record.get('effective_from'),'effective_until':rule.record.get('effective_until'),
                             'channel_discount':cost.get('discount'),'actual_channel_fee_verified':False}
        else:
            buy=number(cost['buy_rate'],positive=False);sell=number(cost['exit_rate'],positive=False)
            if buy>=1 or sell>=1 or cost.get('buy_fee_basis')!='net':
                raise ValueError('explicit fractional rates <1 and net buy-fee basis required')
            required_text(cost,'holding_period_condition')
            rates[f]=(buy,sell)
        application=applications[f]
        if application is not None and date.fromisoformat(application)!=date.fromisoformat(p['end_date']):
            raise ValueError('redemption application must match frozen exit NAV date')
        confirmed=a['entry_confirmation_dates'][f]
        validate_redemption_dates(confirmed, redemption_application=application,
                                  redemption_confirmation=a['exit_confirmation_dates'][f])
        if confirmed is not None and date.fromisoformat(confirmed)<date.fromisoformat(p['entry_date']):
            raise ValueError('assumed confirmation precedes entry')
        exit_confirmed=a['exit_confirmation_dates'][f]
        if exit_confirmed is not None:
            if date.fromisoformat(exit_confirmed)<date.fromisoformat(p['end_date']) or (confirmed is not None and exit_confirmed<confirmed):
                raise ValueError('assumed redemption confirmation precedes exit or subscription confirmation')
    if 'exit_receipt_date' not in a:raise ValueError('exit receipt assumption required, null means unknown')
    receipt=a['exit_receipt_date']
    if receipt is not None and date.fromisoformat(receipt)<=date.fromisoformat(p['end_date']):
        raise ValueError('hypothetical exit proceeds cannot be available at window end')
    if receipt is not None and any(d is not None and receipt<d for d in a['exit_confirmation_dates'].values()):
        raise ValueError('assumed receipt precedes redemption confirmation')
    holding_days={f:(date.fromisoformat(a['exit_confirmation_dates'][f])-date.fromisoformat(a['entry_confirmation_dates'][f])).days
                  if a['entry_confirmation_dates'][f] is not None and a['exit_confirmation_dates'][f] is not None else None for f in funds}
    source_map={}
    if not isinstance(sources,list) or not 1<=len(sources)<=12:raise ValueError('one to twelve source records required')
    for s in sources:
        sid=required_text(s,'id')
        if sid in source_map:raise ValueError('duplicate source ID')
        if not required_text(s,'url').startswith('https://'):raise ValueError('public HTTPS source required')
        if not re.fullmatch('[0-9a-f]{64}',required_text(s,'snapshot_sha256')):
            raise ValueError('captured source SHA256 required')
        if s.get('snapshot_kind') not in ('raw_http','tool_extracted_text','structured_summary'):
            raise ValueError('hash must identify actual captured representation')
        if timestamp(s['known_available_at'])<timestamp(s['retrieved_at']):
            raise ValueError('real known time cannot predate retrieval')
        if timestamp(s['known_available_at'])>protocol_frozen:
            raise ValueError('source must be known before protocol freeze')
        if s.get('reviewed') is not True:raise ValueError('NAV source review required')
        source_map[sid]=s
    nav={}
    for row in csv.DictReader(io.StringIO(nav_raw.decode('utf-8-sig'))):
        key=(row['fund'],row['date'])
        date.fromisoformat(row['date'])
        if key in nav:raise ValueError('duplicate NAV fund/date')
        if row['source_id'] not in source_map:raise ValueError('unknown NAV source')
        if timestamp(row['known_available_at'])<timestamp(row['retrieved_at']):
            raise ValueError('NAV known time precedes retrieval')
        if timestamp(row['known_available_at'])>protocol_frozen:
            raise ValueError('NAV must be known before protocol freeze')
        nav[key]=number(row['nav'])
    missing=[(f,d) for f in funds for d in dates if (f,d) not in nav]
    if missing:raise ValueError('missing NAV, no filling/interpolation: '+str(missing[:3]))
    metadata={**SCOPE,'assumptions':a,'unknown_evidence':p['unknown_evidence']}
    if official:metadata['official_fee_coverage']=fee_coverage

    def curve(allocation):
        free=initial-sum(allocation.values()); units={}; fees=ZERO; turnover=ZERO;quotes={}
        for f in funds:
            if f in official:
                cost=a['costs'][f]
                q=official[f].subscription(allocation[f],discount=cost.get('discount'),discount_evidence=cost.get('discount_evidence'))
                quotes[f]={'subscription':q};net=D(q['net'])
            else:net=allocation[f]/(1+rates[f][0])
            fees+=allocation[f]-net
            units[f]=net/nav[f,dates[0]];turnover+=net
        peak=initial; dd=ZERO; maximum_exposure=ZERO;daily=[]
        for day in dates:
            values={f:units[f]*nav[f,day] for f in funds};risky=sum(values.values());equity=free+risky
            peak=max(peak,equity);dd=max(dd,(peak-equity)/peak)
            exposure=risky/equity if equity else ZERO;maximum_exposure=max(maximum_exposure,exposure)
            pending=sum(v for f,v in values.items() if a['entry_confirmation_dates'][f] is None or day<a['entry_confirmation_dates'][f])
            daily.append({**metadata,'date':day,'book_equity':str(equity),'portfolio_nav_over_initial':str(equity/initial),'book_change_from_initial':str(equity-initial),
                'available_cash':str(free),'modeled_nav_values':{f:str(v) for f,v in values.items()},
                'modeled_units_pending_confirmation_value':str(pending),'modeled_confirmed_value':str(risky-pending),
                'capital_occupied':str(risky),'exposure':str(exposure),'cash_fees_paid_assumed':str(fees),
                'valuation_semantics':'conditional economic exposure from entry NAV; not confirmed actual shares'})
        terminal=daily[-1];gross_exit=sum(units[f]*nav[f,dates[-1]] for f in funds)
        exit_parts={}
        for f in funds:
            if f in official:
                q=official[f].redemption([{'lot_id':'conditional-entry','units':str(units[f]),'confirmed_on':a['entry_confirmation_dates'][f]}],nav[f,dates[-1]],
                    redemption_application=applications[f],redemption_confirmation=a['exit_confirmation_dates'][f])
                quotes[f]['redemption']=q
                exit_parts[f]=ZERO if units[f]==0 else (None if q['fee'] is None else D(q['fee']))
            else:exit_parts[f]=units[f]*nav[f,dates[-1]]*rates[f][1]
        exit_fees=None if any(v is None for v in exit_parts.values()) else sum(exit_parts.values())
        exit_net=None if exit_fees is None else gross_exit-exit_fees
        liquidation_dd=None if exit_net is None else max(dd,(peak-free-exit_net)/peak)
        liquidation={**metadata,'conditional_equity_after_exit_fee':str(free+exit_net) if exit_net is not None else None,
            'hypothetical_exit_fee':str(exit_fees) if exit_fees is not None else None,'hypothetical_exit_proceeds_not_available_cash':str(exit_net) if exit_net is not None else None,
            'available_cash_at_window_end':str(free),'assumed_receipt_date':receipt,
            'conditional_cash_if_assumed_receipt_occurs':str(free+exit_net) if receipt is not None and exit_net is not None else None,
            'not_actual_sale_or_receivable':True,'conditional_total_cash_fees':str(fees+exit_fees) if exit_fees is not None else None,
            'conditional_gross_turnover_including_exit':str(turnover+gross_exit),
            'max_drawdown_including_hypothetical_exit_fee':str(liquidation_dd) if liquidation_dd is not None else None,
            'conditional_risk_gates_passed':liquidation_dd is not None and liquidation_dd<=max_dd and maximum_exposure<=cap and fees+exit_fees<=max_fees}
        return {**metadata,'daily_curve':daily,'pre_liquidation_nav_mark':terminal,'liquidation_scenario':liquidation,
            **({'official_fee_quotes':quotes} if official else {}),'units_hypothetical':{f:str(v) for f,v in units.items()},'entry_cash_fees':str(fees),
            'gross_entry_turnover':str(turnover),'entry_turnover_over_initial':str(turnover/initial),
            'max_drawdown_on_supplied_nav_marks':str(dd),'max_exposure_on_supplied_nav_marks':str(maximum_exposure),
            'mean_capital_occupied':str(sum(D(r['capital_occupied']) for r in daily)/len(daily)),
            'pre_liquidation_risk_gates_passed':dd<=max_dd and maximum_exposure<=cap and fees<=max_fees,
            'liquidation_fee_gate_passed':exit_fees is not None and fees+exit_fees<=max_fees}
    equal={f:initial*cap/D(len(funds)) for f in funds}
    # Last residual stays cash; Decimal equal weights need not divide finitely.
    if sum(equal.values())>initial*cap:equal[funds[-1]]-=sum(equal.values())-initial*cap
    outcomes={'cash':curve({f:ZERO for f in funds}),'equal_weight_buy_hold':curve(equal),'llm_allocation':curve(alloc)}
    candidate=outcomes['llm_allocation']
    comparisons={('against_cash' if k=='cash' else 'against_equal_weight'):{'pre_liquidation_difference':str(D(candidate['pre_liquidation_nav_mark']['book_equity'])-D(outcomes[k]['pre_liquidation_nav_mark']['book_equity'])),
                    'liquidation_difference':(str(D(candidate['liquidation_scenario']['conditional_equity_after_exit_fee'])-D(outcomes[k]['liquidation_scenario']['conditional_equity_after_exit_fee'])) if candidate['liquidation_scenario']['conditional_equity_after_exit_fee'] is not None and outcomes[k]['liquidation_scenario']['conditional_equity_after_exit_fee'] is not None else None)}
                 for k in ('cash','equal_weight_buy_hold')}
    return {**metadata,'producer':decision['producer'],'initial_cash':str(initial),'entry_date':dates[0],'end_date':dates[-1],
        'cash_baseline_interest':'0','risky_allocation_fraction':str(sum(alloc.values())/initial),
        'cash_equivalent_allocation':sum(alloc.values())==0,'active_profitability_validated':False,
        'unseen_validation_required':True,'conditional_holding_calendar_days':holding_days,'holding_days_basis':'assumed redemption confirmation minus assumed subscription confirmation; never valuation steps','outcomes':outcomes,'same_scenario_comparisons':comparisons,
        'fund_nav_path_changes':{f:str(nav[f,dates[-1]]/nav[f,dates[0]]-1) for f in funds},
        'limitations':['Historical LLM memory and prior project exposure prevent OOS claims',
            'Captured source hashes and reviewer declarations require external inspection',
            'Unknown dividends/splits can alter both allocations and cash; NAV path is not total return',
            'Conditional daily economic value may include units never actually confirmed',
            'Exit NAV haircut is not a realizable unknown-price order; no receipt credited',
            'No parameter search, automatic promotion, account use or trading']}


def run(protocol_path, protocol_sha256, decision_path, nav_path, sources_path, output):
    paths={'protocol':protocol_path,'decision':decision_path,'nav':nav_path,'sources':sources_path}
    raw={k:Path(v).read_bytes() for k,v in paths.items()}
    if digest(raw['protocol'])!=protocol_sha256:raise ValueError('frozen protocol hash mismatch')
    p=json.loads(raw['protocol'])
    if any('official_rule' in cost for cost in p['assumptions']['costs'].values()):
        from .upstream_bridge import read_private, private_parent
        for key,path in paths.items():
            if read_private(path)!=raw[key]:raise ValueError('input changed during private fee import')
        with private_parent(output):pass
    for key in ('decision','nav','sources'):
        if p['input_sha256'].get(key)!=digest(raw[key]):raise ValueError('frozen '+key+' hash mismatch')
    result=evaluate(p,json.loads(raw['decision']),raw['nav'],json.loads(raw['sources']))
    out=private_dir(output);write_json(out/'results.json',result)
    write_json(out/'manifest.json',{**SCOPE,'input_sha256':{k:digest(v) for k,v in raw.items()},
        'results_sha256':digest((out/'results.json').read_bytes()),'assumptions':p['assumptions'],
        'unknown_evidence':p['unknown_evidence'],'actual_evaluated_at':datetime.now(timezone.utc).isoformat(),
        'source_capture_records':json.loads(raw['sources'])})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('protocol','protocol-sha256','decision','nav','sources','output'):p.add_argument('--'+key,required=True)
    a=p.parse_args();run(a.protocol,a.protocol_sha256,a.decision,a.nav,a.sources,a.output)
    print('Private retrospective conditional valuation saved; not executable returns.')


if __name__=='__main__':main()
