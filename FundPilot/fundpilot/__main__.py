"""Offline auditable integration demo and inspection CLI; never sends or trades."""
import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from .ledger import Ledger
from .portfolio import PortfolioManager
from .notifications import NotificationManager
from .research import Observation, TradingCalendar, ForecastEngine
from .risk import RiskAdvisor
from .storage import pack, restore, verify_sqlite


def serial(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def smoke(target):
    """Synthetic end-to-end primitives; target must not exist, preventing overwrite."""
    root = Path(target)
    root.mkdir(parents=True, exist_ok=False)
    state = root / 'state'; state.mkdir()
    at = '2026-01-02T13:30:00+00:00'
    with Ledger(root / 'working.sqlite') as ledger:
        pm = PortfolioManager(ledger)
        pm.import_snapshot('synthetic-snapshot', {
            'as_of': at, 'cash': '200',
            'positions': [{'code': '999999', 'units': '100'}]}, {
                'source': 'synthetic-only-not-an-account',
                'confidence': {'as_of': '1', 'positions': '1', 'cash': '1'}})
        calendar = TradingCalendar(tuple(date(2026,1,2)+timedelta(days=i) for i in range(31)),
                                   'synthetic-every-day-calendar-NOT-real-market')
        cutoff = datetime.fromisoformat(at)
        obs = Observation('synthetic-nav','999999',date(2026,1,2),1.0,cutoff,cutoff,'synthetic',basis='total_return')
        forecast = ForecastEngine().predict('synthetic-prediction','999999',[obs],calendar,cutoff,5)
        frozen = json.loads(json.dumps(asdict(forecast), default=serial))
        ledger.append(forecast.forecast_id,'forecast.frozen',frozen,expected_version=ledger.version,occurred_at=at)
        decision = RiskAdvisor().evaluate({})
        notices = NotificationManager(ledger.connection)
        notice = notices.consider({'kind':'hold'})
        ledger.append('synthetic-run','run.completed', {
            'test_only':True,'research_scope':'synthetic integration only',
            'decision':decision,'notification':notice},expected_version=ledger.version,occurred_at=at)
        ledger.backup(state / 'ledger.sqlite')
        summary = {'test_only':True,'portfolio':pm.state(),'frozen_forecast':frozen,
                   'decision':decision,'notification':notice,'event_count':ledger.version,
                   'production_enabled':False,'trade_execution_enabled':False,
                   'platform_silence_verified':False}
        (state/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=serial),encoding='utf-8')
    result=pack(state,root/'smoke.snapshot.zip',run_id='synthetic-integration',test_only=True)
    restore(root/'smoke.snapshot.zip',root/'restored',expected_sha=result['sha256'],allow_test=True)
    if not verify_sqlite(root/'restored/ledger.sqlite'):
        raise RuntimeError('restored database integrity failed')
    with Ledger(root/'restored/ledger.sqlite') as recovered:
        if recovered.version != summary['event_count'] or recovered.get('synthetic-prediction')['payload'] != frozen:
            raise RuntimeError('restored evidence mismatch')
        if NotificationManager(recovered.connection).pending():
            raise RuntimeError('hold generated an unexpected notice')
    receipt={'test_only':True,'status':'passed','snapshot_sha256':result['sha256'],
             'events_restored':summary['event_count'],'notification_intents':0,
             'cloud_restore_verified':False,'real_prediction_validation':False}
    (root/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    s=commands.add_parser('smoke',help='synthetic test only, fresh private staging directory')
    s.add_argument('--output',required=True)
    r=commands.add_parser('restore',help='restore hash-verified immutable snapshot into NEW directory')
    r.add_argument('--snapshot',required=True);r.add_argument('--sha256',required=True);r.add_argument('--output',required=True)
    r.add_argument('--allow-test',action='store_true')
    commands.add_parser('deployment-status',help='report intentional production block')
    args=parser.parse_args()
    if args.command=='smoke': result=smoke(args.output)
    elif args.command=='restore': result=restore(args.snapshot,args.output,expected_sha=args.sha256,allow_test=args.allow_test)
    else: result={'production_enabled':False,'daily_local_time':'21:30','timezone':'Asia/Shanghai',
                  'requires':['reviewed PR','explicit deployment approval','confirmed holdings and risk profile',
                              'complete source/rule adapters','independent cloud restore','platform notification validation']}
    print(json.dumps(result,ensure_ascii=False,indent=2,default=serial))


if __name__=='__main__':
    main()
