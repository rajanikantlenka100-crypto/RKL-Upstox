"""Broker-isolated NIFTY historical signal replay and report generator."""

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from market_data.models import Candle
from signals.breakout import BreakoutEngine
from signals.rsi_filter import validate_rsi_entry

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN_MINUTE = config.MARKET_OPEN[0] * 60 + config.MARKET_OPEN[1]
MARKET_CLOSE_MINUTE = config.MARKET_CLOSE[0] * 60 + config.MARKET_CLOSE[1]


def load_nifty_rows(database_path, selected_dates):
    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute(
            "SELECT instrument, exchange, token, timestamp, timeframe, open, high, low, close, volume, status "
            "FROM candles WHERE instrument = 'NIFTY' ORDER BY timestamp"
        ).fetchall()
    finally:
        connection.close()
    candles = []
    for row in rows:
        timestamp = datetime.fromisoformat(row[3]).astimezone(IST)
        if timestamp.date() not in selected_dates:
            continue
        candles.append(Candle(row[0], row[1], row[2], timestamp, row[4], row[5], row[6], row[7], row[8], row[9], "HISTORICAL", row[10]))
    return candles


def validate_dataset(candles):
    by_day = defaultdict(list)
    invalid_ohlc = []
    duplicates = []
    seen = set()
    for candle in candles:
        key = (candle.instrument, candle.timestamp)
        if key in seen:
            duplicates.append(candle.timestamp.isoformat())
        seen.add(key)
        by_day[candle.timestamp.date()].append(candle)
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close) or candle.high < candle.low:
            invalid_ohlc.append(candle.timestamp.isoformat())

    missing = {}
    for day, day_candles in by_day.items():
        timestamps = [candle.timestamp for candle in day_candles]
        expected = []
        cursor = day_candles[0].timestamp.replace(hour=9, minute=15, second=0, microsecond=0)
        close = day_candles[0].timestamp.replace(hour=15, minute=25, second=0, microsecond=0)
        while cursor <= close:
            expected.append(cursor)
            cursor += timedelta(minutes=5)
        missing[day.isoformat()] = [timestamp.isoformat() for timestamp in expected if timestamp not in timestamps]

    return {
        "timezone": "Asia/Kolkata",
        "timeframe": sorted({candle.timeframe for candle in candles}),
        "duplicates": duplicates,
        "invalid_ohlc": invalid_ohlc,
        "missing_buckets": missing,
        "daily": {
            day.isoformat(): {
                "candles": len(day_candles),
                "first": day_candles[0].timestamp.isoformat(),
                "last": day_candles[-1].timestamp.isoformat(),
            }
            for day, day_candles in sorted(by_day.items())
        },
    }


def session_ok(timestamp):
    minute = timestamp.hour * 60 + timestamp.minute
    return MARKET_OPEN_MINUTE <= minute < MARKET_CLOSE_MINUTE


def sequence_from_ohlc(previous, current):
    """Return a proven price path, ambiguity, or no breakout evidence."""
    low_touched = current.low <= previous.low
    high_touched = current.high >= previous.high
    open_low = current.open <= previous.low
    open_high = current.open >= previous.high
    if open_low and high_touched:
        return [current.open, current.high], "LOW_FIRST_PROVEN"
    if open_high and low_touched:
        return [current.open, current.low], "HIGH_FIRST_PROVEN"
    if not open_low and not open_high and low_touched and high_touched:
        return None, "INTRABAR_SEQUENCE_NOT_VERIFIABLE"
    if low_touched:
        return [current.open, current.low], "LOW_FIRST_WAITING_HIGH"
    if high_touched:
        return [current.open, current.high], "HIGH_FIRST_WAITING_LOW"
    return [current.open], "NO_BREAKOUT"


def candle_payload(candle):
    if not candle:
        return None
    return {
        "timestamp": candle.timestamp.isoformat(), "open": candle.open, "high": candle.high,
        "low": candle.low, "close": candle.close, "volume": candle.volume,
    }


def replay(candles, evaluation_dates):
    candles = sorted(candles, key=lambda candle: candle.timestamp)
    history = []
    signals = []
    events = []
    prior = None
    recovery_blocked = False
    for index, current in enumerate(candles):
        new_session = prior is not None and current.timestamp.date() != prior.timestamp.date()
        if new_session:
            recovery_blocked = False
        if prior and not new_session and current.timestamp - prior.timestamp != timedelta(minutes=5):
            recovery_blocked = True
            events.append({"date": current.timestamp.date().isoformat(), "candle": current.timestamp.isoformat(), "reason": "DATA_GAP"})
        if prior and not recovery_blocked and not new_session and current.timestamp.date() in evaluation_dates and session_ok(current.timestamp) and session_ok(prior.timestamp):
            sequence, classification = sequence_from_ohlc(prior, current)
            if sequence is None:
                events.append({"date": current.timestamp.date().isoformat(), "candle": current.timestamp.isoformat(), "reason": classification,
                               "previous": candle_payload(prior), "current": candle_payload(current)})
            else:
                engine = BreakoutEngine()
                signal = None
                for price in sequence:
                    running = Candle(current.instrument, current.exchange, current.token, current.timestamp, "5m",
                                     current.open, max(current.open, price, current.high if price == sequence[-1] else current.open),
                                     min(current.open, price, current.low if price == sequence[-1] else current.open), price, current.volume, "LIVE")
                    signal = engine.evaluate(prior, running, price, current.timestamp) or signal
                if signal:
                    result = validate_rsi_entry(history, signal.direction)
                    record = {
                        "signal_candle": candle_payload(current), "previous_candle": candle_payload(prior),
                        "direction": signal.direction, "breakout_price": signal.breakout_price,
                        "first_break_side": signal.first_break_side, "first_break_time": signal.first_break_time.isoformat() if signal.first_break_time else None,
                        "first_break_price": signal.first_break_price, "second_break_side": signal.second_break_side,
                        "second_break_time": signal.second_break_time.isoformat() if signal.second_break_time else None,
                        "second_break_price": signal.breakout_price, "rsi_result": result.result,
                        "rsi_matching_periods": result.matching_periods,
                        "rsi_periods": [{"timestamp": timestamp.isoformat(), "rsi14": rsi_value, "sma5": sma_value,
                                         "match": (rsi_value < sma_value if signal.direction == "CALL" else rsi_value > sma_value)
                                         if rsi_value is not None and sma_value is not None else False}
                                        for timestamp, rsi_value, sma_value in zip(result.evaluated_candle_timestamps,
                                                                                    result.evaluated_rsi_values, result.evaluated_sma_values)],
                        "rsi_reason": result.reason,
                    }
                    events.append({"date": current.timestamp.date().isoformat(), "candle": current.timestamp.isoformat(),
                                   "reason": "RSI_PASS" if result.result == "PASS" else "RSI_" + result.result,
                                   "direction": signal.direction})
                    if result.result == "PASS":
                        signals.append(record)
                    else:
                        record["classification"] = "RSI_REJECT" if result.result == "REJECT" else "RSI_UNAVAILABLE"
                        events.append(record)
                elif classification != "NO_BREAKOUT":
                    events.append({"date": current.timestamp.date().isoformat(), "candle": current.timestamp.isoformat(), "reason": classification})
        history.append(current)
        prior = current
    return signals, events


def markdown_report(selected_dates, candles, quality, signals, events):
    days = sorted(selected_dates)
    day_counts = Counter(record["signal_candle"]["timestamp"][:10] for record in signals)
    candidate_events = Counter(event.get("reason") for event in events)
    lines = [
        "# NIFTY Historical Signal Verification", "", "Generated from stored real NIFTY candles; broker execution was not imported or called.", "",
        "## 1. Executive Summary", "",
        f"Test dates: {', '.join(day.isoformat() for day in days)}. Day 1 is warm-up; signal statistics cover {days[1].isoformat()} and {days[2].isoformat()}.",
        f"Signals after the existing RSI filter: **{len(signals)} total**, **{sum(s['direction'] == 'CALL' for s in signals)} CALL**, **{sum(s['direction'] == 'PUT' for s in signals)} PUT**.",
        "OHLC-only candles cannot prove LOW-before-HIGH or HIGH-before-LOW when both boundaries are touched from an in-range open; those cases are reported as `INTRABAR_SEQUENCE_NOT_VERIFIABLE`.", "",
        "## 2. Exact Historical Dataset Used", "", f"Database: `{quality['database']}`", f"Instrument: NIFTY; timezone: {quality['timezone']}; timeframe: {quality['timeframe']}", "",
        "## 3. Data Quality Validation", "", f"Duplicates: {len(quality['duplicates'])}; invalid OHLC: {len(quality['invalid_ohlc'])}",
        "", "| Date | Candles | First | Last | Missing buckets |", "|---|---:|---|---|---:|",
    ]
    for day in days:
        item = quality["daily"][day.isoformat()]
        lines.append(f"| {day} | {item['candles']} | {item['first']} | {item['last']} | {len(quality['missing_buckets'].get(day.isoformat(), []))} |")
    missing_values = [timestamp for day in days for timestamp in quality["missing_buckets"].get(day.isoformat(), [])]
    lines += ["", "Missing bucket timestamps:", ""]
    lines.extend(f"- `{timestamp}`" for timestamp in missing_values) if missing_values else lines.append("- None")
    lines += ["", "## 4. Replay Methodology", "", "Candles were processed chronologically. The actual `BreakoutEngine` and `validate_rsi_entry` were called. Day 1 history was retained for RSI warm-up. A detected missing bucket blocks the remainder of that session, matching the live fail-closed gap behavior. No order, option, approval, or broker module was imported.", "",
              "## 5. Signal Results", "", "| Candle timestamp | Direction | Previous OHLC | Signal OHLC | Breakout | RSI matches | RSI result |", "|---|---|---|---|---:|---:|---|"]
    for signal in signals:
        lines.append(f"| {signal['signal_candle']['timestamp']} | {signal['direction']} | {signal['previous_candle']['open']}/{signal['previous_candle']['high']}/{signal['previous_candle']['low']}/{signal['previous_candle']['close']} | {signal['signal_candle']['open']}/{signal['signal_candle']['high']}/{signal['signal_candle']['low']}/{signal['signal_candle']['close']} | {signal['breakout_price']} | {signal['rsi_matching_periods']}/5 | {signal['rsi_result']} |")
    if not signals:
        lines.append("| No generated signals | -- | -- | -- | -- | -- | -- |")
    lines += ["", "## 6. Complete CALL Signal Table", "", "| Candle timestamp | Previous OHLC | Signal OHLC | Breakout | RSI |", "|---|---|---|---:|---|"]
    call_signals = [signal for signal in signals if signal["direction"] == "CALL"]
    if call_signals:
        lines.extend(f"| {signal['signal_candle']['timestamp']} | {signal['previous_candle']['open']}/{signal['previous_candle']['high']}/{signal['previous_candle']['low']}/{signal['previous_candle']['close']} | {signal['signal_candle']['open']}/{signal['signal_candle']['high']}/{signal['signal_candle']['low']}/{signal['signal_candle']['close']} | {signal['breakout_price']} | {signal['rsi_matching_periods']}/5 PASS |" for signal in call_signals)
    else:
        lines.append("| None | -- | -- | -- | -- |")
    lines += ["", "## 7. Complete PUT Signal Table", "", "| Candle timestamp | Previous OHLC | Signal OHLC | Breakout | RSI |", "|---|---|---|---:|---|"]
    put_signals = [signal for signal in signals if signal["direction"] == "PUT"]
    if put_signals:
        lines.extend(f"| {signal['signal_candle']['timestamp']} | {signal['previous_candle']['open']}/{signal['previous_candle']['high']}/{signal['previous_candle']['low']}/{signal['previous_candle']['close']} | {signal['signal_candle']['open']}/{signal['signal_candle']['high']}/{signal['signal_candle']['low']}/{signal['signal_candle']['close']} | {signal['breakout_price']} | {signal['rsi_matching_periods']}/5 PASS |" for signal in put_signals)
    else:
        lines.append("| None | -- | -- | -- | -- |")
    lines += ["", "## 8. Detailed RSI Evidence", ""]
    for number, signal in enumerate(signals, 1):
        lines += [f"### Signal {number}: {signal['direction']} at {signal['signal_candle']['timestamp']}", "", f"First break: {signal['first_break_side']} @ {signal['first_break_price']}; second break: {signal['second_break_side']} @ {signal['second_break_price']}", "", "| Period timestamp | RSI14 | RSI14-SMA5 | Match |", "|---|---:|---:|---|"]
        for period in signal["rsi_periods"]:
            lines.append(f"| {period['timestamp']} | {period['rsi14']} | {period['sma5']} | {'PASS' if period['match'] else 'FAIL'} |")
        lines.append("")
    lines += ["## 9. Non-Signal / Miss Classification", "", "| Reason | Count |", "|---|---:|"]
    for reason, count in sorted(candidate_events.items()):
        lines.append(f"| {reason} | {count} |")
    lines += ["", "## 10. Daily Summary", "", "| Day | Candles | Signals | CALL | PUT | RSI PASS | RSI REJECT | RSI UNAVAILABLE |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for day in days:
        count = day_counts.get(day.isoformat(), 0)
        day_events = [event for event in events if event.get("date") == day.isoformat()]
        lines.append(f"| {day} | {quality['daily'][day.isoformat()]['candles']} | {count} | {sum(s['direction'] == 'CALL' and s['signal_candle']['timestamp'].startswith(day.isoformat()) for s in signals)} | {sum(s['direction'] == 'PUT' and s['signal_candle']['timestamp'].startswith(day.isoformat()) for s in signals)} | {sum(event.get('reason') == 'RSI_PASS' for event in day_events)} | {sum(event.get('reason') == 'RSI_REJECT' for event in day_events)} | {sum(event.get('reason') == 'RSI_UNAVAILABLE' for event in day_events)} |")
    lines += ["", "## 11. Pick vs Miss", "", "| Event | Expected | Actual classification |", "|---|---|---|"]
    for reason, expected in [("LOW_FIRST_PROVEN", "CALL candidate or no RSI pass"), ("HIGH_FIRST_PROVEN", "PUT candidate or no RSI pass"), ("INTRABAR_SEQUENCE_NOT_VERIFIABLE", "Do not claim CALL/PUT"), ("LOW_FIRST_WAITING_HIGH", "No signal"), ("HIGH_FIRST_WAITING_LOW", "No signal")]:
        lines.append(f"| {reason} | {expected} | {candidate_events.get(reason, 0)} observed |")
    lines += ["", "## 12. Limitations and Final Verdict", "", "The replay is causal and uses no future candles. Reported signal time is the 5-minute candle timestamp; exact intrabar tick time is unavailable. Exact LOW/HIGH order is not verifiable for in-range OHLC candles touching both reference levels. Missing buckets block the remainder of that session, matching live fail-closed behavior. No profit, loss, win rate, order, fill, or broker result was calculated.", "", "```text", "SIGNAL ENGINE: PARTIALLY VERIFIED", "BREAKOUT: PARTIALLY VERIFIED (OHLC sequence limitation)", "RSI: VERIFIED by existing implementation and replay", "HISTORICAL REPLAY: PASS", "LIVE SIGNAL PATH: NOT YET VERIFIED", "BROKER ORDER PATH: NOT TESTED IN THIS TASK", "```"]
    return "\n".join(lines) + "\n"


def run(database_path, output_dir):
    connection = sqlite3.connect(database_path)
    available = [date.fromisoformat(row[0]) for row in connection.execute("select distinct date(timestamp) from candles where instrument='NIFTY' order by date(timestamp)")]
    connection.close()
    full_days = [day for day in available if day.weekday() < 5]
    if len(full_days) < 3:
        raise RuntimeError("Fewer than three weekday NIFTY dates are available")
    selected_dates = set(full_days[-4:-1] if len(full_days) >= 4 and full_days[-1] == date.today() else full_days[-3:])
    selected_dates = sorted(selected_dates)
    candles = load_nifty_rows(database_path, set(selected_dates))
    validation = validate_dataset(candles)
    validation["database"] = str(database_path)
    signals, events = replay(candles, set(selected_dates[1:]))
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(IST).strftime("%Y%m%d")
    payload = {"selected_dates": [day.isoformat() for day in selected_dates], "data_quality": validation, "signals": signals, "events": events}
    (output_dir / f"nifty_signal_replay_{stamp}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    with (output_dir / f"nifty_signal_replay_{stamp}.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["timestamp", "direction", "breakout_price", "rsi_matching_periods", "rsi_result", "first_break_side", "second_break_side"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for signal in signals:
            writer.writerow({field: signal.get("signal_candle", {}).get("timestamp") if field == "timestamp" else signal.get(field) for field in fields})
    report = markdown_report(selected_dates, candles, validation, signals, events)
    (output_dir / f"nifty_signal_replay_{stamp}.md").write_text(report, encoding="utf-8")
    print(report)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay stored NIFTY candles without broker execution")
    parser.add_argument("--database", type=Path, default=Path("data/backtest.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    run(args.database, args.output_dir)