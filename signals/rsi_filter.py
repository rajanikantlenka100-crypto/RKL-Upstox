"""Closed-candle RSI(14)/RSI-SMA(14) entry validation."""

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


def validate_rsi_entry(candles, direction, rsi_period=14, sma_period=14, lookback_periods=1):
    """Evaluate only the latest finalized RSI14/RSI14-SMA14 pair."""
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

    minimum_history = rsi_period + sma_period
    if len(candles) < minimum_history:
        return RSIFilterResult(direction, "UNAVAILABLE", 1, 0,
                               evaluated_candle_timestamps=tuple(candle.timestamp for candle in candles),
                               reason="Insufficient RSI14 or RSI14 SMA14 history")

    rsi_values = rsi_series(candles, rsi_period)
    sma_values = rsi_sma_series(candles, rsi_period, sma_period)
    candle = candles[-1]
    rsi_value = rsi_values[-1] if rsi_values else None
    sma_value = sma_values[-1] if sma_values else None
    if rsi_value is None or sma_value is None:
        return RSIFilterResult(direction, "UNAVAILABLE", 1, 0,
                               evaluated_candle_timestamps=(candle.timestamp,),
                               evaluated_rsi_values=(rsi_value,),
                               evaluated_sma_values=(sma_value,),
                               reason="Latest finalized candle has no RSI14 or RSI14 SMA14")

    matches = [(candle, rsi_value, sma_value)] if (
        rsi_value > sma_value if direction == "CALL" else rsi_value < sma_value
    ) else []
    matching_timestamps = tuple(candle.timestamp for candle, _, _ in matches)
    matching_rsi = tuple(rsi_value for _, rsi_value, _ in matches)
    matching_sma = tuple(sma_value for _, _, sma_value in matches)
    status = "PASS" if matches else "REJECT"
    comparison = "RSI14 > RSI14 SMA14" if direction == "CALL" else "RSI14 < RSI14 SMA14"
    reason = f"Latest finalized period satisfied {comparison}" if matches else f"Latest finalized period did not satisfy {comparison}"
    return RSIFilterResult(direction, status, 1, len(matches),
                           matching_timestamps, matching_rsi, matching_sma,
                           (candle.timestamp,), (rsi_value,), (sma_value,), reason)