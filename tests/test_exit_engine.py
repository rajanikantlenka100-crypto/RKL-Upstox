import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_data.models import Candle
from trading.exit_engine import StrategyExitState


IST = ZoneInfo("Asia/Kolkata")


def candle(minutes, high, low):
    return Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, minutes, tzinfo=IST), "5m", low, high, low, high, 0, "UNIT")


class StrategyExitEngineTests(unittest.TestCase):
    def test_call_arms_then_requires_break_below_recent_green_reference(self):
        state = StrategyExitState("CALL")
        trigger = candle(0, 110, 100)
        self.assertIsNone(state.on_closed_candle(trigger, None, 101))
        self.assertEqual(state.cci_state, "ARMED")

        green = Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, 5, tzinfo=IST), "5m",
                      100, 110, 96, 105, 0, "UNIT")
        self.assertIsNone(state.on_closed_candle(green, None, 90))
        self.assertEqual(state.reference_candle.timestamp, green.timestamp)

        break_candle = candle(10, 109, 94)
        self.assertEqual(state.on_closed_candle(break_candle, None, 90), "CCI_CONFIRMATION")
        self.assertEqual(state.exit_reason, "CCI_CONFIRMATION")
        self.assertEqual(state.confirmation_candle_timestamp, break_candle.timestamp)

    def test_put_arms_then_requires_break_above_recent_green_reference(self):
        state = StrategyExitState("PUT")
        trigger = candle(0, 110, 100)
        self.assertIsNone(state.on_closed_candle(trigger, None, -101))

        red = Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, 5, tzinfo=IST), "5m",
                 95, 97, 88, 92, 0, "UNIT")
        self.assertIsNone(state.on_closed_candle(red, trigger, -90))
        self.assertEqual(state.reference_candle.timestamp, red.timestamp)

        break_candle = Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, 10, tzinfo=IST), "5m",
                             96, 104, 92, 98, 0, "UNIT")
        self.assertEqual(state.on_closed_candle(break_candle, red, -90), "CCI_CONFIRMATION")
        self.assertEqual(state.exit_reason, "CCI_CONFIRMATION")
        self.assertEqual(state.confirmation_candle_timestamp, break_candle.timestamp)

    def test_thresholds_and_same_candle_are_strict(self):
        call = StrategyExitState("CALL")
        trigger = candle(0, 110, 100)
        self.assertIsNone(call.on_closed_candle(trigger, None, 100))
        self.assertIsNone(call.on_closed_candle(trigger, trigger, 101))
        put = StrategyExitState("PUT")
        self.assertIsNone(put.on_closed_candle(trigger, None, -100))

    def test_cci_arms_only_once_and_ignores_repeated_over_threshold_values(self):
        state = StrategyExitState("CALL")
        arm = candle(0, 110, 100)
        self.assertIsNone(state.on_closed_candle(arm, None, 101))
        self.assertEqual(state.cci_state, "ARMED")
        self.assertIsNone(state.on_closed_candle(candle(5, 111, 101), arm, 110))
        self.assertIsNone(state.on_closed_candle(candle(10, 112, 102), candle(5, 111, 101), 105))
        self.assertEqual(state.cci_state, "ARMED")

    def test_call_exit_requires_recent_green_reference_and_not_red_or_doji(self):
        state = StrategyExitState("CALL")
        state.on_closed_candle(candle(0, 110, 100), None, 101)
        red = Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, 5, tzinfo=IST), "5m",
                 110, 112, 98, 100, 0, "UNIT")
        self.assertIsNone(state.on_closed_candle(red, None, 90))
        doji = Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, 15, tzinfo=IST), "5m",
                  100, 103, 99.5, 100.5, 0, "UNIT")
        self.assertIsNone(state.on_closed_candle(doji, None, 90))

        green = Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, 20, tzinfo=IST), "5m",
                      100, 110, 96, 105, 0, "UNIT")
        self.assertIsNone(state.on_closed_candle(green, None, 90))
        break_candle = Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, 25, tzinfo=IST), "5m",
                     95, 108, 90, 94, 0, "UNIT")
        self.assertEqual(state.on_closed_candle(break_candle, green, 90), "CCI_CONFIRMATION")

    def test_exactly_twenty_percent_body_is_directional(self):
        state = StrategyExitState("CALL")
        arm = candle(0, 110, 100)
        self.assertIsNone(state.on_closed_candle(arm, None, 101))
        exact_boundary = Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, 5, tzinfo=IST), "5m",
                                100, 110, 100, 102, 0, "UNIT")
        self.assertIsNone(state.on_closed_candle(exact_boundary, None, 90))
        self.assertEqual(state.reference_candle.timestamp, exact_boundary.timestamp)

    def test_call_previous_index_low_break_exits(self):
        state = StrategyExitState("CALL")
        previous = candle(0, 110, 100)
        running = candle(5, 111, 99)
        self.assertEqual(state.on_running_candle(running, previous), "PREVIOUS_INDEX_CANDLE_BREAK")

    def test_put_previous_index_high_break_exits(self):
        state = StrategyExitState("PUT")
        previous = candle(0, 110, 100)
        running = candle(5, 111, 101)
        self.assertEqual(state.on_running_candle(running, previous), "PREVIOUS_INDEX_CANDLE_BREAK")

    def test_candle_size_exit_is_strictly_greater_than_three_times_previous_range(self):
        previous = candle(0, 110, 100)
        equal = candle(5, 130, 100)
        smaller = candle(10, 120, 100)
        larger = Candle("NIFTY", "NSE", "NIFTY", datetime(2026, 9, 10, 10, 15, tzinfo=IST), "5m",
                        100, 141, 100, 140, 0, "UNIT")
        state_equal = StrategyExitState("CALL", standard_candle=previous)
        state_smaller = StrategyExitState("CALL", standard_candle=previous)
        state_larger = StrategyExitState("CALL", standard_candle=previous)
        self.assertIsNone(state_equal.on_running_candle(equal, previous))
        self.assertIsNone(state_smaller.on_running_candle(smaller, previous))
        self.assertEqual(state_larger.on_running_candle(larger, previous), "CANDLE_SIZE_EXIT")


if __name__ == "__main__":
    unittest.main()
