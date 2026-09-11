import unittest

from trading.positions import OrderState, Position, PositionManager, PositionState


class PositionStateTests(unittest.TestCase):
    def test_confirmed_fill_and_sl_transition(self):
        class Broker:
            def position(self): return {"status": True, "data": []}
        manager = PositionManager(Broker())
        position = Position("T1", "UPSTOX", "NIFTY", "08SEP2026", 23900, "CE", "NSE_FO|42635", 65, 0, 80)
        manager.register_fill(position, "O1", 100, 65)
        self.assertEqual(position.state, PositionState.OPEN)
        manager.mark_sl("T1", "SL1")
        self.assertEqual(position.state, PositionState.SL_ACTIVE)

    def test_partial_fill_and_unprotected_are_explicit(self):
        manager = PositionManager(object())
        position = Position("T2", "UPSTOX", "NIFTY", "08SEP2026", 23900, "CE", "NSE_FO|42635", 65, 0, 80)
        manager.register_partial_fill(position, "O2", 100, 20)
        self.assertEqual(position.state, PositionState.PARTIALLY_FILLED)
        manager.mark_unprotected("T2")
        self.assertEqual(position.state, PositionState.UNPROTECTED)


if __name__ == "__main__":
    unittest.main()
