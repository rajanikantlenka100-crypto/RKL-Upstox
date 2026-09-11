import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_data.models import Candle
from signals.rsi_filter import validate_rsi_entry


def closed_candles(count=25):
    start = datetime(2026, 9, 3, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
    return [Candle("NIFTY", "NSE", "1", start + timedelta(minutes=index * 5), "5m",
                    100, 101, 99, 100, 0, "UNIT") for index in range(count)]


def indicator_series(candles, rsi_values, sma_values):
    rsi_series = [None] * len(candles)
    sma_series = [None] * len(candles)
    rsi_series[-5:] = rsi_values
    sma_series[-5:] = sma_values
    return rsi_series, sma_series


class RSIFilterTests(unittest.TestCase):
    def assert_direction_counts(self, direction, counts):
        candles = closed_candles()
        rsi_values = [50.0] * 5 if direction == "CALL" else [30.0] * 5
        sma_values = [45.0] * 5
        for index in range(counts):
            if direction == "CALL":
                rsi_values[index] = 40.0
            else:
                rsi_values[index] = 50.0
        series = indicator_series(candles, rsi_values, sma_values)
        with patch("signals.rsi_filter.rsi_series", return_value=series[0]), \
             patch("signals.rsi_filter.rsi_sma_series", return_value=series[1]):
            result = validate_rsi_entry(candles, direction)
        self.assertEqual(result.result, "PASS" if counts else "REJECT")
        self.assertEqual(result.matching_periods, counts)
        self.assertEqual(len(result.evaluated_candle_timestamps), 5)

    def test_call_one_to_five_matches_pass(self):
        for count in range(1, 6):
            with self.subTest(count=count):
                self.assert_direction_counts("CALL", count)

    def test_put_one_to_five_matches_pass(self):
        for count in range(1, 6):
            with self.subTest(count=count):
                self.assert_direction_counts("PUT", count)

    def test_call_none_matches_rejects(self):
        self.assert_direction_counts("CALL", 0)

    def test_put_none_matches_rejects(self):
        self.assert_direction_counts("PUT", 0)

    def test_equality_does_not_match(self):
        candles = closed_candles()
        values = indicator_series(candles, [44.0] * 5, [44.0] * 5)
        with patch("signals.rsi_filter.rsi_series", return_value=values[0]), \
             patch("signals.rsi_filter.rsi_sma_series", return_value=values[1]):
            call = validate_rsi_entry(candles, "CALL")
            put = validate_rsi_entry(candles, "PUT")
        self.assertEqual(call.result, "REJECT")
        self.assertEqual(put.result, "REJECT")
        self.assertEqual(call.matching_periods, 0)
        self.assertEqual(put.matching_periods, 0)

    def test_insufficient_lookback_is_unavailable(self):
        candles = closed_candles(4)
        result = validate_rsi_entry(candles, "CALL")
        self.assertEqual(result.result, "UNAVAILABLE")

    def test_insufficient_rsi_or_sma_history_is_unavailable(self):
        candles = closed_candles(18)
        result = validate_rsi_entry(candles, "CALL")
        self.assertEqual(result.result, "UNAVAILABLE")

    def test_comparison_is_period_aligned(self):
        candles = closed_candles()
        rsi_values = [50.0, 40.0, 50.0, 50.0, 50.0]
        sma_values = [45.0, 45.0, 45.0, 45.0, 45.0]
        series = indicator_series(candles, rsi_values, sma_values)
        with patch("signals.rsi_filter.rsi_series", return_value=series[0]), \
             patch("signals.rsi_filter.rsi_sma_series", return_value=series[1]):
            result = validate_rsi_entry(candles, "CALL")
        self.assertEqual(result.result, "PASS")
        self.assertEqual(result.matching_periods, 1)
        self.assertEqual(result.matching_candle_timestamps, (candles[-4].timestamp,))

    def test_running_candle_is_not_part_of_closed_input(self):
        candles = closed_candles()
        values = indicator_series(candles, [50.0, 40.0, 50.0, 50.0, 50.0], [45.0] * 5)
        running = Candle("NIFTY", "NSE", "1", candles[-1].timestamp + timedelta(minutes=5),
                         "5m", 100, 1000, 1, 1000, 0, "LIVE")
        with patch("signals.rsi_filter.rsi_series", return_value=values[0]), \
             patch("signals.rsi_filter.rsi_sma_series", return_value=values[1]):
            before = validate_rsi_entry(candles, "CALL")
            after = validate_rsi_entry(candles, "CALL")
        self.assertEqual(before, after)
        self.assertNotIn(running.timestamp, before.evaluated_candle_timestamps)

    def test_non_final_candle_is_unavailable(self):
        candles = closed_candles()
        candles[-1] = Candle("NIFTY", "NSE", "1", candles[-1].timestamp, "5m",
                             100, 101, 99, 100, 0, "UNIT", status="LIVE")
        result = validate_rsi_entry(candles, "CALL")
        self.assertEqual(result.result, "UNAVAILABLE")
        self.assertIn("non-final", result.reason)

    def test_duplicate_candle_timestamp_is_unavailable(self):
        candles = closed_candles()
        candles[-1] = Candle("NIFTY", "NSE", "1", candles[-2].timestamp, "5m",
                             100, 101, 99, 100, 0, "UNIT")
        result = validate_rsi_entry(candles, "CALL")
        self.assertEqual(result.result, "UNAVAILABLE")

    def test_evaluated_values_are_aligned_and_auditable(self):
        candles = closed_candles()
        values = indicator_series(candles, [50.0, 40.0, 50.0, 50.0, 50.0], [45.0] * 5)
        with patch("signals.rsi_filter.rsi_series", return_value=values[0]), \
             patch("signals.rsi_filter.rsi_sma_series", return_value=values[1]):
            result = validate_rsi_entry(candles, "CALL")
        self.assertEqual(result.evaluated_rsi_values, (50.0, 40.0, 50.0, 50.0, 50.0))
        self.assertEqual(result.evaluated_sma_values, (45.0,) * 5)


if __name__ == "__main__":
    unittest.main()