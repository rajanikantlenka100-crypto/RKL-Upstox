"""SQLite persistence for finalized real candles."""

import sqlite3
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from market_data.models import Candle


class CandleStore:
    def __init__(self, path: Path, mode=None):
        self.lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if mode:
            existing_mode = self.connection.execute(
                "SELECT value FROM runtime_metadata WHERE key = 'execution_mode'"
            ).fetchone()
            if existing_mode and existing_mode[0] != mode:
                self.connection.close()
                raise RuntimeError(
                    f"Database execution mode mismatch: {existing_mode[0]} != {mode}"
                )
            self.connection.execute(
                "INSERT OR REPLACE INTO runtime_metadata (key, value) VALUES ('execution_mode', ?)",
                (mode,),
            )
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                instrument TEXT NOT NULL,
                exchange TEXT NOT NULL,
                token TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                candle_end TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (instrument, timestamp, timeframe)
            )
        """)
        for table, columns in {
            "signals": "signal_id TEXT PRIMARY KEY, instrument TEXT, direction TEXT, status TEXT, created_at TEXT, payload TEXT",
            "approvals": "approval_id TEXT PRIMARY KEY, signal_id TEXT, decision TEXT, created_at TEXT, payload TEXT",
            "orders": "order_id TEXT PRIMARY KEY, signal_id TEXT, trade_id TEXT, status TEXT, created_at TEXT, payload TEXT",
            "fills": "fill_id TEXT PRIMARY KEY, order_id TEXT, trade_id TEXT, quantity INTEGER, average_price REAL, created_at TEXT, payload TEXT",
            "stop_losses": "sl_order_id TEXT PRIMARY KEY, trade_id TEXT, status TEXT, created_at TEXT, payload TEXT",
            "positions": "trade_id TEXT PRIMARY KEY, order_id TEXT, sl_order_id TEXT, state TEXT, created_at TEXT, payload TEXT",
            "exits": "exit_id TEXT PRIMARY KEY, trade_id TEXT, status TEXT, created_at TEXT, payload TEXT",
            "errors": "error_id TEXT PRIMARY KEY, category TEXT, created_at TEXT, payload TEXT",
            "reconciliation_events": "event_id TEXT PRIMARY KEY, entity_type TEXT, entity_id TEXT, action TEXT, created_at TEXT, payload TEXT",
            "signal_events": "event_id TEXT PRIMARY KEY, signal_id TEXT, event_type TEXT, created_at TEXT, payload TEXT",
            "position_events": "event_id TEXT PRIMARY KEY, trade_id TEXT, event_type TEXT, created_at TEXT, payload TEXT",
            "stop_orders": "stop_order_id TEXT PRIMARY KEY, trade_id TEXT, status TEXT, created_at TEXT, payload TEXT",
            "system_events": "event_id TEXT PRIMARY KEY, event_type TEXT, created_at TEXT, payload TEXT",
            "order_requests": "request_id TEXT PRIMARY KEY, signal_id TEXT, position_id TEXT, order_type TEXT, symbol TEXT, token TEXT, quantity INTEGER, created_at TEXT, broker_order_id TEXT, state TEXT, payload TEXT",
            "raw_market_events": "event_id TEXT PRIMARY KEY, instrument_key TEXT, exchange TEXT, exchange_timestamp TEXT, received_timestamp TEXT, ltp REAL, volume INTEGER, source TEXT, sequence INTEGER, payload TEXT",
            "telemetry_events": "event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, severity TEXT NOT NULL, component TEXT NOT NULL, event_type TEXT NOT NULL, message TEXT, exception TEXT, system_state TEXT, recovery_action TEXT, resolution TEXT, payload TEXT",
            "daily_reports": "report_date TEXT PRIMARY KEY, generated_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT",
        }.items():
            self.connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(candles)")}
        if "candle_end" not in columns:
            self.connection.execute("ALTER TABLE candles ADD COLUMN candle_end TEXT NOT NULL DEFAULT ''")
        if "status" not in columns:
            self.connection.execute("ALTER TABLE candles ADD COLUMN status TEXT NOT NULL DEFAULT 'FINAL'")
        for table, additions in {
            "signals": {
                "signal_type": "TEXT NOT NULL DEFAULT 'TYPE_1'",
                "underlying": "TEXT",
            },
            "positions": {
                "signal_id": "TEXT",
                "signal_type": "TEXT NOT NULL DEFAULT 'TYPE_1'",
                "underlying": "TEXT",
                "direction": "TEXT",
                "instrument_key": "TEXT",
                "expiry": "TEXT",
                "strike": "REAL",
                "quantity": "INTEGER",
                "entry_price": "REAL",
                "initial_sl": "REAL",
                "initial_risk": "REAL",
                "exit_state": "TEXT",
                "exit_reason": "TEXT",
                "exit_arm_timestamp": "TEXT",
                "exit_arm_candle": "TEXT",
                "exit_confirmation_candle": "TEXT",
            },
        }.items():
            existing = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            for name, definition in additions.items():
                if name not in existing:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        self.connection.commit()

    def is_healthy(self):
        with self.lock:
            result = self.connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                return False
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.rollback()
        return True

    def maintenance(self, *, raw_market_retention_days, telemetry_retention_days,
                    raw_market_max_rows=None, telemetry_max_rows=None):
        """Bound high-volume operational tables and checkpoint the WAL."""
        raw_cutoff = (datetime.now(timezone.utc) - timedelta(days=raw_market_retention_days)).isoformat()
        telemetry_cutoff = (datetime.now(timezone.utc) - timedelta(days=telemetry_retention_days)).isoformat()
        with self.lock:
            self.connection.execute(
                "DELETE FROM raw_market_events WHERE datetime(received_timestamp) < datetime(?)", (raw_cutoff,)
            )
            self.connection.execute(
                "DELETE FROM telemetry_events WHERE datetime(timestamp) < datetime(?)", (telemetry_cutoff,)
            )
            if raw_market_max_rows:
                self.connection.execute(
                    "DELETE FROM raw_market_events WHERE rowid NOT IN "
                    "(SELECT rowid FROM raw_market_events ORDER BY received_timestamp DESC LIMIT ?)",
                    (raw_market_max_rows,),
                )
            if telemetry_max_rows:
                self.connection.execute(
                    "DELETE FROM telemetry_events WHERE rowid NOT IN "
                    "(SELECT rowid FROM telemetry_events ORDER BY timestamp DESC LIMIT ?)",
                    (telemetry_max_rows,),
                )
            self.connection.commit()
            self.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def storage_metrics(self):
        with self.lock:
            database_path = Path(self.connection.execute("PRAGMA database_list").fetchone()[2])
            wal_path = Path(f"{database_path}-wal")
            shm_path = Path(f"{database_path}-shm")
            return {
                "database_bytes": database_path.stat().st_size if database_path.exists() else 0,
                "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
                "shm_bytes": shm_path.stat().st_size if shm_path.exists() else 0,
            }
    def save(self, candle: Candle):
                with self.lock:
                        self.connection.execute("""
                                INSERT OR IGNORE INTO candles
                                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """, (candle.instrument, candle.exchange, candle.token, candle.timestamp.isoformat(),
                                                                    (candle.timestamp + timedelta(minutes=5)).isoformat(), candle.timeframe, candle.open, candle.high, candle.low,
                                                                candle.close, candle.volume, candle.source, candle.status))
                        self.connection.commit()

    def save_running(self, candle: Candle):
        with self.lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (candle.instrument, candle.exchange, candle.token, candle.timestamp.isoformat(),
                 (candle.timestamp + timedelta(minutes=5)).isoformat(), candle.timeframe,
                 candle.open, candle.high, candle.low, candle.close, candle.volume,
                 candle.source, "RUNNING"),
            )
            self.connection.commit()

    def latest_running(self, instrument):
        with self.lock:
            return self.connection.execute(
                "SELECT * FROM candles WHERE instrument = ? AND status = 'RUNNING' ORDER BY timestamp DESC LIMIT 1",
                (instrument,),
            ).fetchone()

    def record_market_event(self, event_id, values):
        with self.lock:
            row = dict(values)
            row["event_id"] = event_id
            row["payload"] = json.dumps(row.get("payload", {}), default=str)
            self.connection.execute(
                "INSERT OR IGNORE INTO raw_market_events (event_id, instrument_key, exchange, exchange_timestamp, received_timestamp, ltp, volume, source, sequence, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row.get("event_id"), row.get("instrument_key"), row.get("exchange"), row.get("exchange_timestamp"),
                 row.get("received_timestamp"), row.get("ltp"), row.get("volume", 0), row.get("source"),
                 row.get("sequence"), row.get("payload")),
            )
            self.connection.execute(
                "DELETE FROM raw_market_events WHERE rowid NOT IN "
                "(SELECT rowid FROM raw_market_events ORDER BY received_timestamp DESC LIMIT ?)",
                (config.RAW_MARKET_MAX_ROWS,),
            )
            self.connection.commit()

    def latest_market_event(self, instrument_key):
        with self.lock:
            return self.connection.execute(
                "SELECT instrument_key, exchange, exchange_timestamp, received_timestamp, ltp, volume, source, sequence, event_id "
                "FROM raw_market_events WHERE instrument_key = ? ORDER BY received_timestamp DESC LIMIT 1",
                (instrument_key,),
            ).fetchone()

    def reconcile(self, candle: Candle):
        with self.lock:
            existing = self.connection.execute(
                "SELECT open, high, low, close, volume, source, status FROM candles WHERE instrument = ? AND timestamp = ? AND timeframe = ?",
                (candle.instrument, candle.timestamp.isoformat(), candle.timeframe),
            ).fetchone()
            if existing is None:
                self.save(candle)
                return "INSERTED"
            values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
            if tuple(existing[:5]) == values:
                if existing[6] != candle.status:
                    self.connection.execute(
                        "UPDATE candles SET source = ?, status = ?, candle_end = ? WHERE instrument = ? AND timestamp = ? AND timeframe = ?",
                        (candle.source, candle.status, (candle.timestamp + timedelta(minutes=5)).isoformat(), candle.instrument, candle.timestamp.isoformat(), candle.timeframe),
                    )
                    self.connection.commit()
                return "UNCHANGED"
            return "MISMATCH"

    def replace(self, candle: Candle):
        with self.lock:
            self.connection.execute(
                "UPDATE candles SET exchange = ?, token = ?, candle_end = ?, open = ?, high = ?, low = ?, close = ?, volume = ?, source = ?, status = ? "
                "WHERE instrument = ? AND timestamp = ? AND timeframe = ?",
                (candle.exchange, candle.token, (candle.timestamp + timedelta(minutes=5)).isoformat(),
                 candle.open, candle.high, candle.low, candle.close, candle.volume, candle.source, candle.status,
                 candle.instrument, candle.timestamp.isoformat(), candle.timeframe),
            )
            self.connection.commit()

    def existing_ohlc(self, candle: Candle):
        with self.lock:
            return self.connection.execute(
                "SELECT open, high, low, close, volume FROM candles WHERE instrument = ? AND timestamp = ? AND timeframe = ?",
                (candle.instrument, candle.timestamp.isoformat(), candle.timeframe),
            ).fetchone()

    def latest(self, instrument):
        with self.lock:
            return self.connection.execute(
                "SELECT * FROM candles WHERE instrument = ? ORDER BY timestamp DESC LIMIT 1", (instrument,)
            ).fetchone()

    def recent(self, instrument, limit=100):
        with self.lock:
            return self.connection.execute(
                "SELECT * FROM candles WHERE instrument = ? ORDER BY timestamp DESC LIMIT ?", (instrument, limit)
            ).fetchall()

    def close(self):
        with self.lock:
            self.connection.close()

    def is_healthy(self):
        with self.lock:
            try:
                self.connection.execute("SELECT 1").fetchone()
                return True
            except (sqlite3.Error, AttributeError):
                return False

    def order_request(self, request_id):
        with self.lock:
            return self.connection.execute(
                "SELECT request_id, state, broker_order_id FROM order_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()

    def unfinished_order_requests(self):
        with self.lock:
            return self.connection.execute(
                "SELECT request_id, signal_id, state, broker_order_id FROM order_requests "
                "WHERE state IN ('PENDING', 'SUBMITTED', 'OPEN', 'PARTIALLY_FILLED', 'UNKNOWN') "
                "ORDER BY created_at"
            ).fetchall()

    def load_positions(self):
        with self.lock:
            rows = self.connection.execute(
                "SELECT trade_id, signal_id, signal_type, underlying, direction, instrument_key, expiry, strike, "
                "quantity, entry_price, initial_sl, initial_risk, state, exit_state, exit_reason, order_id, payload "
                "FROM positions ORDER BY created_at"
            ).fetchall()
        values = []
        for row in rows:
            stored_payload = json.loads(row[-1] or "{}") if isinstance(row[-1], str) else {}
            nested_payload = stored_payload.get("payload") if isinstance(stored_payload, dict) else None
            payload = dict(nested_payload) if isinstance(nested_payload, dict) else {}
            if isinstance(stored_payload, dict):
                payload.update({key: value for key, value in stored_payload.items() if key != "payload"})
            values.append({
                "trade_id": row[0], "signal_id": row[1] or payload.get("signal_id", ""),
                "signal_type": row[2] or payload.get("signal_type", "TYPE_1"),
                "underlying": row[3] or payload.get("underlying", ""),
                "direction": row[4] or payload.get("direction", ""),
                "instrument_key": row[5] or payload.get("token", ""),
                "expiry": row[6] or payload.get("expiry", ""), "strike": row[7] or payload.get("strike"),
                "quantity": row[8] or payload.get("quantity", 0), "entry_price": row[9] or payload.get("entry_price", 0),
                "initial_sl": row[10] or payload.get("initial_sl", payload.get("sl_reference")),
                "initial_risk": row[11] or payload.get("initial_risk"), "state": row[12],
                "exit_state": row[13] or payload.get("exit_state", "OPEN"),
                "exit_reason": row[14] or payload.get("exit_reason"),
                "order_id": row[15] or payload.get("order_id"),
                "payload": payload,
            })
        return values

    def save_order_request(self, request_id, values):
        with self.lock:
            row = dict(values)
            row["request_id"] = request_id
            row.setdefault("state", "PENDING")
            row.setdefault("created_at", "")
            row["payload"] = json.dumps(row, default=str)
            columns = list(row)
            placeholders = ", ".join("?" for _ in columns)
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                self.connection.execute(
                    f"INSERT OR IGNORE INTO order_requests ({', '.join(columns)}) VALUES ({placeholders})",
                    [row[column] for column in columns],
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def reserve_order_request(self, request_id, values):
        with self.lock:
            if self.order_request(request_id):
                return False
            self.save_order_request(request_id, values)
            return True

    def update_order_request(self, request_id, state, broker_order_id=None):
        with self.lock:
            self.connection.execute(
                "UPDATE order_requests SET state = ?, broker_order_id = COALESCE(?, broker_order_id) WHERE request_id = ?",
                (state, broker_order_id, request_id),
            )
            self.connection.commit()

    def record(self, table, primary_id, values):
        allowed = {
            "signals": "signal_id", "approvals": "approval_id", "orders": "order_id", "fills": "fill_id",
            "stop_losses": "sl_order_id", "positions": "trade_id", "exits": "exit_id", "errors": "error_id",
            "reconciliation_events": "event_id",
            "signal_events": "event_id", "position_events": "event_id", "stop_orders": "stop_order_id",
            "system_events": "event_id", "order_requests": "request_id",
        }
        if table not in allowed:
            raise ValueError(f"Unsupported audit table: {table}")
        key = allowed[table]
        row = dict(values)
        row[key] = primary_id
        payload = json.dumps(row, default=str)
        columns = list(row)
        if "payload" in columns:
            columns.remove("payload")
        row["payload"] = payload
        columns = list(row)
        placeholders = ", ".join("?" for _ in columns)
        with self.lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                self.connection.execute(
                    f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                    [row[column] for column in columns],
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def record_telemetry(self, event_id, values):
        row = dict(values)
        row["event_id"] = event_id
        row.setdefault("timestamp", datetime.now().astimezone().isoformat())
        row.setdefault("severity", "INFO")
        row.setdefault("component", "SYSTEM")
        row.setdefault("event_type", "EVENT")
        row.setdefault("message", "")
        row.setdefault("exception", "")
        row.setdefault("system_state", "")
        row.setdefault("recovery_action", "")
        row.setdefault("resolution", "UNRESOLVED")
        payload = row.get("payload", {})
        row["payload"] = json.dumps(payload, default=str)
        columns = list(row)
        placeholders = ", ".join("?" for _ in columns)
        with self.lock:
            self.connection.execute(
                f"INSERT OR REPLACE INTO telemetry_events ({', '.join(columns)}) VALUES ({placeholders})",
                [row[column] for column in columns],
            )
            self.connection.execute(
                "DELETE FROM telemetry_events WHERE rowid NOT IN "
                "(SELECT rowid FROM telemetry_events ORDER BY timestamp DESC LIMIT ?)",
                (config.TELEMETRY_MAX_ROWS,),
            )
            self.connection.commit()

    def telemetry_events(self, report_date=None):
        with self.lock:
            if report_date:
                return self.connection.execute(
                    "SELECT timestamp, severity, component, event_type, message, exception, system_state, recovery_action, resolution, payload "
                    "FROM telemetry_events WHERE timestamp LIKE ? ORDER BY timestamp",
                    (f"{report_date}%",),
                ).fetchall()
            return self.connection.execute(
                "SELECT timestamp, severity, component, event_type, message, exception, system_state, recovery_action, resolution, payload "
                "FROM telemetry_events ORDER BY timestamp"
            ).fetchall()

    def save_daily_report(self, report_date, report):
        with self.lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO daily_reports (report_date, generated_at, status, payload) VALUES (?, ?, ?, ?)",
                (report_date, datetime.now().astimezone().isoformat(), report.get("status", "NOT OBSERVED"),
                 json.dumps(report, default=str)),
            )
            self.connection.commit()

    def daily_reports(self):
        with self.lock:
            rows = self.connection.execute(
                "SELECT report_date, generated_at, status, payload FROM daily_reports ORDER BY report_date DESC"
            ).fetchall()
        return [
            {"report_date": row[0], "generated_at": row[1], "status": row[2],
             "payload": json.loads(row[3] or "{}")}
            for row in rows
        ]

    def recent_records(self, table, limit=100):
        allowed = {"orders", "fills", "exits", "system_events", "position_events", "reconciliation_events"}
        if table not in allowed:
            raise ValueError(f"Unsupported observer table: {table}")
        with self.lock:
            rows = self.connection.execute(
                f"SELECT payload FROM {table} ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        records = []
        for (payload,) in rows:
            try:
                value = json.loads(payload or "{}")
            except (TypeError, ValueError):
                value = {}
            if isinstance(value, dict):
                records.append(value)
        return records
