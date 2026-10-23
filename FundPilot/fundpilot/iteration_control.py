"""Local research contracts. No execution, platform quota enforcement or promotion.

Caller must persist/serialize reservations BEFORE actions, preserve full history,
verify attestations independently, and stop on platform limits. Hidden runtime
calls and account token balance are outside this module's visibility.
"""
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from .market import timestamp

CAPS = {'prediction_batches': 1, 'funds': 3, 'horizons': 3,
        'concurrent_subtasks': 2, 'subtasks': 3, 'source_attempts': 12,
        'transient_retries': 1, 'candidate_interval_days': 7,
        'candidate_evaluations': 1}
ALLOWED_CHANGES = {'research_prompt', 'role_assignment', 'research_workflow'}


def check_config(config):
    if config != CAPS:
        raise ValueError('budget changes require separate authorization; exact policy required')
    if any(type(v) is not int for v in config.values()):
        raise ValueError('integer limits required')
    return True


@dataclass(frozen=True)
class RunBudget:
    # (operation ID, kind, parent ID); unique IDs must survive retries/restarts.
    reservations: tuple = ()
    active: tuple = ()
    stopped: bool = False
    usage: tuple = ()  # (call ID, actual tokens or None), never estimated as actual

    def stop(self):
        """Platform limit, user quota warning or revocation: terminal for this run."""
        return replace(self, stopped=True)

    def reserve(self, operation_id, kind, *, parent=None, failure=None,
                funds=(), horizons=()):
        if self.stopped:
            return self, 'stop'
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError('operation ID required')
        if any(r[0] == operation_id for r in self.reservations):
            return self, 'already_reserved_do_not_execute'
        counts = lambda k: sum(r[1] == k for r in self.reservations)
        if kind == 'prediction_batch':
            if (not funds or len(set(funds)) != len(funds) or len(funds) > CAPS['funds']
                    or not horizons or len(set(horizons)) != len(horizons)
                    or any(type(h) is not int or h not in (1, 5, 20) for h in horizons)):
                raise ValueError('at most three distinct funds and fixed 1/5/20 horizons')
            allowed = counts(kind) < CAPS['prediction_batches'] and parent is None
        elif kind == 'subtask':
            allowed = (parent is None and counts(kind) < CAPS['subtasks']
                       and len(self.active) < CAPS['concurrent_subtasks'])
        elif kind in ('source', 'retry'):
            allowed = counts('source') + counts('retry') < CAPS['source_attempts']
            if kind == 'retry':
                allowed = (allowed and failure == 'transient' and counts('retry') < CAPS['transient_retries']
                           and any(r[0] == parent and r[1] == 'source' for r in self.reservations))
            else:
                allowed = allowed and parent is None
        else:
            raise ValueError('unsupported operation')
        if not allowed:
            return self, 'skip_partial'
        return replace(self, reservations=self.reservations + ((operation_id, kind, parent),),
                       active=self.active + (operation_id,) if kind == 'subtask' else self.active), 'reserved'

    def finish(self, operation_id):
        if operation_id not in self.active:
            raise ValueError('subtask not active')
        return replace(self, active=tuple(x for x in self.active if x != operation_id))

    def record_usage(self, call_id, actual_tokens=None):
        if actual_tokens is not None and (type(actual_tokens) is not int or actual_tokens < 0):
            raise ValueError('actual nonnegative token count or unknown required')
        if not call_id or any(x[0] == call_id for x in self.usage):
            raise ValueError('unique usage ID required')
        return replace(self, usage=self.usage + ((call_id, actual_tokens),))


def register_candidate(protocol, history):
    """Validate against complete prior registrations; never writes or runs code."""
    required = ('candidate_id', 'stable_version', 'candidate_version', 'hypothesis',
                'one_change', 'evidence_hash', 'evaluation_hash', 'counterexample_archive',
                'metric', 'frozen_at', 'evaluation_start', 'kind', 'change_area')
    if any(not isinstance(protocol.get(k), str) or not protocol[k].strip() for k in required):
        raise ValueError('complete frozen protocol required')
    if protocol['change_area'] not in ALLOWED_CHANGES or protocol['kind'] not in ('process', 'prediction'):
        raise ValueError('candidate cannot modify safety, budget, criteria or test set')
    if protocol['stable_version'] == protocol['candidate_version']:
        raise ValueError('isolated candidate version required')
    frozen = timestamp(protocol['frozen_at'])
    if timestamp(protocol['evaluation_start']) <= frozen:
        raise ValueError('freeze before evaluation')
    if protocol.get('direction') not in ('lower', 'higher'):
        raise ValueError('predeclare metric direction')
    for old in history:
        if old['candidate_id'] == protocol['candidate_id']:
            raise ValueError('candidate already registered')
        if frozen - timestamp(old['frozen_at']) < timedelta(days=CAPS['candidate_interval_days']):
            raise ValueError('one candidate per rolling seven days')
    return True


def review_candidate(protocol, result, prior_evaluations=0):
    """Returns a review state only, never switches stable version or investment use.

    Hash/boolean attestations require external evidence inspection. Statistical
    sufficiency is NOT inferred from a win count or caller's confidence.
    """
    if type(prior_evaluations) is not int or prior_evaluations != 0:
        raise ValueError('single candidate evaluation budget exhausted')
    for k in ('evidence_hash', 'evaluation_hash'):
        if result.get(k) != protocol.get(k) or not result.get(k):
            raise ValueError('same evidence and frozen evaluation required')
    if not result.get('counterexample_review') or not result.get('results_ref'):
        raise ValueError('preserve results and counterexample review, including none found')
    if result.get('regression_checks_passed') is not True:
        return 'retain_stable'
    values = []
    for key in ('stable_metric', 'candidate_metric'):
        value = result.get(key)
        if isinstance(value, (bool, float)) or value is None:
            raise ValueError('finite exact metrics required')
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError('finite exact metrics required')
        values.append(number)
    if protocol.get('direction') not in ('lower', 'higher'):
        raise ValueError('invalid frozen direction')
    improved = values[1] < values[0] if protocol['direction'] == 'lower' else values[1] > values[0]
    if not improved:
        return 'retain_stable'
    if protocol['kind'] == 'process':
        return 'process_review_eligible_not_prediction_evidence'
    if protocol['kind'] != 'prediction':
        raise ValueError('unsupported evaluation kind')
    if result.get('data_role') != 'future_unseen' or result.get('mature') is not True:
        return 'pending_future_validation'
    if any(not result.get(k) for k in ('nonoverlap_analysis', 'uncertainty_analysis',
                                       'cost_risk_comparison', 'sample_sufficiency_review')):
        return 'pending_future_validation'
    return 'independent_review_required_no_automatic_promotion'
