"""Fail-closed production readiness checks for the trading service."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    checked_at: str
    checks: dict[str, bool] = field(default_factory=dict)
    failures: tuple[str, ...] = ()

    @property
    def summary(self):
        return "PASS" if self.passed else "FAILED: " + "; ".join(self.failures)


def run_local_preflight(*, store, instruments, display, position_manager=None,
                        order_manager=None, public_ip=None, require_live_feeds=False):
    """Check production prerequisites that are observable without placing orders."""
    checks = {}
    failures = []
    checks["mode_supported"] = config.EXECUTION_MODE in {"READ_ONLY", "BACKTEST", "SANDBOX", "PRODUCTION"}
    checks["real_order_policy"] = (
        config.ENABLE_REAL_ORDERS
        if config.EXECUTION_MODE in {"SANDBOX", "PRODUCTION"}
        else not config.ENABLE_REAL_ORDERS
    )
    checks["order_environment"] = (
        config.ORDER_ENV == ("sandbox" if config.EXECUTION_MODE == "SANDBOX" else "live")
        if config.EXECUTION_MODE in {"SANDBOX", "PRODUCTION"}
        else True
    )
    checks["database_healthy"] = bool(store and store.is_healthy())
    checks["database_path_present"] = bool(config.DATABASE_PATH.parent.exists()) or checks["database_healthy"]
    checks["instrument_master_available"] = config.INSTRUMENT_MASTER_PATH.exists()
    checks["timezone_ist"] = ZoneInfo("Asia/Kolkata") is not None
    checks["all_active_indexes_resolved"] = set(instruments) == set(config.INSTRUMENTS)
    checks["history_synced"] = all(
        display.rest_status.get(name) == "SYNCED" for name in instruments
    )
    checks["index_feeds_live"] = (
        all(display.health.get(name) == "LIVE" for name in instruments)
        if require_live_feeds else True
    )
    checks["option_feed_live"] = (
        bool(display.option_quotes) if require_live_feeds else True
    )
    checks["broker_authenticated"] = display.components.get("AUTH") == "READY"
    checks["position_reconciled"] = display.components.get("BROKER") == "READY"
    checks["order_reconciled"] = not bool(store.unfinished_order_requests())
    checks["no_unknown_positions"] = not any(
        str(position.state) in {"UNKNOWN", "UNPROTECTED_POSITION"}
        for position in (position_manager.positions.values() if position_manager else ())
    )
    checks["static_order_ip"] = (
        bool(public_ip and config.ORDER_IP_WHITELIST and public_ip == config.ORDER_IP_WHITELIST)
        if config.EXECUTION_MODE in {"SANDBOX", "PRODUCTION"} and config.ORDER_ENV == "live"
        else True
    )

    if order_manager is not None:
        checks["order_client_available"] = bool(order_manager.client) or config.EXECUTION_MODE in {"READ_ONLY", "BACKTEST"}
    else:
        checks["order_client_available"] = config.EXECUTION_MODE in {"READ_ONLY", "BACKTEST"}

    if config.ENABLE_REAL_ORDERS:
        checks["option_engine_configured"] = bool(config.SIGNAL_TYPE_1_ENABLED or config.SIGNAL_TYPE_2_ENABLED)
    else:
        checks["option_engine_configured"] = True

    failures.extend(name for name, passed in checks.items() if not passed)
    return PreflightResult(
        passed=not failures,
        checked_at=datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
        checks=checks,
        failures=tuple(failures),
    )
