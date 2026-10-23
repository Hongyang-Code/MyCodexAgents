import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from fundpilot.market import NavRecord, available_as_of, latest_known, import_reviewed, verify_raw_evidence


class MarketTests(unittest.TestCase):
    def row(self, **changes):
        row = dict(fund_code='000001', share_class='A', nav_date='2026-04-01', unit_nav='1.2',
                   source_url='https://example.org/nav', source_version='fixture-v1',
                   raw_sha256=hashlib.sha256(b'fixture').hexdigest(), retrieved_at='2026-10-23T12:00:00Z',
                   available_at='2026-10-23T12:00:00Z', reviewed_at='2026-10-23T12:01:00Z', reviewed_by='test')
        row.update(changes)
        return row

    def test_no_backdated_availability(self):
        with self.assertRaises(ValueError):
            NavRecord.from_dict(self.row(available_at='2026-04-01T20:00:00+08:00'))

    def test_review_cutoff_and_no_forward_fill(self):
        r = NavRecord.from_dict(self.row())
        self.assertEqual(available_as_of([r], '2026-04-02T00:00:00Z'), [])
        self.assertEqual(available_as_of([r], '2026-10-23T12:00:00Z'), [])
        self.assertEqual(latest_known([r], '2026-10-24T00:00:00Z')[('000001', 'A')].nav_date.isoformat(), '2026-04-01')

    def test_invalid_numbers_and_time(self):
        for value in ['NaN', 'Infinity', '-1', '0', True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                NavRecord.from_dict(self.row(unit_nav=value))
        for field, value in [('available_at', '2026-10-23T12:00:00'), ('fund_code', 1),
                             ('raw_sha256', 'bogus'), ('nav_date', '2026-12-01'),
                             ('published_at', '2026-10-24T00:00:00Z'), ('reviewed_by', '')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                NavRecord.from_dict(self.row(**{field: value}))

    def test_distributions_require_explicit_status(self):
        r = NavRecord.from_dict(self.row())
        self.assertIsNone(r.distribution_per_unit)
        for fields in [dict(distribution_per_unit='0'), dict(distribution_status='verified_none'),
                       dict(distribution_status='verified_cash', distribution_per_unit='0')]:
            with self.assertRaises(ValueError):
                NavRecord.from_dict(self.row(**fields))
        NavRecord.from_dict(self.row(distribution_status='verified_cash', distribution_per_unit='0.03'))

    def test_json_and_csv_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ['.json', '.csv']:
                path = Path(tmp) / ('nav' + suffix)
                if suffix == '.json':
                    path.write_text(json.dumps([self.row()]))
                else:
                    with path.open('w', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=self.row().keys()); writer.writeheader(); writer.writerow(self.row())
                records = import_reviewed(path, reviewer='checked', reviewed_at='2026-10-23T12:02:00Z')
                self.assertEqual(records[0].fund_code, '000001')
                self.assertEqual(records[0].reviewed_by, 'checked')

    def test_duplicate_and_unknown_fields_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'nav.json'; p.write_text(json.dumps([self.row(), self.row()]))
            with self.assertRaises(ValueError):
                import_reviewed(p, reviewer='checked', reviewed_at='2026-10-23T12:02:00Z')
        with self.assertRaises(ValueError):
            NavRecord.from_dict(self.row(surprise=1))

    def test_raw_hash_and_roundtrip(self):
        r = NavRecord.from_dict(self.row())
        self.assertTrue(verify_raw_evidence(r, b'fixture'))
        with self.assertRaises(ValueError):
            verify_raw_evidence(r, b'changed')
        self.assertEqual(NavRecord.from_dict(r.to_dict()), r)

    def test_conflicting_revisions_fail(self):
        a = NavRecord.from_dict(self.row())
        b = NavRecord.from_dict(self.row(unit_nav='1.3', source_version='fixture-v2'))
        with self.assertRaises(ValueError):
            latest_known([a, b], '2026-10-24T00:00:00Z')


if __name__ == '__main__':
    unittest.main()
