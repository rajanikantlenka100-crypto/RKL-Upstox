"""Deterministic sandbox execution adapter for the shared strategy engine."""

import json
from datetime import datetime
import threading
import uuid
from pathlib import Path

import config
from trading.positions import OrderState


class SandboxExecutionError(RuntimeError):
    """A sandbox execution request that cannot be resolved safely."""


class SandboxLedger:
    """Persistent virtual-capital ledger for sandbox trading."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else Path(config.ROOT) / "data" / "sandbox_ledger.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.opening_capital = float(config.SANDBOX_INITIAL_CAPITAL)
        self.available_capital = float(self.opening_capital)
        self.deployed_capital = 0.0
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.charges = 0.0
        self.equity = float(self.opening_capital)
        self.peak_equity = float(self.opening_capital)
        self.drawdown = 0.0
        self.winning_trades = 0
        self.losing_trades = 0
        self.completed_trades = 0
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        if not self.path.exists():
            self._save()
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._save()
            return
        for key, default in {
            "opening_capital": self.opening_capital,
            "available_capital": self.opening_capital,
            "deployed_capital": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "charges": 0.0,
            "equity": self.opening_capital,
            "peak_equity": self.opening_capital,
            "drawdown": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
            "completed_trades": 0,
        }.items():
            setattr(self, key, float(payload.get(key, default)) if key in {"opening_capital", "available_capital", "deployed_capital", "realized_pnl", "unrealized_pnl", "charges", "equity", "peak_equity", "drawdown"} else int(payload.get(key, default)))
        self.equity = self.available_capital + self.deployed_capital + self.unrealized_pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        self.drawdown = max(0.0, self.peak_equity - self.equity)

    def _save(self):
        payload = {
            "opening_capital": self.opening_capital,
            "available_capital": self.available_capital,
            "deployed_capital": self.deployed_capital,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "charges": self.charges,
            "equity": self.equity,
            "peak_equity": self.peak_equity,
            "drawdown": self.drawdown,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "completed_trades": self.completed_trades,
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def record_completed_trade(self, pnl, quantity=None, price=None):
        with self._lock:
            self.completed_trades += 1
            self.realized_pnl += float(pnl)
            self.available_capital = self.opening_capital - self.deployed_capital + self.realized_pnl - self.charges
            self.equity = self.available_capital + self.deployed_capital + self.unrealized_pnl
            self.peak_equity = max(self.peak_equity, self.equity)
            self.drawdown = max(0.0, self.peak_equity - self.equity)
            if float(pnl) > 0:
                self.winning_trades += 1
            elif float(pnl) < 0:
                self.losing_trades += 1
            self._save()

    def snapshot(self):
        with self._lock:
            return {
                "opening_capital": self.opening_capital,
                "available_capital": self.available_capital,
                "deployed_capital": self.deployed_capital,
                "realized_pnl": self.realized_pnl,
                "unrealized_pnl": self.unrealized_pnl,
                "charges": self.charges,
                "equity": self.equity,
                "peak_equity": self.peak_equity,
                "drawdown": self.drawdown,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "completed_trades": self.completed_trades,
            }


class SandboxOrderExecutor:
    """Simulate BUY/SELL fills without ever calling the Upstox order client."""

    def __init__(self, quote_provider):
        self.quote_provider = quote_provider
        self.execution_enabled = True
        self.client = self
        self.order_lock = threading.RLock()
        self.orders = {}
        self.positions = {}
        self.ledger = SandboxLedger()

    def _price(self, token):
        quote = self.quote_provider(token)
        if not quote or quote.ltp is None or quote.ltp <= 0:
            raise SandboxExecutionError(
                f"EXECUTION_BLOCKED: no valid sandbox quote for {token}"
            )
        return float(quote.ltp)

    def _fill_price(self, token, transaction_type):
        model = config.SANDBOX_FILL_MODEL
        if model != "MARKET_LTP":
            raise SandboxExecutionError(f"Unsupported sandbox fill model: {model}")
        price = self._price(token)
        slippage = config.SANDBOX_SLIPPAGE if transaction_type == "BUY" else -config.SANDBOX_SLIPPAGE
        return max(0.01, price + slippage)

    def place_approved_buy(self, contract, quantity, request_id=None):
        if not self.execution_enabled:
            raise SandboxExecutionError("SANDBOX_EXECUTION_DISABLED")
        if quantity <= 0 or quantity % contract["lot_size"] != 0:
            raise ValueError("Sandbox trades must use a positive whole number of current contract lots")
        with self.order_lock:
            if request_id and request_id in self.orders:
                raise SandboxExecutionError(f"Duplicate sandbox order request: {request_id}")
            order_id = f"SBX-{uuid.uuid4().hex[:12].upper()}"
            submitted_at = datetime.now().astimezone()
            fill_price = self._fill_price(contract["token"], "BUY")
            self.orders[order_id] = {
                "order_id": order_id,
                "request_id": request_id,
                "instrument_token": contract["token"],
                "transaction_type": "BUY",
                "quantity": quantity,
                "status": "COMPLETE",
                "filled_quantity": quantity,
                "average_price": fill_price,
                "fill_model": config.SANDBOX_FILL_MODEL,
                "slippage": config.SANDBOX_SLIPPAGE,
                "submitted_at": submitted_at,
            }
            self.positions[contract["token"]] = {
                "instrument_token": contract["token"],
                "quantity": quantity,
                "average_price": fill_price,
            }
            return {
                "order_id": order_id,
                "submitted_at": submitted_at,
                "broker_response_at": datetime.now().astimezone(),
                "broker_response": {"environment": "SANDBOX", "fill_model": config.SANDBOX_FILL_MODEL},
                "status": "SUBMITTED",
                "request_id": request_id,
            }

    def place_exit(self, position, quantity):
        if not self.execution_enabled:
            raise SandboxExecutionError("SANDBOX_EXECUTION_DISABLED")
        with self.order_lock:
            if quantity <= 0 or quantity > position.quantity:
                raise ValueError("Exit quantity must be positive and no greater than the position quantity")
            order_id = f"SBX-{uuid.uuid4().hex[:12].upper()}"
            submitted_at = datetime.now().astimezone()
            fill_price = self._fill_price(position.token, "SELL")
            self.orders[order_id] = {
                "order_id": order_id,
                "instrument_token": position.token,
                "transaction_type": "SELL",
                "quantity": quantity,
                "status": "COMPLETE",
                "filled_quantity": quantity,
                "average_price": fill_price,
                "fill_model": config.SANDBOX_FILL_MODEL,
                "slippage": -config.SANDBOX_SLIPPAGE,
                "submitted_at": submitted_at,
            }
            remaining = self.positions.get(position.token, {}).get("quantity", 0) - quantity
            if remaining > 0:
                self.positions[position.token]["quantity"] = remaining
            else:
                self.positions.pop(position.token, None)
            return order_id

    def wait_for_fill(self, order_id, timeout=30):
        order = self.orders.get(order_id)
        if not order:
            raise SandboxExecutionError(f"SANDBOX_ORDER_UNKNOWN: {order_id}")
        return OrderState.FILLED, (order["average_price"], order["filled_quantity"])

    def order_book(self):
        return list(self.orders.values())

    def order_book_entry(self, order_id):
        return self.orders.get(order_id)

    def duplicate_guard(self, contract, position_manager=None):
        if contract["token"] in self.positions:
            return False, "Sandbox already has an open position for this option token"
        return True, "CLEAR"

    def position(self):
        return {"status": True, "data": list(self.positions.values())}
