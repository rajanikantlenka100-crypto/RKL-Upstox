"""Indicators calculated only from completed index candles."""


def sma(candles, period=8):
    values = sma_series(candles, period)
    return values[-1] if values else None


def sma_series(candles, period=8):
    """Return finalized close-price SMA values aligned to the candle index."""
    if period <= 0:
        raise ValueError("SMA period must be positive")
    result = [None] * len(candles)
    for index in range(len(candles)):
        if index < period - 1:
            continue
        window = [candle.close for candle in candles[index - period + 1:index + 1]]
        if len(window) != period or any(candle.status != "FINAL" for candle in candles[index - period + 1:index + 1]):
            continue
        result[index] = sum(window) / period
    return result


def validate_sma_trend(candles, direction, periods=(8, 13, 21)):
    """Strict finalized-candle trend gate for call/put signals.

    CALL requires SMA8 > SMA13 > SMA21.
    PUT requires SMA8 < SMA13 < SMA21.
    Equality and insufficient data are rejected as unavailable instead of being treated as valid.
    """
    if direction not in {"CALL", "PUT"}:
        raise ValueError(f"Unsupported SMA trend direction: {direction}")
    if len(candles) < max(periods):
        return {"direction": direction, "result": "UNAVAILABLE", "reason": "Insufficient finalized candles for SMA trend"}
    if any(candle.status != "FINAL" for candle in candles):
        return {"direction": direction, "result": "UNAVAILABLE", "reason": "SMA trend uses finalized candles only"}
    values = {period: sma_series(candles, period)[-1] for period in periods}
    if any(value is None for value in values.values()):
        return {"direction": direction, "result": "UNAVAILABLE", "reason": "Insufficient SMA history", "values": values}
    s8, s13, s21 = values[8], values[13], values[21]
    bullish = s8 > s13 > s21
    bearish = s8 < s13 < s21
    if direction == "CALL":
        if bullish:
            return {"direction": direction, "result": "PASS", "reason": "SMA8 > SMA13 > SMA21", "values": values}
        if bearish:
            return {"direction": direction, "result": "BLOCKED", "reason": "CALL blocked when bearish SMA ordering is present", "values": values}
        return {"direction": direction, "result": "UNAVAILABLE", "reason": "SMA equality or non-strict ordering", "values": values}
    if bearish:
        return {"direction": direction, "result": "PASS", "reason": "SMA8 < SMA13 < SMA21", "values": values}
    if bullish:
        return {"direction": direction, "result": "BLOCKED", "reason": "PUT blocked when bullish SMA ordering is present", "values": values}
    return {"direction": direction, "result": "UNAVAILABLE", "reason": "SMA equality or non-strict ordering", "values": values}


def fast_stochastic_series(candles, period=14):
    """Return closed-candle Fast Stochastic %K values aligned to candles."""
    if period <= 0:
        raise ValueError("Stochastic period must be positive")
    result = [None] * len(candles)
    for index in range(period - 1, len(candles)):
        window = candles[index - period + 1:index + 1]
        if any(candle.status != "FINAL" for candle in window):
            continue
        lowest = min(candle.low for candle in window)
        highest = max(candle.high for candle in window)
        if highest == lowest:
            result[index] = None
            continue
        result[index] = 100.0 * (candles[index].close - lowest) / (highest - lowest)
    return result


def fast_stochastic(candles, period=14):
    values = fast_stochastic_series(candles, period)
    return values[-1] if values else None


def stochastic_entry_exception(candles, direction, period=14, lookback=5):
    """Return an entry-only SMA exception from the latest closed candles."""
    if direction not in {"CALL", "PUT"}:
        raise ValueError(f"Unsupported stochastic exception direction: {direction}")
    values = fast_stochastic_series(candles, period)
    recent = tuple(value for value in values[-lookback:] if value is not None)
    threshold = 10.0 if direction == "CALL" else 90.0
    matches = tuple(value for value in recent if value < threshold) if direction == "CALL" else tuple(value for value in recent if value > threshold)
    return {
        "allowed": bool(matches),
        "direction": direction,
        "values": recent,
        "matching_values": matches,
        "threshold": threshold,
        "reason": "STOCHASTIC_EXCEPTION" if matches else "NO_STOCHASTIC_EXCEPTION",
    }


def cci(candles, period=5):
    if len(candles) < period:
        return None
    typical = [(item.high + item.low + item.close) / 3 for item in candles[-period:]]
    mean = sum(typical) / period
    deviation = sum(abs(value - mean) for value in typical) / period
    return 0.0 if deviation == 0 else (typical[-1] - mean) / (0.015 * deviation)


def rsi(candles, period=14):
    values = rsi_series(candles, period)
    return values[-1] if values else None


def rsi_series(candles, period=14):
    """Return Wilder RSI values aligned to candle timestamps without look-ahead."""
    if len(candles) <= period:
        return [None] * len(candles)
    changes = [candles[index].close - candles[index - 1].close for index in range(1, len(candles))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    result = [None] * (period + 1)

    def value():
        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0
        return 100.0 - (100.0 / (1.0 + average_gain / average_loss))

    result[period] = value()
    for index in range(period, len(gains)):
        average_gain = ((average_gain * (period - 1)) + gains[index]) / period
        average_loss = ((average_loss * (period - 1)) + losses[index]) / period
        result.append(value())
    return result


def rsi_sma_series(candles, rsi_period=14, sma_period=5):
    """Return aligned SMA values of the RSI series, without lookahead."""
    values = rsi_series(candles, rsi_period)
    result = []
    for index in range(len(values)):
        window = values[index - sma_period + 1:index + 1]
        result.append(sum(window) / sma_period if len(window) == sma_period and all(value is not None for value in window) else None)
    return result
