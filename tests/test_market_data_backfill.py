import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, call, patch
from zoneinfo import ZoneInfo

import config
from instruments.resolver import Instrument
from main import MarketDataService
from market_data.candles import CandleEngine


class MarketDataBackfillTests(unittest.TestCase):
    def _service(self, rows=None, fetch_error=None):
        instrument = Instrument("NIFTY", "NIFTY", "NSE_INDEX|Nifty 50", "NSE_INDEX")
        adapter = MagicMock()
        adapter.fetch_historical.return_value = rows or []
        if fetch_error is not None:
            adapter.fetch_historical.side_effect = fetch_error
        store = MagicMock()
        store.reconcile.return_value = "UNCHANGED"
        store.latest_running.return_value = None
        engine = CandleEngine()
        engine.seed = Mock(wraps=engine.seed)
        service = MarketDataService.__new__(MarketDataService)
        service.adapter = adapter
        service.store = store
        service.engines = {instrument.name: engine}
        service.display = MagicMock()
        service.reconciliation_blocked = set()
        service.order_manager = MagicMock()
        service.position_manager = MagicMock()
        service._record_event = Mock()
        service._on_status = Mock()
        service._reconcile_intraday = Mock()
        return service, instrument, adapter, store, engine

    @staticmethod
    def _rows(count):
        first_timestamp = datetime(2026, 9, 10, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        return [
            [
                (first_timestamp + timedelta(minutes=5 * index)).isoformat(),
                100 + index,
                102 + index,
                99 + index,
                101 + index,
                1000 + index,
            ]
            for index in range(count)
        ]

    def test_backfill_index_success_reconciles_and_seeds_finalized_history(self):
        instrument = Instrument("NIFTY", "NIFTY", "NSE_INDEX|Nifty 50", "NSE_INDEX")
        minimum_warmup = config.RSI_PERIOD + config.RSI_SMA_PERIOD + config.RSI_LOOKBACK_PERIODS
        row_count = minimum_warmup + 2
        first_timestamp = datetime(2026, 9, 10, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        rows = [
            [
                (first_timestamp + timedelta(minutes=5 * index)).isoformat(),
                100 + index,
                102 + index,
                99 + index,
                101 + index,
                1000 + index,
            ]
            for index in range(row_count)
        ]

        adapter = MagicMock()
        adapter.fetch_historical.return_value = rows
        store = MagicMock()
        store.reconcile.return_value = "UNCHANGED"
        store.latest_running.return_value = None
        engine = CandleEngine()
        engine.seed = Mock(wraps=engine.seed)
        service = MarketDataService.__new__(MarketDataService)
        service.adapter = adapter
        service.store = store
        service.engines = {instrument.name: engine}
        service.display = MagicMock()
        service.reconciliation_blocked = set()
        service.order_manager = MagicMock()
        service.position_manager = MagicMock()
        service._record_event = Mock()
        service._on_status = Mock()
        service._reconcile_intraday = Mock()

        with patch.object(config, "INTRADAY_RECONCILIATION_ENABLED", False):
            result = service._backfill_index(instrument)

        self.assertEqual(result, {"instrument": "NIFTY", "status": "SYNCED", "count": row_count})
        adapter.fetch_historical.assert_called_once_with(instrument, count=config.HISTORICAL_COUNT)
        self.assertEqual(adapter.method_calls, [call.fetch_historical(instrument, count=config.HISTORICAL_COUNT)])
        self.assertEqual(store.reconcile.call_count, row_count)
        reconciled = [call.args[0] for call in store.reconcile.call_args_list]
        store.replace.assert_not_called()
        self.assertEqual(engine.seed.call_count, 1)
        seeded = engine.seed.call_args.args[0]
        self.assertEqual(seeded, reconciled)
        self.assertEqual(seeded, sorted(seeded, key=lambda candle: candle.timestamp))
        self.assertTrue(all(candle.status == "FINAL" for candle in seeded))
        self.assertEqual(service.order_manager.method_calls, [])
        self.assertEqual(service.position_manager.method_calls, [])
        service._reconcile_intraday.assert_not_called()

    def test_backfill_index_mismatch_replaces_and_seeds_corrected_candle(self):
        instrument = Instrument("NIFTY", "NIFTY", "NSE_INDEX|Nifty 50", "NSE_INDEX")
        minimum_warmup = config.RSI_PERIOD + config.RSI_SMA_PERIOD + config.RSI_LOOKBACK_PERIODS
        row_count = minimum_warmup + 2
        mismatch_index = 3
        first_timestamp = datetime(2026, 9, 10, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        rows = [
            [
                (first_timestamp + timedelta(minutes=5 * index)).isoformat(),
                100 + index,
                102 + index,
                99 + index,
                101 + index,
                1000 + index,
            ]
            for index in range(row_count)
        ]
        mismatch_timestamp = first_timestamp + timedelta(minutes=5 * mismatch_index)
        local_ohlc = (98.0, 100.0, 97.0, 99.0, 900)

        adapter = MagicMock()
        adapter.fetch_historical.return_value = rows
        store = MagicMock()
        store.reconcile.side_effect = lambda candle: (
            "MISMATCH" if candle.timestamp == mismatch_timestamp else "UNCHANGED"
        )
        store.existing_ohlc.return_value = local_ohlc
        store.latest_running.return_value = None
        engine = CandleEngine()
        engine.seed = Mock(wraps=engine.seed)
        service = MarketDataService.__new__(MarketDataService)
        service.adapter = adapter
        service.store = store
        service.engines = {instrument.name: engine}
        service.display = MagicMock()
        service.reconciliation_blocked = set()
        service.order_manager = MagicMock()
        service.position_manager = MagicMock()
        service._record_event = Mock()
        service._on_status = Mock()
        service._reconcile_intraday = Mock()

        with patch.object(config, "INTRADAY_RECONCILIATION_ENABLED", False):
            result = service._backfill_index(instrument)

        self.assertEqual(result, {"instrument": "NIFTY", "status": "SYNCED", "count": row_count})
        adapter.fetch_historical.assert_called_once_with(instrument, count=config.HISTORICAL_COUNT)
        self.assertEqual(adapter.method_calls, [call.fetch_historical(instrument, count=config.HISTORICAL_COUNT)])
        reconciled = [call.args[0] for call in store.reconcile.call_args_list]
        mismatched_candle = reconciled[mismatch_index]
        self.assertEqual(mismatched_candle.timestamp, mismatch_timestamp)
        store.existing_ohlc.assert_called_once_with(mismatched_candle)
        service._record_event.assert_called_once_with(
            "BROKER_MISMATCH",
            {
                "instrument": "NIFTY",
                "timestamp": mismatch_timestamp.isoformat(),
                "rest_ohlc": [103.0, 105.0, 102.0, 104.0, 1003],
                "local_ohlc": list(local_ohlc),
            },
            "reconciliation_events",
        )
        store.replace.assert_called_once_with(mismatched_candle)
        self.assertEqual(engine.seed.call_count, 1)
        seeded = engine.seed.call_args.args[0]
        self.assertIn(mismatched_candle, seeded)
        self.assertEqual(seeded, reconciled)
        self.assertEqual(seeded, sorted(seeded, key=lambda candle: candle.timestamp))
        self.assertTrue(all(candle.status == "FINAL" for candle in seeded))
        self.assertEqual(service.order_manager.method_calls, [])
        self.assertEqual(service.position_manager.method_calls, [])
        service._reconcile_intraday.assert_not_called()

    def test_backfill_index_rejects_duplicate_timestamp(self):
        rows = self._rows(2)
        rows[1][0] = rows[0][0]
        rows[1][1:] = [101, 103, 100, 102, 1001]
        service, instrument, adapter, store, engine = self._service(rows)

        with patch.object(config, "INTRADAY_RECONCILIATION_ENABLED", False):
            result = service._backfill_index(instrument)

        self.assertEqual(result["status"], "FAILED")
        self.assertIn("Duplicate historical candle timestamp", result["error"])
        adapter.fetch_historical.assert_called_once_with(instrument, count=config.HISTORICAL_COUNT)
        engine.seed.assert_not_called()

    def test_backfill_index_rejects_out_of_order_timestamp(self):
        rows = self._rows(3)
        rows[1], rows[2] = rows[2], rows[1]
        service, instrument, adapter, store, engine = self._service(rows)

        with patch.object(config, "INTRADAY_RECONCILIATION_ENABLED", False):
            result = service._backfill_index(instrument)

        self.assertEqual(result["status"], "FAILED")
        self.assertIn("not strictly chronological", result["error"])
        adapter.fetch_historical.assert_called_once_with(instrument, count=config.HISTORICAL_COUNT)
        engine.seed.assert_not_called()

    def test_backfill_index_rejects_insufficient_warmup(self):
        minimum_warmup = config.RSI_PERIOD + config.RSI_SMA_PERIOD + config.RSI_LOOKBACK_PERIODS
        rows = self._rows(minimum_warmup - 1)
        service, instrument, adapter, store, engine = self._service(rows)

        with patch.object(config, "INTRADAY_RECONCILIATION_ENABLED", False):
            result = service._backfill_index(instrument)

        self.assertEqual(result["status"], "FAILED")
        self.assertIn("Insufficient historical warm-up", result["error"])
        adapter.fetch_historical.assert_called_once_with(instrument, count=config.HISTORICAL_COUNT)
        self.assertEqual(store.reconcile.call_count, minimum_warmup - 1)
        engine.seed.assert_not_called()

    def test_backfill_index_historical_api_failure(self):
        api_error = RuntimeError("Upstox HTTP 503: historical service unavailable")
        service, instrument, adapter, store, engine = self._service(fetch_error=api_error)

        with patch.object(config, "INTRADAY_RECONCILIATION_ENABLED", False):
            result = service._backfill_index(instrument)

        self.assertEqual(result, {
            "instrument": "NIFTY",
            "status": "FAILED",
            "error": str(api_error),
        })
        adapter.fetch_historical.assert_called_once_with(instrument, count=config.HISTORICAL_COUNT)
        engine.seed.assert_not_called()
        self.assertEqual(service.order_manager.method_calls, [])
        self.assertEqual(service.position_manager.method_calls, [])


if __name__ == "__main__":
    unittest.main()
