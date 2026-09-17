import tempfile
import unittest
from pathlib import Path

from storage.sqlite_store import CandleStore
from trading.positions import Position, PositionManager, PositionState


class Broker:
    def __init__(self, positions):
        self.positions = positions

    def position(self):
        return {"status": True, "data": self.positions}


class MultiPositionRecoveryTests(unittest.TestCase):
    def test_restore_multiple_positions_and_external_close(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CandleStore(Path(directory) / "state.sqlite3")
            store.record("positions", "T1", {
                "signal_id": "S1", "signal_type": "TYPE_1", "underlying": "NIFTY",
                "direction": "CALL", "instrument_key": "OPT1", "expiry": "2026-09-10",
                "strike": 25000, "quantity": 50, "entry_price": 120, "initial_sl": 110,
                "initial_risk": 10, "state": "SL_ACTIVE", "payload": {"symbol": "25000CE", "option_type": "CE"},
            })
            store.record("positions", "T2", {
                "signal_id": "S2", "signal_type": "TYPE_2", "underlying": "BANKNIFTY",
                "direction": "PUT", "instrument_key": "OPT2", "expiry": "2026-09-10",
                "strike": 50000, "quantity": 30, "entry_price": 80, "initial_sl": 72,
                "initial_risk": 8, "state": "SL_ACTIVE", "payload": {"symbol": "50000PE", "option_type": "PE"},
            })
            manager = PositionManager(Broker([{"instrument_token": "OPT2", "quantity": 30}]))
            manager.restore(store.load_positions())
            result = manager.reconcile()
            self.assertEqual(set(manager.positions), {"T1", "T2"})
            self.assertEqual(result["externally_closed"], {"T1"})
            self.assertEqual(manager.positions["T1"].state, PositionState.UNKNOWN)
            self.assertEqual(manager.positions["T1"].exit_reason, "EXTERNAL_POSITION_UNRESOLVED")
            self.assertEqual(manager.positions["T2"].state, PositionState.OPEN)
            self.assertIsNotNone(manager.positions["T2"].strategy_exit)
            store.close()


if __name__ == "__main__":
    unittest.main()
