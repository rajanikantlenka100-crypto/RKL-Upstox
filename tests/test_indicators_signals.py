import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_data.indicators import cci, rsi
from market_data.models import Candle
from signals.breakout import BreakoutEngine


def candle(index, close):
    timestamp = datetime(2026, 9, 3, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")) + timedelta(minutes=index * 5)
    return Candle("NIFTY", "NSE", "1", timestamp, "5m", close - 1, close + 1, close - 2, close, 0, "UNIT")


class IndicatorSignalTests(unittest.TestCase):
    def test_insufficient_history_is_unavailable(self):
        values = [candle(index, 100 + index) for index in range(4)]
        self.assertIsNone(cci(values, 5))
        self.assertIsNone(rsi(values, 14))

    def test_low_then_high_is_one_call(self):
        signals = self._run([95, 89, 95, 101])
        self.assertEqual([signal.direction for signal in signals], ["CALL"])
        self.assertEqual(signals[0].first_break_side, "LOW")
        self.assertEqual(signals[0].second_break_side, "HIGH")
        self.assertEqual(signals[0].candle_colour, "GREEN")

    def test_high_then_low_is_one_put(self):
        signals = self._run([95, 101, 95, 89])
        self.assertEqual([signal.direction for signal in signals], ["PUT"])
        self.assertEqual(signals[0].first_break_side, "HIGH")
        self.assertEqual(signals[0].second_break_side, "LOW")
        self.assertEqual(signals[0].candle_colour, "RED")

    def test_both_directions_are_independent(self):
        signals = self._run([95, 89, 95, 101, 95, 89])
        self.assertEqual([signal.direction for signal in signals], ["CALL", "PUT"])
        self.assertEqual(signals[0].first_break_side, "LOW")
        self.assertEqual(signals[1].first_break_side, "HIGH")
        self.assertEqual(signals[0].first_break_price, 89)
        self.assertEqual(signals[1].first_break_price, 101)

    def test_open_below_range_counts_as_low_first(self):
        signals = self._run([87, 90, 95, 101])
        self.assertEqual([signal.direction for signal in signals], ["CALL"])

    def test_open_above_range_counts_as_high_first(self):
        signals = self._run([103, 100, 95, 89])
        self.assertEqual([signal.direction for signal in signals], ["PUT"])

    def test_first_break_alone_does_not_trade(self):
        self.assertEqual(self._run([95, 89, 85, 80]), [])
        self.assertEqual(self._run([95, 101, 105, 102]), [])

    def test_one_signal_per_direction(self):
        signals = self._run([95, 89, 101, 89, 101])
        self.assertEqual([signal.direction for signal in signals], ["CALL", "PUT"])

    def test_new_running_candle_resets_sequence_and_fired_flags(self):
        previous = Candle("NIFTY", "NSE", "1", datetime(2026, 9, 3, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")), "5m", 95, 100, 90, 95, 0, "UNIT")
        first_timestamp = datetime(2026, 9, 3, 10, 5, tzinfo=ZoneInfo("Asia/Kolkata"))
        second = Candle("NIFTY", "NSE", "1", datetime(2026, 9, 3, 10, 10, tzinfo=ZoneInfo("Asia/Kolkata")), "5m", 95, 95, 95, 95, 0, "UNIT")
        engine = BreakoutEngine()
        self.assertEqual(engine.evaluate(previous, Candle("NIFTY", "NSE", "1", first_timestamp, "5m", 95, 95, 95, 95, 0, "UNIT"), 95), None)
        self.assertEqual(engine.evaluate(previous, Candle("NIFTY", "NSE", "1", first_timestamp, "5m", 95, 95, 89, 89, 0, "UNIT"), 89), None)
        self.assertEqual(engine.evaluate(previous, Candle("NIFTY", "NSE", "1", first_timestamp, "5m", 95, 101, 89, 101, 0, "UNIT"), 101).direction, "CALL")
        self.assertEqual(engine.evaluate(previous, second, 95), None)
        self.assertFalse(engine.call_fired)
        self.assertFalse(engine.put_fired)
        self.assertEqual(engine.previous_ltp, 95)

    def test_explicit_gap_reset_discards_intrabar_sequence(self):
        timestamp = datetime(2026, 9, 3, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        previous = Candle("NIFTY", "NSE", "1", timestamp, "5m", 95, 100, 90, 95, 0, "UNIT")
        engine = BreakoutEngine()
        engine.evaluate(previous, Candle("NIFTY", "NSE", "1", timestamp, "5m", 95, 95, 89, 89, 0, "UNIT"), 89, timestamp)
        engine.reset_sequence()
        self.assertIsNone(engine.evaluate(
            previous, Candle("NIFTY", "NSE", "1", timestamp, "5m", 95, 101, 89, 101, 0, "UNIT"), 101, timestamp
        ))

    @staticmethod
    def _run(prices):
        timestamp = datetime(2026, 9, 3, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        previous = Candle("NIFTY", "NSE", "1", timestamp, "5m", 95, 100, 90, 95, 0, "UNIT")
        engine = BreakoutEngine()
        signals = []
        open_price = prices[0]
        high = open_price
        low = open_price
        for price in prices:
            high = max(high, price)
            low = min(low, price)
            running = Candle("NIFTY", "NSE", "1", timestamp, "5m", open_price, high, low, price, 0, "UNIT")
            signal = engine.evaluate(previous, running, price, timestamp)
            if signal:
                signals.append(signal)
        return signals


if __name__ == "__main__":
    unittest.main()
