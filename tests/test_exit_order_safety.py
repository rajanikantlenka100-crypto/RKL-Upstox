import unittest
from unittest.mock import patch

from broker.order_manager import OrderExecutor


class ExitOrderSafetyTests(unittest.TestCase):
    def test_cancel_and_confirm_requires_broker_cancelled_status(self):
        class Client:
            def cancelOrder(self, variety, order_id):
                return {"status": "success"}

            def orderBook(self):
                return {"status": "success", "data": [{"order_id": "SL1", "status": "CANCELLED"}]}

        executor = OrderExecutor(Client())
        with patch("config.order_execution_enabled", return_value=True):
            result = executor.cancel_and_confirm("SL1", timeout=1)
        self.assertEqual(result["status"], "CANCELLED")

    def test_cancel_and_confirm_blocks_when_stop_remains_open(self):
        class Client:
            def cancelOrder(self, variety, order_id):
                return {"status": "success"}

            def orderBook(self):
                return {"status": "success", "data": [{"order_id": "SL1", "status": "OPEN"}]}

        executor = OrderExecutor(Client())
        with patch("config.order_execution_enabled", return_value=True):
            with self.assertRaises(TimeoutError):
                executor.cancel_and_confirm("SL1", timeout=0)

    def test_cancel_and_confirm_rejects_terminal_stop_fill(self):
        class Client:
            def cancelOrder(self, variety, order_id):
                return {"status": "success"}

            def orderBook(self):
                return {"status": "success", "data": [{"order_id": "SL1", "status": "COMPLETE"}]}

        executor = OrderExecutor(Client())
        with patch("config.order_execution_enabled", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "was not cancelled"):
                executor.cancel_and_confirm("SL1", timeout=1)


if __name__ == "__main__":
    unittest.main()
