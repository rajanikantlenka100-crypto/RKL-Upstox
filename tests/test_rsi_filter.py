import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_data.models import Candle
from signals.rsi_filter import validate_rsi_entry


def candles(count=28, status="FINAL"):
    start = datetime(2026, 9, 3, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
    return [Candle("NIFTY", "NSE", "1", start + timedelta(minutes=index * 5), "5m",
                    100, 101, 99, 100, 0, "UNIT", status) for index in range(count)]


def mocked_series(rsi_value, sma_value, prior_rsi=50.0, prior_sma=50.0):
    rsi_values = [None] * 28
    sma_values = [None] * 28
    rsi_values[-2:] = [prior_rsi, rsi_value]
    sma_values[-2:] = [prior_sma, sma_value]
    return rsi_values, sma_values


class RSIFilterTests(unittest.TestCase):
    def evaluate(self, direction, rsi_value, sma_value, candles_to_use=None):
        rsi_values, sma_values = mocked_series(rsi_value, sma_value)
        with patch("signals.rsi_filter.rsi_series", return_value=rsi_values), \
                patch("signals.rsi_filter.rsi_sma_series", return_value=sma_values):
            return validate_rsi_entry(candles_to_use or candles(), direction)

    def test_call_passes_only_when_latest_rsi_is_above_sma(self):
        self.assertEqual(self.evaluate("CALL", 60, 50).result, "PASS")
        self.assertEqual(self.evaluate("CALL", 50, 50).result, "REJECT")
        self.assertEqual(self.evaluate("CALL", 40, 50).result, "REJECT")

    def test_put_passes_only_when_latest_rsi_is_below_sma(self):
        self.assertEqual(self.evaluate("PUT", 40, 50).result, "PASS")
        self.assertEqual(self.evaluate("PUT", 50, 50).result, "REJECT")
        self.assertEqual(self.evaluate("PUT", 60, 50).result, "REJECT")

    def test_only_latest_finalized_candle_is_evaluated(self):
        values = candles()
        rsi_values, sma_values = mocked_series(40, 50, prior_rsi=60, prior_sma=50)
        with patch("signals.rsi_filter.rsi_series", return_value=rsi_values), \
                patch("signals.rsi_filter.rsi_sma_series", return_value=sma_values):
            result = validate_rsi_entry(values, "CALL")
        self.assertEqual(result.result, "REJECT")
        self.assertEqual(result.evaluated_candle_timestamps, (values[-1].timestamp,))

    def test_latest_missing_values_are_unavailable(self):
        rsi_values, sma_values = mocked_series(60, 50)
        rsi_values[-1] = None
        with patch("signals.rsi_filter.rsi_series", return_value=rsi_values), \
                patch("signals.rsi_filter.rsi_sma_series", return_value=sma_values):
            result = validate_rsi_entry(candles(), "CALL")
        self.assertEqual(result.result, "UNAVAILABLE")

    def test_running_candle_is_not_accepted_as_finalized_input(self):
        values = candles()
        values[-1] = Candle(values[-1].instrument, values[-1].exchange, values[-1].token,
                             values[-1].timestamp, values[-1].timeframe, 100, 101, 99, 100, 0,
                             "UNIT", "RUNNING")
        self.assertEqual(self.evaluate("CALL", 60, 50, values).result, "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
