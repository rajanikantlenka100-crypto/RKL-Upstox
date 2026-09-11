"""Priority queue for human-approved signals."""

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta

_PRIORITY = {"NIFTY": 0, "SENSEX": 1, "BANKNIFTY": 2, "MIDCPNIFTY": 3}


@dataclass(order=True)
class QueuedSignal:
    priority: tuple = field(init=False)
    signal: object = field(compare=False)
    created_at: datetime = field(compare=False)
    status: str = field(default="WAITING", compare=False)

    def __post_init__(self):
        self.priority = (_PRIORITY.get(self.signal.underlying, 99), self.created_at, self.signal.signal_id)


class SignalQueue:
    def __init__(self, expiry_minutes=5):
        self.items = []
        self.expiry = timedelta(minutes=expiry_minutes)

    def add(self, signal):
        heapq.heappush(self.items, QueuedSignal(signal, datetime.now(signal.timestamp.tzinfo)))

    def next(self):
        now = datetime.now().astimezone()
        while self.items:
            item = heapq.heappop(self.items)
            if now - item.created_at > self.expiry:
                item.status = "EXPIRED"
                continue
            item.status = "ACTIVE"
            return item
        return None
