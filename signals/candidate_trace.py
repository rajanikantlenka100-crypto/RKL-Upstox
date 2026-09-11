"""Append-only, secret-free trace for breakout candidate decisions."""

import json
import threading
from datetime import datetime
from pathlib import Path


class CandidateTrace:
    def __init__(self, path, enabled=True):
        self.path = Path(path)
        self.enabled = enabled
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record):
        if not self.enabled:
            return
        payload = dict(record)
        payload["recorded_at"] = datetime.now().astimezone().isoformat()
        with self.lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, default=str) + "\n")