import tempfile
import unittest
from datetime import timezone
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data.models import Candle
from signals.breakout import PutCallSignal
from signals.queue import SignalQueue
from signals.coordinator import SignalCoordinator
from storage.sqlite_store import CandleStore


class QueueDatabaseTests(unittest.TestCase):
    def test_coordinator_allows_one_primary_and_promotes_after_expiry(self):
        timestamp = datetime(2026, 9, 3, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        def event(name, suffix):
            candle = Candle(name, "NSE", suffix, timestamp, "5m", 1, 2, 1, 2, 0, "UNIT")
            return PutCallSignal(suffix, timestamp, name, "CALL", 2, candle, candle, 2)
        coordinator = SignalCoordinator(expiry_seconds=1)
        first = event("NIFTY", "one")
        second = event("SENSEX", "two")
        self.assertEqual(coordinator.submit(first, timestamp), "ACTIVE")
        self.assertEqual(coordinator.submit(second, timestamp), "WAITING")
        coordinator.expire(timestamp.replace(second=17))
        self.assertEqual(coordinator.current("PRIMARY")["signal"].signal_id, "two")

    def test_queue_orders_primary_before_secondary(self):
        timestamp = datetime(2026, 9, 3, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        def event(name):
            candle = Candle(name, "NSE", "1", timestamp, "5m", 1, 2, 1, 2, 0, "UNIT")
            return PutCallSignal(name, timestamp, name, "CALL", 2, candle, candle, 2)
        queue = SignalQueue()
        queue.add(event("BANKNIFTY"))
        queue.add(event("NIFTY"))
        self.assertEqual(queue.next().signal.underlying, "NIFTY")

    def test_database_duplicate_and_mismatch(self):
        path = Path(tempfile.mktemp(suffix=".sqlite3"))
        store = CandleStore(path)
        timestamp = datetime(2026, 9, 3, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        candle = Candle("NIFTY", "NSE", "1", timestamp, "5m", 1, 2, 1, 2, 0, "UNIT")
        self.assertEqual(store.reconcile(candle), "INSERTED")
        self.assertEqual(store.reconcile(candle), "UNCHANGED")
        changed = Candle("NIFTY", "NSE", "1", timestamp, "5m", 1, 3, 1, 2, 0, "UNIT")
        self.assertEqual(store.reconcile(changed), "MISMATCH")
        store.replace(changed)
        self.assertEqual(store.reconcile(changed), "UNCHANGED")
        store.close()
        path.unlink(missing_ok=True)

    def test_audit_chain_is_persisted(self):
        path = Path(tempfile.mktemp(suffix=".sqlite3"))
        store = CandleStore(path)
        now = datetime.now(timezone.utc).isoformat()
        store.record("signals", "S1", {"instrument": "NIFTY", "direction": "CALL", "status": "ACTIVE", "created_at": now})
        store.record("approvals", "A1", {"signal_id": "S1", "decision": "APPROVED", "created_at": now})
        store.record("orders", "O1", {"signal_id": "S1", "trade_id": "T1", "status": "FILLED", "created_at": now})
        store.record("fills", "F1", {"order_id": "O1", "trade_id": "T1", "quantity": 65, "average_price": 100.0, "created_at": now})
        store.record("stop_losses", "SL1", {"trade_id": "T1", "status": "ACTIVE", "created_at": now})
        store.record("positions", "T1", {"order_id": "O1", "sl_order_id": "SL1", "state": "SL_ACTIVE", "created_at": now})
        for table in ("signals", "approvals", "orders", "fills", "stop_losses", "positions"):
            self.assertEqual(store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
        store.close()
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
