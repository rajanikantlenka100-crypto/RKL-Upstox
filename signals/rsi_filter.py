"""Closed-candle RSI(14)/RSI-SMA(5) entry validation."""

from dataclasses import dataclass

from market_data.indicators import rsi_series, rsi_sma_series


@dataclass(frozen=True)
class RSIFilterResult:
    direction: str
    result: str
    lookback_periods: int
    matching_periods: int
    matching_candle_timestamps: tuple = ()
    matching_rsi_values: tuple = ()
    matching_sma_values: tuple = ()
    evaluated_candle_timestamps: tuple = ()
    evaluated_rsi_values: tuple = ()
    evaluated_sma_values: tuple = ()
    reason: str = ""


def validate_rsi_entry(candles, direction, rsi_period=14, sma_period=5, lookback_periods=5):
    """Evaluate exactly the last finalized candles, never a running candle."""
    if direction not in {"CALL", "PUT"}:
        raise ValueError(f"Unsupported RSI filter direction: {direction}")

    candles = list(candles)
    timestamps = [candle.timestamp for candle in candles]
    if any(candle.status != "FINAL" for candle in candles):
        return RSIFilterResult(direction, "UNAVAILABLE", lookback_periods, 0,
                               reason="Candle history contains a non-final candle")
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        return RSIFilterResult(direction, "UNAVAILABLE", lookback_periods, 0,
                               reason="Candle history is not unique and chronological")

    evaluated = candles[-lookback_periods:]
    evaluated_timestamps = tuple(candle.timestamp for candle in evaluated)
    if len(evaluated) != lookback_periods:
        return RSIFilterResult(direction, "UNAVAILABLE", lookback_periods, 0,
                               evaluated_candle_timestamps=evaluated_timestamps,
                               reason="Insufficient closed-candle lookback")

    rsi_values = rsi_series(candles, rsi_period)
    sma_values = rsi_sma_series(candles, rsi_period, sma_period)
    offset = len(candles) - lookback_periods
    pairs = [(candles[index], rsi_values[index], sma_values[index])
             for index in range(offset, len(candles))]
    if any(rsi_value is None or sma_value is None for _, rsi_value, sma_value in pairs):
        return RSIFilterResult(direction, "UNAVAILABLE", lookback_periods, 0,
                               evaluated_candle_timestamps=evaluated_timestamps,
                               evaluated_rsi_values=tuple(rsi_value for _, rsi_value, _ in pairs),
                               evaluated_sma_values=tuple(sma_value for _, _, sma_value in pairs),
                               reason="Insufficient RSI14 or RSI14 SMA5 history")

    matches = [
        (candle, rsi_value, sma_value)
        for candle, rsi_value, sma_value in pairs
        if (rsi_value < sma_value if direction == "CALL" else rsi_value > sma_value)
    ]
    matching_timestamps = tuple(candle.timestamp for candle, _, _ in matches)
    matching_rsi = tuple(rsi_value for _, rsi_value, _ in matches)
    matching_sma = tuple(sma_value for _, _, sma_value in matches)
    evaluated_rsi = tuple(rsi_value for _, rsi_value, _ in pairs)
    evaluated_sma = tuple(sma_value for _, _, sma_value in pairs)
    status = "PASS" if matches else "REJECT"
    comparison = "RSI14 < RSI14 SMA5" if direction == "CALL" else "RSI14 > RSI14 SMA5"
    reason = f"{len(matches)} of {lookback_periods} closed periods satisfied {comparison}"
    return RSIFilterResult(direction, status, lookback_periods, len(matches),
                           matching_timestamps, matching_rsi, matching_sma,
                           evaluated_timestamps, evaluated_rsi, evaluated_sma, reason)