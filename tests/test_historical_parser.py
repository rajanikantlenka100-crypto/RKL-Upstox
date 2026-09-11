import unittest

from market_data.historical import parse_historical_row


class HistoricalParserTests(unittest.TestCase):
    """UNIT: deterministic Upstox row parsing; no broker request."""

    def test_parses_upstox_candle_row(self):
        parsed = parse_historical_row(["2026-09-03T13:30:00+05:30", 100, 105, 99, 104, 0])
        self.assertEqual(parsed[0].strftime("%H:%M"), "13:30")
        self.assertEqual(parsed[1:], (100.0, 105.0, 99.0, 104.0, 0))

    def test_rejects_malformed_row(self):
        with self.assertRaisesRegex(ValueError, "six historical fields"):
            parse_historical_row(["bad timestamp", 1, 2])

    def test_rejects_invalid_ohlc_geometry(self):
        with self.assertRaisesRegex(ValueError, "geometry"):
            parse_historical_row(["2026-09-03T13:30:00+05:30", 100, 90, 99, 104, 0])


if __name__ == "__main__":
    unittest.main()