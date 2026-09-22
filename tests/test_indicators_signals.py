import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_data.models import Candle
from signals.breakout import BreakoutEngine


def make_candle(timestamp, high, low, close=100):
    return Candle("NIFTY", "NSE", "1", timestamp, "5m", 100, high, low, close, 0, "UNIT")


class Type1SignalTests(unittest.TestCase):
    def setUp(self):
        timestamp = datetime(2026, 9, 3, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        self.previous = make_candle(timestamp, 100, 90)
        self.running = make_candle(timestamp + timedelta(minutes=5), 101, 89)

    def test_call_requires_both_running_breaks(self):
        green_running = make_candle(self.running.timestamp, 101, 89, 101)
        signal = BreakoutEngine().evaluate(self.previous, green_running, 100, direction="CALL")
        self.assertEqual(signal.direction, "CALL")
        self.assertEqual(signal.type1_conditions, {
            "running_low_below_previous_low": True,
            "running_high_above_previous_high": True,
            "running_green_for_call": True,
            "running_red_for_put": False,
        })

    def test_put_requires_both_running_breaks(self):
        red_running = make_candle(self.running.timestamp, 101, 89, 99)
        signal = BreakoutEngine().evaluate(self.previous, red_running, 100, direction="PUT")
        self.assertEqual(signal.direction, "PUT")

    def test_rejects_when_either_candle_condition_fails(self):
        no_low = make_candle(self.running.timestamp, 101, 90)
        no_high = make_candle(self.running.timestamp, 100, 89)
        self.assertIsNone(BreakoutEngine().evaluate(self.previous, no_low, 100, direction="CALL"))
        self.assertIsNone(BreakoutEngine().evaluate(self.previous, no_high, 100, direction="PUT"))

    def test_rejects_wrong_colour_and_doji(self):
        red = make_candle(self.running.timestamp, 101, 89, 99)
        doji = make_candle(self.running.timestamp, 101, 89, 100)
        self.assertIsNone(BreakoutEngine().evaluate(self.previous, red, 100, direction="CALL"))
        self.assertIsNone(BreakoutEngine().evaluate(self.previous, doji, 100, direction="PUT"))

    def test_same_running_candle_does_not_duplicate(self):
        engine = BreakoutEngine()
        green = make_candle(self.running.timestamp, 101, 89, 101)
        self.assertIsNotNone(engine.evaluate(self.previous, green, 100, direction="CALL"))
        self.assertIsNone(engine.evaluate(self.previous, green, 101, direction="CALL"))

    def test_new_running_candle_resets_guard(self):
        engine = BreakoutEngine()
        green = make_candle(self.running.timestamp, 101, 89, 101)
        self.assertIsNotNone(engine.evaluate(self.previous, green, 100, direction="CALL"))
        next_running = make_candle(self.running.timestamp + timedelta(minutes=5), 102, 88, 101)
        self.assertIsNotNone(engine.evaluate(self.running, next_running, 101, direction="CALL"))


if __name__ == "__main__":
    unittest.main()
