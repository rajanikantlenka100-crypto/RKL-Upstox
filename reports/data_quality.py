"""Daily data-lineage and quality report for the Upstox session."""

import json
import sqlite3
from collections import Counter
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def build_report(database_path, session_date=None):
    session_date = session_date or datetime.now(IST).date().isoformat()
    connection = sqlite3.connect(database_path)
    try:
        raw = connection.execute(
            "SELECT instrument_key, exchange_timestamp, received_timestamp, ltp, source, sequence FROM raw_market_events WHERE received_timestamp LIKE ? ORDER BY received_timestamp",
            (session_date + "%",),
        ).fetchall()
        candles = connection.execute(
            "SELECT instrument, timestamp, open, high, low, close, volume, source, status FROM candles WHERE timestamp LIKE ? ORDER BY instrument, timestamp",
            (session_date + "%",),
        ).fetchall()
        signals = connection.execute(
            "SELECT signal_id, instrument, direction, status, created_at FROM signals WHERE created_at LIKE ? ORDER BY created_at",
            (session_date + "%",),
        ).fetchall()
    finally:
        connection.close()

    by_instrument = {}
    for instrument in sorted({row[0] for row in raw} | {row[0] for row in candles}):
        events = [row for row in raw if row[0] == instrument]
        instrument_candles = [row for row in candles if row[0] == instrument]
        timestamps = [row[1] for row in events if row[1]]
        duplicate_count = sum(count - 1 for count in Counter((row[1], row[3]) for row in events).values() if count > 1)
        regressions = sum(1 for previous, current in zip(timestamps, timestamps[1:]) if current < previous)
        by_instrument[instrument] = {
            "total_events": len(events),
            "first_exchange_timestamp": timestamps[0] if timestamps else None,
            "last_exchange_timestamp": timestamps[-1] if timestamps else None,
            "duplicate_events": duplicate_count,
            "timestamp_regressions": regressions,
            "stale_ltp_events": sum(1 for row in events if row[3] is None or row[3] <= 0),
            "historical_candles": sum(1 for row in instrument_candles if row[7] == "HISTORICAL"),
            "live_candles": sum(1 for row in instrument_candles if row[7].startswith("UPSTOX")),
            "reconciled_candles": len(instrument_candles),
            "running_candles": sum(1 for row in instrument_candles if row[8] == "RUNNING"),
            "final_candles": sum(1 for row in instrument_candles if row[8] == "FINAL"),
        }
    return {
        "session_date": session_date,
        "source": "UPSTOX_WEBSOCKET_V3",
        "expected_session": {"timezone": "Asia/Kolkata", "open": "09:15", "close": "15:30"},
        "total_events": len(raw),
        "total_candles": len(candles),
        "signals_generated": len(signals),
        "signals": [dict(zip(("signal_id", "instrument", "direction", "status", "created_at"), row)) for row in signals],
        "instruments": by_instrument,
    }


def write_report(database_path, output_path, session_date=None):
    report = build_report(database_path, session_date)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
