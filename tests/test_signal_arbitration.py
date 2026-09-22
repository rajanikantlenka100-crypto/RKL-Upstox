import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_data.models import Candle
from signals.breakout import PutCallSignal
from signals.coordinator import SignalArbitrator


class SignalArbitrationTests(unittest.TestCase):
    def setUp(self):
        timestamp = datetime(2026, 9, 22, 10, 25, tzinfo=ZoneInfo("Asia/Kolkata"))
        candle = Candle("NIFTY", "NSE", "1", timestamp, "5m", 100, 110, 90, 105, 0, "UNIT", "RUNNING")
        self.call_type1 = PutCallSignal("T1", timestamp, "NIFTY", "CALL", 105, candle, candle, 105, signal_type="TYPE_1")
        self.call_type2 = PutCallSignal("T2", timestamp, "NIFTY", "CALL", 105, candle, candle, 105, signal_type="TYPE_2")
        self.put_type2 = PutCallSignal("T3", timestamp, "NIFTY", "PUT", 105, candle, candle, 90, signal_type="TYPE_2")

    def test_same_direction_candidates_consolidate_to_one(self):
        arbitrator = SignalArbitrator()
        accepted, reason = arbitrator.admit([self.call_type1, self.call_type2])
        self.assertIsNotNone(accepted)
        self.assertEqual(reason, "CONSOLIDATED")
        self.assertEqual(accepted.matched_signal_types, ("TYPE_1", "TYPE_2"))
        self.assertEqual(accepted.signal_type, "TYPE_1+TYPE_2")

    def test_later_candidate_is_locked_out(self):
        arbitrator = SignalArbitrator()
        accepted, _ = arbitrator.admit([self.call_type1])
        self.assertIsNotNone(accepted)
        rejected, reason = arbitrator.admit([self.call_type2])
        self.assertIsNone(rejected)
        self.assertEqual(reason, "CANDLE_LOCKED")

    def test_contradictory_directions_are_rejected(self):
        accepted, reason = SignalArbitrator().admit([self.call_type1, self.put_type2])
        self.assertIsNone(accepted)
        self.assertEqual(reason, "CONTRADICTORY_DIRECTION")

    def test_next_candle_is_independent(self):
        arbitrator = SignalArbitrator()
        arbitrator.admit([self.call_type1])
        next_candle = Candle("NIFTY", "NSE", "1", datetime(2026, 9, 22, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata")), "5m", 100, 110, 90, 105, 0, "UNIT", "RUNNING")
        next_signal = PutCallSignal("T4", next_candle.timestamp, "NIFTY", "CALL", 105, next_candle, next_candle, 105, signal_type="TYPE_1")
        accepted, reason = arbitrator.admit([next_signal])
        self.assertIsNotNone(accepted)
        self.assertEqual(reason, "ACCEPTED")

    def test_lock_is_scoped_by_underlying(self):
        arbitrator = SignalArbitrator()
        arbitrator.admit([self.call_type1])
        bank_candle = Candle("BANKNIFTY", "NSE", "2", self.call_type1.timestamp, "5m", 100, 110, 90, 105, 0, "UNIT", "RUNNING")
        bank_signal = PutCallSignal("T5", bank_candle.timestamp, "BANKNIFTY", "CALL", 105, bank_candle, bank_candle, 105, signal_type="TYPE_1")
        accepted, reason = arbitrator.admit([bank_signal])
        self.assertIsNotNone(accepted)
        self.assertEqual(reason, "ACCEPTED")


if __name__ == "__main__":
    unittest.main()
