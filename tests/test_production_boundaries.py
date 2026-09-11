import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from broker.upstox import UpstoxAdapter
from market_data.candles import CandleEngine
from market_data.indicators import rsi_series
from market_data.models import Candle
from storage.sqlite_store import CandleStore

IST = ZoneInfo("Asia/Kolkata")


class ProductionBoundaryTests(unittest.TestCase):
    def test_websocket_message_preserves_exchange_and_receipt_timestamps(self):
        ticks = []
        events = []
        adapter = UpstoxAdapter(ticks.append, lambda status: None, events.append)
        adapter.set_instruments({"NIFTY": type("Instrument", (), {
            "name": "NIFTY", "token": "NSE_INDEX|Nifty 50", "exchange": "NSE_INDEX"
        })()})
        adapter._on_stream_message({
            "type": "live_feed", "currentTs": "1788834600000",
            "feeds": {"NSE_INDEX|Nifty 50": {"ltpc": {"ltp": 25000.0, "ltt": "1788834599000", "ltq": 10}}},
        })
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0].source, "UPSTOX_WEBSOCKET_V3")
        self.assertEqual(ticks[0].exchange_timestamp, ticks[0].timestamp)
        self.assertIsNotNone(ticks[0].received_timestamp)
        self.assertEqual(events[0]["instrument_key"], "NSE_INDEX|Nifty 50")
        self.assertEqual(events[0]["source"], "UPSTOX_WEBSOCKET_V3")

    def test_running_candle_can_be_restored_after_restart(self):
        engine = CandleEngine()
        timestamp = datetime(2026, 9, 8, 10, 5, tzinfo=IST)
        running = Candle("NIFTY", "NSE_INDEX", "NSE_INDEX|Nifty 50", timestamp, "5m", 100, 105, 99, 104, 20, "UPSTOX_WEBSOCKET_V3", "RUNNING")
        engine.restore_running(running)
        self.assertEqual(engine.current["NIFTY"]["timestamp"], timestamp)
        self.assertEqual(engine.current["NIFTY"]["high"], 105)
        self.assertEqual(engine.add(type("Tick", (), {
            "instrument": "NIFTY", "exchange": "NSE_INDEX", "token": "NSE_INDEX|Nifty 50",
            "timestamp": timestamp - timedelta(seconds=1), "ltp": 110, "volume": 1, "source": "LIVE"
        })()), [])
        self.assertEqual(engine.current["NIFTY"]["high"], 105)

    def test_running_volume_accumulates_tick_deltas(self):
        engine = CandleEngine()
        start = datetime(2026, 9, 8, 10, 5, tzinfo=IST)
        tick = lambda timestamp, volume: type("Tick", (), {
            "instrument": "NIFTY", "exchange": "NSE_INDEX", "token": "K",
            "timestamp": timestamp, "ltp": 100, "volume": volume, "source": "LIVE"
        })()
        engine.add(tick(start, 2))
        engine.add(tick(start + timedelta(seconds=1), 3))
        self.assertEqual(engine.current["NIFTY"]["volume"], 5)

    def test_store_keeps_raw_events_and_running_candle(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CandleStore(Path(directory) / "session.sqlite3")
            store.record_market_event("E1", {
                "instrument_key": "NSE_INDEX|Nifty 50", "exchange": "NSE_INDEX",
                "exchange_timestamp": "2026-09-08T10:05:00+05:30",
                "received_timestamp": "2026-09-08T10:05:00.100000+05:30", "ltp": 100,
                "volume": 2, "source": "UPSTOX_WEBSOCKET_V3", "sequence": 1, "payload": {"x": 1},
            })
            store.save_running(Candle("NIFTY", "NSE_INDEX", "K", datetime(2026, 9, 8, 10, 5, tzinfo=IST), "5m", 100, 101, 99, 100, 2, "UPSTOX_WEBSOCKET_V3", "RUNNING"))
            raw_count = store.connection.execute("SELECT COUNT(*) FROM raw_market_events").fetchone()[0]
            self.assertEqual(raw_count, 1)
            self.assertIsNotNone(store.latest_running("NIFTY"))
            store.close()

    def test_wilder_rsi_has_standard_warmup_and_alignment(self):
        candles = []
        start = datetime(2026, 9, 8, 9, 15, tzinfo=IST)
        closes = [44, 44.15, 43.9, 44.35, 44.2, 44.5, 44.7, 44.65, 44.8, 45.0, 44.9, 45.1, 45.2, 45.0, 45.3, 45.5]
        for index, close in enumerate(closes):
            candles.append(Candle("NIFTY", "NSE_INDEX", "K", start + timedelta(minutes=index * 5), "5m", close, close, close, close, 0, "HISTORICAL"))
        values = rsi_series(candles, 14)
        self.assertEqual(values[:14], [None] * 14)
        self.assertIsNotNone(values[14])
        self.assertIsNotNone(values[15])


if __name__ == "__main__":
    unittest.main()
