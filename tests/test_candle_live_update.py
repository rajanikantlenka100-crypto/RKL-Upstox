import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_data.candles import CandleEngine
from market_data.models import MarketTick


class CandleLiveUpdateTests(unittest.TestCase):
    """UNIT: real candle state transitions with deterministic ticks; no broker."""

    def test_running_ohlc_updates_on_each_tick(self):
        start = datetime(2026, 9, 3, 13, 40, tzinfo=ZoneInfo("Asia/Kolkata"))
        engine = CandleEngine()
        engine.add(MarketTick("NIFTY", "1", "NSE", start, 100, 1, "LIVE"))
        engine.add(MarketTick("NIFTY", "1", "NSE", start + timedelta(seconds=1), 105, 2, "LIVE"))
        engine.add(MarketTick("NIFTY", "1", "NSE", start + timedelta(seconds=2), 98, 3, "LIVE"))
        current = engine.current["NIFTY"]
        self.assertEqual((current["open"], current["high"], current["low"], current["close"]), (100, 105, 98, 98))

    def test_rollover_publishes_previous_completed_candle(self):
        start = datetime(2026, 9, 3, 13, 40, tzinfo=ZoneInfo("Asia/Kolkata"))
        closed = []
        engine = CandleEngine(closed.append)
        engine.add(MarketTick("NIFTY", "1", "NSE", start, 100, 1, "LIVE"))
        engine.add(MarketTick("NIFTY", "1", "NSE", start + timedelta(minutes=4), 105, 2, "LIVE"))
        engine.add(MarketTick("NIFTY", "1", "NSE", start + timedelta(minutes=5), 102, 3, "LIVE"))
        engine.add(MarketTick("NIFTY", "1", "NSE", start + timedelta(minutes=10), 103, 4, "LIVE"))
        self.assertEqual(len(closed), 2)
        self.assertEqual(engine.previous["NIFTY"], closed[-1])
        self.assertEqual(closed[0].close, 105)
        self.assertEqual(engine.current["NIFTY"]["open"], 103)
        self.assertEqual(engine.current["NIFTY"]["timestamp"].minute, 50)
        self.assertEqual(engine.prev2["NIFTY"].timestamp.minute, 40)
        self.assertEqual(engine.previous["NIFTY"].timestamp.minute, 45)


if __name__ == "__main__":
    unittest.main()
