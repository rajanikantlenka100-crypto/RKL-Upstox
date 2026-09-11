import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from broker.order_manager import OrderExecutor
from storage.sqlite_store import CandleStore
from services.preflight import run_local_preflight


class ExecutionModeTests(unittest.TestCase):
    def test_order_gate_requires_production_mode_and_preflight(self):
        with patch("config.ENABLE_REAL_ORDERS", True), \
             patch("config.EXECUTION_MODE", "PRODUCTION"), \
             patch("config.PREFLIGHT_PASSED", False):
            self.assertFalse(__import__("config").order_execution_enabled())
        with patch("config.ENABLE_REAL_ORDERS", True), \
             patch("config.EXECUTION_MODE", "PRODUCTION"), \
             patch("config.PREFLIGHT_PASSED", True):
            self.assertTrue(__import__("config").order_execution_enabled())

    def test_database_rejects_execution_mode_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mode.sqlite3"
            first = CandleStore(path, mode="READ_ONLY")
            first.close()
            with self.assertRaisesRegex(RuntimeError, "execution mode mismatch"):
                CandleStore(path, mode="PRODUCTION")

    def test_read_only_preflight_does_not_require_order_client(self):
        class Store:
            def is_healthy(self): return True
            def unfinished_order_requests(self): return []

        class Display:
            rest_status = {name: "SYNCED" for name in ("NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY")}
            components = {"AUTH": "READY", "BROKER": "READY"}

        with patch("config.EXECUTION_MODE", "READ_ONLY"), patch("config.ENABLE_REAL_ORDERS", False):
            result = run_local_preflight(
                store=Store(), instruments=Display.rest_status, display=Display(),
                order_manager=None, public_ip=None,
            )
        self.assertTrue(result.passed, result.summary)


if __name__ == "__main__":
    unittest.main()
