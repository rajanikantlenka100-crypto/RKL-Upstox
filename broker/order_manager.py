"""Explicitly approved Upstox order boundary. Never called automatically."""

import time
import threading
from datetime import datetime

import config
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
    def __init__(self, client, execution_enabled=None):
        self.client = client
        self.execution_enabled = execution_enabled
        self.order_lock = threading.RLock()
        self.submitted_requests = set()

    def place_approved_buy(self, contract, quantity, request_id=None):
        if quantity <= 0 or quantity % contract["lot_size"] != 0:
            raise ValueError("New trades must use a positive whole number of current contract lots")
        if not self._execution_allowed():
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

    def place_exit(self, position, quantity):
        if quantity <= 0 or quantity > position.quantity:
            raise ValueError("Exit quantity must be positive and no greater than the position quantity")
        if not self._execution_allowed():
            raise RuntimeError("Real orders are disabled; exit was not submitted")
        params = {"instrument_token": position.token, "transaction_type": "SELL", "order_type": "MARKET", "price": 0, "quantity": quantity}
        try:
            response = self._place_order(params)
        except Exception as error:
            raise RuntimeError(f"ORDER_STATUS_UNKNOWN: exit request outcome uncertain: {error}") from error
        if not response or not response.get("status"):
            response_data = response.get("data") if isinstance(response, dict) else None
            raise BrokerOrderRejected(
                response.get("message", "Broker rejected exit") if response else "No broker exit response",
                order_id=response_data.get("order_id") if isinstance(response_data, dict) else None,
                response=response,
            )
        if not response.get("data") or not response["data"].get("order_id"):
            raise RuntimeError("ORDER_STATUS_UNKNOWN: broker exit response has no order ID")
        return response["data"]["order_id"]

    def _place_order(self, params):
        with self.order_lock:
            return self.client.place_order(params)

    def _execution_allowed(self):
        return config.order_execution_enabled() if self.execution_enabled is None else bool(self.execution_enabled)

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