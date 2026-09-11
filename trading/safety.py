"""Fail-closed checks shared by the production entry boundary."""

from dataclasses import dataclass, field
from enum import StrEnum


class SystemState(StrEnum):
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    TRADING_HALTED = "TRADING_HALTED"
    EMERGENCY = "EMERGENCY"
    SHUTTING_DOWN = "SHUTTING_DOWN"


@dataclass
class SafetyGate:
    state: str = SystemState.DEGRADED
    reasons: set[str] = field(default_factory=set)

    def running(self):
        self.state = SystemState.RUNNING
        self.reasons.clear()

    def halt(self, reason):
        self.state = SystemState.TRADING_HALTED
        self.reasons.add(reason)

    def emergency(self, reason):
        self.state = SystemState.EMERGENCY
        self.reasons.add(reason)

    def shutdown(self):
        self.state = SystemState.SHUTTING_DOWN
        self.reasons.add("shutdown")

    def degrade(self, reason):
        if self.state not in {SystemState.TRADING_HALTED, SystemState.EMERGENCY, SystemState.SHUTTING_DOWN}:
            self.state = SystemState.DEGRADED
        self.reasons.add(reason)

    def ready(self):
        return self.state == SystemState.RUNNING and not self.reasons

    def allow_buy(self, *, feed_healthy, broker_authenticated, history_ready,
                  contract_valid, option_ltp_fresh, risk_valid, signal_valid,
                  unresolved_order=False, unknown_position=False,
                  unprotected_position=False, database_ready=True):
        checks = {
            "system is not RUNNING": self.state == SystemState.RUNNING and not self.reasons,
            "feed stale or disconnected": feed_healthy,
            "broker authentication uncertain": broker_authenticated,
            "historical reconciliation incomplete": history_ready,
            "option contract invalid": contract_valid,
            "option LTP stale": option_ltp_fresh,
            "risk validation failed": risk_valid,
            "signal expired or invalid": signal_valid,
            "unresolved broker order": not unresolved_order,
            "unknown broker position": not unknown_position,
            "unprotected position": not unprotected_position,
            "database unavailable": database_ready,
        }
        failures = {reason for reason, passed in checks.items() if not passed}
        if failures:
            return False, "; ".join(sorted(failures))
        return True, "READY"
