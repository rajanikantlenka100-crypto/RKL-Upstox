"""Per-position index-only strategy exits; broker market SELL follows a trigger."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class StrategyExitState:
    direction: str
    standard_candle: object | None = None
    cci_state: str = "NORMAL"
    exit_state: str = "OPEN"
    arm_timestamp: datetime | None = None
    arm_candle_timestamp: datetime | None = None
    arm_cci: float | None = None
    confirmation_candle_timestamp: datetime | None = None
    exit_reason: str | None = None
    reference_candle: object | None = None
    stochastic_state: str = "NORMAL"
    stochastic_extreme: float | None = None
    stochastic_extreme_timestamp: datetime | None = None
    previous_stochastic: float | None = None

    def __post_init__(self):
        if self.direction not in {"CALL", "PUT"}:
            raise ValueError("Strategy exit direction must be CALL or PUT")
    @staticmethod
    def _is_qualifying_reference(candle, direction):
        if candle is None:
            return False
        if direction == "CALL" and candle.close <= candle.open:
            return False
        if direction == "PUT" and candle.close >= candle.open:
            return False
        range_size = candle.high - candle.low
        if range_size <= 0:
            return False
        body = abs(candle.close - candle.open)
        if body < 0.20 * range_size:
            return False
        return True

    def _set_exit(self, reason):
        self.exit_state = "EXIT_PENDING"
        self.exit_reason = reason
        return reason

    def on_running_candle(self, candle, previous_candle=None, cci_value=None, closed_candles=()):
        """Evaluate all confirmed index exit rules on the running candle."""
        if self.exit_state != "OPEN":
            return None

        if self.standard_candle is not None:
            standard_range = self.standard_candle.high - self.standard_candle.low
            running_is_directional = (
                self.direction == "CALL" and candle.close > candle.open
            ) or (
                self.direction == "PUT" and candle.close < candle.open
            )
            if standard_range > 0 and running_is_directional and candle.high - candle.low > 3 * standard_range:
                return self._set_exit("CANDLE_SIZE_EXIT")

        threshold_hit = (
            self.direction == "CALL" and cci_value is not None and cci_value > 100
        ) or (
            self.direction == "PUT" and cci_value is not None and cci_value < -100
        )
        if self.arm_timestamp is None and threshold_hit:
            self.cci_state = "ARMED"
            self.arm_timestamp = candle.timestamp
            self.arm_candle_timestamp = candle.timestamp
            self.arm_cci = cci_value

        if self.arm_timestamp is not None:
            for closed_candle in closed_candles:
                if (closed_candle.timestamp > self.arm_candle_timestamp
                        and self._is_qualifying_reference(closed_candle, self.direction)
                        and (self.reference_candle is None
                             or closed_candle.timestamp > self.reference_candle.timestamp)):
                    self.reference_candle = closed_candle

            if self.reference_candle is not None:
                reference_break = (
                    self.direction == "CALL" and candle.low < self.reference_candle.low
                ) or (
                    self.direction == "PUT" and candle.high > self.reference_candle.high
                )
                if reference_break:
                    self.cci_state = "CONFIRMED"
                    self.confirmation_candle_timestamp = candle.timestamp
                    return self._set_exit("CCI_CONFIRMATION")

        if previous_candle is not None:
            directional_break = (
                self.direction == "CALL" and candle.low < previous_candle.low
            ) or (
                self.direction == "PUT" and candle.high > previous_candle.high
            )
            if directional_break:
                return self._set_exit("PREVIOUS_INDEX_CANDLE_BREAK")
        return None

    def on_closed_candle(self, candle, previous_candle, cci_value, timestamp=None):
        """Compatibility wrapper for a completed index candle and audit/replay callers."""
        event_timestamp = timestamp or candle.timestamp
        return self.on_closed_candle_with_stochastic(
            candle, previous_candle, cci_value, None, None, event_timestamp,
        )

    def on_closed_candle_with_stochastic(
        self, candle, previous_candle, cci_value, stochastic_value,
        previous_stochastic=None, timestamp=None,
    ):
        """Evaluate closed-candle exits, including per-position stochastic reversal."""
        if self.exit_state != "OPEN":
            return None
        reason = self.on_running_candle(
            candle,
            previous_candle=previous_candle,
            cci_value=cci_value,
            closed_candles=() if self.reference_candle is not None else (candle,),
        )
        if reason:
            return reason
        if stochastic_value is not None:
            prior = previous_stochastic if previous_stochastic is not None else self.previous_stochastic
            threshold_hit = (
                self.direction == "CALL" and stochastic_value > 90
            ) or (
                self.direction == "PUT" and stochastic_value < 10
            )
            if self.stochastic_state == "NORMAL" and threshold_hit:
                self.stochastic_state = "ARMED"
                self.stochastic_extreme = stochastic_value
                self.stochastic_extreme_timestamp = candle.timestamp
            elif self.stochastic_state == "ARMED":
                if self.direction == "CALL":
                    if stochastic_value > (self.stochastic_extreme or stochastic_value):
                        self.stochastic_extreme = stochastic_value
                        self.stochastic_extreme_timestamp = candle.timestamp
                    elif prior is not None and stochastic_value < prior:
                        self.previous_stochastic = stochastic_value
                        return self._set_exit("STOCHASTIC_REVERSAL_EXIT")
                else:
                    if stochastic_value < (self.stochastic_extreme or stochastic_value):
                        self.stochastic_extreme = stochastic_value
                        self.stochastic_extreme_timestamp = candle.timestamp
                    elif prior is not None and stochastic_value > prior:
                        self.previous_stochastic = stochastic_value
                        return self._set_exit("STOCHASTIC_REVERSAL_EXIT")
            self.previous_stochastic = stochastic_value
        return None
