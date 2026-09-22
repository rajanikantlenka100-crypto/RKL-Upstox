"""Non-inferential observer contract mappings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

UNAVAILABLE = "UNAVAILABLE"
KNOWN_FILTER_RESULTS = {"PASS", "FAIL", UNAVAILABLE}


@dataclass
class SystemHealth:
    server_time_utc: str | None = None
    uptime_seconds: int | float | None = None
    execution_mode: str | None = None
    real_orders_enabled: bool | None = None
    market_open: bool | None = None
    feed_connected: bool | None = None
    database_healthy: bool | None = None
    history_sync: str | None = None
    preflight: str | None = None
    reconciliation: str | None = None
    heartbeat_age_seconds: int | float | None = None
    status: str | None = None


@dataclass
class MarketStatus:
    market_state: str | None = None
    timezone: str | None = None
    market_open_time: str | None = None
    market_close_time: str | None = None
    feed_connected: bool | None = None
    last_tick_received_at: str | None = None
    stale_data_seconds: int | float | None = None
    reason: str | None = None


@dataclass
class CandleState:
    symbol: str | None = None
    timeframe_minutes: int | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    exchange_timestamp: str | None = None
    received_timestamp: str | None = None
    is_final: bool | None = None
    quality: str | None = None
    reason: str | None = None


@dataclass
class IndicatorState:
    symbol: str | None = None
    sma8: float | None = None
    sma13: float | None = None
    sma21: float | None = None
    rsi14: float | None = None
    rsi_sma5: float | None = None
    rsi_sma14: float | None = None
    cci5: float | None = None
    stochastic14: float | None = None
    trend: str | None = None
    ready: bool | None = None
    reason: str | None = None
    timestamp: str | None = None


@dataclass
class FilterResult:
    name: str
    result: str = UNAVAILABLE
    comparison: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    timestamp: str | None = None


@dataclass
class SignalState:
    signal_id: str | None = None
    underlying: str | None = None
    signal_type: str | None = None
    direction: str | None = None
    status: str | None = None
    timestamp: str | None = None
    option: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    type1_conditions: dict[str, Any] = field(default_factory=dict)
    matched_signal_types: tuple = ()
    signal_lock_status: str | None = None
    rsi14: float | None = None
    rsi14_sma14: float | None = None
    entry_filter: str | None = None
    stochastic_values: tuple = ()
    option_details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalLifecycle:
    stage: str | None = None
    status: str | None = None
    updated_at: str | None = None
    reason: str | None = None


@dataclass
class OptionContractState:
    instrument_key: str | None = None
    symbol: str | None = None
    underlying: str | None = None
    expiry: str | None = None
    strike: float | None = None
    option_type: str | None = None
    ltp: float | None = None
    timestamp: str | None = None
    status: str | None = None
    reason: str | None = None


@dataclass
class OrderState:
    order_id: str | None = None
    instrument: str | None = None
    side: str | None = None
    quantity: int | None = None
    status: str | None = None
    average_price: float | None = None
    timestamp: str | None = None


@dataclass
class FillState:
    order_id: str | None = None
    fill_id: str | None = None
    instrument: str | None = None
    quantity: int | None = None
    average_price: float | None = None
    timestamp: str | None = None
    status: str | None = None


@dataclass
class PositionState:
    trade_id: str | None = None
    underlying: str | None = None
    option: str | None = None
    quantity: int | None = None
    entry_price: float | None = None
    current_ltp: float | None = None
    pnl: float | None = None
    state: str | None = None
    timestamp: str | None = None
    signal_id: str | None = None
    signal_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    entry_order_id: str | None = None
    entry_filter: str | None = None
    cci_exit_state: str | None = None
    strategy_exit: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExitState:
    trade_id: str | None = None
    exit_reason: str | None = None
    exit_price: float | None = None
    exit_timestamp: str | None = None
    status: str | None = None
    cci_state: str | None = None
    stochastic_state: str | None = None
    previous_stochastic: float | None = None
    stochastic_extreme: float | None = None
    reference_candle: dict[str, Any] | None = None


@dataclass
class IncidentState:
    incident_id: str | None = None
    component: str | None = None
    severity: str | None = None
    message: str | None = None
    timestamp: str | None = None


@dataclass
class DataQualityState:
    instrument: str | None = None
    quality: str | None = None
    last_tick_age_seconds: int | float | None = None
    last_candle_age_seconds: int | float | None = None
    reason: str | None = None


@dataclass
class ExecutionTimeline:
    step: str
    status: str | None = None
    timestamp: str | None = None
    details: str | None = None


@dataclass
class ReportSummary:
    report_date: str | None = None
    status: str | None = None
    total_events: int | None = None
    order_events: int | None = None
    issues: list[str] | None = None


def _value(mapping: dict[str, Any], key: str) -> Any:
    return mapping.get(key) if isinstance(mapping, dict) else None


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value if isinstance(value, str) else None


def _indicator_values(value: Any) -> tuple[Any, Any]:
    if isinstance(value, (list, tuple)):
        return (value[0] if len(value) > 0 else None, value[1] if len(value) > 1 else None)
    return None, None


def _timeframe_minutes(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.endswith("m"):
        try:
            return int(value[:-1])
        except ValueError:
            return None
    return None


def build_system_health(snapshot: dict[str, Any]) -> SystemHealth:
    source = _value(snapshot, "system_health") or {}
    return SystemHealth(**{field: _value(source, field) for field in SystemHealth.__dataclass_fields__})


def build_market_status(snapshot: dict[str, Any]) -> MarketStatus:
    source = _value(snapshot, "market_status")
    if isinstance(source, dict):
        return MarketStatus(**{field: _value(source, field) for field in MarketStatus.__dataclass_fields__})
    return MarketStatus(market_state=source if isinstance(source, str) else None)


def build_index_state(snapshot: dict[str, Any], symbol: str = "NIFTY") -> dict[str, Any]:
    source = _value(snapshot, "index_state") or {}
    if isinstance(source, dict) and isinstance(source.get(symbol), dict):
        return dict(source[symbol])
    latest = (_value(snapshot, "latest") or {}).get(symbol)
    running = (_value(snapshot, "candles") or {}).get(symbol)
    previous = (_value(snapshot, "previous") or {}).get(symbol)
    previous_previous = (_value(snapshot, "prev2") or {}).get(symbol)
    health = (_value(snapshot, "health") or {}).get(symbol)
    sync = (_value(snapshot, "sync") or {}).get(symbol)
    return {
        "symbol": symbol,
        "ltp": getattr(latest, "ltp", None),
        "timestamp": _iso(getattr(latest, "timestamp", None)),
        "exchange_timestamp": _iso(getattr(latest, "exchange_timestamp", None)),
        "received_timestamp": _iso(getattr(latest, "received_timestamp", None)),
        "source": getattr(latest, "source", None),
        "current_candle": build_candle_state(symbol, running).__dict__,
        "previous_candle": build_candle_state(symbol, previous).__dict__,
        "previous_previous_candle": build_candle_state(symbol, previous_previous).__dict__,
        "health": health,
        "sync": sync,
    }


def build_candle_state(symbol: str, candle: Any) -> CandleState:
    if candle is None:
        return CandleState(symbol=symbol, reason="CANDLE_NOT_AVAILABLE")
    status = getattr(candle, "status", None)
    return CandleState(
        symbol=symbol,
        timeframe_minutes=_timeframe_minutes(getattr(candle, "timeframe", None)),
        open=getattr(candle, "open", None), high=getattr(candle, "high", None),
        low=getattr(candle, "low", None), close=getattr(candle, "close", None),
        volume=getattr(candle, "volume", None),
        exchange_timestamp=_iso(getattr(candle, "timestamp", None)),
        received_timestamp=_iso(getattr(candle, "received_timestamp", None)),
        is_final=status == "FINAL" if status is not None else None,
        quality=getattr(candle, "quality", None),
    )


def build_indicator_state(symbol: str, snapshot: dict[str, Any]) -> IndicatorState:
    cci_value, rsi_value = _indicator_values((_value(snapshot, "indicators") or {}).get(symbol))
    source = _value(snapshot, "indicators") or {}
    sma8 = ((_value(snapshot, "sma8") or {}).get(symbol))
    sma13 = ((_value(snapshot, "sma13") or {}).get(symbol))
    sma21 = ((_value(snapshot, "sma21") or {}).get(symbol))
    rsi_sma5 = ((_value(snapshot, "rsi_sma5") or {}).get(symbol))
    return IndicatorState(
        symbol=symbol,
        sma8=sma8,
        sma13=sma13,
        sma21=sma21,
        rsi14=rsi_value,
        rsi_sma5=rsi_sma5,
        rsi_sma14=((_value(snapshot, "rsi_sma14") or {}).get(symbol)),
        cci5=cci_value,
        stochastic14=((_value(snapshot, "stochastic14") or {}).get(symbol)),
        trend=((_value(snapshot, "indicator_trend") or {}).get(symbol)),
        reason=(_value(snapshot, "indicator_reason") or {}).get(symbol),
        timestamp=_iso((_value(snapshot, "indicator_base") or {}).get(symbol)),
    )


def build_filter_result(name: str, result: str = UNAVAILABLE, comparison: str | None = None,
                        values: dict[str, Any] | None = None, reason: str | None = None,
                        timestamp: str | None = None) -> FilterResult:
    return FilterResult(name=name, result=result if result in KNOWN_FILTER_RESULTS else UNAVAILABLE,
                        comparison=comparison, values=dict(values or {}), reason=reason,
                        timestamp=timestamp)


def build_signal_state(snapshot: dict[str, Any]) -> SignalState:
    signal = _value(snapshot, "signal")
    return SignalState(
        signal_id=signal.get("signal_id"), underlying=signal.get("underlying"),
        signal_type=signal.get("signal_type"), direction=signal.get("direction"),
        status=signal.get("status"), timestamp=signal.get("timestamp"),
        option=signal.get("option"), filters=dict(signal.get("type2_conditions") or {}),
        type1_conditions=dict(signal.get("type1_conditions") or {}),
        matched_signal_types=tuple(signal.get("matched_signal_types") or ()),
        signal_lock_status=signal.get("signal_lock_status"),
        rsi14=signal.get("rsi14"), rsi14_sma14=signal.get("rsi14_sma14"),
        entry_filter=signal.get("entry_filter"),
        stochastic_values=tuple(signal.get("stochastic_values") or ()),
        option_details=dict(signal.get("option_details") or {}),
    ) if isinstance(signal, dict) else SignalState()


def build_signal_lifecycle(snapshot: dict[str, Any]) -> SignalLifecycle:
    signal = _value(snapshot, "signal")
    return SignalLifecycle(stage=signal.get("stage"), status=signal.get("status"),
                           updated_at=signal.get("updated_at"), reason=signal.get("reason")) if isinstance(signal, dict) else SignalLifecycle()


def build_option_contract_state(entry: dict[str, Any]) -> OptionContractState:
    return OptionContractState(
        instrument_key=entry.get("instrument_key"), symbol=entry.get("symbol"),
        underlying=entry.get("underlying"), expiry=entry.get("expiry"),
        strike=entry.get("strike"), option_type=entry.get("option_type"),
        ltp=entry.get("ltp"), timestamp=entry.get("timestamp"),
        status=entry.get("status"), reason=entry.get("reason"),
    ) if isinstance(entry, dict) else OptionContractState(reason="OPTION_CONTRACT_NOT_AVAILABLE")


def build_order_state(order: dict[str, Any]) -> OrderState | None:
    if not isinstance(order, dict):
        return None
    return OrderState(order_id=order.get("order_id"), instrument=order.get("instrument") or order.get("symbol"),
                      side=order.get("direction") or order.get("side"), quantity=order.get("quantity"),
                      status=order.get("status"), average_price=order.get("average_price"),
                      timestamp=order.get("timestamp"))


def build_fill_state(fill: dict[str, Any]) -> FillState | None:
    if not isinstance(fill, dict):
        return None
    return FillState(order_id=fill.get("order_id"), fill_id=fill.get("fill_id"),
                     instrument=fill.get("instrument") or fill.get("symbol"),
                     quantity=fill.get("filled_quantity"), average_price=fill.get("average_price"),
                     timestamp=fill.get("timestamp"), status=fill.get("status"))


def build_position_state(position: dict[str, Any]) -> PositionState:
    return PositionState(trade_id=position.get("trade_id"), underlying=position.get("index") or position.get("underlying"),
                         option=position.get("option") or position.get("symbol"), quantity=position.get("quantity"),
                         entry_price=position.get("entry_price"), current_ltp=position.get("current_ltp"),
                         pnl=position.get("pnl"), state=position.get("position_state") or position.get("state"),
                         timestamp=position.get("timestamp"), signal_id=position.get("signal_id"),
                         signal_type=position.get("signal_type"), strike=position.get("strike"),
                         expiry=position.get("expiry"), entry_order_id=position.get("order_id"),
                         entry_filter=position.get("entry_filter"),
                         cci_exit_state=position.get("cci_exit_state"),
                         strategy_exit=dict(position.get("strategy_exit") or {}))


def build_exit_state(position: dict[str, Any]) -> ExitState:
    strategy_exit = position.get("strategy_exit") or {}
    return ExitState(trade_id=position.get("trade_id"), exit_reason=position.get("exit_reason"),
                     exit_price=position.get("exit_price"), exit_timestamp=position.get("exit_timestamp"),
                     status=position.get("exit_status") or position.get("position_state"),
                     cci_state=strategy_exit.get("cci_state"),
                     stochastic_state=strategy_exit.get("stochastic_state"),
                     previous_stochastic=strategy_exit.get("previous_stochastic"),
                     stochastic_extreme=strategy_exit.get("stochastic_extreme"),
                     reference_candle=strategy_exit.get("reference_candle"))


def build_incident_state(event: dict[str, Any]) -> IncidentState | None:
    if not isinstance(event, dict):
        return None
    return IncidentState(incident_id=event.get("incident_id") or event.get("event_id"),
                         component=event.get("component"), severity=event.get("severity"),
                         message=event.get("message"), timestamp=event.get("timestamp"))


def build_data_quality_state(symbol: str, snapshot: dict[str, Any]) -> DataQualityState:
    source = (_value(snapshot, "data_quality") or {}).get(symbol)
    return DataQualityState(instrument=symbol, **source) if isinstance(source, dict) else DataQualityState(instrument=symbol, reason="DATA_QUALITY_NOT_EXPOSED_BY_BACKEND")


def build_execution_timeline(snapshot: dict[str, Any]) -> list[ExecutionTimeline]:
    source = _value(snapshot, "execution_timeline")
    return [ExecutionTimeline(**item) for item in source if isinstance(item, dict) and item.get("step")] if isinstance(source, list) else []


def build_report_summary(snapshot: dict[str, Any]) -> ReportSummary:
    source = _value(snapshot, "report_summary")
    return ReportSummary(**source) if isinstance(source, dict) else ReportSummary()


def build_ui_contracts(snapshot: dict[str, Any]) -> dict[str, Any]:
    names = _value(snapshot, "instrument_names") or []

    def records(key: str) -> list[dict[str, Any]]:
        value = _value(snapshot, key)
        return value if isinstance(value, list) else []

    orders = [state.__dict__ for state in (build_order_state(item) for item in records("orders")) if state is not None]
    fills = [state.__dict__ for state in (build_fill_state(item) for item in records("fills")) if state is not None]
    incidents = [state.__dict__ for state in (build_incident_state(item) for item in records("incidents")) if state is not None]
    system_health = build_system_health(snapshot).__dict__
    system_health.update({
        "components": _value(snapshot, "components"),
        "startup_phase": _value(snapshot, "startup_phase"),
        "ws_status": _value(snapshot, "ws_status"),
        "last_event": _value(snapshot, "last_event"),
        "reconnects": _value(snapshot, "reconnects"),
    })
    return {
        "SystemHealth": system_health,
        "MarketStatus": build_market_status(snapshot).__dict__,
        "IndexState": {name: build_index_state(snapshot, name) for name in names},
        "CandleState": {name: build_candle_state(name, (_value(snapshot, "candles") or {}).get(name)).__dict__ for name in names},
        "IndicatorState": {name: build_indicator_state(name, snapshot).__dict__ for name in names},
        "FilterResult": [build_filter_result(item.get("name", "UNKNOWN"), item.get("result", UNAVAILABLE), item.get("comparison"), item.get("values"), item.get("reason"), item.get("timestamp")) for item in records("filter_results")],
        "SignalState": build_signal_state(snapshot).__dict__,
        "SignalHistory": records("signal_history"),
        "SignalQueue": records("signal_queue"),
        "SignalLifecycle": build_signal_lifecycle(snapshot).__dict__,
        "OptionContractState": [build_option_contract_state(item).__dict__ for item in records("selected_options")],
        "OptionUniverse": [build_option_contract_state(item).__dict__ for item in (_value(snapshot, "option_universe") or {}).values() if isinstance(item, dict)],
        "OrderState": orders,
        "FillState": fills,
        "PositionState": [build_position_state(item).__dict__ for item in records("position_details")],
        "ExitState": [build_exit_state(item).__dict__ for item in records("position_details")
                  if isinstance(item, dict) and (item.get("strategy_exit") or item.get("exit_reason"))],
        "IncidentState": incidents,
        "DataQualityState": {name: build_data_quality_state(name, snapshot).__dict__ for name in names},
        "ExecutionTimeline": [item.__dict__ for item in build_execution_timeline(snapshot)],
        "ReportSummary": build_report_summary(snapshot).__dict__,
        "StorageMetrics": dict(_value(snapshot, "storage") or {}),
    }


def build_observer_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical observer projection for a backend snapshot."""
    return build_ui_contracts(snapshot)


def build_observer_envelope(*, payload: dict[str, Any], sequence: int,
                            event_type: str, server_time: str,
                            source_timestamp: str | None = None,
                            stale: bool | None = None,
                            stale_reason: str | None = None,
                            state_version: str | int | None = None) -> dict[str, Any]:
    """Build an envelope using caller-supplied transport/source timestamps."""
    return {
        "protocol": "rkl.observer.v1",
        "state_version": state_version,
        "sequence": sequence,
        "event_type": event_type,
        "server_time": server_time,
        "source_timestamp": source_timestamp,
        "stale": stale,
        "stale_reason": stale_reason,
        "payload": payload,
    }
