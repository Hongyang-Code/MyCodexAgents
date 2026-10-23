"""Local evidence contracts, not a collector, truth oracle or trading approval.

Unknown first publication/availability is retained. Operational knowledge cannot
precede actual retrieval/review; this module never relaxes market.NavRecord.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit
from .market import timestamp

# Requirements are selected by use, not by number of sources or agent votes.
REQUIREMENTS = {
    'valuation': ('identity', 'nav'),
    'event_analysis': ('identity', 'exposure', 'event'),
    'action_research': ('identity', 'nav', 'fees', 'dealing', 'distributions', 'calendar'),
}


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    subject: str  # Full fund/class/channel key, or explicit public macro series.
    topic: str
    kind: str  # fact, opinion, hypothesis
    source_url: str
    raw_sha256: str
    version: str
    event_at: datetime | None
    first_published_at: datetime | None
    version_published_at: datetime | None
    revised_at: datetime | None
    first_available_at: datetime | None
    retrieved_at: datetime
    reviewed_at: datetime
    valid_until: datetime
    reviewed: bool = False
    availability_evidence: str | None = None
    supersedes: str | None = None
    conflicted: bool = False

    def __post_init__(self):
        for name in ('evidence_id', 'subject', 'topic', 'version'):
            if not isinstance(getattr(self,name),str) or not getattr(self,name).strip():
                raise ValueError(name+' required')
        if self.kind not in ('fact','opinion','hypothesis'):
            raise ValueError('invalid evidence kind')
        url=urlsplit(self.source_url)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('public HTTPS provenance required')
        if not re.fullmatch('[0-9a-f]{64}',self.raw_sha256):
            raise ValueError('SHA-256 required')
        for name in ('event_at','first_published_at','version_published_at','revised_at',
                     'first_available_at','retrieved_at','reviewed_at','valid_until'):
            value=getattr(self,name)
            if value is None and name in ('retrieved_at','reviewed_at','valid_until'):
                raise ValueError(name+' required')
            if value is not None: object.__setattr__(self,name,timestamp(value))
        if self.reviewed_at<self.retrieved_at or self.valid_until<self.reviewed_at:
            raise ValueError('review/expiry time order invalid')
        if self.first_published_at and self.version_published_at and self.first_published_at>self.version_published_at:
            raise ValueError('version precedes first publication')
        for value in (self.first_published_at,self.version_published_at,self.revised_at,self.first_available_at):
            if value and value>self.retrieved_at: raise ValueError('claimed publication/availability after retrieval')
        if self.revised_at and (not self.supersedes or self.version_published_at!=self.revised_at):
            raise ValueError('revision needs prior evidence ID and exact version timestamp')
        if self.first_available_at and (not self.availability_evidence or not self.availability_evidence.strip()):
            raise ValueError('first availability needs independently reviewed evidence reference')
        if self.first_available_at and self.first_published_at and self.first_available_at<self.first_published_at:
            raise ValueError('availability precedes publication')
        if self.supersedes==self.evidence_id: raise ValueError('self revision')

    @property
    def known_at(self):
        return max(self.retrieved_at,self.reviewed_at)

    def eligible(self,cutoff):
        cutoff=timestamp(cutoff)
        return self.reviewed is True and self.known_at<=cutoff<=self.valid_until


def assess(purpose,subject,records,cutoff):
    """Additional evidence gate only; never authorizes an amount or operation."""
    if purpose not in REQUIREMENTS: raise ValueError('unsupported decision purpose')
    ids=[r.evidence_id for r in records]
    if len(set(ids))!=len(ids): raise ValueError('duplicate evidence IDs')
    known=[r for r in records if r.subject==subject and r.reviewed is True and r.known_at<=timestamp(cutoff)]
    visible=[r for r in known if r.eligible(cutoff)]
    # Expiry of a revision must not resurrect its superseded facts.
    superseded={r.supersedes for r in known if r.supersedes}
    facts=[r for r in visible if r.kind=='fact' and r.evidence_id not in superseded]
    # Known unresolved conflicts survive expiry and ordinary version replacement.
    # This schema has no reviewed resolution event: supersedes is not one.
    conflicts={r.topic for r in known if r.conflicted is not False}
    missing=[topic for topic in REQUIREMENTS[purpose] if topic in conflicts or not any(r.topic==topic for r in facts)]
    return dict(purpose=purpose,subject=subject,status='abstain' if missing else 'evidence_ready_for_review',
                missing=missing,evidence_ids=[r.evidence_id for r in facts],probability=None,
                action_authorized=False,limitations=['Schema/review attestations do not establish source truth',
                'Macro transmission remains a hypothesis; exposure can be stale',
                'Existing account, risk and trading gates remain required'])


def release_surprise(expected,actual,expected_value,actual_value,*,expected_definition,actual_definition,cutoff):
    """Difference only for a frozen comparable pre-release expectation; no probability.

    Definition = (metric, reference period, unit, adjustment basis, statistic).
    Caller must inspect evidence for these exact definitions and values.
    """
    unknown=lambda reason:dict(status='unknown',difference=None,reason=reason,probability=None)
    if expected.conflicted is not False or actual.conflicted is not False:return unknown('unresolved_conflict')
    if not expected.eligible(cutoff) or not actual.eligible(cutoff):return unknown('unavailable_or_stale')
    if expected.kind!='fact' or actual.kind!='fact':return unknown('opinion_or_hypothesis')
    if expected.subject!=actual.subject:return unknown('different_subject')
    if not actual.first_published_at or expected.known_at>=actual.first_published_at:
        return unknown('expectation_not_known_before_release')
    if actual.revised_at or actual.version_published_at!=actual.first_published_at:
        return unknown('initial_release_vintage_not_verified')
    if (not isinstance(expected_definition,tuple) or len(expected_definition)!=5 or
            not all(isinstance(x,str) and x.strip() for x in expected_definition) or expected_definition!=actual_definition):
        return unknown('incomparable_definition')
    try:
        if isinstance(expected_value,(bool,float)) or isinstance(actual_value,(bool,float)):raise ValueError()
        a,b=Decimal(expected_value),Decimal(actual_value)
        if not a.is_finite() or not b.is_finite():raise ValueError()
    except (InvalidOperation,TypeError,ValueError):return unknown('missing_or_invalid_values')
    return dict(status='comparable_difference',difference=str(b-a),probability=None,
                evidence_ids=[expected.evidence_id,actual.evidence_id],
                interpretation='Actual minus documented expectation; not a return forecast or causal proof')


def invalidate_derived(nodes):
    """Copy a declared dependency DAG and clear invalid derived values transitively.

    Node: {status, value, dependencies:[ids]}. No hidden dependencies are inferred.
    Original evidence is untouched. All consumers must use returned values.
    """
    result={};visiting=set()
    allowed={'valid','missing','stale','conflict','rejected'}
    def visit(key):
        if key in result:return result[key]
        if key in visiting:raise ValueError('dependency cycle')
        if key not in nodes:return dict(status='missing',value=None,blocked_by=[key])
        visiting.add(key);node=nodes[key]
        if node.get('status') not in allowed or not isinstance(node.get('dependencies'),list):
            raise ValueError('explicit status and dependencies required')
        blocked=[dep for dep in node['dependencies'] if visit(dep)['status']!='valid']
        status=node['status']
        if blocked:status='rejected'
        if status=='valid' and node.get('value') is None:status='missing'
        result[key]=dict(status=status,value=node.get('value') if status=='valid' else None,blocked_by=blocked)
        visiting.remove(key);return result[key]
    for key in nodes:visit(key)
    return result


def retry_decision(failure,attempts,max_attempts,*,read_only=True):
    """Pure policy only: no network, sleeps, callbacks or repeated ledger writes."""
    if any(type(n) is not int or n<0 for n in (attempts,max_attempts)) or max_attempts<1:
        raise ValueError('explicit finite attempt budget required')
    if failure not in ('transient','validation','permission','unknown_outcome'):
        raise ValueError('classify failure before retry')
    if failure=='unknown_outcome' or read_only is not True:
        return dict(action='reconcile',retry=False,reason='verify prior outcome; never replay writes blindly')
    if failure!='transient':return dict(action='degrade',retry=False,reason=failure)
    if attempts>=max_attempts:return dict(action='degrade',retry=False,reason='budget_exhausted')
    return dict(action='retry_read',retry=True,reason='bounded transient read retry')
