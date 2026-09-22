import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_data.models import Candle
from signals.breakout import Type2Engine, Type3Engine


IST = ZoneInfo("Asia/Kolkata")


def make_candle(timestamp, open_price, high, low, close):
    return Candle("NIFTY", "NSE", "NIFTY", timestamp, "5m", open_price, high, low, close, 0, "UNIT")


class SignalType2Tests(unittest.TestCase):
    def setUp(self):
        self.prev2 = make_candle(datetime(2026, 9, 10, 10, 0, tzinfo=IST), 100, 105, 95, 100)
        self.prev = make_candle(datetime(2026, 9, 10, 10, 5, tzinfo=IST), 98, 102, 90, 101)
        self.running = make_candle(datetime(2026, 9, 10, 10, 10, tzinfo=IST), 101, 104, 91, 103)

    def test_call_all_conditions_pass(self):
        previous = make_candle(self.prev.timestamp, 98, 105, 90, 100)
        running = make_candle(self.running.timestamp, 101, 106, 91, 103)
        signal = Type2Engine().evaluate(self.prev2, previous, running, 103, rsi_pass=True)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.signal_type, "TYPE_2")
        self.assertEqual(signal.direction, "CALL")
        self.assertTrue(all(signal.type2_conditions.values()))

    def test_call_requires_strict_boundaries(self):
        engine = Type2Engine()
        valid_previous = make_candle(self.prev.timestamp, 98, 105, 90, 100)
        self.assertIsNone(engine.evaluate(self.prev2, valid_previous, self.running, 103, rsi_pass=False))
        midpoint_prev = make_candle(self.prev.timestamp, 98, 105, 90, 97)
        self.assertIsNone(Type2Engine().evaluate(self.prev2, midpoint_prev, self.running, 103, rsi_pass=True))
        no_low = make_candle(self.prev.timestamp, 98, 105, 95, 100)
        self.assertIsNone(Type2Engine().evaluate(self.prev2, no_low, self.running, 103, rsi_pass=True))
        no_running_break = make_candle(self.running.timestamp, 101, 102, 89, 101)
        self.assertIsNone(Type2Engine().evaluate(self.prev2, self.prev, no_running_break, 101, rsi_pass=True))

    def test_call_body_must_be_strictly_below_twenty_percent(self):
        twenty_percent = make_candle(self.prev.timestamp, 98, 105, 90, 101)
        nineteen_percent = make_candle(self.prev.timestamp, 98, 105, 90, 100.85)
        running = make_candle(self.running.timestamp, 101, 106, 91, 103)
        self.assertIsNone(Type2Engine().evaluate(self.prev2, twenty_percent, running, 103, rsi_pass=True))
        signal = Type2Engine().evaluate(self.prev2, nineteen_percent, running, 103, rsi_pass=True)
        self.assertIsNotNone(signal)
        self.assertAlmostEqual(signal.body_ratio, 0.19, places=6)

    def test_call_breakout_is_intracandle_and_not_duplicate(self):
        engine = Type2Engine()
        previous = make_candle(self.prev.timestamp, 98, 105, 90, 100)
        running = make_candle(self.running.timestamp, 101, 106, 91, 103)
        first = engine.evaluate(self.prev2, previous, running, 103, rsi_pass=True)
        second = engine.evaluate(self.prev2, previous, running, 104, rsi_pass=True)
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_put_all_conditions_pass(self):
        prev2 = make_candle(self.prev2.timestamp, 100, 109, 95, 100)
        prev = make_candle(self.prev.timestamp, 102, 110, 98, 100)
        running = make_candle(self.running.timestamp, 99, 109, 94, 96)
        signal = Type2Engine().evaluate(prev2, prev, running, 96, direction="PUT", rsi_pass=True)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "PUT")
        self.assertTrue(all(signal.type2_conditions.values()))

    def test_put_boundaries_and_duplicate(self):
        prev2 = make_candle(self.prev2.timestamp, 100, 109, 95, 100)
        prev = make_candle(self.prev.timestamp, 102, 110, 98, 100)
        running = make_candle(self.running.timestamp, 99, 109, 94, 96)
        engine = Type2Engine()
        self.assertIsNotNone(engine.evaluate(prev2, prev, running, 96, direction="PUT", rsi_pass=True))
        self.assertIsNone(engine.evaluate(prev2, prev, running, 95, direction="PUT", rsi_pass=True))
        self.assertIsNone(Type2Engine().evaluate(prev2, prev, running, 96, direction="PUT", rsi_pass=False))

    def test_type3_call_is_mirrored_and_ignores_body_limit(self):
        prev2 = make_candle(self.prev2.timestamp, 100, 108, 92, 100)
        prev = make_candle(self.prev.timestamp, 96, 110, 86, 106.1)
        running = make_candle(self.running.timestamp, 102, 111, 89, 104)
        signal = Type3Engine().evaluate(prev2, prev, running, 104, direction="CALL", rsi_pass=True, sma_pass=True)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "CALL")
        self.assertTrue(signal.type2_conditions["running_low_below_previous_close"])

    def test_type3_requires_body_strictly_above_forty_percent(self):
        prev2 = make_candle(self.prev2.timestamp, 100, 108, 92, 100)
        running = make_candle(self.running.timestamp, 102, 111, 89, 104)
        forty_percent = make_candle(self.prev.timestamp, 96, 110, 86, 105.6)
        forty_one_percent = make_candle(self.prev.timestamp, 96, 110, 86, 106.1)
        self.assertIsNone(Type3Engine().evaluate(prev2, forty_percent, running, 104, direction="CALL", rsi_pass=True, sma_pass=True))
        signal = Type3Engine().evaluate(prev2, forty_one_percent, running, 104, direction="CALL", rsi_pass=True, sma_pass=True)
        self.assertIsNotNone(signal)
        self.assertGreater(signal.body_ratio, 0.40)

    def test_type3_put_is_mirrored_and_requires_high_above_previous_close(self):
        prev2 = make_candle(self.prev2.timestamp, 100, 105, 92, 100)
        prev = make_candle(self.prev.timestamp, 104, 110, 90, 93)
        running = make_candle(self.running.timestamp, 98, 104, 88, 105)
        signal = Type3Engine().evaluate(prev2, prev, running, 110, direction="PUT", rsi_pass=True, sma_pass=True)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "PUT")
        self.assertTrue(signal.type2_conditions["running_high_above_previous_close"])

    def test_type3_rejects_when_mirrored_condition_is_missing(self):
        prev2 = make_candle(self.prev2.timestamp, 100, 108, 92, 100)
        prev = make_candle(self.prev.timestamp, 96, 110, 86, 101)
        running = make_candle(self.running.timestamp, 102, 105, 98, 103)
        self.assertIsNone(Type3Engine().evaluate(prev2, prev, running, 103, direction="CALL", rsi_pass=True, sma_pass=True))
        self.assertIsNone(Type3Engine().evaluate(prev2, prev, running, 102, direction="PUT", rsi_pass=True, sma_pass=True))


if __name__ == "__main__":
    unittest.main()
