import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data.models import Candle
from storage.sqlite_store import CandleStore
from trading.exit_engine import StrategyExitState
from trading.positions import (
    PositionManager,
    PositionState,
    deserialize_candle,
    deserialize_strategy_exit_state,
    serialize_candle,
    serialize_strategy_exit_state,
)


IST = ZoneInfo("Asia/Kolkata")


def make_candle(minute=0, status="FINAL"):
    return Candle(
        "NIFTY", "NSE_INDEX", "NIFTY-TOKEN",
        datetime(2026, 9, 17, 10, minute, tzinfo=IST), "5m",
        100, 106, 98, 104, 42, "UPSTOX", status,
    )


class PositionPersistenceTests(unittest.TestCase):
    def test_candle_round_trip_preserves_structured_fields(self):
        original = make_candle(status="RUNNING")
        restored = deserialize_candle(serialize_candle(original))
        self.assertEqual(restored, original)

    def test_strategy_exit_round_trip_preserves_arm_and_reference_state(self):
        standard = make_candle()
        reference = make_candle(5)
        state = StrategyExitState(
            "CALL", standard_candle=standard, cci_state="CONFIRMED",
            exit_state="EXIT_PENDING", arm_timestamp=standard.timestamp,
            arm_candle_timestamp=standard.timestamp, arm_cci=101.5,
            confirmation_candle_timestamp=reference.timestamp,
            exit_reason="CCI_CONFIRMATION", reference_candle=reference,
        )
        restored = deserialize_strategy_exit_state(serialize_strategy_exit_state(state))
        self.assertEqual(serialize_strategy_exit_state(restored), serialize_strategy_exit_state(state))

    def test_position_restart_restores_complete_states_and_legacy_mapping(self):
        standard = make_candle()
        reference = make_candle(5)
        exit_state = StrategyExitState(
            "PUT", standard_candle=standard, cci_state="ARMED",
            arm_timestamp=standard.timestamp, arm_candle_timestamp=standard.timestamp,
            arm_cci=-101, reference_candle=reference,
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CandleStore(Path(directory) / "state.sqlite3")
            for trade_id, state in (("OPEN", "OPEN"), ("PENDING", "EXIT_PENDING"), ("CLOSED", "CLOSED"), ("UNKNOWN", "UNKNOWN"), ("LEGACY", "SL_ACTIVE")):
                store.record("positions", trade_id, {
                    "signal_id": "S1", "signal_type": "TYPE_2", "underlying": "NIFTY",
                    "direction": "PUT", "instrument_key": "TOKEN", "expiry": "2026-09-17",
                    "strike": 25000, "quantity": 50, "entry_price": 100,
                    "order_id": "BUY-1", "state": state, "exit_state": state,
                    "exit_reason": "CCI_CONFIRMATION" if state == "CLOSED" else None,
                    "payload": {
                        "broker": "UPSTOX", "option_type": "PE", "token": "TOKEN",
                        "symbol": "25000PE", "exchange": "NSE_FO", "standard_candle": serialize_candle(standard),
                        "strategy_exit": serialize_strategy_exit_state(exit_state),
                        "cci_exit_state": "ARMED", "exit_order_id": "SELL-1",
                        "exit_price": 90, "exit_timestamp": standard.timestamp.isoformat(),
                        "realized_pnl": -500,
                    },
                })
            manager = PositionManager(object())
            manager.restore(store.load_positions())
            self.assertEqual(manager.positions["OPEN"].state, PositionState.OPEN)
            self.assertEqual(manager.positions["PENDING"].state, PositionState.EXIT_PENDING)
            self.assertEqual(manager.positions["CLOSED"].state, PositionState.CLOSED)
            self.assertEqual(manager.positions["UNKNOWN"].state, PositionState.UNKNOWN)
            self.assertEqual(manager.positions["LEGACY"].state, PositionState.OPEN)
            restored = manager.positions["OPEN"]
            self.assertEqual(restored.strategy_exit.cci_state, "ARMED")
            self.assertEqual(restored.strategy_exit.reference_candle, reference)
            self.assertEqual(restored.exit_order_id, "SELL-1")
            self.assertEqual(restored.realized_pnl, -500)
            store.close()

    def test_partial_fill_persistence_keeps_restart_context(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CandleStore(Path(directory) / "state.sqlite3")
            candle = serialize_candle(make_candle())
            store.record("positions", "PARTIAL", {
                "signal_id": "S1", "signal_type": "TYPE_1", "underlying": "NIFTY",
                "direction": "CALL", "instrument_key": "TOKEN", "expiry": "2026-09-17",
                "strike": 25000, "quantity": 20, "entry_price": 101,
                "order_id": "BUY-1", "state": "PARTIALLY_FILLED", "exit_state": "OPEN",
                "payload": {"broker": "UPSTOX", "option_type": "CE", "token": "TOKEN",
                            "symbol": "25000CE", "exchange": "NSE_FO", "standard_candle": candle,
                            "quantity": 20, "entry_price": 101},
            })
            rows = store.load_positions()
            self.assertEqual(rows[0]["state"], "PARTIALLY_FILLED")
            self.assertEqual(rows[0]["payload"]["quantity"], 20)
            store.close()


if __name__ == "__main__":
    unittest.main()