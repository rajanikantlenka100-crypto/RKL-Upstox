"""Per-index feed freshness and signal eligibility."""

from datetime import datetime, timedelta, timezone


class FeedHealth:
    def __init__(self, stale_after_seconds=15):
        self.stale_after = timedelta(seconds=stale_after_seconds)
        self.last_tick = {}
        self.status = {}

    def update(self, instrument, timestamp):
        if timestamp > datetime.now(timestamp.tzinfo).astimezone(timestamp.tzinfo):
            self.status[instrument] = "DATA_UNSAFE"
            return
        self.last_tick[instrument] = timestamp
        self.status[instrument] = "LIVE"

    def check(self, instrument, now=None):
        now = now or datetime.now(timezone.utc)
        timestamp = self.last_tick.get(instrument)
        if timestamp is not None:
            timestamp = timestamp.astimezone(timezone.utc)
        if timestamp is None or now - timestamp > self.stale_after:
            self.status[instrument] = "DATA_STALE"
        return self.status.get(instrument, "WAITING")

    def can_signal(self, instrument, now=None):
        return self.check(instrument, now) == "LIVE"

    def diagnostics(self, instrument, now=None):
        now = now or datetime.now(timezone.utc)
        timestamp = self.last_tick.get(instrument)
        age = None if timestamp is None else (now - timestamp.astimezone(timezone.utc)).total_seconds()
        return {"instrument": instrument, "last_tick_time": timestamp,
                "current_time": now, "age_seconds": age,
                "status": self.check(instrument, now)}
