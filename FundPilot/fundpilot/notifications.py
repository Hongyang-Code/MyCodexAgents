"""Durable notification outbox; no transport and no claim about platform silence.

API::
    manager = NotificationManager(sqlite3.connect(private_database_path))
    decision = manager.consider({
        'kind': 'risk', 'fund_id': 'SYNTHETIC', 'reason_code': 'risk_changed',
        'action': 'review', 'material': {'severity': 'high'},
        'message': 'Synthetic risk; review privately.',
        'valid_until': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    # decision = {notify: bool, reason: str, intent_id: str|None}
    intent = manager.claim(decision['intent_id'])  # pending -> sending, atomic
    # transport MUST use intent['intent_id'] as its idempotency key.
    manager.mark_sent(intent['intent_id'], 'verified-provider-receipt')
    manager.acknowledge(intent['intent_id'])  # optional user acknowledgment

Allowed kinds: action, risk, calibration, critical_fault. critical_fault also
requires unrecoverable=True and affects_judgment=True. All other kinds (including
hold, success, weekly_review, monthly_review) are audited and silent. material
contains ONLY meaningful decision state (no run timestamps); stable reason_code
is required. Changed material creates a fresh intent, including A->B->A changes.
All actionable kinds REQUIRE valid_until as an aware ISO-8601 timestamp; dates
and naive timestamps are rejected. UTC is used for comparison; now >= valid_until
is expired. New intents may live at most 24 hours. This is an outbox safety TTL,
not an investment-rule or market-calendar assumption. Choose a shorter expiry
when the underlying advice expires earlier. The caller must refresh evidence
before creating a replacement. Transport must honor valid_until even after claim.
Legacy pending records missing valid timestamps fail closed at claim/pending;
records and audit history are retained. Sent records remain historical facts.
Runner intents with delivery_requires_run_success=True remain unclaimable until
their exact run_id, report_sha256 and intent_id match an append-only succeeded
event. Pending listing excludes these staged intents; failed publication does
not accidentally release delivery. A newly reviewed run may replace an unsent,
uncommitted prior run without being incorrectly suppressed as unchanged.
Pending intents survive process restarts; sending/uncertain cannot be blindly
retried. Resolve with verified delivery evidence or confirmed-not-delivered.
Call resolve(intent_id, evidence) when a recommendation is withdrawn or resolved;
this silently removes pending delivery and permits a genuine recurrence.
Consumers must reconcile provider status or use provider idempotency before
retrying a sending intent; exactly-once delivery is not promised. This module
never sends messages. Do not expose its private database in a public repository.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import uuid


class NotificationManager:
    def __init__(self, connection: sqlite3.Connection, *, clock=None):
        if connection.in_transaction:
            raise RuntimeError("notification manager requires independent transaction boundaries")
        self.connection = connection
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        connection.executescript('''
        CREATE TABLE IF NOT EXISTS fp_notice_intents (
          id TEXT PRIMARY KEY, topic TEXT NOT NULL, fingerprint TEXT NOT NULL,
          event TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS fp_notice_topics (
          topic TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, intent_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fp_notice_audit (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT,
          decision TEXT NOT NULL, details TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        ''')

    def _now(self):
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('clock must return an aware datetime')
        return now.astimezone(timezone.utc)

    def _expiry_problem(self, event, *, new=False):
        try:
            value = event.get('valid_until')
            if not isinstance(value, str):
                return 'missing_or_invalid_expiry'
            expiry = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if expiry.tzinfo is None or expiry.utcoffset() is None:
                return 'missing_or_invalid_expiry'
            now = self._now()
            if now >= expiry:
                return 'expired'
            if expiry > now + timedelta(hours=24):
                return 'expiry_exceeds_24_hour_limit'
        except (ValueError, TypeError, OverflowError):
            return 'missing_or_invalid_expiry'
        return None

    def _expire_pending(self, intent_id, problem):
        self.connection.execute("UPDATE fp_notice_intents SET status='expired' WHERE id=? AND status='pending'", (intent_id,))
        self.connection.execute('DELETE FROM fp_notice_topics WHERE intent_id=?', (intent_id,))
        self._audit('expired', {'reason': problem}, intent_id)

    def _run_committed(self, intent_id, event):
        """Runner intents stay private/staged until their exact run commits.

        Standalone outbox callers are unaffected. Missing ledger/commit evidence
        fails closed without expiring an otherwise valid pending intent.
        """
        if 'delivery_requires_run_success' not in event:
            return True
        if event['delivery_requires_run_success'] is not True:
            return False
        run_id, report_hash = event.get('run_id'), event.get('report_sha256')
        if not isinstance(run_id, str) or not run_id or not isinstance(report_hash, str) or not report_hash:
            return False
        if not self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
            return False
        event_id = 'daily:' + hashlib.sha256(run_id.encode()).hexdigest() + ':succeeded'
        row = self.connection.execute("SELECT payload FROM events WHERE event_id=? AND kind='run.succeeded'", (event_id,)).fetchone()
        if row is None:
            return False
        try:
            outcome = json.loads(row[0])
            return (outcome.get('status') == 'succeeded' and outcome.get('run_id') == run_id
                    and outcome.get('report_sha256') == report_hash
                    and outcome.get('notice', {}).get('intent_id') == intent_id)
        except (ValueError, TypeError, AttributeError):
            return False

    @contextmanager
    def _transaction(self):
        if self.connection.in_transaction:
            raise RuntimeError('notification operation requires its own transaction boundary')
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def _audit(self, decision, details, intent_id=None):
        self.connection.execute('INSERT INTO fp_notice_audit(intent_id,decision,details) VALUES(?,?,?)',
                                (intent_id, decision, json.dumps(details, sort_keys=True, allow_nan=False)))

    def consider(self, event):
        """Atomically audit and queue, deduplicating material unchanged state."""
        encoded = json.dumps(event, sort_keys=True, separators=(',', ':'), allow_nan=False)
        kind = event.get('kind')
        allowed = kind in ('action', 'risk', 'calibration', 'critical_fault')
        if kind == 'critical_fault':
            allowed = event.get('unrecoverable') is True and event.get('affects_judgment') is True
        # BEGIN IMMEDIATE protects the read/insert pair across independent runners.
        if self.connection.in_transaction:
            raise RuntimeError('consider requires its own transaction boundary')
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            if not allowed:
                self._audit('silent', {'kind': kind, 'reason': 'non_actionable'})
                result = dict(notify=False, reason='non_actionable', intent_id=None)
            elif self._expiry_problem(event, new=True):
                problem = self._expiry_problem(event, new=True)
                self._audit('blocked', {'kind': kind, 'reason': problem})
                result = dict(notify=False, reason=problem, intent_id=None)
            else:
                for field in ('reason_code', 'action', 'material', 'message'):
                    if not event.get(field):
                        raise ValueError(f'notification requires {field}')
                if not isinstance(event['material'], dict):
                    raise ValueError('material must be a semantic state object')
                topic = json.dumps([kind, event.get('fund_id'), event['reason_code']], separators=(',', ':'))
                material = json.dumps({'action': event['action'], 'state': event['material']}, sort_keys=True, separators=(',', ':'), allow_nan=False)
                fingerprint = hashlib.sha256((topic + material).encode()).hexdigest()
                prior = self.connection.execute('SELECT fingerprint,intent_id FROM fp_notice_topics WHERE topic=?', (topic,)).fetchone()
                if prior:
                    old = self.connection.execute('SELECT event,status FROM fp_notice_intents WHERE id=?', (prior[1],)).fetchone()
                    if old and old[1] == 'pending':
                        try:
                            old_event = json.loads(old[0])
                            problem = self._expiry_problem(old_event) if isinstance(old_event, dict) else 'invalid_event'
                        except (ValueError, TypeError):
                            problem = 'invalid_event'
                        if problem:
                            self._expire_pending(prior[1], problem)
                            prior = None
                        elif (event.get('delivery_requires_run_success') is True
                              and old_event.get('delivery_requires_run_success') is True
                              and event.get('run_id') != old_event.get('run_id')
                              and not self._run_committed(prior[1], old_event)):
                            # A failed earlier run must not suppress a newly
                            # reviewed replacement bound to a different commit.
                            self.connection.execute("UPDATE fp_notice_intents SET status='superseded' WHERE id=? AND status='pending'", (prior[1],))
                            self._audit('superseded', {'reason': 'uncommitted_run_replaced'}, prior[1])
                            prior = None
                if prior and prior[0] == fingerprint:
                    self._audit('silent', {'reason': 'unchanged'}, prior[1])
                    result = dict(notify=False, reason='unchanged', intent_id=prior[1])
                else:
                    ident = uuid.uuid4().hex
                    # Supersede old pending notices so stale recommendations cannot
                    # be sent after a newer state. In-flight notices need reconciliation.
                    self.connection.execute("UPDATE fp_notice_intents SET status='superseded' WHERE topic=? AND status='pending'", (topic,))
                    self.connection.execute('INSERT INTO fp_notice_intents(id,topic,fingerprint,event,status) VALUES(?,?,?,?,?)',
                                            (ident, topic, fingerprint, encoded, 'pending'))
                    self.connection.execute('INSERT INTO fp_notice_topics(topic,fingerprint,intent_id) VALUES(?,?,?) ON CONFLICT(topic) DO UPDATE SET fingerprint=excluded.fingerprint,intent_id=excluded.intent_id', (topic, fingerprint, ident))
                    self._audit('queued', {'changed': bool(prior)}, ident)
                    result = dict(notify=True, reason='material_change' if prior else 'new', intent_id=ident)
            self.connection.commit()
            return result
        except BaseException:
            self.connection.rollback()
            raise

    def pending(self):
        result = []
        with self._transaction():
            rows = self.connection.execute(
                "SELECT id,event FROM fp_notice_intents WHERE status='pending' ORDER BY created_at,id").fetchall()
            for ident, encoded in rows:
                try:
                    event = json.loads(encoded)
                    problem = self._expiry_problem(event) if isinstance(event, dict) else 'invalid_event'
                except (ValueError, TypeError):
                    event, problem = None, 'invalid_event'
                if problem:
                    self._expire_pending(ident, problem)
                elif self._run_committed(ident, event):
                    result.append(dict(intent_id=ident, event=event))
        return result

    def claim(self, intent_id):
        problem = None
        with self._transaction():
            row = self.connection.execute('SELECT event,status FROM fp_notice_intents WHERE id=?', (intent_id,)).fetchone()
            if row is None or row[1] != 'pending':
                raise ValueError('intent not pending; reconcile uncertain delivery before retry')
            try:
                event = json.loads(row[0])
                problem = self._expiry_problem(event) if isinstance(event, dict) else 'invalid_event'
            except (ValueError, TypeError):
                event, problem = None, 'invalid_event'
            if problem:
                self._expire_pending(intent_id, problem)
            elif not self._run_committed(intent_id, event):
                problem = 'run_not_committed'
                self._audit('delivery_blocked', {'reason': problem}, intent_id)
            else:
                self.connection.execute("UPDATE fp_notice_intents SET status='sending' WHERE id=? AND status='pending'", (intent_id,))
                self._audit('sending', {}, intent_id)
        # Raise AFTER commit so rejected-expiry audit and transition survive.
        if problem:
            raise ValueError('intent cannot be delivered: ' + problem)
        return dict(intent_id=intent_id, event=event)

    def _transition(self, intent_id, status, allowed, receipt=None):
        with self._transaction():
            query = 'UPDATE fp_notice_intents SET status=?,receipt=COALESCE(?,receipt) WHERE id=? AND status IN (' + ','.join('?' for _ in allowed) + ')'
            if self.connection.execute(query, (status, receipt, intent_id, *allowed)).rowcount != 1:
                raise ValueError('invalid notification transition')
            self._audit(status, {'receipt': receipt}, intent_id)

    def mark_sent(self, intent_id, receipt):
        if not isinstance(receipt, str) or not receipt.strip():
            raise ValueError('verified transport receipt required')
        self._transition(intent_id, 'sent', ('sending', 'uncertain'), receipt)

    def mark_uncertain(self, intent_id):
        self._transition(intent_id, 'uncertain', ('sending',))

    def confirm_not_delivered(self, intent_id, evidence):
        """Only after provider reconciliation; stale topics are superseded."""
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError('delivery reconciliation evidence required')
        with self._transaction():
            row = self.connection.execute('SELECT topic FROM fp_notice_intents WHERE id=?', (intent_id,)).fetchone()
            if row is None:
                raise ValueError('unknown intent')
            current = self.connection.execute('SELECT intent_id FROM fp_notice_topics WHERE topic=?', (row[0],)).fetchone()
            status = 'pending' if current and current[0] == intent_id else 'superseded'
            changed = self.connection.execute("UPDATE fp_notice_intents SET status=? WHERE id=? AND status IN ('sending','uncertain')", (status, intent_id)).rowcount
            if changed != 1:
                raise ValueError('invalid notification transition')
            self._audit('delivery_reconciled', {'evidence': evidence}, intent_id)

    def resolve(self, intent_id, evidence):
        """Withdraw a stale/resolved recommendation; silent, fully audited.

        In-flight transport cannot be recalled here: reconcile it before resolve.
        Clearing latest topic allows recurrence after a genuine resolution.
        """
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError('resolution evidence required')
        with self._transaction():
            changed = self.connection.execute(
                "UPDATE fp_notice_intents SET status='resolved' WHERE id=? AND status IN ('pending','sent','acknowledged','superseded','expired')",
                (intent_id,)).rowcount
            if changed != 1:
                raise ValueError('resolve blocked; reconcile in-flight transport first')
            self.connection.execute('DELETE FROM fp_notice_topics WHERE intent_id=?', (intent_id,))
            self._audit('resolved', {'evidence': evidence}, intent_id)

    def acknowledge(self, intent_id):
        self._transition(intent_id, 'acknowledged', ('sent',))
