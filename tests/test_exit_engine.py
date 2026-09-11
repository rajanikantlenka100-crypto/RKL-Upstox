import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_data.models import Candle
from trading.exit_engine import StrategyExitState


IST = ZoneInfo("Asia/Kolkata")


def candle(minutes, high, low):
    return Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, minutes, tzinfo=IST), "5m", low, high, low, high, 0, "UNIT")


class StrategyExitEngineTests(unittest.TestCase):
    def test_call_arms_then_requires_later_low_break(self):
        state = StrategyExitState("CALL", 10)
        trigger = candle(0, 110, 100)
        self.assertIsNone(state.on_closed_candle(trigger, None, 101))
        self.assertEqual(state.cci_state, "ARMED")
        first_later = candle(5, 111, 101)
        confirmed = candle(10, 112, 99)
        self.assertIsNone(state.on_closed_candle(first_later, trigger, 90))
        self.assertEqual(state.on_closed_candle(confirmed, first_later, 90), "CCI_CONFIRMATION")
        self.assertEqual(state.exit_reason, "CCI_CONFIRMATION")
        self.assertEqual(state.confirmation_candle_timestamp, confirmed.timestamp)

    def test_put_arms_then_requires_later_high_break(self):
        state = StrategyExitState("PUT", 8)
        trigger = candle(0, 110, 100)
        self.assertIsNone(state.on_closed_candle(trigger, None, -101))
        self.assertIsNone(state.on_closed_candle(candle(5, 109, 99), trigger, -90))
        self.assertEqual(state.on_closed_candle(candle(10, 111, 99), candle(5, 109, 99), -90), "CCI_CONFIRMATION")
        self.assertEqual(state.exit_reason, "CCI_CONFIRMATION")

    def test_thresholds_and_same_candle_are_strict(self):
        call = StrategyExitState("CALL", 10)
        trigger = candle(0, 110, 100)
        self.assertIsNone(call.on_closed_candle(trigger, None, 100))
        self.assertIsNone(call.on_closed_candle(trigger, trigger, 101))
        put = StrategyExitState("PUT", 10)
        self.assertIsNone(put.on_closed_candle(trigger, None, -100))

    def test_five_r_uses_immutable_initial_risk_and_strict_greater_than(self):
        state = StrategyExitState("CALL", 10)
        self.assertEqual(state.five_r, 50)
        self.assertIsNone(state.on_running_candle(candle(0, 150, 100)))
        self.assertEqual(state.on_running_candle(candle(5, 151, 100)), "FIVE_R_EXIT")
        self.assertEqual(state.initial_risk, 10)
        self.assertEqual(state.five_r, 50)

    def test_five_r_is_direction_neutral(self):
        state = StrategyExitState("PUT", 10)
        self.assertEqual(state.on_running_candle(candle(0, 151, 100)), "FIVE_R_EXIT")


if __name__ == "__main__":
    unittest.main()
