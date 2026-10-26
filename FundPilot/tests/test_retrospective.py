"""Synthetic fixtures only; no historical market or performance evidence."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest
from fundpilot.retrospective import RetrospectivePoint, assumed_view, predict


class RetrospectiveTests(unittest.TestCase):
    def setUp(self):
        self.sessions = tuple(date(2026, 1, 1) + timedelta(days=i) for i in range(70))
        self.retrieved = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.points = tuple(RetrospectivePoint('SYNTH', s, 100 * 1.01**i,
            self.retrieved, self.retrieved,
            datetime.combine(s+timedelta(days=1), datetime.min.time(), timezone.utc),
            'https://example.org/synthetic', 'a'*64, 'synthetic daily calendar; one-session lag')
            for i, s in enumerate(self.sessions))
        self.decision = datetime(2026, 1, 25, tzinfo=timezone.utc)

    def test_retains_actual_knowledge_time(self):
        row = assumed_view(self.points, self.decision)[-1]
        self.assertEqual(row.session, date(2026, 1, 24))
        self.assertGreater(row.known_available_at, self.decision)
        self.assertEqual(row.retrieved_at, self.retrieved)

    def test_rejects_fake_historical_knowledge(self):
        with self.assertRaises(ValueError):
            replace(self.points[0], known_available_at=self.decision)

    def test_rejects_unverified_total_return(self):
        with self.assertRaises(ValueError):
            replace(self.points[0], basis='total_return')

    def test_rejects_same_day_assumption(self):
        with self.assertRaises(ValueError):
            replace(self.points[0], assumed_available_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_trend_accounts_for_lag(self):
        row = predict(self.points, self.sessions, self.decision, 5, 'trend20')
        self.assertEqual(row['target'], date(2026, 1, 30))
        self.assertAlmostEqual(row['prediction'], 100*1.01**29)
        self.assertEqual(row['basis'], 'raw_nav')

    def test_missing_session_blocks_trend(self):
        self.assertIsNone(predict(self.points[:12]+self.points[13:], self.sessions,
                                  self.decision, 5, 'trend20'))

    def test_future_values_cannot_change_prediction(self):
        changed = tuple(replace(p, value=9999) if p.assumed_available_at > self.decision else p for p in self.points)
        self.assertEqual(predict(changed,self.sessions,self.decision,5,'trend20'),
                         predict(self.points,self.sessions,self.decision,5,'trend20'))

    def test_abstention_is_not_numeric_prediction(self):
        self.assertIsNone(predict(self.points,self.sessions,self.decision,1,'abstain')['prediction'])

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError): assumed_view(self.points+self.points[:1],self.decision)

    def test_no_production_shape(self):
        self.assertFalse(hasattr(self.points[0], 'available_at'))


if __name__ == '__main__': unittest.main()
