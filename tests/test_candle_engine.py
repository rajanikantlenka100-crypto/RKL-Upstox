import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_data.candles import CandleEngine
from market_data.models import MarketTick
from market_data.health import FeedHealth


class CandleEngineTests(unittest.TestCase):
    def test_stale_feed_blocks_signals(self):
        health = FeedHealth(15)
        base = datetime(2026, 9, 3, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        health.update("NIFTY", base)
        self.assertFalse(health.can_signal("NIFTY", base + timedelta(seconds=16)))
    def test_rollover_and_duplicate_tick(self):
        base = datetime(2026, 9, 3, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        closed = []
        engine = CandleEngine(closed.append)
        engine.add(MarketTick("NIFTY", "1", "NSE", base, 100, 10, "LIVE"))
        engine.add(MarketTick("NIFTY", "1", "NSE", base + timedelta(minutes=4), 105, 12, "LIVE"))
        engine.add(MarketTick("NIFTY", "1", "NSE", base + timedelta(minutes=4), 999, 12, "LIVE"))
        engine.add(MarketTick("NIFTY", "1", "NSE", base + timedelta(minutes=5), 103, 15, "LIVE"))
        self.assertEqual(len(closed), 1)
        self.assertEqual((closed[0].open, closed[0].high, closed[0].low, closed[0].close), (100, 105, 100, 105))
        self.assertEqual(engine.previous["NIFTY"].close, 105)

    def test_rejects_naive_tick(self):
        engine = CandleEngine()
        with self.assertRaises(ValueError):
            engine.add(MarketTick("NIFTY", "1", "NSE", datetime.now(), 100, 0, "LIVE"))

    def test_future_tick_is_not_marked_live(self):
        health = FeedHealth(15)
        future = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(minutes=1)
        health.update("NIFTY", future)
        self.assertEqual(health.status["NIFTY"], "DATA_UNSAFE")

    def test_feed_health_isolated_and_diagnostic(self):
        from market_data.health import FeedHealth

        base = datetime(2026, 9, 3, 13, 40, tzinfo=ZoneInfo("Asia/Kolkata"))
        health = FeedHealth(15)
        health.update("NIFTY", base)
        health.update("MIDCPNIFTY", base)
        now = base + timedelta(seconds=16)
        self.assertFalse(health.can_signal("NIFTY", now))
        self.assertFalse(health.can_signal("MIDCPNIFTY", now))
        health.update("NIFTY", now)
        self.assertTrue(health.can_signal("NIFTY", now))
        self.assertFalse(health.can_signal("MIDCPNIFTY", now))
        self.assertEqual(health.diagnostics("MIDCPNIFTY", now)["age_seconds"], 16.0)

if __name__ == "__main__":
    unittest.main()
