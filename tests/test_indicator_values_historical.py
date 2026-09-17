import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_data.indicators import cci, fast_stochastic_series, rsi_series, rsi_sma_series, sma_series
from market_data.models import Candle
from signals.rsi_filter import validate_rsi_entry


IST = ZoneInfo("Asia/Kolkata")


def make_candles(instrument="NIFTY", status="FINAL", count=30):
    start = datetime(2026, 9, 17, 9, 15, tzinfo=IST)
    candles = []
    for index in range(count):
        close = 100.0 + ((index * 7) % 13) - index * 0.35
        open_price = close - (0.8 if index % 2 else -0.4)
        low = min(open_price, close) - 1.5 - (index % 3) * 0.1
        high = max(open_price, close) + 1.7 + (index % 4) * 0.1
        candles.append(Candle(
            instrument, "NSE_INDEX", instrument,
            start + timedelta(minutes=index * 5), "5m",
            open_price, high, low, close, 100 + index, "HISTORICAL", status,
        ))
    return candles


def expected_sma(candles, index, period):
    return sum(item.close for item in candles[index - period + 1:index + 1]) / period


def expected_rsi(candles, index, period=14):
    changes = [candles[position].close - candles[position - 1].close for position in range(1, index + 1)]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for offset in range(period, len(gains)):
        average_gain = ((average_gain * (period - 1)) + gains[offset]) / period
        average_loss = ((average_loss * (period - 1)) + losses[offset]) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    return 100.0 - (100.0 / (1.0 + average_gain / average_loss))


def expected_cci(candles, index, period=5):
    window = candles[index - period + 1:index + 1]
    typical = [(item.high + item.low + item.close) / 3 for item in window]
    mean = sum(typical) / period
    deviation = sum(abs(value - mean) for value in typical) / period
    return 0.0 if deviation == 0 else (typical[-1] - mean) / (0.015 * deviation)


def expected_stochastic(candles, index, period=14):
    window = candles[index - period + 1:index + 1]
    lowest = min(item.low for item in window)
    highest = max(item.high for item in window)
    return None if highest == lowest else 100.0 * (candles[index].close - lowest) / (highest - lowest)


class HistoricalIndicatorValueTests(unittest.TestCase):
    def test_numerical_values_match_independent_reference(self):
        candles = make_candles()
        sma8 = sma_series(candles, 8)
        sma13 = sma_series(candles, 13)
        sma21 = sma_series(candles, 21)
        rsi_values = rsi_series(candles, 14)
        rsi_sma_values = rsi_sma_series(candles, 14, 5)
        stochastic_values = fast_stochastic_series(candles, 14)
        for index in (7, 12, 13, 18, 20, 21, 29):
            self.assertAlmostEqual(sma8[index], expected_sma(candles, index, 8))
            if index >= 12:
                self.assertAlmostEqual(sma13[index], expected_sma(candles, index, 13))
            if index >= 20:
                self.assertAlmostEqual(sma21[index], expected_sma(candles, index, 21))
            if index >= 14:
                self.assertAlmostEqual(rsi_values[index], expected_rsi(candles, index))
            if index >= 18:
                expected_rsi_sma = sum(rsi_values[index - 4:index + 1]) / 5
                self.assertAlmostEqual(rsi_sma_values[index], expected_rsi_sma)
            if index >= 13:
                self.assertAlmostEqual(stochastic_values[index], expected_stochastic(candles, index))
            if index >= 4:
                self.assertAlmostEqual(cci(candles[:index + 1], 5), expected_cci(candles, index))

    def test_insufficient_history_and_running_candle_are_unavailable(self):
        candles = make_candles(count=13)
        self.assertIsNone(sma_series(candles, 21)[-1])
        self.assertIsNone(rsi_series(candles, 14)[-1])
        self.assertIsNone(fast_stochastic_series(candles, 14)[-1])
        self.assertIsNone(cci(candles, 14))
        running = make_candles(status="RUNNING")
        self.assertIsNone(sma_series(running, 8)[-1])
        # RSI series accepts caller-supplied candles; the live entry path passes
        # finalized engine.history and therefore excludes the running candle.
        self.assertIsNotNone(rsi_series(running, 14)[-1])
        self.assertIsNone(fast_stochastic_series(running, 14)[-1])

    def test_zero_stochastic_range_is_none(self):
        candles = [Candle("NIFTY", "NSE_INDEX", "NIFTY", datetime(2026, 9, 17, 9, 15, tzinfo=IST) + timedelta(minutes=index * 5), "5m", 100, 100, 100, 100, 0, "HISTORICAL") for index in range(14)]
        self.assertIsNone(fast_stochastic_series(candles, 14)[-1])

    def test_duplicate_timestamp_is_rejected_by_entry_filter(self):
        candles = make_candles()
        candles[10] = candles[9]
        result = validate_rsi_entry(candles, "CALL")
        self.assertEqual(result.result, "UNAVAILABLE")
        self.assertIn("unique and chronological", result.reason)

    def test_histories_are_isolated_by_underlying(self):
        nifty = make_candles("NIFTY")
        sensex = make_candles("SENSEX")
        sensex[-1] = Candle("SENSEX", "BSE_INDEX", "SENSEX", sensex[-1].timestamp, "5m", 500, 510, 490, 505, 1, "HISTORICAL")
        self.assertNotEqual(fast_stochastic_series(nifty, 14)[-1], fast_stochastic_series(sensex, 14)[-1])


if __name__ == "__main__":
    unittest.main()
