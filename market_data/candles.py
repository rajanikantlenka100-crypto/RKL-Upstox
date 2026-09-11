"""Exchange-timestamped 5-minute candle aggregation."""

from datetime import datetime

from market_data.models import Candle, MarketTick


class CandleEngine:
    def __init__(self, on_close=None):
        self.current = {}
        self.previous = {}
        self.prev2 = {}
        self.history = {}
        self.last_tick = {}
        self.on_close = on_close

    @staticmethod
    def bucket(timestamp: datetime):
        minute = timestamp.minute - timestamp.minute % 5
        return timestamp.replace(minute=minute, second=0, microsecond=0)

    def add(self, tick: MarketTick):
        if tick.ltp <= 0 or tick.timestamp.tzinfo is None:
            raise ValueError("Tick must have a positive LTP and timezone-aware timestamp")
        if tick.instrument in self.last_tick and tick.timestamp <= self.last_tick[tick.instrument]:
            return []
        self.last_tick[tick.instrument] = tick.timestamp
        start = self.bucket(tick.timestamp)
        current = self.current.get(tick.instrument)
        finalized = []
        if current and start > current["timestamp"]:
            candle = self._finalize(current)
            finalized.append(candle)
            if self.previous.get(tick.instrument) is not None:
                self.prev2[tick.instrument] = self.previous[tick.instrument]
            self.previous[tick.instrument] = candle
            self.history.setdefault(tick.instrument, []).append(candle)
            self.current.pop(tick.instrument)
            current = None
        if current is None:
            self.current[tick.instrument] = {
                "instrument": tick.instrument, "exchange": tick.exchange, "token": tick.token,
                "timestamp": start, "open": tick.ltp, "high": tick.ltp, "low": tick.ltp,
                "close": tick.ltp, "volume": tick.volume, "source": tick.source,
            }
        else:
            current["high"] = max(current["high"], tick.ltp)
            current["low"] = min(current["low"], tick.ltp)
            current["close"] = tick.ltp
            current["volume"] += max(0, tick.volume)
        for candle in finalized:
            if self.on_close:
                self.on_close(candle)
        return finalized

    def seed(self, candles):
        for candle in candles:
            history = self.history.setdefault(candle.instrument, [])
            if not any(existing.timestamp == candle.timestamp for existing in history):
                history.append(candle)
        for instrument, history in self.history.items():
            history.sort(key=lambda candle: candle.timestamp)
            if len(history) >= 2:
                self.prev2[instrument] = history[-2]
                self.previous[instrument] = history[-1]
            elif history:
                self.previous[instrument] = history[-1]

    def context(self, instrument):
        return {
            "prev2": self.prev2.get(instrument),
            "previous": self.previous.get(instrument),
            "running": self.current.get(instrument),
        }

    def restore_running(self, candle):
        if candle.status != "RUNNING":
            raise ValueError("Only RUNNING candles may be restored")
        self.current[candle.instrument] = {
            "instrument": candle.instrument, "exchange": candle.exchange, "token": candle.token,
            "timestamp": candle.timestamp, "open": candle.open, "high": candle.high,
            "low": candle.low, "close": candle.close, "volume": candle.volume,
            "source": candle.source,
        }
        self.last_tick[candle.instrument] = candle.timestamp

    def _finalize(self, data):
        if not (data["high"] >= data["open"] >= data["low"] and data["high"] >= data["close"] >= data["low"]):
            raise ValueError("Invalid OHLC candle")
        return Candle(timeframe="5m", **data)
