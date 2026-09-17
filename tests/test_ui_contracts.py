import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from ui_contracts import (
    UNAVAILABLE,
    build_candle_state,
    build_exit_state,
    build_filter_result,
    build_indicator_state,
    build_incident_state,
    build_option_contract_state,
    build_report_summary,
    build_ui_contracts,
)


class UiContractsTests(unittest.TestCase):
    def test_empty_snapshot_does_not_fabricate_health_or_timestamps(self):
        contracts = build_ui_contracts({"instrument_names": ["NIFTY"]})
        health = contracts["SystemHealth"]
        self.assertIsNone(health["uptime_seconds"])
        self.assertIsNone(health["heartbeat_age_seconds"])
        self.assertIsNone(health["status"])
        self.assertEqual(contracts["ExecutionTimeline"], [])
        self.assertIsNone(contracts["ReportSummary"]["status"])

    def test_missing_indicator_values_remain_unavailable(self):
        indicator = build_indicator_state("NIFTY", {"indicators": {}})
        self.assertIsNone(indicator.sma8)
        self.assertIsNone(indicator.sma13)
        self.assertIsNone(indicator.sma21)
        self.assertIsNone(indicator.rsi_sma5)
        self.assertIsNone(indicator.trend)
        self.assertIsNone(indicator.ready)
        self.assertIsNone(indicator.timestamp)

    def test_source_backed_indicator_fields_are_exposed_when_present(self):
        indicator = build_indicator_state(
            "NIFTY",
            {
                "indicators": {"NIFTY": (78.5, 51.2)},
                "indicator_reason": {"NIFTY": "LIVE"},
                "indicator_base": {"NIFTY": datetime(2026, 9, 16, tzinfo=timezone.utc)},
                "sma8": {"NIFTY": 104.2},
                "sma13": {"NIFTY": 103.8},
                "sma21": {"NIFTY": 102.9},
                "rsi_sma5": {"NIFTY": 57.4},
            },
        )
        self.assertEqual(indicator.sma8, 104.2)
        self.assertEqual(indicator.sma13, 103.8)
        self.assertEqual(indicator.sma21, 102.9)
        self.assertEqual(indicator.rsi_sma5, 57.4)
        self.assertEqual(indicator.cci5, 78.5)
        self.assertEqual(indicator.rsi14, 51.2)

    def test_supplied_cci_and_rsi_are_mapped_without_inference(self):
        indicator = build_indicator_state(
            "NIFTY",
            {
                "indicators": {"NIFTY": (78.5, 51.2)},
                "indicator_reason": {"NIFTY": "LIVE"},
                "indicator_base": {"NIFTY": datetime(2026, 9, 16, tzinfo=timezone.utc)},
            },
        )
        self.assertEqual(indicator.cci5, 78.5)
        self.assertEqual(indicator.rsi14, 51.2)
        self.assertIsNone(indicator.trend)
        self.assertIsNone(indicator.ready)
        self.assertEqual(indicator.timestamp, "2026-09-16T00:00:00+00:00")

    def test_missing_filter_is_unavailable_without_values(self):
        result = build_filter_result("SMA_TREND")
        self.assertEqual(result.result, UNAVAILABLE)
        self.assertEqual(result.values, {})
        self.assertIsNone(result.timestamp)

    def test_invalid_filter_result_is_not_accepted(self):
        result = build_filter_result("RSI", "READY", values={"rsi": 50})
        self.assertEqual(result.result, UNAVAILABLE)
        self.assertEqual(result.values, {"rsi": 50})

    def test_missing_structured_records_are_not_created(self):
        contracts = build_ui_contracts({"orders": ["ORDER-1 FILLED"], "events": ["ORDER-1 FILLED"]})
        self.assertEqual(contracts["OrderState"], [])
        self.assertEqual(contracts["FillState"], [])
        self.assertEqual(contracts["IncidentState"], [])

    def test_option_universe_does_not_imply_selection(self):
        contracts = build_ui_contracts({
            "option_universe": {"TOKEN": {"instrument_key": "TOKEN", "strike": 24000}},
        })
        self.assertEqual(contracts["OptionContractState"], [])
        contract = build_option_contract_state({"instrument_key": "TOKEN", "strike": 24000})
        self.assertIsNone(contract.status)
        self.assertIsNone(contract.timestamp)

    def test_exit_is_not_created_from_position_details(self):
        contracts = build_ui_contracts({"position_details": [{"trade_id": "T1", "position_state": "OPEN"}]})
        self.assertEqual(contracts["ExitState"], [])

    def test_dashboard_contract_preserves_signal_and_position_exit_context(self):
        contracts = build_ui_contracts({
            "instrument_names": ["NIFTY"],
            "signal": {
                "signal_id": "S1", "underlying": "NIFTY", "signal_type": "TYPE_2",
                "direction": "CALL", "entry_filter": "stochastic_exception",
                "stochastic_values": (8.0, 12.0),
            },
            "position_details": [{
                "trade_id": "T1", "index": "NIFTY", "position_state": "OPEN",
                "strategy_exit": {
                    "stochastic_state": "ARMED", "previous_stochastic": 93.0,
                    "stochastic_extreme": 96.0,
                },
            }],
        })
        self.assertEqual(contracts["SignalState"]["entry_filter"], "stochastic_exception")
        self.assertEqual(contracts["SignalState"]["stochastic_values"], (8.0, 12.0))
        self.assertEqual(contracts["PositionState"][0]["strategy_exit"]["stochastic_state"], "ARMED")
        self.assertEqual(contracts["ExitState"][0]["previous_stochastic"], 93.0)
        exit_state = build_exit_state({"trade_id": "T1"})
        self.assertIsNone(exit_state.status)
        self.assertIsNone(exit_state.exit_timestamp)

    def test_incident_requires_structured_source(self):
        self.assertIsNone(build_incident_state("display event"))
        incident = build_incident_state({"event_id": "E1", "component": "SYSTEM", "severity": "ERROR"})
        self.assertEqual(incident.incident_id, "E1")
        self.assertIsNone(incident.timestamp)

    def test_candle_timestamp_only_comes_from_source(self):
        candle = build_candle_state("NIFTY", SimpleNamespace(
            timeframe="5m", open=1, high=2, low=0, close=1.5, volume=10,
            timestamp=datetime(2026, 9, 16, tzinfo=timezone.utc), status="FINAL",
        ))
        self.assertEqual(candle.exchange_timestamp, "2026-09-16T00:00:00+00:00")
        self.assertIsNone(candle.received_timestamp)
        self.assertEqual(candle.is_final, True)

    def test_candle_contract_preserves_five_minute_source_only(self):
        candle = build_candle_state("NIFTY", SimpleNamespace(
            timeframe="5m", open=100, high=105, low=99, close=104, volume=20,
            timestamp="2026-09-16T10:30:00+05:30", status="RUNNING",
        ))
        self.assertEqual(candle.timeframe_minutes, 5)
        self.assertIsNone(candle.received_timestamp)
        self.assertEqual(candle.is_final, False)
        self.assertFalse(hasattr(candle, "three_minute"))

    def test_report_without_authoritative_source_is_unavailable(self):
        report = build_report_summary({"events": ["something happened"]})
        self.assertIsNone(report.status)
        self.assertIsNone(report.report_date)
        self.assertIsNone(report.total_events)


if __name__ == "__main__":
    unittest.main()
