import unittest
from unittest.mock import patch

from broker.order_manager import BrokerOrderRejected, OrderExecutor
from trading.positions import Position


class ExitOrderSafetyTests(unittest.TestCase):
    def setUp(self):
        self.position = Position(
            "T1", "UPSTOX", "NIFTY", "2026-09-10", 25000, "CE",
            "NSE_FO|1", 65, 100, symbol="NIFTY25000CE", exchange="NSE_FO",
        )

    def test_market_exit_uses_broker_confirmed_order_id(self):
        class Client:
            def place_order(self, params):
                return {"status": True, "data": {"order_id": "EXIT1"}}

        executor = OrderExecutor(Client())
        with patch("config.order_execution_enabled", return_value=True):
            result = executor.place_exit(self.position, 65)
        self.assertEqual(result, "EXIT1")

    def test_market_exit_rejection_is_distinct(self):
        class Client:
            def place_order(self, params):
                return {"status": False, "message": "rejected", "data": None}

        executor = OrderExecutor(Client())
        with patch("config.order_execution_enabled", return_value=True):
            with self.assertRaises(BrokerOrderRejected):
                executor.place_exit(self.position, 65)

    def test_market_exit_transport_failure_is_unknown(self):
        class Client:
            def place_order(self, params):
                raise OSError("connection lost")

        executor = OrderExecutor(Client())
        with patch("config.order_execution_enabled", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "ORDER_STATUS_UNKNOWN"):
                executor.place_exit(self.position, 65)


if __name__ == "__main__":
    unittest.main()
