"""Append-only, secret-free signal audit records for review."""

import json
import threading
from datetime import datetime
from pathlib import Path
from storage.retention import append_line
import config


class SignalAudit:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record):
        payload = dict(record)
        payload["updated_at"] = datetime.now().astimezone().isoformat()
        with self.lock:
            append_line(self.path, json.dumps(payload, default=str) + "\n",
                        config.LOG_MAX_BYTES, config.LOG_BACKUP_COUNT)

    def report(self):
        if not self.path.exists():
            return "SIGNAL AUDIT\nNo signals recorded."
        records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        sections = []
        for record in records:
            sections.append("\n".join([
                "SIGNAL AUDIT", "-" * 28,
                f"Signal ID: {record.get('signal_id', '--')}",
                f"Time: {record.get('created_at', '--')}",
                f"Instrument: {record.get('instrument', '--')}  Direction: {record.get('direction', '--')}  Priority: {record.get('priority', '--')}",
                f"Running OHLC: {record.get('running_ohlc', '--')}",
                f"Previous OHLC: {record.get('previous_ohlc', '--')}",
                f"Breakout: {record.get('breakout_condition', '--')} => {record.get('breakout_result', '--')}",
                f"CCI(5): {record.get('cci', '--')}  RSI(14): {record.get('rsi', '--')}",
                f"Option: {record.get('option_symbol', '--')} token={record.get('option_token', '--')} LTP={record.get('option_ltp', '--')}",
                f"SL: {record.get('sl', '--')}  Quantity: {record.get('quantity', '--')}  Risk: {record.get('risk', '--')}",
                f"Lifecycle: {record.get('status', '--')}  Approval: {record.get('approval', '--')}  Order: {record.get('order_id', '--')}",
            ]))
        return "\n\n".join(sections)
