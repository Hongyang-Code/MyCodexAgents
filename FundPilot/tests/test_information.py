"""Synthetic records only; evidence attestations are not real source verification."""
from dataclasses import replace
import unittest
from fundpilot.information import Evidence,assess,release_surprise


def evidence(**changes):
    row=dict(evidence_id='synthetic-1',subject='SYNTH-A/class/channel',topic='event',kind='fact',
             source_url='https://example.org/synthetic',raw_sha256='a'*64,version='1',
             event_at='2026-01-01T00:00:00+00:00',first_published_at='2026-01-02T00:00:00+00:00',
             version_published_at='2026-01-02T00:00:00+00:00',revised_at=None,first_available_at=None,
             retrieved_at='2026-01-02T01:00:00+00:00',reviewed_at='2026-01-02T02:00:00+00:00',
             valid_until='2026-01-10T00:00:00+00:00',reviewed=True)
    row.update(changes);return Evidence(**row)


class InformationTests(unittest.TestCase):
    cutoff='2026-01-04T00:00:00+00:00'

    def test_unknown_first_availability_not_backfilled(self):
        r=evidence();self.assertIsNone(r.first_available_at)
        self.assertFalse(r.eligible('2026-01-01T12:00:00+00:00'))
        self.assertTrue(r.eligible(self.cutoff))

    def test_first_availability_requires_evidence(self):
        with self.assertRaises(ValueError):evidence(first_available_at='2026-01-02T00:00:00+00:00')

    def test_revision_does_not_backdate_knowledge(self):
        r=evidence(evidence_id='revision',supersedes='synthetic-1',version='2',
                   revised_at=self.cutoff,version_published_at=self.cutoff,retrieved_at=self.cutoff,reviewed_at=self.cutoff)
        self.assertFalse(r.eligible('2026-01-03T00:00:00+00:00'))
        with self.assertRaises(ValueError):replace(r,supersedes=None)

    def test_time_order_and_timezone(self):
        for change in (dict(reviewed_at='2026-01-01T00:00:00+00:00'),dict(retrieved_at='2026-01-02'),
                       dict(version_published_at='2025-12-01T00:00:00+00:00'),dict(valid_until='2026-01-01T00:00:00+00:00')):
            with self.assertRaises(ValueError):evidence(**change)

    def test_expired_unreviewed_and_opinion_cannot_fill_requirements(self):
        for changes in (dict(kind='opinion'),dict(reviewed=False),dict(valid_until='2026-01-03T00:00:00+00:00')):
            r=evidence(topic='identity',**changes)
            self.assertIn('identity',assess('valuation',r.subject,[r],self.cutoff)['missing'])

    def test_wrong_class_or_channel_does_not_fill(self):
        r=evidence(topic='identity')
        self.assertIn('identity',assess('valuation','different-class',[r],self.cutoff)['missing'])

    def test_expired_revision_does_not_restore_old_fact(self):
        old=evidence(topic='identity')
        new=evidence(evidence_id='new',topic='identity',supersedes=old.evidence_id,valid_until='2026-01-03T00:00:00+00:00')
        self.assertIn('identity',assess('valuation',old.subject,[old,new],self.cutoff)['missing'])

    def test_action_missing_distribution_abstains(self):
        rows=[evidence(evidence_id=t,topic=t) for t in ('identity','nav','fees','dealing','calendar')]
        result=assess('action_research',rows[0].subject,rows,self.cutoff)
        self.assertEqual(result['missing'],['distributions']);self.assertEqual(result['status'],'abstain')
        rows.append(evidence(evidence_id='dist',topic='distributions'))
        result=assess('action_research',rows[0].subject,rows,self.cutoff)
        self.assertEqual(result['status'],'evidence_ready_for_review');self.assertFalse(result['action_authorized'])
        self.assertIsNone(result['probability'])

    def test_unresolved_conflict_abstains_even_with_other_fact(self):
        rows=[evidence(topic='identity'),evidence(evidence_id='other',topic='identity',conflicted=True)]
        self.assertIn('identity',assess('valuation',rows[0].subject,rows,self.cutoff)['missing'])
        self.assertEqual(self.surprise(expected=evidence(conflicted=True))['status'],'unknown')

    def test_expired_conflict_with_valid_facts_stays_blocked(self):
        rows=[evidence(evidence_id=t,topic=t) for t in ('identity','nav')]
        rows.append(evidence(evidence_id='conflict',topic='nav',conflicted=True,
                             valid_until='2026-01-03T00:00:00+00:00'))
        result=assess('valuation',rows[0].subject,rows,self.cutoff)
        self.assertEqual(result['status'],'abstain')
        self.assertEqual(result['missing'],['nav'])

    def test_revision_chain_does_not_imply_conflict_resolution(self):
        old=evidence(evidence_id='conflict',topic='nav',conflicted=True,
                     valid_until='2026-01-03T00:00:00+00:00')
        corrected=evidence(evidence_id='corrected',topic='nav',supersedes=old.evidence_id,
                           version='2',revised_at=self.cutoff,version_published_at=self.cutoff,
                           retrieved_at=self.cutoff,reviewed_at=self.cutoff)
        next_version=replace(corrected,evidence_id='latest',version='3',supersedes='corrected')
        rows=[evidence(evidence_id='identity',topic='identity'),old,corrected,next_version]
        self.assertEqual(assess('valuation',old.subject,rows,self.cutoff)['missing'],['nav'])

    def test_future_or_other_subject_conflict_does_not_block(self):
        rows=[evidence(evidence_id=t,topic=t) for t in ('identity','nav')]
        future=evidence(evidence_id='future',topic='nav',conflicted=True,
                        retrieved_at='2026-01-05T00:00:00+00:00',reviewed_at='2026-01-05T00:00:00+00:00')
        other=evidence(evidence_id='other',subject='other-class',topic='nav',conflicted=True)
        self.assertEqual(assess('valuation',rows[0].subject,rows+[future,other],self.cutoff)['missing'],[])

    def test_exposure_required_for_event_analysis(self):
        rows=[evidence(),evidence(evidence_id='identity',topic='identity')]
        self.assertEqual(assess('event_analysis',rows[0].subject,rows,self.cutoff)['missing'],['exposure'])

    def test_superseded_fact_and_duplicate_ids(self):
        old=evidence(topic='identity')
        new=evidence(evidence_id='new',topic='identity',kind='hypothesis',supersedes=old.evidence_id)
        self.assertIn('identity',assess('valuation',old.subject,[old,new],self.cutoff)['missing'])
        with self.assertRaises(ValueError):assess('valuation',old.subject,[old,old],self.cutoff)

    def surprise(self,**changes):
        expected=evidence();actual=evidence(evidence_id='release',first_published_at='2026-01-03T00:00:00+00:00',
            version_published_at='2026-01-03T00:00:00+00:00',retrieved_at=self.cutoff,reviewed_at=self.cutoff)
        args=dict(expected=expected,actual=actual,expected_value='1',actual_value='2',
                  expected_definition=('metric','period','unit','basis','median'),
                  actual_definition=('metric','period','unit','basis','median'),cutoff=self.cutoff)
        args.update(changes);return release_surprise(**args)

    def test_surprise_comparable_not_probability(self):
        r=self.surprise();self.assertEqual(r['difference'],'1');self.assertIsNone(r['probability'])

    def test_surprise_missing_or_mismatched_unknown(self):
        for change in (dict(actual_value=None),dict(actual_value='NaN'),dict(actual_value=True),
                       dict(actual_definition=('metric','period','other-unit','basis','median')),
                       dict(expected=evidence(reviewed_at=self.cutoff))):
            self.assertEqual(self.surprise(**change)['status'],'unknown')

    def test_revised_release_cannot_be_initial_surprise(self):
        revised=evidence(evidence_id='r',supersedes='old',revised_at=self.cutoff,
            version_published_at=self.cutoff,retrieved_at=self.cutoff,reviewed_at=self.cutoff)
        self.assertEqual(self.surprise(actual=revised)['status'],'unknown')

class DependencyTests(unittest.TestCase):
    def test_fee_rejection_clears_return_rank_and_summary_only(self):
        from fundpilot.information import invalidate_derived
        nodes={'fee':dict(status='rejected',value='bad',dependencies=[]),
               'net':dict(status='valid',value='10',dependencies=['fee']),
               'rank':dict(status='valid',value=1,dependencies=['net']),
               'summary':dict(status='valid',value='best',dependencies=['rank']),
               'nav':dict(status='valid',value='1.2',dependencies=[])}
        result=invalidate_derived(nodes)
        for key in ('fee','net','rank','summary'):self.assertIsNone(result[key]['value'])
        self.assertEqual(result['nav']['value'],'1.2')
        self.assertEqual(nodes['summary']['value'],'best') # Immutable source remains auditable.

    def test_zero_missing_stale_conflict_and_unknown_dependency(self):
        from fundpilot.information import invalidate_derived
        for status in ('valid','missing','stale','conflict'):
            r=invalidate_derived({'x':dict(status=status,value=0,dependencies=[])})
            self.assertEqual(r['x']['status'],status)
            self.assertEqual(r['x']['value'],0 if status=='valid' else None)
        r=invalidate_derived({'x':dict(status='valid',value=1,dependencies=['absent'])})
        self.assertEqual(r['x']['status'],'rejected')

    def test_cycle_rejected(self):
        from fundpilot.information import invalidate_derived
        with self.assertRaises(ValueError):
            invalidate_derived({'x':dict(status='valid',value=1,dependencies=['x'])})

    def test_validation_never_retried_and_budget_degrades(self):
        from fundpilot.information import retry_decision
        self.assertFalse(retry_decision('validation',0,3)['retry'])
        self.assertFalse(retry_decision('permission',0,3)['retry'])
        self.assertTrue(retry_decision('transient',1,3)['retry'])
        self.assertEqual(retry_decision('transient',3,3)['action'],'degrade')

    def test_uncertain_outcomes_and_writes_require_reconcile(self):
        from fundpilot.information import retry_decision
        self.assertEqual(retry_decision('unknown_outcome',0,3)['action'],'reconcile')
        self.assertEqual(retry_decision('transient',0,3,read_only=False)['action'],'reconcile')
