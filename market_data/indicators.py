"""Indicators calculated only from completed index candles."""


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
