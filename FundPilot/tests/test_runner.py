"""All fixtures/adapters here are SYNTHETIC, test_only; no real market claims."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from fundpilot.ledger import Ledger, ConflictError
from fundpilot.runner import DailyRunner

AT = '2026-01-05T13:30:00+00:00'

def envelope(payload):
    return {'complete': True, 'payload': payload, 'evidence': [dict(
        source='synthetic:test_only', sha256='a'*64, available_at=AT, verified_by='synthetic-fixture')]}

def inputs():
    nav = dict(fund_code='000001', share_class='A', nav_date='2026-01-05',
               unit_nav='2', source_url='https://synthetic.invalid/nav', source_version='test_only',
               raw_sha256='a'*64, retrieved_at=AT, available_at=AT, reviewed_at=AT,
               reviewed_by='synthetic-fixture')
    observation = dict(observation_id='synthetic-obs', instrument='000001:A', session='2026-01-05',
                       value=2, published_at=AT, available_at=AT, source='synthetic:test_only')
    return dict(portfolio=envelope(dict(as_of='2026-01-05', available_cash='5', holdings=[dict(fund_id='000001',
                        share_class='A', units='3', confirmed=True, as_of='2026-01-05')])),
                market=envelope(dict(navs=[nav], news=[{'scope': 'synthetic news coverage only'}])),
                research=envelope(dict(observations=[observation], calendar=dict(
                    sessions=['2026-01-05', '2026-01-06'], source='synthetic-calendar'),
                    requests=[dict(forecast_id='synthetic-f1', instrument='000001:A', horizon=1, model='no_direction')])),
                experience=envelope(dict(summary='Synthetic candidate retained; no proven skill.')))

def review(content, manifest):
    assert hashlib.sha256(content).hexdigest() == manifest['report_sha256']
    return dict(report_sha256=manifest['report_sha256'], **{
        k: {'passed': True, 'evidence': 'synthetic-test-only-review'}
        for k in ('facts', 'textreadable', 'structure')})

def persist(manifest):
    # Deliberately only a local test adapter, NOT proof of cloud deployment.
    for kind in ('checkpoint', 'report'):
        assert hashlib.sha256(Path(manifest[kind+'_path']).read_bytes()).hexdigest() == manifest[kind+'_sha256']
    return dict(manifest_sha256=manifest['manifest_sha256'], verified=True,
                receipt='synthetic-readback', backend='test_only_local', test_only=True)


class DailyRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = Ledger(self.root/'state.sqlite')
        self.runner = DailyRunner(self.ledger, self.root/'reports', review=review, persist=persist,
                                  clock=lambda: datetime.fromisoformat(AT))

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def run_daily(self, **changes):
        args = dict(run_id='synthetic-run', cutoff=AT, config_version='test-only-v1',
                    code_commit='synthetic-commit', inputs=inputs(), test_only=True)
        args.update(changes)
        return self.runner.run(**args)

    def test_complete_synthetic_run_silent_and_private(self):
        result = self.run_daily()
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertFalse(result['notice']['notify'])
        report = Path(result['report_path'])
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)
        self.assertEqual(report.parent.stat().st_mode & 0o777, 0o700)
        self.assertIn('冻结预测与到期结算', report.read_text())
        self.assertEqual(len(self.ledger.events('forecast.frozen')), 1)
        self.assertEqual(self.runner.last_success['run_id'], 'synthetic-run')
        self.assertEqual(self.ledger.events('run.inputs')[0]['payload']['inputs'], inputs())

    def test_missing_data_fails_closed(self):
        result = self.run_daily(inputs={})
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(self.runner.last_success)
        self.assertEqual(len(self.ledger.events('run.started')), 1)

    def test_missing_review_then_resume_no_repeat_forecast(self):
        self.runner.review = None
        self.assertEqual(self.run_daily()['status'], 'partial')
        self.assertIsNone(self.runner.last_success)
        self.runner.review = review
        result = self.run_daily()
        self.assertEqual(result['status'], 'succeeded', result)
        version = self.ledger.version
        self.assertEqual(self.run_daily(), result)
        self.assertEqual(self.ledger.version, version)
        self.assertEqual(len(self.ledger.events('forecast.frozen')), 1)

    def test_persistence_failure_stable_manifest_and_no_success(self):
        seen = []
        def failing(manifest):
            seen.append(manifest['manifest_sha256'])
            raise RuntimeError('synthetic transient error')
        self.runner.persist = failing
        self.assertEqual(self.run_daily()['status'], 'partial')
        self.assertEqual(self.run_daily()['status'], 'partial')
        self.assertEqual(seen[0], seen[1])
        self.assertIsNone(self.runner.last_success)
        self.runner.persist = persist
        self.assertEqual(self.run_daily()['status'], 'succeeded')

    def test_changed_inputs_conflict(self):
        self.run_daily()
        changed = inputs()
        changed['portfolio']['payload']['available_cash'] = '7'
        with self.assertRaises(ConflictError):
            self.run_daily(inputs=changed)

    def test_due_reviews_missing_block(self):
        result = self.run_daily(weekly_due=True, monthly_due=True)
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(self.runner.last_success)

    def test_due_reviews_supplied(self):
        data = inputs()
        data['weekly'] = envelope({'summary': 'Synthetic weekly internal review'})
        data['monthly'] = envelope({'summary': 'Synthetic monthly internal review; no promotion'})
        result = self.run_daily(inputs=data, weekly_due=True, monthly_due=True)
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertFalse(result['notice']['notify'])

    def test_future_evidence_blocks(self):
        data = inputs()
        data['market']['evidence'][0]['available_at'] = '2026-01-06T00:00:00+00:00'
        self.assertEqual(self.run_daily(inputs=data)['status'], 'partial')
        self.assertIsNone(self.runner.last_success)

    def test_bad_review_hash_blocks(self):
        self.runner.review = lambda *args: {'report_sha256': 'bad'}
        self.assertEqual(self.run_daily()['status'], 'partial')
        self.assertIsNone(self.runner.last_success)

    def test_naive_cutoff_rejected(self):
        with self.assertRaises(ValueError):
            self.run_daily(cutoff='2026-01-05T13:30:00')

    def test_notice_verified_and_deduplicated(self):
        data = inputs()
        notice = dict(kind='risk', claim_verified=True, review_evidence=dict(message_sha256=hashlib.sha256(b'Synthetic review only').hexdigest(), **{k: {'passed': True, 'evidence': 'synthetic-review'} for k in ('facts', 'textreadable', 'structure')}),
                      fund_id='000001', fund_name='SYNTHETIC', basis='synthetic verified event',
                      amount_basis='N/A: review only', fees='N/A: no transaction', timing='review only',
                      uncertainties=['synthetic'], user_action='review', valid_until='2026-01-05T14:30:00+00:00',
                      action='review', reason_code='synthetic-risk', material={'severity': 'high'}, message='Synthetic review only')
        data['notice'] = envelope(notice)
        first = self.run_daily(inputs=data)
        self.assertEqual(first['status'], 'succeeded', first)
        self.assertTrue(first['notice']['notify'])
        self.assertEqual(self.run_daily(inputs=data), first)
        # Different run, unchanged material: no second notice.
        data['research']['payload']['requests'] = []
        data['research']['payload']['abstention_reason'] = 'synthetic abstention'
        second = self.run_daily(run_id='synthetic-run2', inputs=data)
        self.assertEqual(second['status'], 'succeeded', second)
        self.assertFalse(second['notice']['notify'])
        self.assertEqual(self.ledger.connection.execute('SELECT count(*) FROM fp_notice_intents').fetchone()[0], 1)

    def test_unverified_notice_blocked(self):
        data = inputs()
        data['notice'] = envelope(dict(kind='risk'))
        self.assertEqual(self.run_daily(inputs=data)['status'], 'partial')
        self.assertIsNone(self.runner.last_success)

    def test_concurrent_run_does_not_duplicate(self):
        def worker(_):
            with Ledger(self.root/'state.sqlite') as ledger:
                runner = DailyRunner(ledger, self.root/'reports', review=review, persist=persist)
                return runner.run(run_id='concurrent-test', cutoff=AT, config_version='test',
                                  code_commit='synthetic', inputs=inputs(), test_only=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]['status'], 'succeeded', results)
        self.assertEqual(len(self.ledger.events('run.started')), 1)
        self.assertEqual(len(self.ledger.events('forecast.frozen')), 1)

    def test_no_overwrite_conflicting_report(self):
        self.runner.review = None
        result = self.run_daily()
        path = next((self.root/'reports').glob('*/report.md'))
        path.write_text('synthetic tampered file')
        self.runner.review = review
        result = self.run_daily()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(path.read_text(), 'synthetic tampered file')
        self.assertIsNone(self.runner.last_success)

    def test_future_cutoff_and_holding_rejected(self):
        self.runner.clock = lambda: datetime(2025, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            self.run_daily()
        self.runner.clock = lambda: datetime.fromisoformat(AT)
        data = inputs()
        data['portfolio']['payload']['holdings'][0]['as_of'] = '2099-01-01'
        self.assertEqual(self.run_daily(inputs=data)['status'], 'failed')
        self.assertIsNone(self.runner.last_success)

    def test_missing_persistence_does_not_succeed(self):
        self.runner.persist = None
        result = self.run_daily()
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(self.runner.last_success)
        self.assertTrue(Path(result['partial_report_path']).exists())

    def test_settlement_payload_and_provenance_survive_restart(self):
        self.assertEqual(self.run_daily()['status'], 'succeeded')
        at = '2026-01-06T13:30:00+00:00'
        data = inputs()
        data['research']['payload']['requests'] = []
        data['research']['payload']['abstention_reason'] = 'Synthetic no new prediction'
        data['research']['payload']['observations'].append(dict(
            observation_id='synthetic-outcome', instrument='000001:A', session='2026-01-06',
            value=2.2, published_at=at, available_at=at, source='synthetic:test_only'))
        self.runner.clock = lambda: datetime.fromisoformat(at)
        result = self.run_daily(run_id='synthetic-day2', cutoff=at, inputs=data)
        self.assertEqual(result['status'], 'succeeded', result)
        settled = self.ledger.events('forecast.settled')
        self.assertEqual(len(settled), 1)
        self.assertAlmostEqual(settled[0]['payload']['settlement']['actual_return'], 0.1)
        self.assertEqual(settled[0]['payload']['forecast_event_id'], 'forecast:synthetic-f1')
        self.assertTrue(settled[0]['payload']['provenance'])
        with Ledger(self.root/'state.sqlite') as reloaded:
            runner = DailyRunner(reloaded, self.root/'reports', review=review, persist=persist)
            self.assertEqual(runner.last_success['run_id'], 'synthetic-day2')

    def test_final_snapshot_plus_commit_receipt_recovers_success(self):
        import shutil
        completed = self.run_daily()
        final = completed['persistence']
        restored = self.root/'restored.sqlite'
        shutil.copy2(final['manifest']['checkpoint_path'], restored)
        with Ledger(restored) as ledger:
            runner = DailyRunner(ledger, self.root/'reports', review=review, persist=persist)
            self.assertIsNone(runner.last_success)  # snapshot alone is not a publish receipt
            recovered = runner.recover_committed(final['manifest'], final['receipt'])
            self.assertEqual(recovered, completed)
            self.assertEqual(runner.last_success, completed)
            version = ledger.version
            self.assertEqual(runner.recover_committed(final['manifest'], final['receipt']), completed)
            self.assertEqual(ledger.version, version)
            bad = dict(final['receipt'], manifest_sha256='bad')
            with self.assertRaises(ValueError):
                runner.recover_committed(final['manifest'], bad)

    def test_later_partial_does_not_advance_last_success(self):
        self.assertEqual(self.run_daily()['status'], 'succeeded')
        self.assertEqual(self.run_daily(run_id='synthetic-failed', inputs={})['status'], 'failed')
        self.assertEqual(self.runner.last_success['run_id'], 'synthetic-run')

    def test_risk_notice_cannot_bypass_action_gate(self):
        data = inputs()
        data['notice'] = envelope(dict(kind='risk', action='buy', claim_verified=True))
        result = self.run_daily(inputs=data)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('cannot bypass', result['error'])
        self.assertIsNone(self.runner.last_success)

    def test_recover_committed_relocated_paths_preserve_original_evidence(self):
        import shutil
        completed = self.run_daily()
        final = completed['persistence']
        original = copy.deepcopy(final)
        with tempfile.TemporaryDirectory() as destination:
            target = Path(destination)
            local_paths = {}
            for key in ('checkpoint_path', 'report_path'):
                local = target/Path(final['manifest'][key]).name
                shutil.copy2(final['manifest'][key], local)
                local_paths[key] = str(local)
                Path(final['manifest'][key]).unlink()  # original workspace is unavailable
            shutil.copy2(local_paths['checkpoint_path'], target/'restored.sqlite')
            with Ledger(target/'restored.sqlite') as ledger:
                runner = DailyRunner(ledger, target/'new-reports')
                recovered = runner.recover_committed(final['manifest'], final['receipt'], local_paths=local_paths)
                self.assertEqual(recovered['local_paths'], local_paths)
                self.assertEqual(runner.last_success, completed)
                self.assertEqual(final, original)
                version = ledger.version
                self.assertEqual(runner.recover_committed(final['manifest'], final['receipt'],
                                                          local_paths=local_paths), recovered)
                self.assertEqual(ledger.version, version)

    def test_relocated_recovery_rejects_tampered_bytes(self):
        import shutil
        completed = self.run_daily()
        final = completed['persistence']
        with tempfile.TemporaryDirectory() as destination:
            target = Path(destination)
            checkpoint, report = target/'checkpoint.sqlite', target/'report.md'
            shutil.copy2(final['manifest']['checkpoint_path'], checkpoint)
            shutil.copy2(checkpoint, target/'restored.sqlite')
            shutil.copy2(final['manifest']['report_path'], report)
            report.write_bytes(b'synthetic tampered report')
            with Ledger(target/'restored.sqlite') as ledger:
                runner = DailyRunner(ledger, target/'reports')
                with self.assertRaisesRegex(ValueError, 'byte hash mismatch'):
                    runner.recover_committed(final['manifest'], final['receipt'], local_paths={
                        'checkpoint_path': checkpoint, 'report_path': report})
                self.assertIsNone(runner.last_success)

    def test_relocated_recovery_rejects_nonprivate_or_symlink(self):
        import shutil
        completed = self.run_daily()
        final = completed['persistence']
        with tempfile.TemporaryDirectory() as destination:
            target = Path(destination)
            report = target/'report.md'
            shutil.copy2(final['manifest']['report_path'], report)
            report.chmod(0o644)
            with self.assertRaises(ValueError):
                self.runner.recover_committed(final['manifest'], final['receipt'],
                                              local_paths={'report_path': report})
            report.chmod(0o600)
            alias = target/'alias.md'
            alias.symlink_to(report)
            with self.assertRaises(OSError):
                self.runner.recover_committed(final['manifest'], final['receipt'],
                                              local_paths={'report_path': alias})

if __name__ == '__main__':
    unittest.main()
