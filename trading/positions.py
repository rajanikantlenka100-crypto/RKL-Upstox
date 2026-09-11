"""Broker-authoritative position state and reconciliation."""

from dataclasses import dataclass
from enum import StrEnum
import threading

from trading.exit_engine import StrategyExitState


class PositionState(StrEnum):
    PENDING_ENTRY = "PENDING_ENTRY"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    OPEN = "OPEN"
    SL_PENDING = "SL_PENDING"
    SL_ACTIVE = "SL_ACTIVE"
    UNPROTECTED = "UNPROTECTED_POSITION"
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
    sl_reference: float
    state: PositionState = PositionState.PENDING_ENTRY
    order_id: str | None = None
    sl_order_id: str | None = None
    symbol: str = ""
    exchange: str = ""
    signal_id: str = ""
    signal_type: str = "TYPE_1"
    initial_sl: float | None = None
    initial_risk: float | None = None
    cci_exit_state: str = "NORMAL"
    five_r_state: str = "NOT_HIT"
    exit_reason: str | None = None
    strategy_exit: object | None = None
    entry_timestamp: object | None = None
    exit_order_id: str | None = None
    exit_price: float | None = None
    exit_timestamp: object | None = None
    realized_pnl: float | None = None


class PositionManager:
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
        open_tokens = {str(item.get("instrument_token")) for item in broker_positions if int(item.get("quantity", 0) or 0) != 0}
        local_tokens = {position.token for position in self.positions.values()
                if position.state not in {PositionState.CLOSED, PositionState.ERROR}}
        unknown_external = open_tokens - local_tokens
        missing_local = local_tokens - open_tokens
        externally_closed = set()
        for position in self.positions.values():
            if position.token not in open_tokens and position.state in {
                PositionState.OPEN, PositionState.SL_ACTIVE, PositionState.UNPROTECTED}:
                position.state = PositionState.CLOSED
                position.exit_reason = "EXTERNAL_MANUAL_EXIT"
                externally_closed.add(position.trade_id)
        return {"broker_positions": broker_positions, "unknown_external": unknown_external,
            "missing_local": missing_local, "externally_closed": externally_closed}

    def restore(self, rows):
        """Restore persisted trade contexts before broker-authoritative reconciliation."""
        with self.lock:
            for row in rows:
                trade_id = row.get("trade_id")
                if not trade_id or trade_id in self.positions:
                    continue
                payload = row.get("payload") or {}
                option_type = payload.get("option_type", "CE" if row.get("direction") == "CALL" else "PE")
                position = Position(
                    trade_id=trade_id, broker="UPSTOX", underlying=row.get("underlying", ""),
                    expiry=row.get("expiry", ""), strike=float(row.get("strike") or 0),
                    option_type=option_type, token=row.get("instrument_key", ""),
                    quantity=int(row.get("quantity") or 0), entry_price=float(row.get("entry_price") or 0),
                    sl_reference=float(row.get("initial_sl") or 0),
                    state=PositionState(row.get("state", PositionState.UNKNOWN)),
                    order_id=payload.get("order_id"), sl_order_id=payload.get("sl_order_id"),
                    symbol=payload.get("symbol", ""), exchange=payload.get("exchange", ""),
                    signal_id=row.get("signal_id", ""), signal_type=row.get("signal_type", "TYPE_1"),
                    initial_sl=row.get("initial_sl"), initial_risk=row.get("initial_risk"),
                    exit_reason=row.get("exit_reason"),
                )
                if position.initial_risk and position.initial_risk > 0:
                    position.strategy_exit = StrategyExitState(
                        "CALL" if option_type == "CE" else "PUT", position.initial_risk
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
            position.initial_sl = position.initial_sl if position.initial_sl is not None else position.sl_reference
            position.initial_risk = average_price - position.initial_sl
            if position.initial_risk <= 0:
                position.state = PositionState.UNPROTECTED
                self.positions[position.trade_id] = position
                raise ValueError("Protective SL must be below confirmed entry price")
            position.strategy_exit = StrategyExitState(position.option_type == "CE" and "CALL" or "PUT", position.initial_risk)
            position.state = PositionState.OPEN
            self.positions[position.trade_id] = position

    def register_partial_fill(self, position: Position, order_id: str, average_price: float, filled_quantity: int):
        if filled_quantity <= 0 or average_price <= 0:
            raise ValueError("Broker partial fill must contain positive quantity and average price")
        with self.lock:
            position.order_id = order_id
            position.quantity = filled_quantity
            position.entry_price = average_price
            position.initial_sl = position.initial_sl if position.initial_sl is not None else position.sl_reference
            position.initial_risk = average_price - position.initial_sl
            if position.initial_risk <= 0:
                position.state = PositionState.UNPROTECTED
                self.positions[position.trade_id] = position
                raise ValueError("Protective SL must be below confirmed entry price")
            position.strategy_exit = StrategyExitState(position.option_type == "CE" and "CALL" or "PUT", position.initial_risk)
            position.state = PositionState.PARTIALLY_FILLED
            self.positions[position.trade_id] = position

    def mark_sl(self, trade_id: str, sl_order_id: str):
        with self.lock:
            position = self.positions[trade_id]
            position.sl_order_id = sl_order_id
            position.state = PositionState.SL_ACTIVE

    def mark_sl_pending(self, trade_id: str):
        with self.lock:
            self.positions[trade_id].state = PositionState.SL_PENDING

    def mark_unprotected(self, trade_id: str):
        with self.lock:
            self.positions[trade_id].state = PositionState.UNPROTECTED

    def mark_error(self, trade_id: str):
        with self.lock:
            self.positions[trade_id].state = PositionState.ERROR

    def mark_exit_pending(self, trade_id: str):
        with self.lock:
            self.positions[trade_id].state = PositionState.EXIT_PENDING

    def mark_closed(self, trade_id: str):
        with self.lock:
            self.positions[trade_id].state = PositionState.CLOSED

    def mark_unknown(self, trade_id: str):
        with self.lock:
            self.positions[trade_id].state = PositionState.UNKNOWN

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
