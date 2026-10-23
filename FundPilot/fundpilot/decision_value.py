"""One synthetic decision-value comparison using the existing accounting kernel.

No direction-to-order conversion, real fund execution claims or parameter search.
"""
import argparse
from decimal import Decimal as D
import json
from pathlib import Path
from .backtest import Rule, Order, Confirmation, Receipt, EventSimulator
from .market import timestamp, number
from .llm_loop import digest, private_dir, write_json


def evaluate(p):
    if p.get('mode') != 'synthetic' or p.get('synthetic_rules_reviewed') is not True:
        raise ValueError('only reviewed synthetic rules supported; real execution evidence not implemented')
    if p.get('no_distributions_or_splits') is not True:
        raise ValueError('this small synthetic entry requires no distributions/splits')
    if p.get('producer') not in ('actual_llm_on_synthetic_data', 'synthetic_fixture'):
        raise ValueError('explicit simulated-decision producer required')
    initial=number(p['initial_cash']); cap=number(p['risk']['max_exposure'])
    if cap>1 or p['risk'].get('no_leverage') is not True:raise ValueError('no leverage and exposure <=1 required')
    max_dd=number(p['risk']['max_drawdown'],positive=False)
    fee_budget=number(p['risk']['max_cash_fees'],positive=False)
    if max_dd>1:raise ValueError('drawdown limit must be <=1')
    start,end=timestamp(p['start']),timestamp(p['end'])
    frozen=timestamp(p['frozen_at'])
    if not frozen<start<end:raise ValueError('freeze before common evaluation window')
    if not p.get('evidence_refs') or not p.get('missing_evidence'):
        raise ValueError('synthetic evidence and real-world evidence gaps required')
    fund=p['instrument']; buy=number(p['buy_rate'],positive=False);sell=number(p['sell_rate'],positive=False)
    rule=Rule('synthetic-rule',fund,start,end,frozen,frozen,buy,sell,'reviewed synthetic fixture only',True)
    ops=p['opportunities'];marks=p['marks'];decisions=p['decisions']
    if not ops or len(decisions)>9:raise ValueError('one small candidate, at most nine explicit decisions')
    if len({o['id'] for o in ops})!=len(ops):raise ValueError('duplicate opportunity')
    times=[timestamp(o['at']) for o in ops]
    if times!=sorted(set(times)) or any(not start<=t<end for t in times):raise ValueError('ordered common opportunities required')
    for o in ops:
        if not timestamp(o['at'])<timestamp(o['determined_at'])<=timestamp(o['published_at'])<=timestamp(o['confirmed_at'])<=timestamp(o['received_at']):
            raise ValueError('explicit unknown-price confirmation/receipt order required')
        number(o['price'])
    mark_times=[timestamp(m['at']) for m in marks]
    if not marks or mark_times!=sorted(set(mark_times)) or mark_times[-1]!=end or any(not start<=t<=end for t in mark_times):
        raise ValueError('common marks including terminal mark required')
    for m in marks:number(m['nav'])
    ids={o['id'] for o in ops};seen=set()
    for d in decisions:
        if d['opportunity'] not in ids or d['opportunity'] in seen:raise ValueError('unknown/duplicate decision opportunity')
        seen.add(d['opportunity'])
        if d['action'] not in ('buy','sell','hold'):raise ValueError('explicit action required; direction is not action')
        for field in ('reason','no_action_counterfactual','cost_coverage_evidence'):
            if not d.get(field):raise ValueError('missing decision rationale: '+field)
        if timestamp(d['evidence_cutoff'])>frozen:
            raise ValueError('future decision evidence')
        if d['action']=='buy':
            if d.get('expected_gain_bps') is None:raise ValueError('unknown expected gain cannot authorize simulated buy')
            if number(d['expected_gain_bps'],positive=False)<= (buy+sell)*10000:
                raise ValueError('declared expected gain does not cover fixed fee hurdle')
        if d['action']!='hold':number(d['quantity'])
    candidate={d['opportunity']:d for d in decisions}
    baseline={ops[0]['id']:{'action':'buy','quantity':str(initial*cap)}}

    def replay(requests):
        sim=EventSimulator(initial,[rule]); events=[]; records=[]; turnover=D(0)
        for o in ops:
            d=requests.get(o['id'])
            if not d or d['action']=='hold':continue
            order_id='order-'+o['id']; confirmation_id='confirm-'+o['id']
            events.append(Order(order_id,timestamp(o['at']),'synthetic explicit request',True,fund,d['action'],number(d['quantity']),rule.rule_id,timestamp(o['at'])))
            events.append(Confirmation(confirmation_id,timestamp(o['confirmed_at']),'synthetic common execution',True,order_id,number(o['price']),timestamp(o['determined_at']),timestamp(o['published_at']),timestamp(o['confirmed_at'])))
            if d['action']=='sell':events.append(Receipt('receipt-'+o['id'],timestamp(o['received_at']),'synthetic common receipt',True,confirmation_id))
        timeline=sorted([(e.at,0,e) for e in events if e.at<=end]+[(timestamp(m['at']),1,m) for m in marks],key=lambda x:(x[0],x[1]))
        peak=initial;dd=D(0);daily=[]; max_exposure=D(0);last_mark=None
        for at,kind,value in timeline:
            if kind==0:
                before=sim.state
                if isinstance(value,Order) and value.side=='buy':
                    if before.shares.get(fund,D(0)) and last_mark is None:raise ValueError('missing known mark for exposure check')
                    invested=before.shares.get(fund,D(0))*(last_mark or D(0))+before.reserved_cash+value.quantity
                    equity=before.equity({fund:last_mark} if last_mark else {})
                    if invested>equity*cap:raise ValueError('decision exceeds preset exposure budget')
                state=sim.apply(value)
                if isinstance(value,Confirmation):
                    order=before.orders[value.order_id]
                    turnover += (state.shares.get(fund,D(0))-before.shares.get(fund,D(0)))*value.price if order.side=='buy' else order.quantity*value.price
                records.append({'event':type(value).__name__,'id':value.event_id,'at':at.isoformat(),'cash':str(state.cash),'fees':str(state.fees)})
            else:
                last_mark=number(value['nav']);s=sim.state;equity=s.equity({fund:last_mark})
                risky=s.shares.get(fund,D(0))*last_mark
                peak=max(peak,equity);dd=max(dd,(peak-equity)/peak)
                exposure=(risky+s.reserved_cash)/equity;max_exposure=max(max_exposure,exposure)
                daily.append({'at':at.isoformat(),'equity':str(equity),'cash':str(s.cash),'available_cash':str(s.available_cash(at)),
                    'reserved_cash':str(s.reserved_cash),'receivables':str(sum((x[1] for x in s.receivables.values()),D(0))),
                    'risky_value':str(risky),'exposure':str(exposure),'occupied_capital':str(equity-s.available_cash(at))})
        s=sim.state;terminal=D(daily[-1]['equity'])
        return {'terminal_book_equity':str(terminal),'book_change_after_explicit_fees':str(terminal-initial),
            'cash_fees':str(s.fees),'gross_turnover':str(turnover),'turnover_over_initial':str(turnover/initial),
            'max_drawdown_on_supplied_marks':str(dd),'max_exposure_on_supplied_marks':str(max_exposure),
            'available_cash':str(s.available_cash(end)),'terminal_occupied_capital':daily[-1]['occupied_capital'],
            'pending_orders':len(s.orders)-len(s.confirmed),'daily_assets':daily,'transactions':records,
            'risk_gates_passed':dd<=max_dd and max_exposure<=cap and s.fees<=fee_budget}
    outcomes={'cash':replay({}),'buy_hold':replay(baseline),'candidate':replay(candidate)}
    c=outcomes['candidate'];deltas={k:str(D(c['terminal_book_equity'])-D(outcomes[k]['terminal_book_equity'])) for k in ('cash','buy_hold')}
    return {'scope':'synthetic_decision_value_only','not_executable':True,'not_actual_fund_total_return':True,
        'independent_oos':False,'producer':p['producer'],'initial_cash':str(initial),'outcomes':outcomes,
        'candidate_minus_baseline_terminal_equity':deltas,'cash_baseline_return':'0',
        'nav_path_change':str(number(marks[-1]['nav'])/number(marks[0]['nav'])-1),
        'promotion':'retain_stable_pending_unseen_validation',
        'synthetic_value_improvement_and_risk_pass':all(D(v)>0 for v in deltas.values()) and c['risk_gates_passed'],
        'missing_evidence':p['missing_evidence'],
        'limitations':['Synthetic expectations are assertions, not calibrated forecasts',
            'No automatic promotion; future unseen evaluation and uncertainty/cost/risk review required',
            'Book equity is not withdrawable cash; no forced liquidation or invented cash yield',
            'Drawdown/exposure measured only at supplied marks; no intraperiod guarantee']}


def run(input_path, output):
    raw=Path(input_path).read_bytes();result=evaluate(json.loads(raw));out=private_dir(output)
    write_json(out/'results.json',result)
    write_json(out/'manifest.json',{'input_sha256':digest(raw),'results_sha256':digest((out/'results.json').read_bytes()),'scope':'synthetic_only'})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.input,a.output);print('Synthetic private comparison saved; no trading or promotion.')


if __name__=='__main__':main()
