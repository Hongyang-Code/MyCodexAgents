"""Independent adversarial regression checks; all data is synthetic."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fundpilot.ledger import Ledger
from fundpilot.portfolio import PortfolioManager
from fundpilot.notifications import NotificationManager
from fundpilot.storage import pack, restore


class IndependentSafetyTests(unittest.TestCase):
    def test_old_snapshot_cannot_restore_spent_cash(self):
        proof = {'source': 'synthetic', 'confidence': {'as_of': '1', 'positions': '1', 'cash': '1'}}
        with Ledger(':memory:') as ledger:
            portfolio = PortfolioManager(ledger)
            snapshot = {'as_of': '2026-01-01T00:00:00Z', 'positions': [], 'cash': '100'}
            portfolio.import_snapshot('first', snapshot, proof)
            portfolio.submit_trade('buy', 'buy', '000001', amount='100', evidence=proof)
            portfolio.confirm_trade('buy', units='100', evidence=proof)
            before = portfolio.state()
            with self.assertRaises(ValueError):
                portfolio.import_snapshot('old-copy', snapshot, proof)
            self.assertEqual(portfolio.state(), before)

    def test_expired_action_cannot_be_claimed(self):
        manager = NotificationManager(sqlite3.connect(':memory:'))
        event = {'kind': 'action', 'fund_id': '000001', 'reason_code': 'synthetic',
                 'action': 'buy', 'material': {'severity': 'high'},
                 'message': 'Synthetic advisory only', 'valid_until': '2000-01-01'}
        try:
            decision = manager.consider(event)
        except ValueError:
            return  # Rejecting before enqueue is equally safe.
        if decision['notify']:
            with self.assertRaises(ValueError):
                manager.claim(decision['intent_id'])
        self.assertEqual(manager.pending(), [])

    def test_private_snapshot_permissions_independent_of_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            (source / 'private.json').write_text('{"synthetic":true}')
            previous = os.umask(0o022)
            try:
                output = root / 'private.zip'
                result = pack(source, output, run_id='synthetic', test_only=True)
                restored = root / 'restored'
                restore(output, restored, expected_sha=result['sha256'], allow_test=True)
            finally:
                os.umask(previous)
            self.assertEqual(output.stat().st_mode & 0o077, 0)
            self.assertEqual(restored.stat().st_mode & 0o077, 0)
            self.assertEqual((restored / 'private.json').stat().st_mode & 0o077, 0)


class IndependentRunnerDeliveryTests(unittest.TestCase):
    def test_final_persistence_failure_blocks_delivery_then_receipt_recovers(self):
        import hashlib
        import shutil
        from datetime import datetime
        from fundpilot.runner import DailyRunner
        from test_runner import inputs, envelope, review, persist, AT
        data = inputs()
        message = 'Synthetic reviewed risk'
        proof = dict(message_sha256=hashlib.sha256(message.encode()).hexdigest(), **{
            key: {'passed': True, 'evidence': 'synthetic'} for key in ('facts', 'textreadable', 'structure')})
        data['notice'] = envelope(dict(kind='risk', claim_verified=True, review_evidence=proof,
            fund_id='000001', fund_name='SYNTHETIC', basis='synthetic', amount_basis='N/A',
            fees='N/A', timing='review', uncertainties=['synthetic'], user_action='review',
            valid_until='2026-01-05T14:30:00+00:00', action='review', reason_code='synthetic',
            material={'severity': 'high'}, message=message))
        captured = {}
        def fail_final(manifest):
            if manifest['stage'] == 'final_persistence':
                captured.update(manifest)
                raise RuntimeError('synthetic publish failure')
            return persist(manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Ledger(root/'ledger.sqlite') as ledger:
                runner = DailyRunner(ledger, root/'reports', review=review, persist=fail_final,
                                     clock=lambda: datetime.fromisoformat(AT))
                result = runner.run(run_id='delivery-boundary', cutoff=AT, config_version='test',
                                    code_commit='synthetic', inputs=data, test_only=True)
                self.assertEqual(result['status'], 'partial', result)
                ident = ledger.connection.execute('SELECT id FROM fp_notice_intents').fetchone()[0]
                manager = NotificationManager(ledger.connection, clock=lambda: datetime.fromisoformat(AT))
                self.assertEqual(manager.pending(), [])
                with self.assertRaisesRegex(ValueError, 'run_not_committed'):
                    manager.claim(ident)
                self.assertEqual(ledger.connection.execute('SELECT status FROM fp_notice_intents').fetchone()[0], 'pending')
                restored_path = root/'restored.sqlite'
                shutil.copy2(captured['checkpoint_path'], restored_path)
                with Ledger(restored_path) as restored:
                    recovered = DailyRunner(restored, root/'reports', clock=lambda: datetime.fromisoformat(AT))
                    notices = NotificationManager(restored.connection, clock=lambda: datetime.fromisoformat(AT))
                    self.assertEqual(notices.pending(), [])
                    recovered.recover_committed(captured, persist(captured))
                    self.assertEqual(notices.claim(ident)['intent_id'], ident)

    def test_failed_run_does_not_suppress_reviewed_new_run(self):
        from datetime import datetime
        import hashlib
        now = datetime.fromisoformat('2026-01-05T13:30:00+00:00')
        with Ledger(':memory:') as ledger:
            manager = NotificationManager(ledger.connection, clock=lambda: now)
            event = dict(kind='risk', fund_id='000001', reason_code='synthetic', action='review',
                         material={'severity': 'high'}, message='Synthetic',
                         valid_until='2026-01-05T14:30:00+00:00',
                         delivery_requires_run_success=True, run_id='failed', report_sha256='a'*64)
            first = manager.consider(event)
            replacement = dict(event, run_id='new-reviewed-run', report_sha256='b'*64)
            second = manager.consider(replacement)
            self.assertTrue(second['notify'])
            self.assertNotEqual(first['intent_id'], second['intent_id'])
            ledger.append('daily:' + hashlib.sha256(replacement['run_id'].encode()).hexdigest() + ':succeeded',
                          'run.succeeded', dict(run_id=replacement['run_id'], status='succeeded',
                            report_sha256=replacement['report_sha256'], notice=second))
            self.assertEqual(manager.claim(second['intent_id'])['intent_id'], second['intent_id'])
            with self.assertRaises(ValueError):
                manager.claim(first['intent_id'])
