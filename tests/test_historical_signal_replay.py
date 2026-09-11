import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from historical_signal_replay import replay, sequence_from_ohlc, validate_dataset
from market_data.models import Candle


class HistoricalSignalReplayTests(unittest.TestCase):
    def candle(self, open_price, high, low, close, minute=0):
        return Candle("NIFTY", "NSE", "1", datetime(2026, 9, 2, 9, 15 + minute, tzinfo=ZoneInfo("Asia/Kolkata")), "5m", open_price, high, low, close, 0, "HISTORICAL")

    def test_ohlc_inside_range_with_both_breaks_is_not_verifiable(self):
        previous = self.candle(100, 105, 95, 100)
        current = self.candle(100, 106, 94, 100, 5)
        path, reason = sequence_from_ohlc(previous, current)
        self.assertIsNone(path)
        self.assertEqual(reason, "INTRABAR_SEQUENCE_NOT_VERIFIABLE")

    def test_open_outside_range_proves_sequence(self):
        previous = self.candle(100, 105, 95, 100)
        current = self.candle(94, 106, 94, 101, 5)
        path, reason = sequence_from_ohlc(previous, current)
        self.assertEqual(path, [94, 106])
        self.assertEqual(reason, "LOW_FIRST_PROVEN")

    def test_quality_detects_missing_bucket(self):
        candles = [self.candle(100, 101, 99, 100), self.candle(100, 101, 99, 100, 10)]
        quality = validate_dataset(candles)
        self.assertTrue(quality["missing_buckets"]["2026-09-02"])

    def test_replay_does_not_evaluate_after_same_session_gap(self):
        candles = [
            self.candle(100, 101, 99, 100, 0),
            self.candle(100, 101, 99, 100, 5),
            self.candle(94, 106, 94, 101, 15),
        ]
        signals, events = replay(candles, {datetime(2026, 9, 2).date()})
        self.assertEqual(signals, [])
        self.assertIn("DATA_GAP", {event["reason"] for event in events})


if __name__ == "__main__":
    unittest.main()