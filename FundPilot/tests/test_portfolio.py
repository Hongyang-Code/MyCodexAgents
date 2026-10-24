"""Synthetic accounting fixtures; no real personal data."""
from decimal import Decimal
import unittest
from fundpilot.ledger import Ledger, ConflictError
from fundpilot.portfolio import PortfolioManager, number

PROOF = {"source": "synthetic user-confirmed fixture", "confidence": {"as_of": "1", "positions": "1", "cash": "1"}}


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(":memory:")
        self.manager = PortfolioManager(self.ledger)

    def tearDown(self):
        self.ledger.close()

    def snapshot(self, cash="100", key="initial", date="2026-01-01T00:00:00Z"):
        data = {"as_of": date, "positions": [{"code": "000001", "units": "100"}]}
        if cash is not None:
            data["cash"] = cash
        return self.manager.import_snapshot(key, data, PROOF)

    def test_cash_conservation_pending_confirmation_and_receipt(self):
        self.snapshot()
        self.manager.submit_trade("buy", "buy", "000001", amount="20", evidence=PROOF)
        state = self.manager.state()
        self.assertEqual(state["cash"], Decimal(80))
        self.assertEqual(state["positions"]["000001"], Decimal(100))
        self.manager.confirm_trade("buy", units="19", fee="1", evidence=PROOF)
        self.assertEqual(self.manager.state()["cash"], Decimal(80))
        self.manager.submit_trade("sell", "sell", "000001", units="19", evidence=PROOF)
        self.assertEqual(self.manager.state()["positions"]["000001"], Decimal(119))
        self.manager.confirm_trade("sell", units="19", fee="1", net_cash="18", evidence=PROOF)
        self.assertEqual(self.manager.state()["cash"], Decimal(80))
        self.assertEqual(self.manager.state()["receivables"]["sell"], Decimal(18))
        self.manager.settle_redemption("sell", evidence=PROOF)
        self.assertEqual(self.manager.state()["cash"], Decimal(98))
        self.assertEqual(self.manager.state()["positions"]["000001"], Decimal(100))

    def test_idempotent_trade_and_overspend(self):
        self.snapshot()
        one = self.manager.submit_trade("buy", "buy", "000001", amount="60", evidence=PROOF)
        self.assertEqual(one, self.manager.submit_trade("buy", "buy", "000001", amount="60", evidence=PROOF))
        with self.assertRaises(ValueError):
            self.manager.submit_trade("buy2", "buy", "000001", amount="60", evidence=PROOF)
        with self.assertRaises(ConflictError):
            self.manager.submit_trade("buy", "buy", "000001", amount="61", evidence=PROOF)
        self.assertEqual(self.manager.state()["cash"], Decimal(40))

    def test_unknown_cash_never_infers_external_capital(self):
        self.snapshot(None)
        with self.assertRaises(ValueError):
            self.manager.submit_trade("b", "buy", "000001", amount="1", evidence=PROOF)
        self.manager.record_dividend("d", "000001", "cash", amount="10", evidence=PROOF)
        self.assertIsNone(self.manager.state()["cash"])

    def test_reconciliation_preserves_history(self):
        self.snapshot()
        self.manager.record_dividend("dividend", "000001", "cash", amount="5", evidence=PROOF, occurred_at="2026-01-01T12:00:00Z")
        self.snapshot("105", key="new", date="2026-01-02T00:00:00Z")
        self.assertEqual(len(self.ledger.events()), 3)
        self.assertEqual(self.manager.state()["cash"], Decimal(105))
        with self.assertRaises(ValueError):
            self.snapshot("100", key="older")
        self.manager.submit_trade("b", "buy", "000001", amount="5", evidence=PROOF)
        with self.assertRaises(ValueError):
            self.snapshot("100", key="unresolved", date="2026-01-03T00:00:00Z")

    def test_sell_reservations(self):
        self.snapshot()
        self.manager.submit_trade("s", "sell", "000001", units="60", evidence=PROOF)
        with self.assertRaises(ValueError):
            self.manager.submit_trade("s2", "sell", "000001", units="60", evidence=PROOF)
        with self.assertRaises(ValueError):
            self.manager.confirm_trade("s", units="50", net_cash="50", evidence=PROOF)

    def test_dividend_and_nav_no_double_fee(self):
        self.snapshot()
        self.manager.record_dividend("d", "000001", "reinvest", units="2", evidence=PROOF)
        self.manager.record_dividend("d", "000001", "reinvest", units="2", evidence=PROOF)
        result = self.manager.estimate({"000001": {"nav": "1.5", "nav_date": "2026-01-02"}}, estimated_at="2026-01-03T00:00:00Z")
        self.assertEqual(result["values"]["000001"]["value"], Decimal(153))
        self.assertEqual(result["kind"], "model_estimate_not_account_balance")
        self.assertEqual(self.manager.state()["cash"], Decimal(100))
        self.assertEqual(self.manager.estimate({}, estimated_at="2026-01-03T00:00:00Z")["missing_navs"], ["000001"])

    def test_numeric_rejections(self):
        for value in (True, 1.2, "NaN", "sNaN", "Infinity", "-1", "1e1000", "0.00000000001", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value)

    def test_confidence_and_identity(self):
        with self.assertRaises(ValueError):
            self.manager.import_snapshot("x", {"as_of": "2026-01-01T00:00:00Z", "positions": []}, {"source": "unclear screenshot", "confidence": {"positions": "0.8", "as_of": "1"}})
        with self.assertRaises(ValueError):
            self.manager.import_snapshot("x", {"as_of": "2026-01-01T00:00:00Z", "positions": [{"code": "1", "units": "10"}]}, PROOF)
        self.assertEqual(self.ledger.version, 0)

    def test_old_snapshot_cannot_restore_spent_cash(self):
        self.manager.import_snapshot("s1", {"as_of": "2026-01-01T00:00:00Z", "positions": [], "cash": "100"}, PROOF)
        self.manager.submit_trade("b", "buy", "000001", amount="100", evidence=PROOF)
        self.manager.confirm_trade("b", units="100", evidence=PROOF)
        for reconcile in (False, True):
            with self.assertRaises(ValueError):
                self.manager.import_snapshot("s2", {"as_of": "2026-01-01T00:00:00Z", "positions": [], "cash": "100"}, PROOF, reconcile=reconcile)
        self.assertEqual(self.manager.state()["cash"], Decimal(0))
        self.assertEqual(self.manager.state()["positions"]["000001"], Decimal(100))
        self.assertEqual(self.ledger.version, 3)

    def test_historical_import_and_explicit_audited_reconciliation(self):
        self.snapshot()
        self.manager.submit_trade("b", "buy", "000001", amount="10", evidence=PROOF, occurred_at="2026-01-01T10:00:00Z")
        self.manager.confirm_trade("b", units="10", evidence=PROOF, occurred_at="2026-01-01T11:00:00Z")
        snapshot = {"as_of": "2026-01-02T00:00:00Z", "cash": "91", "positions": [{"code": "000001", "units": "110"}]}
        with self.assertRaisesRegex(ValueError, "before.*after|after.*before"):
            self.manager.import_snapshot("correction", snapshot, PROOF)
        event = self.manager.import_snapshot("correction", snapshot, PROOF, reconcile=True)
        self.assertEqual(event["payload"]["reconciliation"]["before"]["cash"], "90")
        self.assertEqual(event["payload"]["reconciliation"]["after"]["cash"], "91")
        self.assertTrue(event["payload"]["reconcile_confirmed"])
        self.assertEqual(event, self.manager.import_snapshot("correction", snapshot, PROOF, reconcile=True))
        with self.assertRaises(ValueError):
            self.manager.record_dividend("late", "000001", "cash", amount="1", evidence=PROOF, occurred_at="2026-01-01T12:00:00Z")

    def test_cancel_buy_releases_cash_once_and_conflicts(self):
        self.snapshot()
        self.manager.submit_trade("b", "buy", "000001", amount="80", evidence=PROOF)
        version = self.ledger.version
        with self.assertRaises(ConflictError):
            self.manager.cancel_trade("b", evidence=PROOF, reason="confirmed rejection", outcome="rejected", expected_version=version - 1)
        self.assertEqual(self.manager.state()["cash"], Decimal(20))
        event = self.manager.cancel_trade("b", evidence=PROOF, reason="confirmed rejection", outcome="rejected", expected_version=version)
        self.assertEqual(self.manager.state()["cash"], Decimal(100))
        self.assertEqual(self.manager.state()["pending"], {})
        self.assertEqual(event, self.manager.cancel_trade("b", evidence=PROOF, reason="confirmed rejection", outcome="rejected", expected_version=version))
        with self.assertRaises(ConflictError):
            self.manager.cancel_trade("b", evidence=PROOF, reason="different reason", outcome="rejected")
        with self.assertRaises(ValueError):
            self.manager.confirm_trade("b", units="80", evidence=PROOF)

    def test_cancel_sell_releases_units_but_not_confirmed_trades(self):
        self.snapshot()
        self.manager.submit_trade("s", "sell", "000001", units="100", evidence=PROOF)
        self.manager.cancel_trade("s", evidence=PROOF, reason="platform confirmed cancellation")
        self.assertEqual(self.manager.state()["positions"]["000001"], Decimal(100))
        self.manager.submit_trade("s2", "sell", "000001", units="100", evidence=PROOF)
        self.manager.confirm_trade("s2", units="100", net_cash="100", evidence=PROOF)
        with self.assertRaises(ValueError):
            self.manager.cancel_trade("s2", evidence=PROOF, reason="too late")
        self.manager.settle_redemption("s2", evidence=PROOF)
        with self.assertRaises(ValueError):
            self.manager.cancel_trade("s2", evidence=PROOF, reason="too late")
        self.assertEqual(self.manager.state()["cash"], Decimal(200))

    def test_cancel_needs_provenance_and_terminal_outcome(self):
        self.snapshot()
        self.manager.submit_trade("b", "buy", "000001", amount="80", evidence=PROOF)
        with self.assertRaises(ValueError):
            self.manager.cancel_trade("b", evidence={}, reason="unknown")
        with self.assertRaises(ValueError):
            self.manager.cancel_trade("b", evidence=PROOF, reason="requested only", outcome="requested")
        self.assertEqual(self.manager.state()["cash"], Decimal(20))

class CompleteResearchBookTests(unittest.TestCase):
    def test_full_inventory_capacity_and_unsettled_cash_never_truncated(self):
        for count in (10,20,50):
            with self.subTest(count=count):
                ledger=Ledger(':memory:');p=PortfolioManager(ledger)
                positions=[{'code':f'{i+1:06d}','units':'100','lots':[{'units':'100','confirmed_date':None}]} for i in range(count)]
                p.import_snapshot('synthetic-full',{'as_of':'2020-01-01T00:00:00Z','cash':'100','positions':positions},PROOF)
                p.submit_trade('buy','buy','000001',amount='20',evidence=PROOF)
                p.submit_trade('sell-frozen','sell','000002',units='10',evidence=PROOF)
                p.submit_trade('sell-receivable','sell','000003',units='10',evidence=PROOF)
                p.confirm_trade('sell-receivable',units='10',net_cash='9',evidence=PROOF)
                before=ledger.version;b=p.research_book(coverage='complete')
                self.assertEqual(len(b['confirmed_positions']),count)
                self.assertEqual(b['confirmed_positions']['000003'],'90')
                self.assertEqual(b['available_cash'],'80');self.assertEqual(b['buy_cash_reserved'],'20')
                self.assertEqual(b['sell_units_frozen'],{'000002':'10'})
                self.assertEqual(b['redemption_receivables'],{'sell-receivable':'9'})
                self.assertEqual(len(b['original_position_evidence']),count)
                self.assertIsNone(b['original_position_evidence'][-1]['lots'][0]['confirmed_date'])
                self.assertIsNone(b['weights']);self.assertIsNone(b['risk_exposure'])
                self.assertEqual(ledger.version,before);ledger.close()

    def test_partial_unknown_is_retained_not_zero_or_a_full_replacement(self):
        ledger=Ledger(':memory:');p=PortfolioManager(ledger)
        p.import_snapshot('known',{'as_of':'2020-01-01T00:00:00Z','positions':[{'code':'000001','units':'10'}]},PROOF)
        b=p.research_book(coverage='partial',unresolved=[{'id':'SYNTHETIC_UNRESOLVED','code':None,'weight':None}])
        self.assertIsNone(b['available_cash']);self.assertEqual(len(b['unresolved_positions']),1)
        self.assertIsNone(b['unresolved_positions'][0]['weight'])
        with self.assertRaises(ValueError):p.research_book(coverage='complete',unresolved=b['unresolved_positions'])
        self.assertEqual(p.state()['positions'],{'000001':Decimal('10')});ledger.close()
