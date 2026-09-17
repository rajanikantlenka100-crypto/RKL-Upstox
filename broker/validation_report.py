"""Append-only report records for controlled real-broker validation."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from storage.retention import append_line
import config


class LiveBrokerValidationReport:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, values):
        values = dict(values)
        record = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "data_classification": values.pop("data_classification", "LOCAL SYSTEM DATA"),
            **values,
        }
        with self.lock:
            append_line(self.path, json.dumps(record, default=str, sort_keys=True) + "\n",
                        config.LOG_MAX_BYTES, config.LOG_BACKUP_COUNT)
        return record
