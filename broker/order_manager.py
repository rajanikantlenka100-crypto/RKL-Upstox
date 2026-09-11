"""Explicitly approved Upstox order boundary. Never called automatically."""

import time
import threading
from datetime import datetime

import config
from instruments.options import OptionContract, round_to_tick
from trading.positions import OrderState


class BrokerOrderRejected(RuntimeError):
    """A broker-confirmed rejection, distinct from an unknown transport result."""

    def __init__(self, message, *, order_id=None, response=None, request_timestamp=None, response_timestamp=None):
        super().__init__(message)
        self.order_id = order_id
        self.response = response
        self.request_timestamp = request_timestamp
        self.response_timestamp = response_timestamp


class OrderExecutor:
    def __init__(self, client):
        self.client = client
        self.order_lock = threading.RLock()
        self.submitted_requests = set()

    def place_approved_buy(self, contract, quantity, request_id=None):
        if quantity != contract["lot_size"]:
            raise ValueError("New trades must use exactly one current contract lot")
        if not config.order_execution_enabled():
            raise RuntimeError("Real orders are disabled; set REAL_ORDERS_ENABLED=ON only after Upstox rule review")
        with self.order_lock:
            if request_id and request_id in self.submitted_requests:
                raise RuntimeError(f"Duplicate logical order request: {request_id}")
            params = {"instrument_token": contract["token"], "transaction_type": "BUY", "order_type": "MARKET", "price": 0, "quantity": quantity}
            request_timestamp = datetime.now().astimezone()
            try:
                response = self._place_order(params)
            except Exception as error:
                unknown = RuntimeError(f"ORDER_STATUS_UNKNOWN: BUY request outcome uncertain: {error}")
                unknown.request_timestamp = request_timestamp
                unknown.response_timestamp = datetime.now().astimezone()
                raise unknown from error
            response_timestamp = datetime.now().astimezone()
            data = response.get("data") if isinstance(response, dict) else None
            if not response or not response.get("status"):
                raise BrokerOrderRejected(
                    response.get("message", "Broker rejected order") if response else "No broker order response",
                    order_id=data.get("order_id") if isinstance(data, dict) else None,
                    response=response,
                    request_timestamp=request_timestamp,
                    response_timestamp=response_timestamp,
                )
            if not isinstance(data, dict):
                raise RuntimeError("ORDER_STATUS_UNKNOWN: broker response has no order data")
            order_id = data.get("order_id")
            if not order_id:
                raise RuntimeError("ORDER_STATUS_UNKNOWN: broker response has no order ID")
            if request_id:
                self.submitted_requests.add(request_id)
            return {
                "order_id": order_id, "submitted_at": request_timestamp,
                "broker_response_at": response_timestamp, "broker_response": response,
                "status": "SUBMITTED", "request_id": request_id,
            }

    def duplicate_guard(self, contract, position_manager=None):
        if position_manager and any(
            position.token == contract.instrument_key and position.state not in {"CLOSED", "ERROR"}
            for position in position_manager.positions.values()
        ):
            return False, "A local active position already uses this option token"
        response = self.client.position()
        if response and response.get("status"):
            for position in response.get("data") or []:
                if str(position.get("instrument_token")) == contract.instrument_key and int(position.get("quantity", 0) or 0) != 0:
                    return False, "Broker already has an open position for this option token"
        orders = self.client.orderBook()
        if orders and orders.get("status"):
            active = {"OPEN", "OPEN_PENDING", "PENDING", "TRIGGER_PENDING", "PARTIALLY_FILLED", "PUT_ORDER_REQ_RECEIVED", "VALIDATION_PENDING"}
            for order in orders.get("data") or []:
                if str(order.get("instrument_token")) == contract.instrument_key and str(order.get("status", "")).upper() in active:
                    return False, "Broker already has an active order for this option token"
        return True, "CLEAR"

    def order_book(self):
        try:
            response = self.client.orderBook()
        except Exception as error:
            raise RuntimeError(f"ORDER_STATUS_UNKNOWN: order book lookup failed: {error}") from error
        if not response or not response.get("status"):
            raise RuntimeError(response.get("message", "Order book unavailable") if response else "No order book response")
        return response.get("data") or []

    def order_book_entry(self, order_id):
        return next((order for order in self.order_book() if str(order.get("order_id")) == str(order_id)), None)

    def place_stop_loss(self, contract, quantity, trigger_price, limit_price, current_ltp=None):
        params = self.build_stop_loss_params(contract, quantity, trigger_price, limit_price, current_ltp)
        if not config.order_execution_enabled():
            raise RuntimeError("Real stop-loss orders are disabled")
        try:
            response = self._place_order(params)
        except Exception as error:
            raise RuntimeError(f"ORDER_STATUS_UNKNOWN: SL request outcome uncertain: {error}") from error
        if not response or not response.get("status"):
            raise BrokerOrderRejected(
                response.get("message", "Broker rejected stop-loss") if response else "No broker stop-loss response",
                order_id=(response or {}).get("data", {}).get("order_id") if isinstance(response, dict) else None,
                response=response,
            )
        if not response.get("data"):
            raise RuntimeError("ORDER_STATUS_UNKNOWN: broker response has no stop-loss data")
        order_id = response["data"].get("order_id")
        if not order_id:
            raise RuntimeError("ORDER_STATUS_UNKNOWN: SL response has no order ID")
        return order_id

    def place_exit(self, position, quantity):
        if quantity <= 0 or quantity > position.quantity:
            raise ValueError("Exit quantity must be positive and no greater than the position quantity")
        if not config.order_execution_enabled():
            raise RuntimeError("Real orders are disabled; exit was not submitted")
        params = {"instrument_token": position.token, "transaction_type": "SELL", "order_type": "MARKET", "price": 0, "quantity": quantity}
        try:
            response = self._place_order(params)
        except Exception as error:
            raise RuntimeError(f"ORDER_STATUS_UNKNOWN: exit request outcome uncertain: {error}") from error
        if not response or not response.get("status"):
            raise BrokerOrderRejected(
                response.get("message", "Broker rejected exit") if response else "No broker exit response",
                order_id=(response or {}).get("data", {}).get("order_id") if isinstance(response, dict) else None,
                response=response,
            )
        if not response.get("data") or not response["data"].get("order_id"):
            raise RuntimeError("ORDER_STATUS_UNKNOWN: broker exit response has no order ID")
        return response["data"]["order_id"]

    def cancel_order(self, order_id, variety="STOPLOSS"):
        if not config.order_execution_enabled():
            raise RuntimeError("Real orders are disabled; cancellation was not submitted")
        try:
            response = self.client.cancelOrder(variety, str(order_id))
        except Exception as error:
            raise RuntimeError(f"ORDER_STATUS_UNKNOWN: cancellation outcome uncertain: {error}") from error
        if not response or not response.get("status"):
            raise BrokerOrderRejected(
                response.get("message", "Broker rejected cancellation") if response else "No broker cancellation response",
                response=response,
            )
        return response

    def cancel_and_confirm(self, order_id, variety="STOPLOSS", timeout=30):
        """Cancel a protective order and require broker-authoritative cancellation."""
        self.cancel_order(order_id, variety=variety)
        deadline = time.time() + timeout
        terminal = {"CANCELLED", "REJECTED", "COMPLETE", "TRIGGERED"}
        while time.time() < deadline:
            entry = self.order_book_entry(order_id)
            status = self._canonical_status((entry or {}).get("status", ""))
            if status == "CANCELLED":
                return entry
            if status in terminal:
                raise RuntimeError(f"Protective order {order_id} was not cancelled: {status}")
            time.sleep(2)
        raise TimeoutError(f"ORDER_STATUS_UNKNOWN: timed out confirming cancellation for {order_id}")

    def _place_order(self, params):
        with self.order_lock:
            return self.client.place_order(params)

    def build_stop_loss_params(self, contract, quantity, trigger_price, limit_price, current_ltp=None):
        if quantity <= 0 or trigger_price <= 0 or limit_price <= 0:
            raise ValueError("Invalid protective order values")
        if not isinstance(contract, OptionContract):
            raise TypeError("Stop-loss requires an OptionContract with master-derived tick size")
        trigger_price = round_to_tick(trigger_price, contract.tick_size)
        limit_price = round_to_tick(limit_price, contract.tick_size)
        if not limit_price < trigger_price:
            raise ValueError("SELL stop-loss limit price must be below trigger price")
        if current_ltp is not None and trigger_price >= current_ltp - config.SL_MIN_TICK_DISTANCE * contract.tick_size:
            raise ValueError("SELL stop-loss trigger is too close to current option LTP")
        params = {"instrument_token": contract.instrument_key, "transaction_type": "SELL", "order_type": "SL",
                  "price": limit_price, "trigger_price": trigger_price, "quantity": quantity}
        return params

    def confirm_order(self, order_id, expected_statuses=("OPEN", "TRIGGER PENDING", "COMPLETE")):
        response = self.client.orderBook()
        if not response or not response.get("status"):
            raise RuntimeError("Unable to confirm broker order status")
        for order in response.get("data") or []:
            if str(order.get("order_id")) == str(order_id):
                status = str(order.get("status", "")).upper()
                if self._canonical_status(status) not in {self._canonical_status(value) for value in expected_statuses}:
                    raise RuntimeError(f"Broker order {order_id} status is {status}")
                return order
        raise RuntimeError(f"Broker order {order_id} was not found")

    def wait_for_fill(self, order_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                response = self.client.orderBook()
            except Exception as error:
                raise RuntimeError(f"ORDER_STATUS_UNKNOWN: fill status lookup failed: {error}") from error
            for order in (response.get("data") or []) if response and response.get("status") else []:
                if str(order.get("order_id")) != str(order_id):
                    continue
                status = str(order.get("status", "")).upper()
                filled = int(order.get("filled_quantity") or 0)
                if filled > 0 and status not in {"COMPLETE", "REJECTED", "CANCELLED"}:
                    return OrderState.PARTIALLY_FILLED, self._fill_values(order, filled)
                if status in {"COMPLETE", "REJECTED", "CANCELLED"}:
                    if status == "REJECTED":
                        raise BrokerOrderRejected(
                            f"Broker order {order_id} ended as REJECTED",
                            order_id=order_id,
                            response=order,
                        )
                    if status == "CANCELLED":
                        raise BrokerOrderRejected(
                            f"Broker order {order_id} ended as CANCELLED",
                            order_id=order_id,
                            response=order,
                        )
                    average, quantity = self._fill_values(order, filled)
                    if average <= 0 or quantity <= 0:
                        raise RuntimeError(f"Broker order {order_id} has no valid fill")
                    return OrderState.FILLED, (average, quantity)
            time.sleep(2)
        raise TimeoutError(f"ORDER_STATUS_UNKNOWN: timed out waiting for broker order {order_id}; reconcile before retrying")

    @staticmethod
    def _fill_values(order, filled):
        average = float(order.get("average_price") or 0)
        quantity = filled or int(order.get("quantity") or 0)
        return average, quantity

    @staticmethod
    def _canonical_status(status):
        return str(status).upper().replace(" ", "_")


ApprovedOrderManager = OrderExecutor