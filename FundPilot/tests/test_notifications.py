from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from fundpilot.notifications import NotificationManager


def event(level='high'):
    return dict(kind='risk', fund_id='SYNTHETIC', reason_code='drawdown',
                action='review', material={'severity': level}, message='Synthetic only',
                valid_until=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.manager = NotificationManager(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_silent_routine_and_recoverable_faults(self):
        for kind in ('hold', 'success', 'weekly_review', 'monthly_review', 'ordinary_volatility', 'critical_fault'):
            self.assertFalse(self.manager.consider(dict(kind=kind))['notify'])
        self.assertEqual(len(self.manager.pending()), 0)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM fp_notice_audit').fetchone()[0], 6)

    def test_fault_requires_both_strict_attestations(self):
        e = event(); e.update(kind='critical_fault', unrecoverable=True, affects_judgment=True)
        self.assertTrue(self.manager.consider(e)['notify'])
        e['unrecoverable'] = 'yes'
        self.assertFalse(self.manager.consider(e)['notify'])

    def test_unchanged_silent_and_material_change_realerts(self):
        first = self.manager.consider(event())
        e = event(); e['message'] = 'Different wording, same decision'; e['run_timestamp'] = 'later'
        self.assertFalse(self.manager.consider(e)['notify'])
        self.assertTrue(self.manager.consider(event('critical'))['notify'])
        self.assertTrue(self.manager.consider(event())['notify'])
        self.assertEqual(len(self.manager.pending()), 1)
        with self.assertRaises(ValueError): self.manager.claim(first['intent_id'])

    def test_claim_no_duplicate_delivery_and_uncertain_reconciliation(self):
        intent = self.manager.consider(event())['intent_id']
        self.manager.claim(intent)
        with self.assertRaises(ValueError): self.manager.claim(intent)
        self.manager.mark_uncertain(intent)
        with self.assertRaises(ValueError): self.manager.claim(intent)
        self.manager.confirm_not_delivered(intent, 'Synthetic provider confirms no send')
        self.manager.claim(intent)
        self.manager.mark_sent(intent, 'synthetic-receipt')
        self.manager.acknowledge(intent)
        with self.assertRaises(ValueError): self.manager.claim(intent)
        self.assertFalse(self.manager.consider(event())['notify'])

    def test_not_sent_before_transport(self):
        intent = self.manager.consider(event())['intent_id']
        with self.assertRaises(ValueError): self.manager.mark_sent(intent, 'invalid-before-claim')
        with self.assertRaises(ValueError): self.manager.acknowledge(intent)
        self.manager.claim(intent)
        with self.assertRaises(ValueError): self.manager.mark_sent(intent, '')
        self.manager.mark_uncertain(intent)
        self.manager.mark_sent(intent, 'verified-after-reconciliation')

    def test_stale_uncertain_not_requeued(self):
        intent = self.manager.consider(event())['intent_id']
        self.manager.claim(intent)
        self.manager.consider(event('critical'))
        self.manager.confirm_not_delivered(intent, 'Synthetic no-send evidence')
        with self.assertRaises(ValueError): self.manager.claim(intent)
        self.assertEqual(len(self.manager.pending()), 1)

    def test_restart_retains_outbox_and_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'synthetic.sqlite'
            c = sqlite3.connect(path); m = NotificationManager(c)
            ident = m.consider(event())['intent_id']; c.close()
            c = sqlite3.connect(path); m = NotificationManager(c)
            self.assertFalse(m.consider(event())['notify'])
            self.assertEqual(m.pending()[0]['intent_id'], ident)
            m.claim(ident); c.close()
            c = sqlite3.connect(path); m = NotificationManager(c)
            with self.assertRaises(ValueError): m.claim(ident)
            c.close()

    def test_all_categories_require_current_aware_expiry(self):
        for kind in ('action', 'risk', 'calibration', 'critical_fault'):
            for expiry in (None, '2000-01-01', '2000-01-01T00:00:00+00:00',
                           '2999-01-01T00:00:00+00:00', '2027-01-01T12:00:00'):
                e = event(); e.update(kind=kind, valid_until=expiry,
                                     unrecoverable=True, affects_judgment=True)
                with self.subTest(kind=kind, expiry=expiry):
                    self.assertFalse(self.manager.consider(e)['notify'])
        self.assertFalse(self.manager.pending())

    def test_expiry_checked_again_at_claim_and_audited(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.manager.clock = lambda: now
        e = event(); e['valid_until'] = (now + timedelta(hours=1)).isoformat()
        ident = self.manager.consider(e)['intent_id']
        now += timedelta(hours=1)
        with self.assertRaises(ValueError): self.manager.claim(ident)
        self.assertEqual(self.connection.execute('SELECT status FROM fp_notice_intents WHERE id=?', (ident,)).fetchone()[0], 'expired')
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM fp_notice_audit WHERE intent_id=? AND decision='expired'", (ident,)).fetchone()[0], 1)

    def test_legacy_pending_without_expiry_fails_closed_preserves_history(self):
        ident = self.manager.consider(event())['intent_id']
        legacy = event(); legacy.pop('valid_until')
        self.connection.execute('UPDATE fp_notice_intents SET event=? WHERE id=?', (json.dumps(legacy), ident))
        self.connection.commit()
        with self.assertRaises(ValueError): self.manager.claim(ident)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM fp_notice_intents').fetchone()[0], 1)
        self.assertFalse(self.manager.pending())

    def test_changed_action_supersedes_old_pending(self):
        first = self.manager.consider(event())['intent_id']
        e = event(); e['action'] = 'reduce'
        self.assertTrue(self.manager.consider(e)['notify'])
        self.assertEqual(len(self.manager.pending()), 1)
        with self.assertRaises(ValueError): self.manager.claim(first)

    def test_resolved_notice_silent_until_recurrence(self):
        ident = self.manager.consider(event())['intent_id']
        self.manager.resolve(ident, 'Synthetic risk resolved')
        self.assertEqual(self.manager.pending(), [])
        self.assertTrue(self.manager.consider(event())['notify'])

    def test_autocommit_connection_and_two_runner_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'synthetic.sqlite'
            c1 = sqlite3.connect(path, isolation_level=None)
            c2 = sqlite3.connect(path, isolation_level=None)
            m1, m2 = NotificationManager(c1), NotificationManager(c2)
            ident = m1.consider(event())['intent_id']
            self.assertFalse(m2.consider(event())['notify'])
            m1.claim(ident)
            with self.assertRaises(ValueError): m2.claim(ident)
            self.assertFalse(c1.in_transaction)
            c1.close(); c2.close()

    def test_invalid_json_and_missing_material_rejected(self):
        e = event(); e['material'] = {'bad': float('nan')}
        with self.assertRaises(ValueError): self.manager.consider(e)
        e = event(); e.pop('material')
        with self.assertRaises(ValueError): self.manager.consider(e)
        self.assertEqual(len(self.manager.pending()), 0)


if __name__ == '__main__':
    unittest.main()
