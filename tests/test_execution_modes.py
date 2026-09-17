import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from broker.order_manager import OrderExecutor
from main import MarketDataService
from services.preflight import PreflightResult
from storage.sqlite_store import CandleStore
from services.preflight import run_local_preflight


class ExecutionModeTests(unittest.TestCase):
    def _preflight_service(self, result):
        service = MarketDataService.__new__(MarketDataService)
        service.display = MagicMock()
        service.store = MagicMock()
        service.instruments = {}
        service.position_manager = None
        service.order_manager = None
        service.public_ip = None
        return service, result

    def _startup_preflight_service(self):
        service = MarketDataService.__new__(MarketDataService)
        service.display = MagicMock()
        service.display.lock = threading.Lock()
        service.display.rest_status = {"NIFTY": "SYNCED"}
        service.store = MagicMock()
        service.instruments = {"NIFTY": MagicMock()}
        service.position_manager = None
        service.order_manager = None
        service.public_ip = None
        service.stop_event = MagicMock()
        service.stop_event.is_set.return_value = False
        service.stop_event.wait.return_value = True
        service.dashboard = MagicMock()
        service.dashboard.start.return_value = "http://127.0.0.1:8765/"
        service.adapter = MagicMock()
        service.safety = MagicMock()
        service.safety.state = "RUNNING"
        service.trading_state = "RUNNING"
        service.recovery_required = False
        service.websocket_started = False
        service.dashboard_started = False
        service.stop_reason = None
        service._lifecycle = MagicMock()
        service._authenticate_and_validate = MagicMock()
        service._check_public_ip = MagicMock()
        service._reconcile_positions = MagicMock()
        service._reconcile_order_requests = MagicMock()
        service._backfill = MagicMock()
        service._initialize_option_universe = MagicMock()
        service._periodic_sync = MagicMock()
        return service

    def _assert_startup_preflight_does_not_open_gate(self, mode, enable_real_orders):
        service = self._startup_preflight_service()
        result = PreflightResult(True, "2026-09-12T09:15:00+05:30")
        with patch("config.EXECUTION_MODE", mode), \
             patch("config.ENABLE_REAL_ORDERS", enable_real_orders), \
             patch("config.PREFLIGHT_PASSED", False), \
             patch("config.validate_runtime"), \
             patch("main.run_local_preflight", return_value=result), \
             patch("main.threading.Thread"):
            service.start()
            self.assertTrue(result.passed)
            self.assertFalse(__import__("config").PREFLIGHT_PASSED)
            self.assertFalse(__import__("config").order_execution_enabled())

    def test_production_startup_preflight_pass_is_readiness_only(self):
        self._assert_startup_preflight_does_not_open_gate("PRODUCTION", True)

    def test_sandbox_startup_preflight_pass_is_readiness_only(self):
        self._assert_startup_preflight_does_not_open_gate("SANDBOX", False)

    def test_production_preflight_pass_opens_execution_gate(self):
        result = PreflightResult(True, "2026-09-12T09:15:00+05:30")
        service, _ = self._preflight_service(result)
        with patch("config.EXECUTION_MODE", "PRODUCTION"), \
               patch("config.ENABLE_REAL_ORDERS", True), \
             patch("config.PREFLIGHT_PASSED", False), \
             patch("main.run_local_preflight", return_value=result):
            service._try_activate_execution_preflight()
            self.assertTrue(__import__("config").PREFLIGHT_PASSED)
            self.assertTrue(__import__("config").order_execution_enabled())

    def test_production_preflight_failure_keeps_execution_gate_closed(self):
        result = PreflightResult(False, "2026-09-12T09:15:00+05:30", failures=("database_healthy",))
        service, _ = self._preflight_service(result)
        with patch("config.EXECUTION_MODE", "PRODUCTION"), \
             patch("config.PREFLIGHT_PASSED", False), \
             patch("main.run_local_preflight", return_value=result):
            service._try_activate_execution_preflight()
            self.assertFalse(__import__("config").PREFLIGHT_PASSED)
            self.assertFalse(__import__("config").order_execution_enabled())

    def test_sandbox_preflight_pass_opens_execution_gate(self):
        result = PreflightResult(True, "2026-09-12T09:15:00+05:30")
        service, _ = self._preflight_service(result)
        with patch("config.EXECUTION_MODE", "SANDBOX"), \
               patch("config.ENABLE_REAL_ORDERS", False), \
             patch("config.PREFLIGHT_PASSED", False), \
             patch("main.run_local_preflight", return_value=result):
            service._try_activate_execution_preflight()
            self.assertTrue(__import__("config").PREFLIGHT_PASSED)
            self.assertTrue(__import__("config").order_execution_enabled())

    def test_sandbox_requires_real_orders_disabled(self):
        with patch("config.EXECUTION_MODE", "SANDBOX"), \
             patch("config.ENABLE_REAL_ORDERS", True), \
             patch("config.ORDER_ENV", "sandbox"), \
             patch("config.PREFLIGHT_PASSED", True):
            with self.assertRaisesRegex(RuntimeError, "SANDBOX requires REAL_ORDERS_ENABLED=OFF"):
                __import__("config").validate_runtime()

    def test_read_only_and_backtest_cannot_execute_real_orders(self):
        for mode in ("READ_ONLY", "BACKTEST"):
            with self.subTest(mode=mode), \
                 patch("config.EXECUTION_MODE", mode), \
                 patch("config.ENABLE_REAL_ORDERS", True), \
                 patch("config.PREFLIGHT_PASSED", True):
                self.assertFalse(__import__("config").order_execution_enabled())

    def test_order_gate_requires_production_mode_and_preflight(self):
        with patch("config.ENABLE_REAL_ORDERS", True), \
             patch("config.EXECUTION_MODE", "PRODUCTION"), \
             patch("config.PREFLIGHT_PASSED", False):
            self.assertFalse(__import__("config").order_execution_enabled())
        with patch("config.ENABLE_REAL_ORDERS", True), \
             patch("config.EXECUTION_MODE", "PRODUCTION"), \
             patch("config.PREFLIGHT_PASSED", True):
            self.assertTrue(__import__("config").order_execution_enabled())

    def test_order_boundary_rejects_when_preflight_has_not_passed(self):
        client = MagicMock()
        executor = OrderExecutor(client)
        with patch("config.ENABLE_REAL_ORDERS", True), \
             patch("config.EXECUTION_MODE", "PRODUCTION"), \
             patch("config.PREFLIGHT_PASSED", False):
            with self.assertRaisesRegex(RuntimeError, "Real orders are disabled"):
                executor.place_approved_buy({"lot_size": 1, "token": "TOKEN"}, 1)
        client.place_order.assert_not_called()

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

    def test_production_mode_allows_real_orders_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "production.sqlite3"
            with patch("config.EXECUTION_MODE", "PRODUCTION"), \
                 patch("config.ENABLE_REAL_ORDERS", False), \
                 patch("config.LIVE_BROKER_VALIDATION_ENABLED", False), \
                 patch("config.ORDER_ENV", "live"), \
                 patch("config.AUTO_TRADING_ENABLED", True), \
                 patch("config.AUTO_ENTRY_ENABLED", True), \
                 patch("config.DATABASE_PATH", db_path):
                __import__("config").validate_runtime()

    def test_production_mode_rejects_sandbox_environment(self):
        with patch("config.EXECUTION_MODE", "PRODUCTION"), \
             patch("config.ENABLE_REAL_ORDERS", False), \
             patch("config.ORDER_ENV", "sandbox"), \
             patch("config.AUTO_TRADING_ENABLED", True), \
             patch("config.AUTO_ENTRY_ENABLED", True):
            with self.assertRaisesRegex(RuntimeError, "PRODUCTION requires ORDER_ENV=live"):
                __import__("config").validate_runtime()

    def test_read_only_mode_rejects_real_orders(self):
        with patch("config.EXECUTION_MODE", "READ_ONLY"), \
             patch("config.ENABLE_REAL_ORDERS", True), \
             patch("config.ORDER_ENV", "live"), \
             patch("config.ORDER_IP_WHITELIST", "192.0.2.1"):
            with self.assertRaisesRegex(RuntimeError, "REAL_ORDERS_ENABLED=ON requires SANDBOX or PRODUCTION"):
                __import__("config").validate_runtime()

    def test_production_mode_uses_mode_specific_database_without_override(self):
        with patch("config._DATABASE_OVERRIDE", ""), \
             patch("config.EXECUTION_MODE", "PRODUCTION"):
            config = __import__("config")
            self.assertEqual(config._MODE_DATABASES["PRODUCTION"], config.ROOT / "data" / "production.sqlite3")

    def test_legacy_database_override_is_rejected_outside_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_path = Path(directory) / "market_data.sqlite3"
            with patch("config._DATABASE_OVERRIDE", str(legacy_path)), \
                 patch("config.DATABASE_PATH", legacy_path), \
                 patch("config.EXECUTION_MODE", "PRODUCTION"):
                with self.assertRaisesRegex(RuntimeError, "Legacy shared database path"):
                    __import__("config").validate_runtime()

    def test_order_gate_remains_disabled_when_real_orders_are_off(self):
        with patch("config.ENABLE_REAL_ORDERS", False), \
             patch("config.EXECUTION_MODE", "PRODUCTION"), \
             patch("config.PREFLIGHT_PASSED", True):
            self.assertFalse(__import__("config").order_execution_enabled())

    def test_sandbox_ledger_starts_with_virtual_capital_and_persists_completed_trade_count(self):
        from trading.sandbox_execution import SandboxLedger
        path = Path(tempfile.mkdtemp()) / "sandbox_ledger.json"
        ledger = SandboxLedger(path)
        self.assertEqual(ledger.opening_capital, 200000)
        self.assertEqual(ledger.available_capital, 200000)
        self.assertEqual(ledger.completed_trades, 0)
        ledger.record_completed_trade(100, 50, 10)
        ledger.record_completed_trade(95, 45, 8)
        self.assertEqual(ledger.completed_trades, 2)
        self.assertEqual(ledger.realized_pnl, 195)
        reloaded = SandboxLedger(path)
        self.assertEqual(reloaded.completed_trades, 2)
        self.assertEqual(reloaded.realized_pnl, 195)

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
