import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from signals.breakout import PutCallSignal
from signals.coordinator import ApprovalController, SignalCoordinator
from market_data.models import Candle


class ApprovalControllerTests(unittest.TestCase):
    """UNIT: queued approval decisions; no stdin, broker, or market connection."""

    def signal(self, name, identifier):
        candle = Candle(name, "NSE", "1", datetime(2026, 9, 3, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")), "5m", 1, 2, 1, 2, 0, "UNIT")
        return PutCallSignal(identifier, candle.timestamp, name, "CALL", 2, candle, candle, 2)

    def test_numbered_multiple_signal_approval(self):
        coordinator = SignalCoordinator(expiry_seconds=60)
        first = self.signal("NIFTY", "one")
        second = self.signal("BANKNIFTY", "two")
        coordinator.submit(first, first.timestamp)
        coordinator.submit(second, second.timestamp)
        decisions = []
        controller = ApprovalController(coordinator, decisions.append)
        controller.process_key("A2")
        self.assertEqual(decisions[0]["signal"].signal_id, "two")
        self.assertEqual(decisions[0]["status"], "APPROVED")

    def test_unqualified_key_is_ignored_when_multiple_active(self):
        coordinator = SignalCoordinator()
        first = self.signal("NIFTY", "one")
        second = self.signal("SENSEX", "two")
        coordinator.submit(first, first.timestamp)
        coordinator.submit(second, second.timestamp)
        decisions = []
        controller = ApprovalController(coordinator, decisions.append)
        controller.process_key("A")
        self.assertEqual(decisions, [])

    def test_expired_signal_is_resolved_and_removed(self):
        coordinator = SignalCoordinator(expiry_seconds=1)
        first = self.signal("NIFTY", "one")
        coordinator.submit(first, first.timestamp)
        expired = coordinator.expire(first.timestamp.replace(second=2))
        self.assertEqual(expired[0]["status"], "EXPIRED")
        self.assertIsNone(coordinator.current("PRIMARY"))


if __name__ == "__main__":
    unittest.main()
