"""Index breakout signal generation without repeated events."""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4


@dataclass(frozen=True)
class PutCallSignal:
    signal_id: str
    timestamp: datetime
    underlying: str
    direction: str
    ltp: float
    previous_candle: object
    running_candle: object
    breakout_price: float
    status: str = "WAITING_APPROVAL"
    first_break_side: str = ""
    first_break_time: datetime | None = None
    first_break_price: float | None = None
    second_break_side: str = ""
    second_break_time: datetime | None = None
    candle_colour: str = ""
    rsi_filter_status: str = "UNAVAILABLE"
    rsi_matching_periods: int = 0
    rsi_evaluated_periods: tuple = ()
    rsi_evaluated_values: tuple = ()
    rsi_evaluated_sma_values: tuple = ()
    rsi_first_matching_timestamp: datetime | None = None
    rsi_reason: str = ""
    type1_conditions: object = None
    rsi14: float | None = None
    rsi14_sma14: float | None = None
    body_ratio: float | None = None
    matched_signal_types: tuple = ()
    signal_lock_status: str = "UNLOCKED"
    sma_filter_status: str = "UNAVAILABLE"
    sma_values: object = None
    sma_reason: str = ""
    signal_type: str = "TYPE_1"
    prev2_candle: object | None = None
    type2_conditions: object = None
    entry_filter: str = "sma_normal"
    stochastic_values: tuple = ()


class BreakoutEngine:
    def __init__(self, trace_sink=None):
        self.candle_timestamp = None
        self.previous_ltp = None
        self.low_breached = False
        self.high_breached = False
        self.signal_fired = False
        self.trace_sink = trace_sink

    def reset_sequence(self):
        self.candle_timestamp = None
        self.previous_ltp = None
        self.low_breached = False
        self.high_breached = False
        self.signal_fired = False

    def evaluate(self, previous, running, ltp, tick_timestamp=None, direction=None):
        if previous is None or running is None:
            self._trace(previous, running, None)
            return None

        new_candle = self.candle_timestamp != running.timestamp

        if new_candle:
            self.candle_timestamp = running.timestamp
            self.previous_ltp = getattr(running, "open", None)
            self.low_breached = (
                self.previous_ltp is not None
                and self.previous_ltp < previous.low
            )
            self.high_breached = (
                self.previous_ltp is not None
                and self.previous_ltp > previous.high
            )
            self.signal_fired = False

        prior_ltp = self.previous_ltp if self.previous_ltp is not None else ltp

        was_low_breached = self.low_breached
        was_high_breached = self.high_breached

        low_cross = prior_ltp >= previous.low and ltp < previous.low
        high_cross = prior_ltp <= previous.high and ltp > previous.high

        candidate_direction = None

        if not self.signal_fired:
            # If the first observed state of a new candle already contains
            # both strict boundary breaches, this observation is the
            # completion event available to the engine. Check colour now.
            initial_complete_breakout = (
                new_candle
                and running.low < previous.low
                and running.high > previous.high
            )

            # Normal live path: the signal is created only when the SECOND
            # boundary is actually crossed. Candle colour is checked at
            # that exact tick.
            if initial_complete_breakout:
                if running.close > running.open:
                    candidate_direction = "CALL"
                elif running.close < running.open:
                    candidate_direction = "PUT"
            elif high_cross and was_low_breached and not was_high_breached:
                candidate_direction = "CALL"
            elif low_cross and was_high_breached and not was_low_breached:
                candidate_direction = "PUT"

            # RSI direction authorization must agree with the breakout.
            if (
                candidate_direction is not None
                and direction in {"CALL", "PUT"}
                and direction != candidate_direction
            ):
                candidate_direction = None

            if candidate_direction == "CALL" and running.close <= running.open:
                candidate_direction = None

            if candidate_direction == "PUT" and running.close >= running.open:
                candidate_direction = None

            if candidate_direction is not None:
                self.signal_fired = True

        self.low_breached = self.low_breached or low_cross
        self.high_breached = self.high_breached or high_cross
        self.previous_ltp = ltp

        self._trace(previous, running, candidate_direction)

        if candidate_direction is None:
            return None

        return PutCallSignal(
            str(uuid4()),
            running.timestamp,
            running.instrument,
            candidate_direction,
            ltp,
            previous,
            running,
            ltp,
            candle_colour="GREEN" if running.close >= running.open else "RED",
            type1_conditions={
                "running_low_below_previous_low": running.low < previous.low,
                "running_high_above_previous_high": running.high > previous.high,
                "running_green_for_call": running.close > running.open,
                "running_red_for_put": running.close < running.open,
            },
        )

    def _trace(self, previous, running, direction):
        if not self.trace_sink:
            return

        previous_values = self._candle_values(previous)
        running_values = self._candle_values(running)

        record = {
            "stage": "BREAKOUT_EVALUATION",
            "reason_code": "TYPE_1_CANDIDATE" if direction else "NO_BREAKOUT",
            "underlying": (running_values or previous_values or {}).get("instrument"),
            "previous_candle": previous_values,
            "running_candle": running_values,
            "candidate_direction": direction,
        }

        try:
            self.trace_sink(record)
        except Exception:
            pass

    @staticmethod
    def _candle_values(candle):
        if candle is None:
            return None

        values = {}
        for name in (
            "instrument",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "status",
        ):
            values[name] = getattr(candle, name, None)

        return values


class Type2Engine:
    """Intracandle Prev2/Prev/Running signal engine sharing PutCallSignal."""

    def __init__(self, trace_sink=None):
        self.trace_sink = trace_sink
        self.candle_timestamp = None
        self.fired = set()

    def reset(self):
        self.candle_timestamp = None
        self.fired.clear()

    def evaluate(self, prev2, previous, running, ltp, direction=None, rsi_pass=False):
        if prev2 is None or previous is None or running is None:
            return None
        if self.candle_timestamp != running.timestamp:
            self.candle_timestamp = running.timestamp
            self.fired.clear()
        body_range = previous.high - previous.low
        body_ratio = abs(previous.close - previous.open) / body_range if body_range > 0 else None
        small_body = body_ratio is not None and body_ratio < 0.20
        common = {
            "body_below_20_percent_range": small_body,
        }
        directions = (direction,) if direction else ("CALL", "PUT")
        for candidate_direction in directions:
            if candidate_direction == "CALL":
                conditions = {
                    **common,
                    "close_above_midpoint": previous.close > (previous.high + previous.low) / 2,
                    "previous_low_below_prev2_low": previous.low < prev2.low,
                    "previous_low_below_running_low": previous.low < running.low,
                    "running_high_breaks_previous_high": running.high > previous.high,
                    "rsi_filter": bool(rsi_pass),
                }
            elif candidate_direction == "PUT":
                conditions = {
                    **common,
                    "close_below_midpoint": previous.close < (previous.high + previous.low) / 2,
                    "previous_high_above_prev2_high": previous.high > prev2.high,
                    "previous_high_above_running_high": previous.high > running.high,
                    "running_low_breaks_previous_low": running.low < previous.low,
                    "rsi_filter": bool(rsi_pass),
                }
            else:
                raise ValueError(f"Unsupported Type 2 direction: {candidate_direction}")
            self._trace(prev2, previous, running, candidate_direction, conditions)
            if candidate_direction in self.fired or not all(conditions.values()):
                continue
            self.fired.add(candidate_direction)
            return PutCallSignal(
                signal_id=str(uuid4()), timestamp=running.timestamp,
                underlying=running.instrument, direction=candidate_direction,
                ltp=ltp, previous_candle=previous, running_candle=running,
                breakout_price=running.high if candidate_direction == "CALL" else running.low,
                signal_type="TYPE_2", prev2_candle=prev2,
                type2_conditions=conditions,
                body_ratio=body_ratio,
                candle_colour="GREEN" if running.close >= running.open else "RED",
            )
        return None

    def _trace(self, prev2, previous, running, direction, conditions):
        if not self.trace_sink:
            return
        try:
            self.trace_sink({
                "stage": "TYPE_2_EVALUATION",
                "signal_type": "TYPE_2",
                "direction": direction,
                "prev2_timestamp": prev2.timestamp,
                "previous_timestamp": previous.timestamp,
                "running_timestamp": running.timestamp,
                "conditions": conditions,
            })
        except Exception:
            pass


class Type3Engine:
    """Mirrored Type 2 engine without the small-body restriction and with close-based trigger checks."""

    def __init__(self, trace_sink=None):
        self.trace_sink = trace_sink
        self.candle_timestamp = None
        self.fired = set()

    def reset(self):
        self.candle_timestamp = None
        self.fired.clear()

    def evaluate(self, prev2, previous, running, ltp, direction=None, rsi_pass=False, sma_pass=False):
        if prev2 is None or previous is None or running is None:
            return None
        if self.candle_timestamp != running.timestamp:
            self.candle_timestamp = running.timestamp
            self.fired.clear()
        body_range = previous.high - previous.low
        body_ratio = abs(previous.close - previous.open) / body_range if body_range > 0 else None
        large_body = body_ratio is not None and body_ratio > 0.40
        directions = (direction,) if direction else ("CALL", "PUT")
        for candidate_direction in directions:
            if candidate_direction == "CALL":
                conditions = {
                    "body_above_40_percent_range": large_body,
                    "close_above_midpoint": previous.close > (previous.high + previous.low) / 2,
                    "previous_low_below_prev2_low": previous.low < prev2.low,
                    "previous_low_below_running_low": previous.low < running.low,
                    "running_high_breaks_previous_high": running.high > previous.high,
                    "running_low_below_previous_close": running.low < previous.close,
                    "rsi_filter": bool(rsi_pass),
                }
            elif candidate_direction == "PUT":
                conditions = {
                    "body_above_40_percent_range": large_body,
                    "close_below_midpoint": previous.close < (previous.high + previous.low) / 2,
                    "previous_high_above_prev2_high": previous.high > prev2.high,
                    "previous_high_above_running_high": previous.high > running.high,
                    "running_low_breaks_previous_low": running.low < previous.low,
                    "running_high_above_previous_close": running.high > previous.close,
                    "rsi_filter": bool(rsi_pass),
                }
            else:
                raise ValueError(f"Unsupported Type 3 direction: {candidate_direction}")
            self._trace(prev2, previous, running, candidate_direction, conditions)
            if candidate_direction in self.fired or not all(conditions.values()):
                continue
            self.fired.add(candidate_direction)
            return PutCallSignal(
                signal_id=str(uuid4()), timestamp=running.timestamp,
                underlying=running.instrument, direction=candidate_direction,
                ltp=ltp, previous_candle=previous, running_candle=running,
                breakout_price=running.high if candidate_direction == "CALL" else running.low,
                signal_type="TYPE_3", prev2_candle=prev2,
                type2_conditions=conditions,
                body_ratio=body_ratio,
                candle_colour="GREEN" if running.close >= running.open else "RED",
            )
        return None

    def _trace(self, prev2, previous, running, direction, conditions):
        if not self.trace_sink:
            return
        try:
            self.trace_sink({
                "stage": "TYPE_3_EVALUATION",
                "signal_type": "TYPE_3",
                "direction": direction,
                "prev2_timestamp": prev2.timestamp,
                "previous_timestamp": previous.timestamp,
                "running_timestamp": running.timestamp,
                "conditions": conditions,
            })
        except Exception:
            pass
