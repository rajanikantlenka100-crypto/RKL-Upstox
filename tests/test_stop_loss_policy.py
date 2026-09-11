import unittest

from instruments.options import OptionContract
from trading.stop_loss_policy import build_stop_loss


class StopLossPolicyTests(unittest.TestCase):
    """UNIT: deterministic SL policy validation; no broker order is sent."""

    def setUp(self):
        self.contract = OptionContract("NIFTY", "08SEP2026", 23900, "CE", "NIFTY08SEP2623900CE", "42635", "NFO", 65, 0.05)

    def test_policy_aligns_trigger_and_limit_to_tick_size(self):
        trigger, limit = build_stop_loss(self.contract, 120.03, 131.60)
        self.assertEqual((trigger, limit), (119.05, 119.0))

    def test_policy_rejects_trigger_above_market(self):
        with self.assertRaises(ValueError):
            build_stop_loss(self.contract, 140, 131.60)

    def test_policy_keeps_one_tick_relationship_when_offset_rounds_away(self):
        coarse = OptionContract("NIFTY", "08SEP2026", 23900, "CE", "NIFTY", "1", "NFO", 65, 0.10)
        trigger, limit = build_stop_loss(coarse, 101.0, 120.0, buffer=1.0, limit_offset=0.05)
        self.assertEqual((trigger, limit), (100.0, 99.9))


if __name__ == "__main__":
    unittest.main()
