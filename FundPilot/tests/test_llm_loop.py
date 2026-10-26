import csv
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from fundpilot.llm_loop import freeze, score, now


def fixture(root):
    days=[(date(2026,1,1)+timedelta(days=i)).isoformat() for i in range(60)]
    calendar={'reviewed':True,'evidence_ref':'synthetic daily calendar, not market sessions','dates':{'999999':days}}
    cards={'mode':'synthetic','producer':'synthetic_fixture','model_ref':'synthetic-not-LLM','prompt_version':'synthetic-v1',
           'cutoff':'2026-01-25T21:30:00+08:00','generated_at':'2026-01-25T22:00:00+08:00','cards':[]}
    for h,d in ((1,'up'),(5,'abstain'),(20,'down')):
        cards['cards'].append({'id':str(h),'fund':'999999','origin':'2026-01-26','horizon':h,'direction':d,
            'source_ids':['s1'],'reasoning':'synthetic only','counterevidence':['opposite possible'],
            'invalidation':'synthetic condition','gaps':[],'scenarios':[], 'abstention_reason':'insufficient evidence'})
    sources=[{'id':'s1','url':'https://example.org/synthetic','raw_sha256':'0'*64,'reviewed':True,
              'published_at':'2026-01-20T00:00:00Z','retrieved_at':'2026-01-21T00:00:00Z',
              'known_available_at':'2026-01-21T00:00:00Z','assumed_available_at':'2026-01-21T00:00:00Z'}]
    for name,data in (('cards',cards),('sources',sources),('calendar',calendar)):
        (root/(name+'.json')).write_text(json.dumps(data))
    with (root/'nav.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['fund','date','nav','retrieved_at','known_available_at','assumed_available_at'])
        for i,d in enumerate(days):writer.writerow(['999999',d,str(100+i),d+'T12:00:00Z',d+'T12:00:00Z',d+'T12:00:00Z'])
    manifest(root)
    return cards


def manifest(root):
    (root/'nav-manifest.json').write_text(json.dumps({'sha256':hashlib.sha256((root/'nav.csv').read_bytes()).hexdigest(),
        'reviewed':True,'reviewed_by':'synthetic-test','evidence_refs':['synthetic-only']}))


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.cards=fixture(self.root)
    def frozen(self):
        return freeze(self.root/'cards.json',self.root/'sources.json',self.root/'calendar.json',self.root/'frozen')
    def scored(self):
        return score(self.root/'frozen',self.root/'nav.csv',self.root/'nav-manifest.json',now(),self.root/'output')
    def alter(self,name,fn):
        p=self.root/name;data=json.loads(p.read_text());fn(data);p.write_text(json.dumps(data))
    def test_complete_cli_and_abstention_denominators(self):
        args=[sys.executable,'-m','fundpilot.llm_loop']
        subprocess.run(args+['freeze','--cards',str(self.root/'cards.json'),'--sources',str(self.root/'sources.json'),
            '--calendar',str(self.root/'calendar.json'),'--output',str(self.root/'frozen')],check=True,capture_output=True)
        subprocess.run(args+['score','--frozen',str(self.root/'frozen'),'--nav',str(self.root/'nav.csv'),
            '--nav-manifest',str(self.root/'nav-manifest.json'),'--as-of',now(),'--output',str(self.root/'output')],check=True,capture_output=True)
        r=json.loads((self.root/'output/results.json').read_text())
        self.assertEqual(r['metrics']['scored'],2);self.assertEqual(r['metrics']['abstained'],1)
        self.assertEqual(r['metrics']['llm_accuracy'],.5);self.assertIsNone(r['tape'][1]['llm_hit'])
        self.assertEqual(r['metrics']['paired_n'],2);self.assertEqual(len(r['improvement_proposals']),1)
        self.assertFalse(r['independent_oos']);self.assertEqual((self.root/'output/results.json').stat().st_mode&0o777,0o600)
    def test_duplicate_card(self):
        self.alter('cards.json',lambda d:d['cards'].append(d['cards'][0]))
        with self.assertRaises(ValueError):self.frozen()
    def test_malformed_hash_types_raise_validation_error_before_freeze(self):
        # Real parser failure: unknown raw hash was null rather than an empty string.
        # Malformed source metadata must not create a frozen record or leak TypeError.
        for value in (None, False, 13, [], {}):
            with self.subTest(hash_type=type(value).__name__):
                self.alter('sources.json',lambda d:d[0].update(raw_sha256=value))
                with self.assertRaisesRegex(ValueError,'source hash required'):
                    self.frozen()
                self.assertFalse((self.root/'frozen').exists())

    def test_null_raw_hash_diagnostic_does_not_become_strict_evidence(self):
        self.diagnostic()
        self.alter('sources.json',lambda d:d[0].update(raw_sha256=None))
        self.frozen()
        receipt=json.loads((self.root/'frozen/receipt.json').read_text())
        self.assertEqual(receipt['source_time_qualification'],'limited')
        self.assertTrue(receipt['non_oos'])
        self.alter('cards.json',lambda d:d.update(mode='retrospective'))
        with self.assertRaisesRegex(ValueError,'source hash required'):
            freeze(self.root/'cards.json',self.root/'sources.json',self.root/'calendar.json',self.root/'strict-output')
        self.assertFalse((self.root/'strict-output').exists())

    def test_future_source(self):
        self.alter('sources.json',lambda d:d[0].update(known_available_at='2026-02-01T00:00:00Z'))
        with self.assertRaises(ValueError):self.frozen()
    def test_card_hash_tamper(self):
        self.frozen();self.alter('frozen/cards.json',lambda d:d['cards'][0].update(direction='flat'))
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.scored()
    def test_missing_truth(self):
        self.frozen();p=self.root/'nav.csv';p.write_text('\n'.join(l for l in p.read_text().splitlines() if ',2026-01-27,' not in l)+'\n');manifest(self.root)
        self.assertEqual(self.scored()['tape'][0]['status'],'missing')
    def test_pending_calendar(self):
        self.alter('calendar.json',lambda d:d['dates'].update({'999999':d['dates']['999999'][:27]}))
        self.frozen();r=self.scored();self.assertEqual(r['metrics']['pending'],2)
        self.assertEqual(r['tape'][2]['missing_reason'],'target_calendar_missing')
    def test_duplicate_nav_and_hash(self):
        self.frozen();p=self.root/'nav.csv';p.write_text(p.read_text()+p.read_text().splitlines()[1]+'\n');manifest(self.root)
        with self.assertRaisesRegex(ValueError,'duplicate NAV'):self.scored()
    def test_no_future_baseline_access(self):
        self.frozen();p=self.root/'nav.csv';p.write_text(p.read_text().replace('2026-01-20T12:00:00Z','2026-02-20T12:00:00Z'));manifest(self.root)
        r=self.scored();self.assertIsNone(r['tape'][0]['trend20_direction'])
    def test_wrong_origin_and_fake_llm(self):
        self.alter('cards.json',lambda d:d.update(producer='actual_llm'))
        with self.assertRaises(ValueError):self.frozen()

    def test_not_yet_mature(self):
        self.alter('calendar.json',lambda d:d['dates'].update({'999999':d['dates']['999999'][:26]+['2099-01-01']}))
        self.frozen();r=self.scored()
        self.assertEqual(r['tape'][0]['missing_reason'],'target_not_mature')
        self.assertIsNone(r['tape'][0]['llm_hit'])

    def test_zero_change_is_flat(self):
        self.frozen();p=self.root/'nav.csv';p.write_text(p.read_text().replace('2026-01-27,126,','2026-01-27,125,'));manifest(self.root)
        r=self.scored();self.assertEqual(r['tape'][0]['actual_direction'],'flat')
        self.assertTrue(r['tape'][0]['persistence_hit'])

    def diagnostic(self):
        self.alter('cards.json',lambda d:d.update(mode='retrospective_diagnostic',producer='actual_llm'))
        content='Synthetic captured summary, not raw HTTP'
        source={'id':'s1','url':'https://example.org/synthetic','reviewed':True,
                'published_precision':'day','published_date':'2026-01-20','timezone':'unknown',
                'retrieved_at':'2026-10-01T00:00:00Z','known_available_at':'2026-10-01T00:00:00Z',
                'snapshot_kind':'structured_summary','snapshot_content':content,
                'snapshot_sha256':hashlib.sha256(content.encode()).hexdigest(),'revision_status':'unknown'}
        (self.root/'sources.json').write_text(json.dumps([source]))

    def test_diagnostic_day_summary_and_output_labels(self):
        self.diagnostic();receipt=self.frozen();r=self.scored()
        for row in [receipt,r,*r['tape'],*r['improvement_proposals'],json.loads((self.root/'output/manifest.json').read_text())]:
            self.assertEqual(row['source_time_qualification'],'limited')
            self.assertTrue(row['non_blind']);self.assertTrue(row['non_oos']);self.assertTrue(row['current_vintage'])
        self.assertEqual(r['metrics']['scored'],2)
        self.assertEqual(json.loads((self.root/'frozen/sources.json').read_text())[0]['revision_status'],'unknown')

    def test_strict_rejects_day_summary(self):
        self.diagnostic();self.alter('cards.json',lambda d:d.update(mode='retrospective'))
        with self.assertRaises(ValueError):self.frozen()

    def test_same_day_and_timezone_boundary_rejected(self):
        self.diagnostic()
        for day in ('2026-01-25','2026-01-26'):
            self.alter('sources.json',lambda d:d[0].update(published_date=day))
            with self.assertRaises(ValueError):self.frozen()
        self.alter('sources.json',lambda d:d[0].update(published_date='2026-01-24'))
        self.alter('cards.json',lambda d:d.update(cutoff='2026-01-25T19:00:00+08:00'))
        with self.assertRaises(ValueError):self.frozen()

    def test_summary_hash_and_unknown_publication_rejected(self):
        self.diagnostic();self.alter('sources.json',lambda d:d[0].update(snapshot_content='changed'))
        with self.assertRaises(ValueError):self.frozen()
        self.diagnostic();self.alter('sources.json',lambda d:d[0].update(published_precision='unknown'))
        with self.assertRaises(ValueError):self.frozen()
        self.diagnostic();self.alter('sources.json',lambda d:d[0].update(revision_status='verified_unrevised'))
        with self.assertRaises(ValueError):self.frozen()
