"""Synthetic documents and prices only; no real fund materials or fee imports."""
from copy import deepcopy
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path
import json
import tempfile
import unittest

from fundpilot.official_fees import OfficialFees
from fundpilot.conditional_value import evaluate, run
from test_conditional_value import fixture

RAW = b'SYNTHETIC DOCUMENT ONLY'


def record(share='A'):
    return {'fund_code':'SYNTHETIC', 'share_class':share, 'currency':'CNY',
            'version':'synthetic-v1', 'source_url':'https://example.org/synthetic',
            'published_on':'2025-01-01', 'reviewed_by':'synthetic reviewer',
            'pages':'synthetic page 1', 'applicability_note':'synthetic interval',
            'reviewed':True, 'raw_sha256':sha256(RAW).hexdigest(),
            'effective_from':'2025-01-01', 'effective_until':'2026-12-31',
            'nav_includes_recurring_fees':True,
            'holding_basis':'confirmation_to_confirmation_exclusive_end',
            'holding_basis_evidence':'synthetic convention, not universal',
            'subscription_bands':[{'min_amount':'0','max_amount':'1000','rate':'.02' if share=='A' else '0'},
                                  {'min_amount':'1000','max_amount':'2000','rate':'.01' if share=='A' else '0'},
                                  {'min_amount':'2000','max_amount':None,'fixed_fee':'5' if share=='A' else '0'}],
            'redemption_bands':[{'min_days':0,'max_days':6,'rate':'.03'},
                                {'min_days':7,'max_days':29,'rate':'.01'},
                                {'min_days':30,'max_days':None,'rate':'0'}]}


class OfficialFeeTests(unittest.TestCase):
    def test_amount_edges_fixed_fee_and_share_identity(self):
        q=OfficialFees(record(),RAW)
        for gross,net in [('999',D('999')/D('1.02')),('1000',D('1000')/D('1.01')),('2000',D('1995'))]:
            self.assertEqual(D(q.subscription(gross)['net']),net)
        self.assertEqual(q.subscription('0')['fee'],'0')
        with self.assertRaisesRegex(ValueError,'identity'):
            q.check({'fund_code':'SYNTHETIC','share_class':'C','currency':'CNY'},'2026-01-01')
        self.assertEqual(OfficialFees(record('C'),RAW).subscription('1000')['fee'],'0')

    def test_unknown_discount_standard_and_explicit_no_discount(self):
        q=OfficialFees(record(),RAW)
        self.assertEqual(q.subscription('500')['net'],q.subscription('500',discount='1',discount_evidence='synthetic no discount')['net'])
        self.assertEqual(q.subscription('500',discount='0',discount_evidence='synthetic waiver')['fee'],'0')
        with self.assertRaises(ValueError):q.subscription('500',discount='.5')
        with self.assertRaises(ValueError):q.subscription('2000',discount='.5',discount_evidence='unsupported')

    def test_natural_day_edges_and_different_lots(self):
        q=OfficialFees(record(),RAW)
        for start,days,rate in [('2026-01-25',6,'.03'),('2026-01-24',7,'.01'),('2026-01-02',29,'.01'),('2026-01-01',30,'0')]:
            r=q.redemption([{'lot_id':'x','units':'10','confirmed_on':start}],'2',redemption_confirmation='2026-01-31')
            self.assertEqual(r['lots'][0]['holding_days'],days);self.assertEqual(D(r['lots'][0]['rate']),D(rate))
        r=q.redemption([{'lot_id':'old','units':'10','confirmed_on':'2026-01-01'},
                        {'lot_id':'new','units':'10','confirmed_on':'2026-01-25'}],'2',redemption_confirmation='2026-01-31')
        self.assertEqual(D(r['fee']),D('.6'))
        with self.assertRaises(ValueError):q.redemption([{'lot_id':'x','units':'1','confirmed_on':'2026-02-01'}],'2',redemption_confirmation='2026-01-31')

    def test_missing_dates_or_basis_do_not_guess(self):
        q=OfficialFees(record(),RAW);lot=[{'lot_id':'x','units':'10','confirmed_on':'2026-01-01'}]
        self.assertIsNone(q.redemption(lot,'2',redemption_application='2026-01-31')['fee'])
        r=record();r['holding_basis']=None
        self.assertIsNone(OfficialFees(r,RAW).redemption(lot,'2',redemption_confirmation='2026-01-31')['fee'])
        r=record();r.pop('holding_basis_evidence')
        with self.assertRaises(ValueError):OfficialFees(r,RAW)

    def test_versions_raw_hash_and_band_corruption(self):
        q=OfficialFees(record(),RAW);identity={k:record()[k] for k in ('fund_code','share_class','currency')}
        with self.assertRaises(ValueError):q.check(identity,'2024-12-31',document_version_scenario=True)
        with self.assertRaises(ValueError):q.check(identity,'2027-01-01',document_version_scenario=True)
        r=record();r['effective_from']=r['effective_until']=None;q=OfficialFees(r,RAW)
        with self.assertRaises(ValueError):q.check(identity,'2026-01-01')
        self.assertIn('conditional',q.check(identity,'2026-01-01',document_version_scenario=True))
        with self.assertRaises(ValueError):OfficialFees(r,b'corrupted')
        r=record();r['subscription_bands'][1]['min_amount']='999'
        with self.assertRaises(ValueError):OfficialFees(r,RAW)

    def test_official_selection_enters_valuation_and_nav_expenses_not_added(self):
        p,d,n,s=fixture();r=record();a=p['assumptions']
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);root.chmod(0o700);raw=root/'source';raw.write_bytes(RAW);raw.chmod(0o600)
            for f in p['funds']:
                rf=deepcopy(r);rf['fund_code']=f
                a['costs'][f]={'official_rule':rf,'raw_document_path':str(raw),
                             'identity':{k:rf[k] for k in ('fund_code','share_class','currency')}}
            result=evaluate(p,d,n,s);c=result['outcomes']['llm_allocation']
            expected=D('500')+D('500')/D('1.02')/D('10')*D('12')
            self.assertEqual(D(c['pre_liquidation_nav_mark']['book_equity']),expected)
            self.assertIsNone(c['liquidation_scenario']['conditional_equity_after_exit_fee'])
            self.assertEqual(c['liquidation_scenario']['conditional_liquidation_status'],
                             'pending_missing_redemption_evidence')
            self.assertIsNone(result['same_scenario_comparisons']['against_cash']['liquidation_difference'])
            self.assertFalse(c['liquidation_scenario']['conditional_risk_gates_passed'])
            a['entry_confirmation_dates']={f:'2026-01-03' for f in p['funds']}
            a['exit_confirmation_dates']={f:'2026-01-07' for f in p['funds']}
            c=evaluate(p,d,n,s)['outcomes']['llm_allocation']
            self.assertEqual(c['liquidation_scenario']['conditional_liquidation_status'],
                             'conditional_fee_computed')
            self.assertAlmostEqual(D(c['liquidation_scenario']['hypothetical_exit_fee']),(expected-D('500'))*D('.03'), places=24)
            self.assertEqual(c['liquidation_scenario']['available_cash_at_window_end'],'500')
            swapped=deepcopy(p);swapped['assumptions']['costs']['A']=deepcopy(a['costs']['B'])
            with self.assertRaisesRegex(ValueError,'different fund'):evaluate(swapped,d,n,s)
            raw.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'hash'):evaluate(p,d,n,s)

    def test_private_cli_import_preserves_original_and_refuses_repeat_output(self):
        p,d,n,s=fixture()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);root.chmod(0o700);raw=root/'document';raw.write_bytes(RAW);raw.chmod(0o600)
            for f in p['funds']:
                r=record();r['fund_code']=f
                p['assumptions']['costs'][f]={'official_rule':r,'raw_document_path':str(raw),
                    'identity':{k:r[k] for k in ('fund_code','share_class','currency')}}
            blobs={'decision':json.dumps(d).encode(),'nav':n,'sources':json.dumps(s).encode()}
            p['input_sha256']={k:sha256(v).hexdigest() for k,v in blobs.items()}
            blobs['protocol']=json.dumps(p).encode()
            for k,v in blobs.items():(root/k).write_bytes(v);(root/k).chmod(0o600)
            h=sha256(blobs['protocol']).hexdigest()
            result=run(root/'protocol',h,root/'decision',root/'nav',root/'sources',root/'output')
            self.assertIsNone(result['outcomes']['llm_allocation']['liquidation_scenario']['hypothetical_exit_fee'])
            self.assertEqual((root/'protocol').read_bytes(),blobs['protocol'])
            with self.assertRaises(FileExistsError):run(root/'protocol',h,root/'decision',root/'nav',root/'sources',root/'output')
            (root/'document').chmod(0o644)
            with self.assertRaisesRegex(ValueError,'private'):run(root/'protocol',h,root/'decision',root/'nav',root/'sources',root/'denied')
