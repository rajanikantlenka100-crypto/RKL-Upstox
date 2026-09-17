import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from main import MarketDataService
from market_data.indicators import fast_stochastic, fast_stochastic_series, stochastic_entry_exception
from market_data.models import Candle
from trading.exit_engine import StrategyExitState
from trading.positions import Position, PositionManager, PositionState, deserialize_strategy_exit_state, serialize_strategy_exit_state


IST = ZoneInfo("Asia/Kolkata")


def candle(index, close, low=90, high=110, instrument="NIFTY", status="FINAL"):
    timestamp = datetime(2026, 9, 17, 9, 15, tzinfo=IST) + timedelta(minutes=index * 5)
    return Candle(instrument, "NSE_INDEX", instrument, timestamp, "5m", close, high, low, close, 1, "TEST", status)


class StochasticIndicatorTests(unittest.TestCase):
    def test_fast_stochastic_uses_latest_fourteen_closed_candles(self):
        candles = [candle(index, 100) for index in range(13)]
        candles.append(candle(13, 105, low=90, high=110))
        self.assertEqual(fast_stochastic(candles), 75.0)

    def test_insufficient_zero_range_and_running_candle_are_unavailable(self):
        self.assertIsNone(fast_stochastic([candle(index, 100) for index in range(13)]))
        flat = [candle(index, 100, low=100, high=100) for index in range(14)]
        self.assertIsNone(fast_stochastic(flat))
        running = [candle(index, 100) for index in range(13)] + [candle(13, 105, status="RUNNING")]
        self.assertIsNone(fast_stochastic(running))

    def test_entry_exception_thresholds_are_strict_and_directional(self):
        candles = [candle(index, 100, low=80, high=100) for index in range(13)]
        candles.append(candle(13, 89, low=80, high=100))
        self.assertFalse(stochastic_entry_exception(candles, "PUT")["allowed"])
        candles[-1] = candle(13, 90, low=80, high=100)
        self.assertFalse(stochastic_entry_exception(candles, "PUT")["allowed"])
        candles[-1] = candle(13, 99, low=80, high=100)
        self.assertTrue(stochastic_entry_exception(candles, "PUT")["allowed"])

    def test_entry_sma_exception_is_per_index(self):
        history = [candle(index, 100 + index, instrument="NIFTY") for index in range(21)]
        result = MarketDataService._entry_sma_result(history, "CALL")
        self.assertEqual(result["entry_filter"], "sma_normal")
        other = [candle(index, 100 + index, instrument="SENSEX") for index in range(21)]
        other[-1] = candle(20, 90, low=80, high=100, instrument="SENSEX")
        self.assertEqual(len(fast_stochastic_series(history)), len(fast_stochastic_series(other)))

    def test_bearish_sma_call_is_allowed_only_by_closed_stochastic_exception(self):
        history = [candle(index, 121 - index, low=120 - index, high=122 - index) for index in range(20)]
        history.append(candle(20, 100, low=100, high=110))
        result = MarketDataService._entry_sma_result(history, "CALL")
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["entry_filter"], "stochastic_exception")
        self.assertTrue(any(value < 10 for value in result["stochastic_values"]))

    def test_all_signal_types_share_the_same_entry_exception_decision(self):
        history = [candle(index, 121 - index, low=120 - index, high=122 - index) for index in range(20)]
        history.append(candle(20, 100, low=100, high=110))
        decisions = [MarketDataService._entry_sma_result(history, "CALL") for _ in ("TYPE_1", "TYPE_2", "TYPE_3")]
        self.assertEqual({decision["result"] for decision in decisions}, {"PASS"})
        self.assertEqual({decision["entry_filter"] for decision in decisions}, {"stochastic_exception"})


class StochasticExitTests(unittest.TestCase):
    def test_call_arms_then_exits_on_closed_stochastic_reversal(self):
        state = StrategyExitState("CALL")
        first = candle(14, 100)
        second = candle(15, 100)
        self.assertIsNone(state.on_closed_candle_with_stochastic(first, None, None, 93, None))
        self.assertEqual(state.stochastic_state, "ARMED")
        self.assertIsNone(state.on_closed_candle_with_stochastic(second, None, None, 96, 93))
        self.assertEqual(state.stochastic_extreme, 96)
        self.assertEqual(state.on_closed_candle_with_stochastic(candle(16, 100), None, None, 91, 96), "STOCHASTIC_REVERSAL_EXIT")

    def test_call_reversal_uses_immediately_previous_value_after_new_high(self):
        state = StrategyExitState("CALL")
        self.assertIsNone(state.on_closed_candle_with_stochastic(candle(14, 100), None, None, 93, None))
        self.assertIsNone(state.on_closed_candle_with_stochastic(candle(15, 100), None, None, 96, 93))
        self.assertEqual(state.on_closed_candle_with_stochastic(candle(16, 100), None, None, 94, 96), "STOCHASTIC_REVERSAL_EXIT")

    def test_put_requires_strict_increase_after_low_extreme(self):
        state = StrategyExitState("PUT")
        self.assertIsNone(state.on_closed_candle_with_stochastic(candle(14, 100), None, None, 7, None))
        self.assertIsNone(state.on_closed_candle_with_stochastic(candle(15, 100), None, None, 5, 7))
        self.assertIsNone(state.on_closed_candle_with_stochastic(candle(16, 100), None, None, 5, 5))
        self.assertEqual(state.on_closed_candle_with_stochastic(candle(17, 100), None, None, 12, 5), "STOCHASTIC_REVERSAL_EXIT")

    def test_stochastic_state_round_trips(self):
        state = StrategyExitState("CALL", stochastic_state="ARMED", stochastic_extreme=96,
                                  stochastic_extreme_timestamp=candle(15, 100).timestamp,
                                  previous_stochastic=96)
        restored = deserialize_strategy_exit_state(serialize_strategy_exit_state(state))
        self.assertEqual(serialize_strategy_exit_state(restored), serialize_strategy_exit_state(state))

    def test_each_position_exit_state_is_independent(self):
        call = StrategyExitState("CALL")
        put = StrategyExitState("PUT")
        self.assertIsNone(call.on_closed_candle_with_stochastic(candle(14, 100), None, None, 93, None))
        self.assertEqual(call.stochastic_state, "ARMED")
        self.assertEqual(put.stochastic_state, "NORMAL")
        self.assertIsNone(put.on_closed_candle_with_stochastic(candle(14, 100, instrument="SENSEX"), None, None, 93, None))
        self.assertEqual(put.stochastic_state, "NORMAL")

    def test_multiple_positions_and_underlyings_keep_independent_exit_states(self):
        positions = [
            Position("A", "UPSTOX", "NIFTY", "2026-09-17", 25000, "CE", "NIFTY-A", 50, 100),
            Position("B", "UPSTOX", "NIFTY", "2026-09-17", 25000, "CE", "NIFTY-B", 50, 100),
            Position("C", "UPSTOX", "NIFTY", "2026-09-17", 25000, "PE", "NIFTY-C", 50, 100),
            Position("D", "UPSTOX", "SENSEX", "2026-09-17", 82000, "CE", "SENSEX-D", 20, 100),
            Position("E", "UPSTOX", "SENSEX", "2026-09-17", 82000, "PE", "SENSEX-E", 20, 100),
        ]
        for position in positions:
            position.strategy_exit = StrategyExitState("CALL" if position.option_type == "CE" else "PUT")
        manager = PositionManager(object())
        for position in positions:
            manager.register_fill(position, position.order_id or position.trade_id, 100, position.quantity)
        manager.positions["A"].strategy_exit.on_closed_candle_with_stochastic(candle(14, 100, instrument="NIFTY"), None, None, 93, None)
        manager.positions["B"].strategy_exit.on_closed_candle_with_stochastic(candle(14, 100, instrument="NIFTY"), None, None, 93, None)
        manager.positions["C"].strategy_exit.on_closed_candle_with_stochastic(candle(14, 100, instrument="NIFTY"), None, None, 7, None)
        manager.positions["D"].strategy_exit.on_closed_candle_with_stochastic(candle(14, 100, instrument="SENSEX"), None, None, 93, None)
        self.assertEqual({manager.positions[key].strategy_exit.stochastic_state for key in ("A", "B", "D")}, {"ARMED"})
        self.assertEqual(manager.positions["C"].strategy_exit.stochastic_state, "ARMED")
        self.assertEqual(manager.positions["E"].strategy_exit.stochastic_state, "NORMAL")
        self.assertEqual(len({position.trade_id for position in manager.positions.values()}), 5)

    def test_exit_state_transition_is_one_way_and_blocks_second_trigger(self):
        state = StrategyExitState("CALL")
        state.on_closed_candle_with_stochastic(candle(14, 100), None, None, 93, None)
        reason = state.on_closed_candle_with_stochastic(candle(15, 100), None, None, 89, 93)
        self.assertEqual(reason, "STOCHASTIC_REVERSAL_EXIT")
        self.assertEqual(state.exit_state, "EXIT_PENDING")
        self.assertIsNone(state.on_closed_candle_with_stochastic(candle(16, 100), None, None, 80, 89))


if __name__ == "__main__":
    unittest.main()