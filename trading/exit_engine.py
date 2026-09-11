"""Per-position strategy exits; protective stops remain outside this engine."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class StrategyExitState:
    direction: str
    initial_risk: float
    cci_state: str = "NORMAL"
    exit_state: str = "OPEN"
    arm_timestamp: datetime | None = None
    arm_candle_timestamp: datetime | None = None
    arm_cci: float | None = None
    confirmation_candle_timestamp: datetime | None = None
    exit_reason: str | None = None

    def __post_init__(self):
        if self.direction not in {"CALL", "PUT"}:
            raise ValueError("Strategy exit direction must be CALL or PUT")
        if self.initial_risk <= 0:
            raise ValueError("Initial risk must be positive")

    @property
    def five_r(self):
        return self.initial_risk * 5

    def on_running_candle(self, candle):
        """Return FIVE_R_EXIT when this position's index range crosses its own threshold."""
        if self.exit_state != "OPEN":
            return None
        if candle.high - candle.low > self.five_r:
            self.exit_state = "EXIT_PENDING"
            self.exit_reason = "FIVE_R_EXIT"
            return self.exit_reason
        return None

    def on_closed_candle(self, candle, previous_candle, cci_value, timestamp=None):
        """Arm on CCI and confirm only on a later candle's directional break."""
        if self.exit_state != "OPEN":
            return None
        event_timestamp = timestamp or candle.timestamp
        threshold_hit = (
            self.direction == "CALL" and cci_value is not None and cci_value > 100
        ) or (
            self.direction == "PUT" and cci_value is not None and cci_value < -100
        )
        if self.arm_timestamp is None:
            if threshold_hit:
                self.cci_state = "ARMED"
                self.arm_timestamp = event_timestamp
                self.arm_candle_timestamp = candle.timestamp
                self.arm_cci = cci_value
            return None
        if candle.timestamp <= self.arm_candle_timestamp:
            return None
        confirmed = (
            self.direction == "CALL" and previous_candle is not None and candle.low < previous_candle.low
        ) or (
            self.direction == "PUT" and previous_candle is not None and candle.high > previous_candle.high
        )
        if confirmed:
            self.cci_state = "CONFIRMED"
            self.exit_state = "EXIT_PENDING"
            self.exit_reason = "CCI_CONFIRMATION"
            self.confirmation_candle_timestamp = candle.timestamp
            return self.exit_reason
        return None
