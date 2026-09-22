import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from broker.order_manager import OrderExecutor
from instruments.options import OptionContract
from market_data.models import Candle
from signals.breakout import BreakoutEngine
from signals.rsi_filter import validate_rsi_entry
from trading.approval import approval_summary
from trading.safety import SafetyGate


class SignalReplayTests(unittest.TestCase):
    """Deterministic CALL replay; no broker or real order is used."""

    def setUp(self):
        self.timestamp = datetime(2026, 9, 7, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        self.previous = Candle("NIFTY", "NSE", "1", self.timestamp, "5m", 95, 100, 90, 95, 0, "FINAL")
        self.contract = OptionContract("NIFTY", "08SEP2026", 23900, "CE", "NIFTY08SEP2623900CE", "42635", "NFO", 65, 0.05)

    def running_signal(self, prices):
        engine = BreakoutEngine()
        signal = None
        high = low = prices[0]
        for price in prices:
            high = max(high, price)
            low = min(low, price)
            running = Candle("NIFTY", "NSE", "1", self.timestamp, "5m", prices[0], high, low, price, 0, "LIVE")
            signal = engine.evaluate(self.previous, running, price, self.timestamp) or signal
        return signal

    def test_call_reaches_mock_order_boundary(self):
        signal = self.running_signal([95, 89, 95, 101])
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "CALL")
        closed = [Candle("NIFTY", "NSE", "1", self.timestamp + timedelta(minutes=index * 5), "5m",
                         100, 101, 99, 100, 0, "FINAL") for index in range(28)]
        rsi_values = [None] * 28
        sma_values = [None] * 28
        rsi_values[-1], sma_values[-1] = 60, 50
        with patch("signals.rsi_filter.rsi_series", return_value=rsi_values), \
                patch("signals.rsi_filter.rsi_sma_series", return_value=sma_values):
            rsi_result = validate_rsi_entry(closed, "CALL")
        self.assertEqual(rsi_result.result, "PASS")
        summary = approval_summary(signal, self.contract, 65)
        self.assertEqual(summary["status"], "AUTO ENTRY PENDING")
        gate = SafetyGate()
        gate.running()
        allowed, reason = gate.allow_buy(
            feed_healthy=True, broker_authenticated=True, history_ready=True,
            contract_valid=True, signal_valid=True, database_ready=True,
        )
        self.assertTrue(allowed, reason)
        client = type("Broker", (), {"place_order": lambda _, params: {
            "status": True, "data": {"order_id": "MOCK-1"}
        }})()
        with patch("config.ENABLE_REAL_ORDERS", True), \
                patch("config.EXECUTION_MODE", "PRODUCTION"), \
                patch("config.PREFLIGHT_PASSED", True):
            result = OrderExecutor(client).place_approved_buy(self.contract, 65, request_id=signal.signal_id)
        self.assertEqual(result["status"], "SUBMITTED")

    def test_negative_replays_and_latest_rsi_reject(self):
        self.assertIsNone(self.running_signal([95, 89, 85, 80]))
        self.assertIsNone(self.running_signal([95, 101, 105, 102]))
        closed = [Candle("NIFTY", "NSE", "1", self.timestamp + timedelta(minutes=index * 5), "5m",
                         100, 101, 99, 100, 0, "FINAL") for index in range(28)]
        rsi_values = [None] * 28
        sma_values = [None] * 28
        rsi_values[-1], sma_values[-1] = 50, 45
        with patch("signals.rsi_filter.rsi_series", return_value=rsi_values), \
                patch("signals.rsi_filter.rsi_sma_series", return_value=sma_values):
            result = validate_rsi_entry(closed, "PUT")
        self.assertEqual(result.result, "REJECT")

    def test_candidate_trace_reports_new_type1_reason(self):
        records = []
        engine = BreakoutEngine(records.append)
        self.assertIsNone(engine.evaluate(self.previous, Candle("NIFTY", "NSE", "1", self.timestamp, "5m", 95, 95, 89, 89, 0, "LIVE"), 89, self.timestamp))
        signal = engine.evaluate(self.previous, Candle("NIFTY", "NSE", "1", self.timestamp, "5m", 95, 101, 89, 101, 0, "LIVE"), 101, self.timestamp)
        self.assertEqual(signal.direction, "CALL")
        self.assertEqual(records[0]["reason_code"], "NO_BREAKOUT")
        self.assertEqual(records[-1]["reason_code"], "TYPE_1_CANDIDATE")
        self.assertEqual(records[-1]["candidate_direction"], "CALL")


if __name__ == "__main__":
    unittest.main()
