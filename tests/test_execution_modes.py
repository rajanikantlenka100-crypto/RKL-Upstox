import json
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

    def test_read_only_mode_disables_auto_entry_reporting(self):
        with patch("config.EXECUTION_MODE", "READ_ONLY"), \
             patch("config.AUTO_ENTRY_ENABLED", True), \
             patch("config.AUTO_TRADING_ENABLED", True):
            self.assertFalse(__import__("config").effective_auto_entry_enabled())
            self.assertEqual(__import__("config").execution_status_label(), "READ_ONLY")

    def test_live_mode_requires_static_ip_and_real_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "production.sqlite3"
            with patch("config.EXECUTION_MODE", "PRODUCTION"), \
                 patch("config.ENABLE_REAL_ORDERS", True), \
                 patch("config.ORDER_ENV", "live"), \
                 patch("config.AUTO_TRADING_ENABLED", True), \
                 patch("config.ORDER_IP_WHITELIST", ""), \
                 patch("config.DATABASE_PATH", db_path):
                with self.assertRaisesRegex(RuntimeError, "UPSTOX_ORDER_IP"):
                    __import__("config").validate_runtime()

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

        with tempfile.TemporaryDirectory() as directory:
            instrument_master = Path(directory) / "instrument_master.json"
            instrument_master.write_text(json.dumps([
                {"instrument_key": "NSE_INDEX|Nifty 50"},
                {"instrument_key": "NSE_INDEX|Nifty Bank"},
                {"instrument_key": "BSE_INDEX|SENSEX"},
                {"instrument_key": "NSE_INDEX|NIFTY MID SELECT"},
            ]), encoding="utf-8")
            with patch("config.EXECUTION_MODE", "READ_ONLY"), \
                 patch("config.ENABLE_REAL_ORDERS", False), \
                 patch("config.INSTRUMENT_MASTER_PATH", instrument_master):
                result = run_local_preflight(
                    store=Store(), instruments=Display.rest_status, display=Display(),
                    order_manager=None, public_ip=None,
                )
        self.assertTrue(result.passed, result.summary)


if __name__ == "__main__":
    unittest.main()
