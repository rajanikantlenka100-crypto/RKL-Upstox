"""Strict normalization of Upstox historical candle rows."""

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def parse_historical_row(row):
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        raise ValueError(f"Expected six historical fields, got {type(row).__name__} length {len(row) if hasattr(row, '__len__') else 'unknown'}")
    raw_timestamp = str(row[0]).replace("Z", "+00:00")
    try:
        timestamp = datetime.fromisoformat(raw_timestamp)
    except ValueError as error:
        raise ValueError(f"Invalid historical timestamp {row[0]!r}") from error
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=IST)
    timestamp = timestamp.astimezone(IST)
    try:
        open_price, high, low, close = (float(row[index]) for index in range(1, 5))
        volume = int(row[5] or 0)
    except (TypeError, ValueError, IndexError) as error:
        raise ValueError(f"Invalid historical OHLCV row {row!r}") from error
    if min(open_price, high, low, close) <= 0:
        raise ValueError(f"Historical OHLC must be positive: {row!r}")
    if high < max(open_price, close) or low > min(open_price, close):
        raise ValueError(f"Invalid historical OHLC geometry: {row!r}")
    if volume < 0:
        raise ValueError(f"Historical volume cannot be negative: {row!r}")
    return timestamp, open_price, high, low, close, volume
