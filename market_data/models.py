"""Broker-independent market data models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MarketTick:
    instrument: str
    token: str
    exchange: str
    timestamp: datetime
    ltp: float
    volume: int
    source: str
    exchange_timestamp: datetime | None = None
    received_timestamp: datetime | None = None
    sequence: int | None = None
    raw_event_id: str | None = None


@dataclass(frozen=True)
class Candle:
    instrument: str
    exchange: str
    token: str
    timestamp: datetime
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
    status: str = "FINAL"
