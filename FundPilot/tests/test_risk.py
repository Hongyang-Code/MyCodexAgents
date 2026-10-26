import copy
import unittest
from decimal import Decimal
from fundpilot.risk import FeeBand, FeeSchedule, RiskAdvisor, decimal


def valid():
    context = dict(confirmed=True, horizon_months='24', max_loss_fraction='0.1',
                   risk_preference='synthetic', other_restrictions_confirmed=True,
                   holdings=[dict(fund_id='SYNTHETIC', share_class='A', units='10',
                                  confirmed=True, as_of='2026-01-02')], as_of='2026-01-02',
                   evaluation_date='2026-01-02', cash_confirmed=True, available_cash='20',
                   trading_rules_confirmed=True, validation_passed=True)
    p = dict(action='buy', fund_id='SYNTHETIC', amount='5', estimated_fee='0.01',
             conservative_expected_benefit='0.02', evidence=['synthetic'],
             valid_until='2026-01-03', rules_effective_from='2026-01-01',
             rules_effective_until='2026-01-03', rules_source='synthetic',
             trading_timing='synthetic calendar', uncertainties=['unknown NAV'])
    for key in ('fund_identity_confirmed', 'rules_current', 'validated', 'risk_within_limits',
                'fees_confirmed', 'timing_confirmed', 'restrictions_satisfied', 'market_calendar_confirmed'):
        p[key] = True
    return context, p


class RiskTests(unittest.TestCase):
    def test_silent_default(self):
        self.assertEqual(RiskAdvisor().evaluate({})['action'], 'hold')

    def test_valid_advisory_does_not_mutate(self):
        c, p = valid()
        before = copy.deepcopy(c)
        result = RiskAdvisor().evaluate(c, p)
        self.assertEqual(result['amount'], '5')
        self.assertFalse(result['auto_trade'])
        self.assertEqual(c, before)

    def test_each_missing_context_field_fails_closed(self):
        c, p = valid()
        for field in set(c) - {'evaluation_date'}:
            with self.subTest(field=field):
                altered = copy.deepcopy(c)
                del altered[field]
                result = RiskAdvisor().evaluate(altered, p)
                self.assertEqual(result['action'], 'calibration')
                self.assertIsNone(result['amount'])

    def test_no_unconfirmed_extra_or_proceeds(self):
        c, p = valid()
        c.update(available_cash='0', potential_extra_cash='99999', pending_proceeds='99999', unrealized_gains='99999')
        self.assertIsNone(RiskAdvisor().evaluate(c, p)['amount'])

    def test_nonfinite_and_boolean_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity', True, 1.2, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decimal(value)
        for key in ('amount', 'estimated_fee', 'conservative_expected_benefit'):
            c, p = valid(); p[key] = 'NaN'
            self.assertIsNone(RiskAdvisor().evaluate(c, p)['amount'])

    def test_truthy_attestations_not_valid(self):
        c, p = valid(); c['confirmed'] = 'yes'
        self.assertIsNone(RiskAdvisor().evaluate(c, p)['amount'])
        c, p = valid(); p['validated'] = 'true'
        self.assertIsNone(RiskAdvisor().evaluate(c, p)['amount'])

    def test_expired_and_future_rules_block(self):
        for key, value in [('valid_until', '2025-12-31'), ('rules_effective_until', '2025-12-31'), ('rules_effective_from', '2027-01-01')]:
            c, p = valid(); p[key] = value
            self.assertIsNone(RiskAdvisor().evaluate(c, p)['amount'])

    def test_sell_requires_confirmed_sellable(self):
        c, p = valid(); p['action'] = 'sell'
        self.assertIsNone(RiskAdvisor().evaluate(c, p)['amount'])
        p.update(sellable_value='6', sellable_value_confirmed=True)
        self.assertEqual(RiskAdvisor().evaluate(c, p)['amount'], '5')
        p['fund_id'] = 'UNKNOWN'
        self.assertIsNone(RiskAdvisor().evaluate(c, p)['amount'])

    def test_observed_fee_edges_and_nav_no_double_charge(self):
        f = FeeSchedule('SYNTHETIC', 'synthetic', '2026-01-01', '0.01',
                        (FeeBand(0, 6, '0.015'), FeeBand(7, 29, '0.005'), FeeBand(30, None, '0')),
                        effective_from='2026-01-01', effective_until='2026-01-31')
        self.assertEqual(f.estimate_cost('sell', '100', 6), Decimal('1.500'))
        self.assertEqual(f.estimate_cost('sell', '100', 7), Decimal('0.500'))
        self.assertEqual(f.estimate_cost('sell', '100', 30), 0)
        self.assertEqual(f.estimate_cost('buy', '101'), 1)
        with self.assertRaises(ValueError): f.estimate_cost('buy', '1', trade_date='2026-02-01')
        with self.assertRaises(ValueError): FeeSchedule('S', 'test', '2026-01-01', '0', (FeeBand(0,7,'0'), FeeBand(7,None,'0')))
        with self.assertRaises(ValueError): FeeBand(0, 7, 'NaN')


if __name__ == '__main__':
    unittest.main()
