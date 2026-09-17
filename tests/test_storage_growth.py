import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from storage.sqlite_store import CandleStore


class StorageGrowthTests(unittest.TestCase):
    def test_raw_market_events_and_telemetry_are_hard_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CandleStore(Path(directory) / "bounded.sqlite3")
            try:
                with patch("config.RAW_MARKET_MAX_ROWS", 25), patch("config.TELEMETRY_MAX_ROWS", 25):
                    for index in range(100):
                        timestamp = (datetime.now(timezone.utc) + timedelta(seconds=index)).isoformat()
                        store.record_market_event(f"event-{index}", {
                            "instrument_key": "NIFTY",
                            "exchange": "NSE_INDEX",
                            "exchange_timestamp": timestamp,
                            "received_timestamp": timestamp,
                            "ltp": 100 + index,
                            "volume": 1,
                            "source": "TEST",
                            "sequence": index,
                            "payload": {},
                        })
                        store.record_telemetry(f"telemetry-{index}", {
                            "timestamp": timestamp,
                            "event_type": "TEST",
                            "payload": {},
                        })
                    raw_count = store.connection.execute("SELECT COUNT(*) FROM raw_market_events").fetchone()[0]
                    telemetry_count = store.connection.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0]
                self.assertLessEqual(raw_count, 25)
                self.assertLessEqual(telemetry_count, 25)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
