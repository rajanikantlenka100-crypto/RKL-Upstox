import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_data.models import Candle
from signals.breakout import Type2Engine


IST = ZoneInfo("Asia/Kolkata")


def make_candle(timestamp, open_price, high, low, close):
    return Candle("NIFTY", "NSE", "NIFTY", timestamp, "5m", open_price, high, low, close, 0, "UNIT")


class SignalType2Tests(unittest.TestCase):
    def setUp(self):
        self.prev2 = make_candle(datetime(2026, 9, 10, 10, 0, tzinfo=IST), 100, 105, 95, 100)
        self.prev = make_candle(datetime(2026, 9, 10, 10, 5, tzinfo=IST), 98, 102, 90, 101)
        self.running = make_candle(datetime(2026, 9, 10, 10, 10, tzinfo=IST), 101, 104, 91, 103)

    def test_call_all_conditions_pass(self):
        signal = Type2Engine().evaluate(self.prev2, self.prev, self.running, 103, rsi_pass=True)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.signal_type, "TYPE_2")
        self.assertEqual(signal.direction, "CALL")
        self.assertTrue(all(signal.type2_conditions.values()))

    def test_call_requires_strict_boundaries(self):
        engine = Type2Engine()
        self.assertIsNone(engine.evaluate(self.prev2, self.prev, self.running, 103, rsi_pass=False))
        midpoint_prev = make_candle(self.prev.timestamp, 98, 102, 90, 96)
        self.assertIsNone(Type2Engine().evaluate(self.prev2, midpoint_prev, self.running, 103, rsi_pass=True))
        no_low = make_candle(self.prev.timestamp, 98, 102, 95, 101)
        self.assertIsNone(Type2Engine().evaluate(self.prev2, no_low, self.running, 103, rsi_pass=True))
        no_running_break = make_candle(self.running.timestamp, 101, 102, 89, 101)
        self.assertIsNone(Type2Engine().evaluate(self.prev2, self.prev, no_running_break, 101, rsi_pass=True))

    def test_call_body_must_be_at_most_twenty_five_percent(self):
        large_body = make_candle(self.prev.timestamp, 90, 102, 90, 101)
        self.assertIsNone(Type2Engine().evaluate(self.prev2, large_body, self.running, 103, rsi_pass=True))

    def test_call_breakout_is_intracandle_and_not_duplicate(self):
        engine = Type2Engine()
        first = engine.evaluate(self.prev2, self.prev, self.running, 103, rsi_pass=True)
        second = engine.evaluate(self.prev2, self.prev, self.running, 104, rsi_pass=True)
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_put_all_conditions_pass(self):
        prev2 = make_candle(self.prev2.timestamp, 100, 109, 95, 100)
        prev = make_candle(self.prev.timestamp, 102, 110, 98, 99)
        running = make_candle(self.running.timestamp, 99, 109, 94, 96)
        signal = Type2Engine().evaluate(prev2, prev, running, 96, direction="PUT", rsi_pass=True)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "PUT")
        self.assertTrue(all(signal.type2_conditions.values()))

    def test_put_boundaries_and_duplicate(self):
        prev2 = make_candle(self.prev2.timestamp, 100, 109, 95, 100)
        prev = make_candle(self.prev.timestamp, 102, 110, 98, 99)
        running = make_candle(self.running.timestamp, 99, 109, 94, 96)
        engine = Type2Engine()
        self.assertIsNotNone(engine.evaluate(prev2, prev, running, 96, direction="PUT", rsi_pass=True))
        self.assertIsNone(engine.evaluate(prev2, prev, running, 95, direction="PUT", rsi_pass=True))
        self.assertIsNone(Type2Engine().evaluate(prev2, prev, running, 96, direction="PUT", rsi_pass=False))


if __name__ == "__main__":
    unittest.main()
