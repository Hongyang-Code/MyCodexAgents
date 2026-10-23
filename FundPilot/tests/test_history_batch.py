"""Entirely synthetic data/calendars. No live funds, networks or trading."""
import copy
import csv
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

from fundpilot.history_batch import (digest, estimates, forecast_tape, load_input,
                                    metrics, protocol_check, run, simulate)


def fixture(root):
    """Synthetic every-day valuation calendar; explicitly not a real calendar."""
    sessions=[date(2026,1,1)+timedelta(days=i) for i in range(280)]
    p={'version':2,'retrospective':True,'recorded_at':'2026-01-01T00:00:00+08:00',
       'original_information_cutoff':'2026-08-31T22:00:00+08:00',
       'vintage_evidence_cutoff':'2026-08-31T23:10:04+08:00',
       'analysis_start':'2026-03-01','validation_end':'2026-05-31',
       'test_start':'2026-06-01','analysis_end':'2026-08-31',
       'instruments':['SYNTH-A','SYNTH-B','SYNTH-C'],
       'models':['abstain','persistence','trend20'],'horizons':[1,5,20],
       'information_lags':[1,3,5],'settlement_lags':[1,3], 'cost_bps':[0,20,100],
       'initial_cash':10000,'installment_dates':[f'2026-{m:02}-01' for m in range(3,9)]}
    pb=json.dumps(p,indent=2).encode();(root/'protocol.json').write_bytes(pb)
    files={};instruments=[]
    def add(name,data):
        (root/name).write_bytes(data)
        files[name]={'path':name,'sha256':digest(data),'source_url':'https://example.org/synthetic/'+name,
            'retrieved_at':'2026-08-31T22:30:00+08:00','known_available_at':'2026-08-31T22:30:00+08:00',
            'license_note':'Synthetic fixture generated for testing; no source-market claim.'}
    add('evidence.txt',b'SYNTHETIC attestation only, not official evidence.')
    add('calendar.csv',('date\n'+'\n'.join(d.isoformat() for d in sessions)+'\n').encode())
    # NAV exists on this day but dealing is suspended.
    closed=date(2026,4,1)
    add('dealing.csv',('date\n'+'\n'.join(d.isoformat() for d in sessions if d!=closed)+'\n').encode())
    for j,c in enumerate(p['instruments']):
        rows=['date,nav']
        for i,d in enumerate(sessions):
            if d<=date(2026,8,31): rows.append(f'{d},{100+i*(j+1)/100}')
        add(c+'.csv',('\n'.join(rows)+'\n').encode())
        instruments.append({'instrument':c,'share_class':'SYNTHETIC-A','nav_file':c+'.csv',
            'calendar_file':'calendar.csv','dealing_calendar_file':'dealing.csv',
            'calendar_evidence':'evidence.txt','dealing_calendar_evidence':'evidence.txt',
            'identity_evidence':'evidence.txt','channel_evidence':'evidence.txt','rules_evidence':'evidence.txt',
            'calendar_reviewed':True,'dealing_calendar_reviewed':True,'public_ant_sale_and_product_open':True,
            'channel_limitations':'SYNTHETIC ONLY; not actual Alipay availability/fees.',
            'distribution_status':'verified_none','distribution_evidence':'evidence.txt',
            'distribution_start':'2026-01-01','distribution_end':'2026-08-31','no_split_reviewed':True})
    config={'schema_version':1,'synthetic':True,'calendar_mode':'verified_open_sessions','files':files,'instruments':instruments}
    (root/'input.json').write_text(json.dumps(config))
    return p,config,digest(pb)


class HistoryBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.p,self.config,self.sha=fixture(self.root)
        _,self.assets,_=load_input(self.root/'input.json',self.p)

    def save_config(self):
        (self.root/'input.json').write_text(json.dumps(self.config))

    def test_hash_failure(self):
        (self.root/'SYNTH-A.csv').write_text('changed')
        with self.assertRaisesRegex(ValueError,'hash mismatch'): load_input(self.root/'input.json',self.p)

    def test_no_calendar_fallback(self):
        self.config['calendar_mode']='weekdays';self.save_config()
        with self.assertRaisesRegex(ValueError,'verified'): load_input(self.root/'input.json',self.p)

    def test_no_backdated_actual_knowledge(self):
        self.config['files']['SYNTH-A.csv']['known_available_at']='2026-03-01T00:00:00Z';self.save_config()
        with self.assertRaisesRegex(ValueError,'backdate'): load_input(self.root/'input.json',self.p)

    def test_path_traversal_and_symlink(self):
        self.config['files']['evidence.txt']['path']='../evidence.txt';self.save_config()
        with self.assertRaisesRegex(ValueError,'unsafe'): load_input(self.root/'input.json',self.p)
        self.config['files']['evidence.txt']['path']='link.txt'
        (self.root/'link.txt').symlink_to(self.root/'evidence.txt');self.save_config()
        with self.assertRaisesRegex(ValueError,'symlink'): load_input(self.root/'input.json',self.p)

    def test_nan_prices_rejected(self):
        f=self.root/'SYNTH-A.csv';b=f.read_bytes().replace(b'100.0',b'NaN',1);f.write_bytes(b)
        self.config['files']['SYNTH-A.csv']['sha256']=digest(b);self.save_config()
        with self.assertRaises(ValueError): load_input(self.root/'input.json',self.p)

    def test_unregistered_model_rejected(self):
        self.p['models'].append('tuned_best')
        with self.assertRaises(ValueError): protocol_check(self.p)

    def test_future_prices_not_used_in_features(self):
        a=self.assets['SYNTH-A'];d=date(2026,4,15)
        expected=estimates(a,d,3,'trend20',20)
        other=copy.deepcopy(a)
        for s in other['nav']:
            if s>d-timedelta(days=3): other['nav'][s]=Decimal(999999)
        self.assertEqual(expected,estimates(other,d,3,'trend20',20))

    def test_return_definition_and_target_origin(self):
        rows=forecast_tape({'SYNTH-A':self.assets['SYNTH-A']},self.p)
        r=next(r for r in rows if r['origin']=='2026-04-15' and r['model']=='trend20' and r['information_lag']==3 and r['horizon']==1)
        self.assertEqual(r['target'],'2026-04-16')
        self.assertAlmostEqual(r['predicted_return'],r['target_level_estimate']/r['decision_level_estimate']-1)
        self.assertEqual(r['anchor_date'],'2026-04-12')
        self.assertTrue(r['assumed_available_at'].endswith('+08:00'))

    def test_purge_and_pending_retained(self):
        rows=forecast_tape({'SYNTH-A':self.assets['SYNTH-A']},self.p)
        self.assertEqual(len(rows),184*3*3*3)
        self.assertTrue(all(r['status']=='pending' for r in rows if r['origin']=='2026-08-31'))
        self.assertTrue(all(r['status']=='purged' for r in rows if r['origin']=='2026-05-31'))

    def test_missing_history_retained(self):
        del self.assets['SYNTH-A']['nav'][date(2026,3,15)]
        rows=forecast_tape({'SYNTH-A':self.assets['SYNTH-A']},self.p)
        self.assertTrue(any(r['status']=='missing' and r['reason']=='missing_20_session_history' for r in rows))

    def test_cutoff_known_different_from_ex_post(self):
        rows=forecast_tape({'SYNTH-A':self.assets['SYNTH-A']},self.p)
        last=[r for r in rows if r['target']=='2026-08-31' and r['status']=='scored']
        self.assertTrue(last);self.assertTrue(all(r['ex_post_eligible'] and not r['cutoff_known_eligible'] for r in last))
        self.assets['SYNTH-A']['source']['known_available_at']='2026-09-01T00:00:00Z'
        rows=forecast_tape({'SYNTH-A':self.assets['SYNTH-A']},self.p)
        self.assertFalse(any(r['cutoff_known_eligible'] for r in rows))

    def test_nonoverlap_and_no_fake_calibration(self):
        stats=metrics(forecast_tape({'SYNTH-A':self.assets['SYNTH-A']},self.p))
        a=next(r for r in stats if r['horizon']==20 and r['model']=='persistence' and r['information_lag']==1 and r['split']=='test' and r['scope']=='ex_post' and r['sample']=='all_overlapping')
        b=next(r for r in stats if r['horizon']==20 and r['model']=='persistence' and r['information_lag']==1 and r['split']=='test' and r['scope']=='ex_post' and r['sample']=='fixed_nonoverlap')
        self.assertGreater(a['n'],b['n']);self.assertEqual(b['n'],4)
        self.assertIsNone(b['confidence_interval']);self.assertIsNone(b['probability_calibration'])

    def simulate(self,strategy='buy_hold',lag=1,settlement=1,cost=0):
        return simulate(self.assets,self.p,strategy,lag,settlement,cost)

    def test_future_unknown_execution_price(self):
        result=self.simulate()
        first=next(t for t in result['transactions'] if t['event']=='submitted')
        priced=next(t for t in result['transactions'] if t['event']=='priced')
        self.assertEqual(first['date'],'2026-03-01');self.assertEqual(priced['date'],'2026-03-02')
        self.assertNotIn('nav',first)
        self.assertEqual(Decimal(priced['nav']),self.assets[priced['instrument']]['nav'][date(2026,3,2)])

    def test_nav_present_but_closed_for_dealing(self):
        result=self.simulate('monthly_rebalance')
        self.assertTrue(all(t['date']!='2026-04-01' for t in result['transactions'] if t['event']=='submitted'))
        day=next(d for d in result['daily_assets'] if d['date']=='2026-04-01')
        self.assertFalse(day['common_dealing_session'])
        self.assertTrue(any(t['date']=='2026-04-02' for t in result['transactions'] if t['event']=='submitted'))

    def test_zero_move_conserves_funds_and_fees(self):
        for a in self.assets.values(): a['nav']={d:Decimal(100) for d in a['nav']}
        for strategy in ('buy_hold','installments','monthly_rebalance','trend20'):
            r=self.simulate(strategy,cost=100)
            self.assertAlmostEqual(float(Decimal(r['terminal_equity'])+Decimal(r['fees_paid'])),10000,places=8)
            self.assertGreaterEqual(Decimal(r['available_cash']),0)
            self.assertIsNone(r['liquidatable_return'])

    def test_six_installments_no_external_cash(self):
        r=self.simulate('installments')
        requests=[x for x in r['transactions'] if x['event']=='submitted' and x['side']=='buy']
        self.assertEqual(len(requests),18)
        self.assertLessEqual(sum(Decimal(x['budget']) for x in requests),Decimal('10000.00000001'))
        self.assertIn('2026-04-02',{x['date'] for x in requests})

    def test_pending_sale_not_spendable(self):
        # Sharp synthetic decline after initial investment forces trend exits.
        for a in self.assets.values():
            for d in a['nav']:
                if d>=date(2026,4,1): a['nav'][d]=Decimal(80)
        r=self.simulate('trend20',settlement=3)
        receivable_days=[d for d in r['daily_assets'] if Decimal(d['receivables'])>0]
        self.assertTrue(receivable_days)
        self.assertTrue(all(Decimal(d['available_cash'])<Decimal(d['equity']) for d in receivable_days))
        for row in r['transactions']:
            if row['event']=='priced' and row['side']=='sell':
                self.assertGreater(row['settle_date'],row['date'])

    def test_missing_price_fails_strategy(self):
        del self.assets['SYNTH-A']['nav'][date(2026,4,1)]
        with self.assertRaisesRegex(ValueError,'missing expected'): self.simulate()

    def test_unverified_distribution_blocks_strategy(self):
        self.assets['SYNTH-A']['distribution_status']='unknown'
        with self.assertRaisesRegex(ValueError,'distribution'): self.simulate()

    def test_does_not_liquidate_at_window_end(self):
        r=self.simulate('buy_hold')
        self.assertFalse(any(x.get('side')=='sell' for x in r['transactions']))
        self.assertGreater(Decimal(r['terminal_equity']),Decimal(r['available_cash']))

    def test_end_to_end_cli_and_private_archive(self):
        output=self.root/'output'
        completed=subprocess.run([sys.executable,'-m','fundpilot.history_batch','--input',str(self.root/'input.json'),
            '--protocol',str(self.root/'protocol.json'),'--protocol-sha256',self.sha,'--output',str(output)],
            text=True,capture_output=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        receipt=json.loads(completed.stdout);self.assertEqual(receipt['strategy_scenarios'],72)
        self.assertTrue(receipt['synthetic'])
        self.assertEqual(stat.S_IMODE(output.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((output/'audit.zip').stat().st_mode),0o600)
        self.assertEqual(digest((output/'audit.zip').read_bytes()),receipt['archive_sha256'])
        with zipfile.ZipFile(output/'audit.zip') as z:
            manifest=json.loads(z.read('audit-manifest.json'))
            for name,sha in manifest.items(): self.assertEqual(digest(z.read(name)),sha)
            self.assertIn('source/FundPilot/fundpilot/history_batch.py',manifest)
            replay=json.loads(z.read('replay-input.json'))
            self.assertTrue(all(x['path'].startswith('evidence/') for x in replay['files'].values()))
            self.assertIn('frozen-predictions.json',manifest)
            self.assertIn('report.txt',manifest)
        with self.assertRaises(FileExistsError): run(self.root/'input.json',self.root/'protocol.json',self.sha,output)

    def test_wrong_protocol_hash(self):
        with self.assertRaisesRegex(ValueError,'protocol hash'): run(self.root/'input.json',self.root/'protocol.json','0'*64,self.root/'out')

    def test_real_run_requires_supplement(self):
        self.config['synthetic']=False;self.save_config()
        with self.assertRaisesRegex(ValueError,'calendar supplement'): run(self.root/'input.json',self.root/'protocol.json',self.sha,self.root/'out')

    def test_unknown_distributions_prediction_only(self):
        self.config['instruments'][0]['distribution_status']='unknown';self.save_config()
        receipt=run(self.root/'input.json',self.root/'protocol.json',self.sha,self.root/'pred-only',True)
        self.assertEqual(receipt['strategy_scenarios'],0)
        self.assertTrue((self.root/'pred-only/frozen-predictions.json').exists())

    def test_missing_review_attestation(self):
        self.config['instruments'][0]['dealing_calendar_reviewed']=False;self.save_config()
        with self.assertRaisesRegex(ValueError,'review missing'): load_input(self.root/'input.json',self.p)

    def test_future_nav_after_window_never_scores_pending(self):
        a=self.assets['SYNTH-A']
        before=forecast_tape({'SYNTH-A':a},self.p)
        for d in a['sessions']:
            if d>date(2026,8,31): a['nav'][d]=Decimal(999999)
        after=forecast_tape({'SYNTH-A':a},self.p)
        self.assertEqual(before,after)

    def test_longer_information_lag_changes_anchor_only_as_declared(self):
        a=self.assets['SYNTH-A'];d=date(2026,4,15)
        for lag in (1,3,5):
            est,_=estimates(a,d,lag,'persistence',20)
            self.assertEqual(est['anchor_date'],(d-timedelta(days=lag)).isoformat())
            self.assertEqual(est['predicted_return'],0)

    def test_declared_blackouts_do_not_execute_even_with_nav(self):
        dates={date(2026,4,3),date(2026,4,7),date(2026,5,25),date(2026,7,1)}
        self.assets['SYNTH-C']['dealing_sessions']=[d for d in self.assets['SYNTH-C']['dealing_sessions'] if d not in dates]
        result=self.simulate('monthly_rebalance')
        for trade in result['transactions']:
            self.assertNotIn(date.fromisoformat(trade['date']),dates)
        self.assertTrue(dates.issubset({date.fromisoformat(d['date']) for d in result['daily_assets']}))

    def test_confirmation_delay_and_higher_fees(self):
        quick=self.simulate(settlement=1,cost=0)
        slow=self.simulate(settlement=3,cost=100)
        self.assertGreater(Decimal(quick['terminal_equity']),Decimal(slow['terminal_equity']))
        first_quick=next(t['date'] for t in quick['transactions'] if t['event']=='settled')
        first_slow=next(t['date'] for t in slow['transactions'] if t['event']=='settled')
        self.assertGreater(first_slow,first_quick)

    def test_supplement_hash_binding(self):
        s=self.root/'supplement.json';s.write_text(json.dumps({'supplement_to_sha256':'bad'}))
        with self.assertRaisesRegex(ValueError,'supplement hash/link'):
            run(self.root/'input.json',self.root/'protocol.json',self.sha,self.root/'out',False,s,digest(s.read_bytes()))


if __name__=='__main__': unittest.main()
