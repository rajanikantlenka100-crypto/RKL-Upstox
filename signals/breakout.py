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
        self.low_seen = False
        self.high_seen = False
        self.call_fired = False
        self.put_fired = False
        self.previous_ltp = None
        self.first_break_side = None
        self.first_break_time = None
        self.first_break_price = None
        self.last_break_side = None
        self.last_break_time = None
        self.last_break_price = None
        self.trace_sink = trace_sink

    def reset_sequence(self):
        self.candle_timestamp = None
        self.low_seen = False
        self.high_seen = False
        self.call_fired = False
        self.put_fired = False
        self.previous_ltp = None
        self.first_break_side = None
        self.first_break_time = None
        self.first_break_price = None
        self.last_break_side = None
        self.last_break_time = None
        self.last_break_price = None

    def evaluate(self, previous, running, ltp, tick_timestamp=None):
        if previous is None or running is None:
            self._trace(previous, running, None, ltp, None, None, "DATA_UNAVAILABLE")
            return None
        if self.candle_timestamp != running.timestamp:
            self.candle_timestamp = running.timestamp
            self.low_seen = running.open <= previous.low
            self.high_seen = running.open >= previous.high
            self.call_fired = False
            self.put_fired = False
            self.previous_ltp = running.open
            self.first_break_side = "LOW" if self.low_seen else "HIGH" if self.high_seen else None
            self.first_break_time = tick_timestamp if self.first_break_side else None
            self.first_break_price = running.open if self.first_break_side else None
            self.last_break_side = self.first_break_side
            self.last_break_time = self.first_break_time
            self.last_break_price = self.first_break_price

        previous_ltp = self.previous_ltp
        if previous_ltp is None:
            previous_ltp = ltp
        event_time = tick_timestamp or running.timestamp
        crossed_side = None
        sequence_start_side = self.last_break_side
        sequence_start_time = self.last_break_time
        sequence_start_price = self.last_break_price
        if previous_ltp > previous.low and ltp <= previous.low:
            self.low_seen = True
            self._record_break("LOW", event_time, ltp)
            crossed_side = "LOW"
        if previous_ltp < previous.high and ltp >= previous.high:
            self.high_seen = True
            self._record_break("HIGH", event_time, ltp)
            crossed_side = "HIGH"
        self.previous_ltp = ltp

        direction = None
        if crossed_side == "HIGH" and sequence_start_side == "LOW" and not self.call_fired:
            direction = "CALL"
            self.call_fired = True
        elif crossed_side == "LOW" and sequence_start_side == "HIGH" and not self.put_fired:
            direction = "PUT"
            self.put_fired = True
        reason_code = (
            "CALL_CANDIDATE" if direction == "CALL" else
            "PUT_CANDIDATE" if direction == "PUT" else
            "CALL_DUPLICATE" if crossed_side == "HIGH" and sequence_start_side == "LOW" else
            "PUT_DUPLICATE" if crossed_side == "LOW" and sequence_start_side == "HIGH" else
            "BREAKOUT_LOW_FIRST_WAITING_HIGH" if self.last_break_side == "LOW" else
            "BREAKOUT_HIGH_FIRST_WAITING_LOW" if self.last_break_side == "HIGH" else
            "NO_BREAKOUT"
        )
        self._trace(previous, running, previous_ltp, ltp, crossed_side, direction, reason_code,
                    sequence_start_side=sequence_start_side, sequence_start_time=sequence_start_time,
                    sequence_start_price=sequence_start_price)
        if direction is None:
            return None
        signal = PutCallSignal(
            str(uuid4()), running.timestamp, running.instrument, direction, ltp,
            previous, running, ltp, first_break_side=sequence_start_side,
            first_break_time=sequence_start_time, first_break_price=sequence_start_price,
            second_break_side=crossed_side,
            second_break_time=event_time,
            candle_colour="GREEN" if running.close >= running.open else "RED",
        )
        return signal

    def _trace(self, previous, running, previous_ltp, current_ltp, crossed_side, direction,
               reason_code, sequence_start_side=None, sequence_start_time=None,
               sequence_start_price=None):
        if not self.trace_sink:
            return
        previous_values = self._candle_values(previous)
        running_values = self._candle_values(running)
        record = {
            "stage": "BREAKOUT_EVALUATION",
            "reason_code": reason_code,
            "underlying": (running_values or previous_values or {}).get("instrument"),
            "previous_candle": previous_values,
            "running_candle": running_values,
            "previous_ltp": previous_ltp,
            "current_ltp": current_ltp,
            "low_cross": bool(previous_values and previous_ltp is not None and
                               previous_ltp > previous_values["low"] and current_ltp <= previous_values["low"]),
            "high_cross": bool(previous_values and previous_ltp is not None and
                                previous_ltp < previous_values["high"] and current_ltp >= previous_values["high"]),
            "low_seen": self.low_seen,
            "high_seen": self.high_seen,
            "first_break_side": self.first_break_side,
            "first_break_time": self.first_break_time,
            "first_break_price": self.first_break_price,
            "second_break_side": crossed_side,
            "second_break_time": sequence_start_time if crossed_side is None else (self.last_break_time),
            "second_break_price": sequence_start_price if crossed_side is None else self.last_break_price,
            "sequence_start_side": sequence_start_side,
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
        for name in ("instrument", "timestamp", "open", "high", "low", "close", "volume", "status"):
            values[name] = getattr(candle, name, None)
        return values

    def _record_break(self, side, event_time, price):
        if self.first_break_side is None:
            self.first_break_side = side
            self.first_break_time = event_time
            self.first_break_price = price
        self.last_break_side = side
        self.last_break_time = event_time
        self.last_break_price = price


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
        small_body = abs(previous.close - previous.open) <= 0.25 * body_range
        common = {
            "body_at_most_25_percent_range": small_body,
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
        directions = (direction,) if direction else ("CALL", "PUT")
        for candidate_direction in directions:
            if candidate_direction == "CALL":
                conditions = {
                    "close_above_midpoint": previous.close > (previous.high + previous.low) / 2,
                    "previous_low_below_prev2_low": previous.low < prev2.low,
                    "previous_low_below_running_low": previous.low < running.low,
                    "running_high_breaks_previous_high": running.high > previous.high,
                    "running_low_below_previous_close": running.low < previous.close,
                    "rsi_filter": bool(rsi_pass),
                    "sma_filter": bool(sma_pass),
                }
            elif candidate_direction == "PUT":
                conditions = {
                    "close_below_midpoint": previous.close < (previous.high + previous.low) / 2,
                    "previous_high_above_prev2_high": previous.high > prev2.high,
                    "previous_high_above_running_high": previous.high > running.high,
                    "running_low_breaks_previous_low": running.low < previous.low,
                    "running_high_above_previous_close": running.high > previous.close,
                    "rsi_filter": bool(rsi_pass),
                    "sma_filter": bool(sma_pass),
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
