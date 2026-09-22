import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from market_data.candles import CandleEngine
from market_data.models import Candle, MarketTick
from signals.breakout import BreakoutEngine, Type2Engine, Type3Engine


IST = ZoneInfo("Asia/Kolkata")


def candle(name, minute, open_price, high, low, close, status="FINAL"):
    return Candle(name, "NSE_INDEX", name, datetime(2026, 9, 17, 10, minute, tzinfo=IST), "5m", open_price, high, low, close, 1, "TEST", status)


class RealtimeEngineVerificationTests(unittest.TestCase):
    def test_candle_gap_finalizes_only_the_last_running_bucket(self):
        engine = CandleEngine()
        engine.add(MarketTick("NIFTY", "NIFTY", "NSE_INDEX", datetime(2026, 9, 17, 10, 0, tzinfo=IST), 100, 1, "TEST"))
        finalized = engine.add(MarketTick("NIFTY", "NIFTY", "NSE_INDEX", datetime(2026, 9, 17, 10, 15, tzinfo=IST), 105, 1, "TEST"))
        self.assertEqual(len(finalized), 1)
        self.assertEqual(finalized[0].timestamp.minute, 0)
        self.assertEqual(engine.current["NIFTY"]["timestamp"].minute, 15)
        self.assertNotIn(5, [item.timestamp.minute for item in engine.history["NIFTY"]])

    def test_type1_call_is_running_candle_signal(self):
        previous = candle("NIFTY", 0, 100, 110, 90, 100)
        running = candle("NIFTY", 5, 100, 100, 89, 89, "RUNNING")
        engine = BreakoutEngine()
        self.assertIsNone(engine.evaluate(previous, running, 89, running.timestamp))
        running = candle("NIFTY", 5, 100, 111, 89, 111, "RUNNING")
        signal = engine.evaluate(previous, running, 111, running.timestamp)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.signal_type, "TYPE_1")
        self.assertEqual(signal.direction, "CALL")

    def test_type2_and_type3_are_running_candle_signals(self):
        prev2 = candle("NIFTY", 0, 100, 110, 95, 100)
        previous = candle("NIFTY", 5, 98, 105, 90, 100)
        running = candle("NIFTY", 10, 101, 111, 91, 103, "RUNNING")
        type2 = Type2Engine().evaluate(prev2, previous, running, 103, direction="CALL", rsi_pass=True)
        self.assertIsNotNone(type2)
        self.assertEqual(type2.signal_type, "TYPE_2")

        type3_previous = candle("NIFTY", 5, 96, 108, 86, 106.1)
        type3 = Type3Engine().evaluate(prev2, type3_previous, running, 103, direction="CALL", rsi_pass=True, sma_pass=True)
        self.assertIsNotNone(type3)
        self.assertEqual(type3.signal_type, "TYPE_3")

    def test_session_configuration_is_1515(self):
        self.assertEqual(config.MARKET_OPEN, (9, 15))
        self.assertEqual(config.MARKET_CLOSE, (15, 15))


if __name__ == "__main__":
    unittest.main()
