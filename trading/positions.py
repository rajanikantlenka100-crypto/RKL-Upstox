"""Broker-authoritative position state and reconciliation."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import threading

from market_data.models import Candle
from trading.exit_engine import StrategyExitState


class PositionState(StrEnum):
    PENDING_ENTRY = "PENDING_ENTRY"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    OPEN = "OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class OrderState(StrEnum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


def serialize_candle(candle):
    if candle is None:
        return None
    return {
        "instrument": candle.instrument,
        "exchange": candle.exchange,
        "token": candle.token,
        "timestamp": candle.timestamp.isoformat(),
        "timeframe": candle.timeframe,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
        "source": candle.source,
        "status": candle.status,
    }


def deserialize_candle(value):
    if value is None:
        return None
    if isinstance(value, Candle):
        return value
    if not isinstance(value, dict):
        return None
    timestamp = value.get("timestamp")
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)
    required = ("instrument", "exchange", "token", "timeframe", "open", "high", "low", "close", "volume", "source")
    if not isinstance(timestamp, datetime) or any(key not in value for key in required):
        return None
    return Candle(
        instrument=value["instrument"], exchange=value["exchange"], token=value["token"],
        timestamp=timestamp, timeframe=value["timeframe"], open=value["open"],
        high=value["high"], low=value["low"], close=value["close"], volume=value["volume"],
        source=value["source"], status=value.get("status", "FINAL"),
    )


def _deserialize_timestamp(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value if isinstance(value, datetime) else None


def serialize_strategy_exit_state(state):
    if state is None:
        return None
    return {
        "direction": state.direction,
        "standard_candle": serialize_candle(state.standard_candle),
        "cci_state": state.cci_state,
        "exit_state": state.exit_state,
        "arm_timestamp": state.arm_timestamp.isoformat() if state.arm_timestamp else None,
        "arm_candle_timestamp": state.arm_candle_timestamp.isoformat() if state.arm_candle_timestamp else None,
        "arm_cci": state.arm_cci,
        "confirmation_candle_timestamp": state.confirmation_candle_timestamp.isoformat()
        if state.confirmation_candle_timestamp else None,
        "exit_reason": state.exit_reason,
        "reference_candle": serialize_candle(state.reference_candle),
        "stochastic_state": state.stochastic_state,
        "stochastic_extreme": state.stochastic_extreme,
        "stochastic_extreme_timestamp": state.stochastic_extreme_timestamp.isoformat()
        if state.stochastic_extreme_timestamp else None,
        "previous_stochastic": state.previous_stochastic,
    }


def deserialize_strategy_exit_state(value, *, fallback_direction=None, fallback_candle=None):
    if not isinstance(value, dict):
        if fallback_direction not in {"CALL", "PUT"}:
            return None
        return StrategyExitState(fallback_direction, standard_candle=fallback_candle)
    direction = value.get("direction", fallback_direction)
    if direction not in {"CALL", "PUT"}:
        return None
    return StrategyExitState(
        direction,
        standard_candle=deserialize_candle(value.get("standard_candle")) or fallback_candle,
        cci_state=value.get("cci_state", "NORMAL"),
        exit_state=value.get("exit_state", "OPEN"),
        arm_timestamp=_deserialize_timestamp(value.get("arm_timestamp")),
        arm_candle_timestamp=_deserialize_timestamp(value.get("arm_candle_timestamp")),
        arm_cci=value.get("arm_cci"),
        confirmation_candle_timestamp=_deserialize_timestamp(value.get("confirmation_candle_timestamp")),
        exit_reason=value.get("exit_reason"),
        reference_candle=deserialize_candle(value.get("reference_candle")),
        stochastic_state=value.get("stochastic_state", "NORMAL"),
        stochastic_extreme=value.get("stochastic_extreme"),
        stochastic_extreme_timestamp=_deserialize_timestamp(value.get("stochastic_extreme_timestamp")),
        previous_stochastic=value.get("previous_stochastic"),
    )


@dataclass
class Position:
    trade_id: str
    broker: str
    underlying: str
    expiry: str
    strike: float
    option_type: str
    token: str
    quantity: int
    entry_price: float
    standard_candle: object | None = None
    state: PositionState = PositionState.PENDING_ENTRY
    order_id: str | None = None
    symbol: str = ""
    exchange: str = ""
    signal_id: str = ""
    signal_type: str = "TYPE_1"
    entry_filter: str = "sma_normal"
    entry_stochastic_values: tuple = ()
    cci_exit_state: str = "NORMAL"
    exit_reason: str | None = None
    strategy_exit: object | None = None
    entry_timestamp: object | None = None
    exit_order_id: str | None = None
    exit_price: float | None = None
    exit_timestamp: object | None = None
    realized_pnl: float | None = None


class PositionManager:
    _ALLOWED_TRANSITIONS = {
        PositionState.PENDING_ENTRY: {PositionState.PARTIALLY_FILLED, PositionState.OPEN, PositionState.ERROR, PositionState.UNKNOWN},
        PositionState.PARTIALLY_FILLED: {PositionState.OPEN, PositionState.UNKNOWN, PositionState.ERROR},
        PositionState.OPEN: {PositionState.EXIT_PENDING, PositionState.UNKNOWN, PositionState.ERROR},
        PositionState.EXIT_PENDING: {PositionState.CLOSED, PositionState.UNKNOWN, PositionState.ERROR},
        PositionState.CLOSED: set(),
        PositionState.UNKNOWN: set(),
        PositionState.ERROR: set(),
    }

    def __init__(self, broker_client):
        self.broker = broker_client
        self.positions: dict[str, Position] = {}
        self.lock = threading.RLock()

    def reconcile(self):
        with self.lock:
            response = self.broker.position()
        if not response or not response.get("status"):
            raise RuntimeError(response.get("message", "Position reconciliation failed") if response else "No position response")
        broker_positions = response.get("data") or []
        local_active = [position for position in self.positions.values()
                        if position.state not in {PositionState.CLOSED, PositionState.ERROR}]
        local_quantities = {}
        local_by_token = {}
        for position in local_active:
            local_quantities[position.token] = local_quantities.get(position.token, 0) + position.quantity
            local_by_token.setdefault(position.token, []).append(position)
        broker_quantities = {}
        broker_by_token = {}
        for item in broker_positions:
            token = str(item.get("instrument_token"))
            quantity = int(item.get("quantity", 0) or 0)
            if quantity:
                broker_quantities[token] = broker_quantities.get(token, 0) + quantity
                broker_by_token.setdefault(token, []).append(item)
        open_tokens = set(broker_quantities)
        local_tokens = set(local_quantities)
        unknown_external = open_tokens - local_tokens
        missing_local = local_tokens - open_tokens
        quantity_mismatches = {
            token: {"local": local_quantities.get(token, 0), "broker": broker_quantities.get(token, 0)}
            for token in local_tokens & open_tokens
            if local_quantities[token] != broker_quantities[token]
        }
        allocation_unresolved = {}
        for token, positions in local_by_token.items():
            if len(positions) <= 1 or token not in broker_by_token:
                continue
            mapped_ids = {
                str(item.get("trade_id") or item.get("order_id"))
                for item in broker_by_token[token]
                if item.get("trade_id") or item.get("order_id")
            }
            known_ids = {position.trade_id for position in positions} | {
                position.order_id for position in positions if position.order_id
            }
            if not mapped_ids or not mapped_ids.issubset(known_ids):
                allocation_unresolved[token] = [position.trade_id for position in positions]
        externally_closed = set()
        for position in self.positions.values():
            if position.token not in open_tokens and position.state == PositionState.OPEN:
                self._transition(position, PositionState.UNKNOWN)
                position.exit_reason = "EXTERNAL_POSITION_UNRESOLVED"
                externally_closed.add(position.trade_id)
        return {"broker_positions": broker_positions, "unknown_external": unknown_external,
            "missing_local": missing_local, "externally_closed": externally_closed,
            "quantity_mismatches": quantity_mismatches,
            "allocation_unresolved": allocation_unresolved}

    def restore(self, rows):
        """Restore persisted trade contexts before broker-authoritative reconciliation."""
        with self.lock:
            for row in rows:
                trade_id = row.get("trade_id")
                if not trade_id or trade_id in self.positions:
                    continue
                payload = row.get("payload") or {}
                option_type = payload.get("option_type", "CE" if row.get("direction") == "CALL" else "PE")
                legacy_state = row.get("state", PositionState.UNKNOWN)
                if legacy_state in {"SL_ACTIVE", "SL_PENDING", "UNPROTECTED_POSITION"}:
                    legacy_state = PositionState.OPEN
                standard_candle = deserialize_candle(payload.get("standard_candle"))
                option_type = payload.get("option_type", option_type)
                direction = payload.get("direction") or row.get("direction") or ("CALL" if option_type == "CE" else "PUT")
                position = Position(
                    trade_id=trade_id, broker=payload.get("broker", "UPSTOX"), underlying=row.get("underlying", "") or payload.get("underlying", ""),
                    expiry=row.get("expiry", "") or payload.get("expiry", ""), strike=float(row.get("strike") or payload.get("strike") or 0),
                    option_type=option_type, token=row.get("instrument_key", "") or payload.get("token", ""),
                    quantity=int(row.get("quantity") or 0), entry_price=float(row.get("entry_price") or 0),
                    standard_candle=standard_candle, state=PositionState(legacy_state),
                    order_id=payload.get("order_id") or row.get("order_id"),
                    symbol=payload.get("symbol", ""), exchange=payload.get("exchange", ""),
                    signal_id=row.get("signal_id", ""), signal_type=row.get("signal_type", "TYPE_1"),
                    entry_filter=payload.get("entry_filter", "sma_normal"),
                    entry_stochastic_values=tuple(payload.get("entry_stochastic_values", ())),
                    cci_exit_state=payload.get("cci_exit_state", "NORMAL"),
                    exit_reason=row.get("exit_reason") or payload.get("exit_reason"),
                    exit_order_id=payload.get("exit_order_id"), exit_price=payload.get("exit_price"),
                    exit_timestamp=_deserialize_timestamp(payload.get("exit_timestamp")),
                    realized_pnl=payload.get("realized_pnl"),
                )
                position.strategy_exit = deserialize_strategy_exit_state(
                    payload.get("strategy_exit"), fallback_direction=direction, fallback_candle=standard_candle,
                )
                self.positions[trade_id] = position

    def register_pending(self, position: Position):
        with self.lock:
            if position.trade_id in self.positions:
                raise ValueError(f"Duplicate local trade ID: {position.trade_id}")
            self.positions[position.trade_id] = position

    def register_fill(self, position: Position, order_id: str, average_price: float, filled_quantity: int):
        if filled_quantity <= 0 or average_price <= 0:
            raise ValueError("Broker fill must contain positive quantity and average price")
        with self.lock:
            position.order_id = order_id
            position.quantity = filled_quantity
            position.entry_price = average_price
            position.strategy_exit = StrategyExitState(
                position.option_type == "CE" and "CALL" or "PUT",
                standard_candle=position.standard_candle,
            )
            position.state = PositionState.OPEN
            self.positions[position.trade_id] = position

    def register_partial_fill(self, position: Position, order_id: str, average_price: float, filled_quantity: int):
        if filled_quantity <= 0 or average_price <= 0:
            raise ValueError("Broker partial fill must contain positive quantity and average price")
        with self.lock:
            position.order_id = order_id
            position.quantity = filled_quantity
            position.entry_price = average_price
            position.strategy_exit = StrategyExitState(
                position.option_type == "CE" and "CALL" or "PUT",
                standard_candle=position.standard_candle,
            )
            position.state = PositionState.PARTIALLY_FILLED
            self.positions[position.trade_id] = position

    def mark_error(self, trade_id: str):
        with self.lock:
            self._transition(self.positions[trade_id], PositionState.ERROR)

    def mark_exit_pending(self, trade_id: str):
        with self.lock:
            self._transition(self.positions[trade_id], PositionState.EXIT_PENDING)

    def mark_closed(self, trade_id: str):
        with self.lock:
            self._transition(self.positions[trade_id], PositionState.CLOSED)

    def mark_unknown(self, trade_id: str):
        with self.lock:
            self._transition(self.positions[trade_id], PositionState.UNKNOWN)

    @classmethod
    def _transition(cls, position, target):
        if target not in cls._ALLOWED_TRANSITIONS[position.state]:
            raise ValueError(f"Illegal position transition: {position.state} -> {target}")
        position.state = target

    def reserve_exit(self, trade_id, reason):
        """Atomically reserve one exit worker for an OPEN position."""
        with self.lock:
            position = self.positions.get(trade_id)
            if not position or position.state != PositionState.OPEN:
                return None
            position.exit_reason = reason
            self._transition(position, PositionState.EXIT_PENDING)
            return position

    def active_tokens(self):
        """Return locally active tokens and broker-authoritative non-zero tokens."""
        with self.lock:
            local = {
                position.token for position in self.positions.values()
                if position.state not in {PositionState.CLOSED, PositionState.ERROR}
            }
        response = self.broker.position()
        if not response or not response.get("status"):
            raise RuntimeError("Unable to determine broker-authoritative active positions")
        broker = {
            str(item.get("instrument_token")) for item in response.get("data") or []
            if int(item.get("quantity", 0) or 0) != 0
        }
        return local | broker
