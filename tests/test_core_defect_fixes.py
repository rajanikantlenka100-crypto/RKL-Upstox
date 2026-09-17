import threading
import unittest

from trading.positions import Position, PositionManager, PositionState


class Broker:
    def __init__(self, positions):
        self.positions = positions

    def position(self):
        return {"status": True, "data": self.positions}


def position(trade_id, token="TOKEN", quantity=1, state=PositionState.OPEN, order_id=None):
    return Position(
        trade_id, "UPSTOX", "NIFTY", "2026-09-17", 25000, "CE", token,
        quantity, 100, state=state, order_id=order_id,
    )


class AtomicExitReservationTests(unittest.TestCase):
    def test_many_concurrent_reservations_produce_one_winner(self):
        manager = PositionManager(object())
        manager.positions["T1"] = position("T1")
        winners = []
        barrier = threading.Barrier(20)

        def reserve():
            barrier.wait()
            if manager.reserve_exit("T1", "STOCHASTIC_REVERSAL_EXIT"):
                winners.append("T1")

        threads = [threading.Thread(target=reserve) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(winners, ["T1"])
        self.assertEqual(manager.positions["T1"].state, PositionState.EXIT_PENDING)
        self.assertEqual(manager.positions["T1"].exit_reason, "STOCHASTIC_REVERSAL_EXIT")


class SameTokenReconciliationTests(unittest.TestCase):
    def test_matching_aggregate_quantity_keeps_same_token_allocation_unresolved(self):
        manager = PositionManager(Broker([{"instrument_token": "X", "quantity": 2}]))
        manager.positions.update({"A": position("A", "X"), "B": position("B", "X")})
        result = manager.reconcile()
        self.assertEqual(result["quantity_mismatches"], {})
        self.assertEqual(result["allocation_unresolved"], {"X": ["A", "B"]})
        self.assertEqual(manager.positions["A"].state, PositionState.OPEN)
        self.assertEqual(manager.positions["B"].state, PositionState.OPEN)

    def test_same_token_quantity_mismatch_is_explicit(self):
        manager = PositionManager(Broker([{"instrument_token": "X", "quantity": 1}]))
        manager.positions.update({"A": position("A", "X"), "B": position("B", "X")})
        result = manager.reconcile()
        self.assertEqual(result["quantity_mismatches"], {"X": {"local": 2, "broker": 1}})
        self.assertEqual(result["allocation_unresolved"], {"X": ["A", "B"]})

    def test_single_position_reconciliation_remains_resolved(self):
        manager = PositionManager(Broker([{"instrument_token": "X", "quantity": 1}]))
        manager.positions["A"] = position("A", "X")
        result = manager.reconcile()
        self.assertEqual(result["quantity_mismatches"], {})
        self.assertEqual(result["allocation_unresolved"], {})


class PositionLifecycleGuardTests(unittest.TestCase):
    def test_valid_transitions_are_allowed(self):
        manager = PositionManager(object())
        item = position("T1", state=PositionState.PENDING_ENTRY)
        manager.positions["T1"] = item
        manager.register_partial_fill(item, "O1", 100, 1)
        manager.register_fill(item, "O1", 100, 1)
        manager.mark_exit_pending("T1")
        manager.mark_closed("T1")
        self.assertEqual(item.state, PositionState.CLOSED)

    def test_illegal_transitions_are_rejected(self):
        manager = PositionManager(object())
        item = position("T1", state=PositionState.OPEN)
        manager.positions["T1"] = item
        with self.assertRaises(ValueError):
            manager.mark_closed("T1")
        manager.mark_unknown("T1")
        with self.assertRaises(ValueError):
            manager.mark_error("T1")


if __name__ == "__main__":
    unittest.main()