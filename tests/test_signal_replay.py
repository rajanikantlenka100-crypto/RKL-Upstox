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
    """Deterministic CALL/PUT replay; no broker or real order is used."""

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

    def test_call_and_put_reach_mock_order_boundary(self):
        for prices, direction, option_type in (
            ([95, 89, 95, 101], "CALL", "CE"),
            ([95, 101, 95, 89], "PUT", "PE"),
        ):
            with self.subTest(direction=direction):
                signal = self.running_signal(prices)
                self.assertEqual(signal.direction, direction)
                closed = [Candle("NIFTY", "NSE", "1", self.timestamp + timedelta(minutes=index * 5), "5m",
                                 100, 101, 99, 100, 0, "FINAL") for index in range(25)]
                with patch("signals.rsi_filter.rsi_series", return_value=[None] * 20 + [40, 50, 50, 50, 50]), \
                     patch("signals.rsi_filter.rsi_sma_series", return_value=[None] * 20 + [45, 45, 45, 45, 45]):
                    rsi_result = validate_rsi_entry(closed, direction)
                self.assertEqual(rsi_result.result, "PASS")
                option = self.contract if option_type == "CE" else OptionContract(
                    "NIFTY", "08SEP2026", 23900, "PE", "NIFTY08SEP2623900PE", "42636", "NFO", 65, 0.05
                )
                summary = approval_summary(signal, option, 65)
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
                    result = OrderExecutor(client).place_approved_buy(option, 65, request_id=signal.signal_id)
                self.assertEqual(result["status"], "SUBMITTED")

    def test_negative_replays_preserve_reason_classes(self):
        self.assertIsNone(self.running_signal([95, 89, 85, 80]))
        self.assertIsNone(self.running_signal([95, 101, 105, 102]))
        closed = [Candle("NIFTY", "NSE", "1", self.timestamp + timedelta(minutes=index * 5), "5m",
                 100, 101, 99, 100, 0, "FINAL") for index in range(25)]
        with patch("signals.rsi_filter.rsi_series", return_value=[None] * 20 + [50] * 5), \
             patch("signals.rsi_filter.rsi_sma_series", return_value=[None] * 20 + [45] * 5):
            result = validate_rsi_entry(closed, "CALL")
        self.assertEqual(result.result, "REJECT")

    def test_candidate_trace_reports_pick_and_miss(self):
        records = []
        engine = BreakoutEngine(records.append)
        self.assertIsNone(engine.evaluate(self.previous, Candle("NIFTY", "NSE", "1", self.timestamp, "5m", 95, 95, 89, 89, 0, "LIVE"), 89, self.timestamp))
        signal = engine.evaluate(self.previous, Candle("NIFTY", "NSE", "1", self.timestamp, "5m", 95, 101, 89, 101, 0, "LIVE"), 101, self.timestamp)
        self.assertEqual(signal.direction, "CALL")
        self.assertEqual(records[0]["reason_code"], "BREAKOUT_LOW_FIRST_WAITING_HIGH")
        self.assertEqual(records[-1]["reason_code"], "CALL_CANDIDATE")
        self.assertTrue(records[-1]["low_cross"] is False)
        self.assertTrue(records[-1]["high_cross"])


if __name__ == "__main__":
    unittest.main()