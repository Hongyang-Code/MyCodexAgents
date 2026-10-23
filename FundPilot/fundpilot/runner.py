"""Input-driven daily research orchestration, NOT an autonomous data service.

DailyRunner(ledger, output_root, review=None, persist=None, clock=None).run(
    run_id=..., cutoff=aware_ISO, config_version=..., code_commit=...,
    inputs=..., test_only=False, weekly_due=False, monthly_due=False)

All paths must be private and outside a checkout. Local checkpoints are durable
on the current filesystem only; a supplied persistence adapter must prove its
own authorized backend readback. Adapters are trusted application code, never
code extracted from sources. No web, OCR, scheduler, broker, or send transport.

inputs contains portfolio, market, research, experience envelopes, plus optional
proposal, notice, weekly, monthly. Every envelope is {complete: True, payload:
object, evidence: [{source, sha256, available_at, verified_by}]}. These receipts
are caller attestations, not independent proof of source truth. All available_at
values must be <= cutoff. Portfolio payload is RiskAdvisor's explicit context;
portfolio must explicitly include as_of, holdings (with as_of), and available_cash
(null means unknown, never zero). The market payload is {navs: [NavRecord.to_dict()], news: [structured evidence]};
research payload is {observations: [Observation fields], calendar: {sessions,
source}, requests: [{forecast_id, instrument, horizon, model}]}. Empty requests
require an abstention_reason. Experience/weekly/monthly payloads require summary
and evidence; a due review without its envelope blocks completion.

review(report_bytes, manifest) -> {report_sha256, facts: {passed: True, evidence},
textreadable: {passed: True, evidence}, structure: {passed: True, evidence}}.
The adapter must actually perform these separate reviews (TextReadable policy),
not manufacture receipts. persist(manifest) -> {manifest_sha256, verified: True,
receipt, backend, test_only}. For final_persistence the adapter must durably
store the exact manifest + verified receipt alongside its published HEAD; use
recover_committed(manifest, receipt) after restoring that snapshot. The manifest includes immutable report/checkpoint
paths and hashes. Adapter must idempotently publish/read back by manifest hash;
uncertain external operations must be reconciled, never blindly repeated.

Success means this configured input-driven run completed, not deployment,
platform silence, real prediction skill or end-to-end acquisition. test_only
propagates into artifacts/receipts. No bundled production adapters are supplied.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import threading

from .ledger import Ledger, ConflictError, canonical, timestamp, _private_file
from .market import NavRecord, latest_known
from .notifications import NotificationManager
from .research import Observation, TradingCalendar, ForecastEngine, FrozenForecast, Settlement, settle_forecast
from .risk import RiskAdvisor


def _json(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def _plain(value):
    return json.loads(json.dumps(value, default=_json, allow_nan=False))


def _hash(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


def _aware(value):
    return datetime.fromisoformat(timestamp(value))


def _forecast(value):
    data = dict(value)
    for key in ('created_at', 'data_cutoff', 'estimated_verification_at'):
        if data.get(key) is not None:
            data[key] = _aware(data[key])
    for key in ('anchor_session', 'target_session'):
        data[key] = date.fromisoformat(data[key])
    return FrozenForecast(**data)


def _observation(value):
    data = dict(value)
    for key in ('published_at', 'available_at'):
        data[key] = _aware(data[key])
    data['session'] = date.fromisoformat(data['session'])
    return Observation(**data)


def _read_private(path):
    """Read a 0600, singly linked file under a 0700 parent; follow no symlinks."""
    path = Path(os.path.abspath(os.fspath(path)))
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        if stat.S_IMODE(os.fstat(directory).st_mode) != 0o700:
            raise ValueError('recovery evidence parent must be private (0700)')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError('recovery evidence must be a private regular file (0600)')
            return stream.read()
    finally:
        os.close(directory)


class IncompleteRun(ValueError):
    """Missing/unverified input or dependency; never treated as success."""


class DailyRunner:
    def __init__(self, ledger: Ledger, output_root, *, review=None, persist=None, clock=None):
        if ledger.path == ':memory:':
            raise ValueError('daily runs require a persistent ledger')
        self.ledger = ledger
        self._thread_lock = threading.RLock()
        self.root = Path(os.path.abspath(output_root))
        # Reject checkout placement, including a real ancestor reached by symlink.
        for target in (self.root, Path(ledger.path).absolute()):
            if any(((p / '.git').is_file() or (p / '.git' / 'HEAD').is_file()) for p in (target, *target.parents)):
                raise ValueError('private runtime data must be outside a checkout')
        _private_file(self.root / '.runner-lock')
        if stat.S_IMODE(self.root.stat().st_mode) != 0o700:
            raise ValueError('output_root must have mode 0700')
        self.review, self.persist = review, persist
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def last_success(self):
        events = self.ledger.events('run.succeeded')
        return events[-1]['payload'] if events else None

    def _event(self, suffix, kind, payload):
        return self.ledger.append(self.prefix + suffix, kind, _plain(payload), occurred_at=self.cutoff)

    def _envelope(self, inputs, key):
        envelope = inputs.get(key)
        if not isinstance(envelope, dict) or envelope.get('complete') is not True:
            raise IncompleteRun(f'{key}: missing complete verified input')
        evidence = envelope.get('evidence')
        if not isinstance(envelope.get('payload'), dict) or not isinstance(evidence, list) or not evidence:
            raise IncompleteRun(f'{key}: payload and provenance required')
        for item in evidence:
            if (not isinstance(item, dict) or not item.get('source') or not item.get('verified_by')
                    or not isinstance(item.get('sha256'), str) or len(item['sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in item['sha256'])
                    or _aware(item.get('available_at')) > _aware(self.cutoff)):
                raise IncompleteRun(f'{key}: invalid or future provenance')
        return envelope['payload']

    def _step(self, name, fn):
        old = self.ledger.get(self.prefix + 'step:' + name)
        if old:
            return old['payload']['result']
        result = _plain(fn())
        self._event('step:' + name, 'run.step', {'name': name, 'result': result})
        return result

    def _write(self, path, content):
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o600 or path.read_bytes() != content):
                raise ConflictError('immutable report conflicts')
            return
        # Atomic no-replace publication; an interrupted temp never becomes report.
        import tempfile
        fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
            directory = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(temporary)

    def run(self, *, run_id, cutoff, config_version, code_commit, inputs,
            test_only=False, weekly_due=False, monthly_due=False):
        """Resume identical inputs; changed input requires a new run_id.

        All processes sharing this ledger serialize using an advisory OS lock.
        Successfully checkpointed steps/reviews/persistence are never repeated.
        Partial attempts remain audited and do not advance last_success.
        """
        if not all(isinstance(x, str) and x.strip() for x in (run_id, config_version, code_commit)):
            raise ValueError('run ID, config version and code commit required')
        if any(type(x) is not bool for x in (test_only, weekly_due, monthly_due)):
            raise ValueError('explicit boolean flags required')
        cutoff = timestamp(cutoff)
        if _aware(cutoff) > _aware(self.clock().isoformat()):
            raise ValueError('cutoff cannot be in the future')
        if not isinstance(inputs, dict):
            raise ValueError('structured inputs required')
        inputs = _plain(inputs)
        # Lock keyed to ledger, not report root, avoiding cross-root double work.
        lock_path = _private_file(self.ledger.path + '.runner-lock')
        with self._thread_lock, open(lock_path, 'r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._run(run_id, cutoff, config_version, code_commit, inputs,
                             test_only, weekly_due, monthly_due)

    def _run(self, run_id, cutoff, config_version, code_commit, inputs, test_only, weekly_due, monthly_due):
        self.cutoff = cutoff
        self.prefix = 'daily:' + _hash(run_id.encode()) + ':'
        previous = self.ledger.get(self.prefix + 'started')
        started_at = previous['payload']['started_at'] if previous else timestamp(self.clock().isoformat())
        metadata = dict(started_at=started_at, run_id=run_id, cutoff=cutoff, config_version=config_version,
                        code_commit=code_commit, input_sha256=_hash(inputs), test_only=test_only,
                        weekly_due=weekly_due, monthly_due=monthly_due, output_root=str(self.root))
        self._event('started', 'run.started', metadata)
        self._event('inputs', 'run.inputs', {'inputs': inputs, 'test_only': test_only})
        done = self.ledger.get(self.prefix + 'succeeded')
        if done:
            return done['payload']
        results = {}
        try:
            results['portfolio'] = self._step('portfolio', lambda: self._portfolio(inputs))
            results['market'] = self._step('market', lambda: self._market(inputs, results['portfolio']))
            # Freeze new predictions before any outcome settlement processing.
            results['research'] = self._step('research', lambda: self._research(inputs))
            results['settlements'] = self._step('settlements', lambda: self._settlements(inputs))
            results['risk'] = self._step('risk', lambda: RiskAdvisor().evaluate(
                dict(results['portfolio'], evaluation_date=_aware(cutoff).date().isoformat()), inputs.get('proposal')))
            results['experience'] = self._step('experience', lambda: self._summary(inputs, 'experience'))
            for key, due in (('weekly', weekly_due), ('monthly', monthly_due)):
                results[key] = self._step(key, lambda key=key, due=due:
                    {'due': due, 'review': self._summary(inputs, key) if due else None})
            report = self._report(metadata, results)
            folder = self.root / _hash(run_id.encode())
            if not folder.exists():
                folder.mkdir(mode=0o700)
            if folder.is_symlink() or stat.S_IMODE(folder.stat().st_mode) != 0o700:
                raise ValueError('unsafe report directory')
            path = folder / 'report.md'
            self._write(path, report)
            manifest = dict(metadata, report_path=str(path), report_sha256=_hash(report))
            self._event('report', 'run.report', manifest)
            results['review'] = self._step('review', lambda: self._review(report, manifest))
            # Persist a consistent snapshot containing all input provenance,
            # frozen predictions, settlements, review receipts and report hash.
            def persist_step(stage):
                if self.persist is None:
                    raise IncompleteRun('authorized persistence/readback adapter missing')
                def prepare():
                    snapshot = folder / (stage + '-checkpoint.sqlite')
                    if not snapshot.exists():
                        self.ledger.backup(snapshot)
                    request = dict(manifest, stage=stage, checkpoint_path=str(snapshot),
                                   checkpoint_sha256=_hash(snapshot.read_bytes()))
                    if stage == 'final_persistence':
                        request['completion'] = completion
                    request['manifest_sha256'] = _hash(request)
                    return request
                request = self._step(stage + '_manifest', prepare)
                receipt = self.persist(dict(request))
                if (not isinstance(receipt, dict) or receipt.get('verified') is not True
                        or receipt.get('manifest_sha256') != request['manifest_sha256']
                        or receipt.get('test_only') is not test_only
                        or not receipt.get('receipt') or not receipt.get('backend')):
                    raise IncompleteRun('persistence receipt missing/mismatched')
                return {'manifest': request, 'receipt': receipt}
            results['persistence'] = self._step('persistence', lambda: persist_step('persistence'))
            results['notice'] = self._step('notice', lambda: self._notice(inputs, results, manifest))
            completion = dict(metadata, status='succeeded', report_path=str(path),
                              report_sha256=manifest['report_sha256'], notice=results['notice'],
                              scope='input-driven research; not deployment')
            results['final_persistence'] = self._step('final_persistence', lambda: persist_step('final_persistence'))
            outcome = dict(completion, persistence=results['final_persistence'])
            self._event('succeeded', 'run.succeeded', outcome)
            return outcome
        except Exception as exc:
            # No private exception text from arbitrary adapters in public logs.
            attempts = sum(e['event_id'].startswith(self.prefix + 'attempt:') for e in self.ledger.events())
            outcome = dict(metadata, status='partial' if results else 'failed',
                           completed_steps=list(results), error_type=type(exc).__name__,
                           error=str(exc) if isinstance(exc, (IncompleteRun, ValueError)) else 'adapter failure; inspect private adapter logs')
            try:
                folder = self.root / _hash(run_id.encode())
                folder.mkdir(mode=0o700, exist_ok=True)
                if folder.is_symlink() or stat.S_IMODE(folder.stat().st_mode) != 0o700:
                    raise ValueError('unsafe partial report directory')
                partial = folder / ('partial-' + str(attempts) + '.md')
                content = ('# FundPilot 部分/失败运行报告\n\n未经完整审校；不得作为操作建议。\n\n```json\n'
                           + json.dumps({'outcome': outcome, 'completed': results}, ensure_ascii=False,
                                        sort_keys=True, indent=2) + '\n```\n').encode()
                self._write(partial, content)
                outcome['partial_report_path'] = str(partial)
                outcome['partial_report_sha256'] = _hash(content)
            except Exception:
                outcome['partial_report_error'] = 'private report unavailable; ledger remains authoritative'
            self._event('attempt:' + str(attempts), 'run.' + outcome['status'], outcome)
            return outcome

    def recover_committed(self, manifest, receipt, *, local_paths=None):
        """Recover a remotely committed final checkpoint using its readback receipt.

        A snapshot alone intentionally cannot prove upload/HEAD publication. The
        persistence adapter must durably store the exact final manifest and its
        verified receipt beside the immutable snapshot, then return that receipt.
        Recovery first verifies/restores the snapshot with storage.py, retrieves
        the manifest/receipt through the authorized adapter, and calls this method.
        No new external writes occur here. Repeating this import is idempotent.
        Optional local_paths maps report_path/checkpoint_path to relocated private
        files. Only byte lookup changes: original manifest, receipts and success
        evidence remain untouched. Returned local_paths describes local locations;
        last_success remains the original committed evidence. No original path is
        read or written when its replacement is supplied.
        """
        manifest, receipt = _plain(manifest), _plain(receipt)
        unsigned = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
        if (_hash(unsigned) != manifest.get('manifest_sha256')
                or manifest.get('stage') != 'final_persistence'
                or receipt.get('manifest_sha256') != manifest['manifest_sha256']
                or receipt.get('verified') is not True or not receipt.get('receipt')
                or not receipt.get('backend') or type(manifest.get('test_only')) is not bool
                or receipt.get('test_only') is not manifest['test_only']):
            raise ValueError('verified final commit receipt required')
        completion = manifest.get('completion')
        if not isinstance(completion, dict) or completion.get('status') != 'succeeded':
            raise ValueError('final completion record required')
        if local_paths is not None and (not isinstance(local_paths, dict)
                or not set(local_paths).issubset({'report_path', 'checkpoint_path'})):
            raise ValueError('local_paths only accepts report_path/checkpoint_path')
        located = {}
        for kind in ('checkpoint', 'report'):
            key = kind + '_path'
            path = Path(os.path.abspath(os.fspath((local_paths or {}).get(key, manifest[key]))))
            if _hash(_read_private(path)) != manifest.get(kind + '_sha256'):
                raise ValueError('committed ' + kind + ' byte hash mismatch')
            located[key] = str(path)
        run_id = manifest['run_id']
        prefix = 'daily:' + _hash(run_id.encode()) + ':'
        lock_path = _private_file(self.ledger.path + '.runner-lock')
        with self._thread_lock, open(lock_path, 'r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            started = self.ledger.get(prefix + 'started')
            if not started or any(completion.get(k) != v or manifest.get(k) != v for k, v in started['payload'].items()):
                raise ValueError('commit metadata does not match restored run')
            for key in ('portfolio', 'market', 'research', 'settlements', 'risk',
                        'experience', 'weekly', 'monthly', 'review', 'persistence', 'notice'):
                if not self.ledger.get(prefix + 'step:' + key):
                    raise ValueError('incomplete restored checkpoint: ' + key)
            report = self.ledger.get(prefix + 'report')['payload']
            if (completion.get('report_sha256') != report['report_sha256']
                    or manifest.get('report_sha256') != report['report_sha256']
                    or completion.get('notice') != self.ledger.get(prefix + 'step:notice')['payload']['result']):
                raise ValueError('completion/report/notice mismatch')
            self.prefix, self.cutoff = prefix, manifest['cutoff']
            self._event('step:final_persistence_manifest', 'run.step',
                        {'name': 'final_persistence_manifest', 'result': manifest})
            persisted = {'manifest': manifest, 'receipt': receipt}
            self._event('step:final_persistence', 'run.step',
                        {'name': 'final_persistence', 'result': persisted})
            outcome = dict(completion, persistence=persisted)
            self._event('succeeded', 'run.succeeded', outcome)
            return dict(outcome, local_paths=located) if local_paths is not None else outcome

    def _summary(self, inputs, key):
        value = self._envelope(inputs, key)
        if not isinstance(value.get('summary'), str) or not value['summary'].strip():
            raise IncompleteRun(f'{key}: actual review summary missing')
        return {'payload': value, 'provenance': inputs[key]['evidence']}

    def _portfolio(self, inputs):
        data = self._envelope(inputs, 'portfolio')
        if 'available_cash' not in data or not isinstance(data.get('holdings'), list):
            raise IncompleteRun('portfolio: explicit cash (null if unknown) and holdings required')
        cutoff_date = _aware(self.cutoff).date()
        if not data.get('as_of') or date.fromisoformat(data['as_of']) > cutoff_date:
            raise IncompleteRun('portfolio: snapshot date missing or after cutoff')
        for holding in data['holdings']:
            if not holding.get('as_of') or date.fromisoformat(holding['as_of']) > cutoff_date:
                raise IncompleteRun('portfolio: holding date missing or after cutoff')
        if data['available_cash'] is not None:
            cash = Decimal(data['available_cash'])
            if not cash.is_finite() or cash < 0:
                raise IncompleteRun('portfolio: invalid available cash')
        return data

    def _market(self, inputs, portfolio):
        data = self._envelope(inputs, 'market')
        if not isinstance(data.get('navs'), list) or not data['navs'] or not isinstance(data.get('news'), list):
            raise IncompleteRun('market: reviewed NAVs and explicit news coverage required')
        records = [NavRecord.from_dict(row) for row in data['navs']]
        known = latest_known(records, _aware(self.cutoff))
        if len(known) == 0:
            raise IncompleteRun('market: no available NAVs by cutoff')
        valuations = []
        for holding in portfolio.get('holdings', []):
            key = (holding.get('fund_id'), holding.get('share_class'))
            nav = known.get(key)
            if nav is None or holding.get('confirmed') is not True:
                raise IncompleteRun('portfolio: confirmed units/current known NAV identity missing')
            units = Decimal(holding['units'])
            if not units.is_finite() or units < 0:
                raise IncompleteRun('portfolio: invalid units')
            valuations.append(dict(fund_id=key[0], share_class=key[1], units=str(units),
                                   estimated_value=str(units * nav.unit_nav), nav_date=nav.nav_date.isoformat(),
                                   available_at=nav.available_at.isoformat(), account_balance=False))
        return {'navs': [x.to_dict() for x in known.values()], 'valuations': valuations,
                'news': data['news'], 'provenance': inputs['market']['evidence']}

    def _research(self, inputs):
        data = self._envelope(inputs, 'research')
        observations = [_observation(x) for x in data.get('observations', [])]
        if not observations:
            raise IncompleteRun('research: comparable total-return observations missing')
        calendar = TradingCalendar(tuple(date.fromisoformat(x) for x in data['calendar']['sessions']), data['calendar']['source'])
        requests = data.get('requests')
        if not isinstance(requests, list) or (not requests and not data.get('abstention_reason')):
            raise IncompleteRun('research: forecast requests or explicit abstention required')
        forecasts = []
        for request in requests:
            forecast = ForecastEngine().predict(observations=observations, calendar=calendar,
                                                 cutoff=_aware(self.cutoff), **request)
            payload = _plain(asdict(forecast))
            self.ledger.append('forecast:' + forecast.forecast_id, 'forecast.frozen',
                               {'forecast': payload, 'provenance': inputs['research']['evidence']},
                               occurred_at=self.cutoff)
            forecasts.append(payload)
        return {'forecasts': forecasts, 'abstention_reason': data.get('abstention_reason'),
                'provenance': inputs['research']['evidence']}

    def _settlements(self, inputs):
        data = self._envelope(inputs, 'research')
        observations = [_observation(x) for x in data['observations']]
        result = {'settled': [], 'pending': []}
        for event in self.ledger.events('forecast.frozen'):
            forecast = _forecast(event['payload']['forecast'])
            old = self.ledger.get('settlement:' + forecast.forecast_id)
            if old:
                result['settled'].append(dict(old['payload']['settlement'], previously_recorded=True))
                continue
            outcome = settle_forecast(forecast, observations, _aware(self.cutoff))
            if outcome is None:
                result['pending'].append({'forecast_id': forecast.forecast_id,
                                          'reason': 'not_due_or_target_evidence_unavailable'})
                if forecast.target_session <= _aware(self.cutoff).date():
                    raise IncompleteRun('settlements: due target evidence missing')
                continue
            payload = _plain(asdict(outcome))
            self.ledger.append('settlement:' + forecast.forecast_id, 'forecast.settled',
                               {'settlement': payload, 'forecast_event_id': event['event_id'],
                                'provenance': inputs['research']['evidence']}, occurred_at=self.cutoff)
            result['settled'].append(payload)
        return result

    def _review(self, report, manifest):
        if self.review is None:
            raise IncompleteRun('fact/TextReadable/structure review adapter missing')
        proof = self.review(report, dict(manifest))
        if not isinstance(proof, dict) or proof.get('report_sha256') != manifest['report_sha256']:
            raise IncompleteRun('review not bound to frozen report')
        for key in ('facts', 'textreadable', 'structure'):
            if not isinstance(proof.get(key), dict) or proof[key].get('passed') is not True or not proof[key].get('evidence'):
                raise IncompleteRun(f'{key}: verified review missing')
        return proof

    def _notice(self, inputs, results, manifest):
        if 'notice' not in inputs:
            return {'notify': False, 'reason': 'default_hold_no_notice', 'intent_id': None}
        notice = self._envelope(inputs, 'notice')
        kind = notice.get('kind')
        if kind == 'action' and results['risk']['action'] not in ('buy', 'sell'):
            raise IncompleteRun('notice: actionable risk gate not passed')
        if kind not in ('action', 'risk', 'calibration', 'critical_fault'):
            return {'notify': False, 'reason': 'non_actionable', 'intent_id': None}
        if kind != 'action' and notice.get('action') not in ('review', 'calibrate', 'refresh_snapshot', 'resolve_fault'):
            raise IncompleteRun('notice: non-action kind cannot bypass investment action gates')
        if notice.get('claim_verified') is not True:
            raise IncompleteRun('notice: verified claim and message review required')
        # Explicit content coverage even for risk/calibration; use justified N/A,
        # never invented amounts/fees. Separate sender must reverify expiry/claim.
        for field in ('fund_id', 'fund_name', 'basis', 'amount_basis', 'fees', 'timing',
                      'uncertainties', 'user_action', 'valid_until'):
            if not notice.get(field):
                raise IncompleteRun('notice: missing ' + field)
        if kind == 'action':
            risk = results['risk']
            if (notice.get('action') != risk['action'] or notice.get('fund_id') != risk['fund_id']
                    or notice.get('amount') != risk['amount']
                    or notice.get('estimated_fee') != risk['estimated_fee']
                    or _aware(notice['valid_until']).date() > date.fromisoformat(risk['valid_until'])):
                raise IncompleteRun('notice: action/fund/amount mismatch with computed risk decision')
        # User-supplied 'approved' fields cannot replace the configured reviewer.
        message = notice.get('message', '').encode()
        message_manifest = dict(manifest, report_sha256=_hash(message), scope='notification',
                                structured_notice=notice)
        proof = self._review(message, message_manifest)
        notice = dict(notice, review_receipt=proof)
        notice = dict(notice, report_sha256=manifest['report_sha256'], run_id=manifest['run_id'],
                      delivery_requires_run_success=True)
        return NotificationManager(self.ledger.connection, clock=self.clock).consider(notice)

    @staticmethod
    def _report(metadata, results):
        sections = [('本轮状态与数据边界', dict(metadata, status='awaiting_review_and_persistence', data_gaps=[])), ('持仓及现金', results['portfolio']),
                    ('市场与来源', results['market']), ('冻结预测与到期结算',
                     {'research': results['research'], 'settlements': results['settlements']}),
                    ('风险与决策', results['risk']), ('经验与复盘',
                     {k: results[k] for k in ('experience', 'weekly', 'monthly')})]
        text = '# FundPilot 研究报告\n\n输入驱动研究；无自动交易。合成测试：' + str(metadata['test_only']) + '\n'
        for heading, value in sections:
            text += '\n## ' + heading + '\n\n```json\n' + json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, sort_keys=True) + '\n```\n'
        text += ('\n## 质量检查与存储\n\n本正文冻结时审校、私有持久化及通知意向尚待核验；'
                 '最终状态以同一 run_id 的追加审计事件及哈希绑定回执为准。正常持有静默；无发送接口。\n')
        return text.encode('utf-8')
