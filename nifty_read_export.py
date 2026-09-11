"""Export a read-only NIFTY LTP and today's 5-minute candles."""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from broker.upstox import UpstoxAdapter
from instruments.resolver import resolve_indices
from market_data.historical import parse_historical_row

IST = ZoneInfo("Asia/Kolkata")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now(IST).date().isoformat(), help="IST date in YYYY-MM-DD format")
    parser.add_argument("--output-dir", default=str(config.ROOT / "reports"))
    args = parser.parse_args()
    selected_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config.validate_runtime()
    instruments = resolve_indices()
    if "NIFTY" not in instruments:
        raise RuntimeError("NIFTY must be included in INSTRUMENTS")
    adapter = UpstoxAdapter(lambda tick: None, lambda status: print(status, flush=True))
    adapter.authenticate()
    nifty = instruments["NIFTY"]
    ltp = adapter.ltp(nifty)
    today = datetime.now(IST).date()
    source = "UPSTOX_HISTORICAL_V3"
    if selected_date == today:
        rows = adapter.fetch_intraday(nifty, count=max(config.HISTORICAL_COUNT, 500))
        source = "UPSTOX_INTRADAY_V3"
    else:
        rows = adapter.fetch_historical(nifty, count=config.HISTORICAL_COUNT)
    candles = []
    for row in rows:
        timestamp, open_price, high, low, close, volume = parse_historical_row(row)
        if timestamp.date() == selected_date:
            candles.append({
                "timestamp": timestamp.isoformat(), "open": open_price, "high": high,
                "low": low, "close": close, "volume": volume,
            })
    if not candles:
        raise RuntimeError(f"No NIFTY 5-minute candles returned for {selected_date}")

    stamp = selected_date.isoformat()
    ltp_path = output_dir / f"nifty_ltp_{stamp}.json"
    candles_json_path = output_dir / f"nifty_5m_candles_{stamp}.json"
    candles_csv_path = output_dir / f"nifty_5m_candles_{stamp}.csv"
    ltp_path.write_text(json.dumps({
        "instrument": "NIFTY", "instrument_key": nifty.token, "exchange": nifty.exchange,
        "ltp": ltp, "retrieved_at": datetime.now(IST).isoformat(), "source": "UPSTOX_REST",
    }, indent=2) + "\n", encoding="utf-8")
    candles_json_path.write_text(json.dumps({
        "instrument": "NIFTY", "timeframe": "5m", "date": stamp,
        "source": source, "count": len(candles), "candles": candles,
    }, indent=2) + "\n", encoding="utf-8")
    with candles_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("timestamp", "open", "high", "low", "close", "volume"))
        writer.writeheader()
        writer.writerows(candles)

    print(f"NIFTY LTP: {ltp:.2f} -> {ltp_path}", flush=True)
    print(f"NIFTY {selected_date} 5m candles: {len(candles)} -> {candles_json_path}", flush=True)
    print(f"CSV export: {candles_csv_path}", flush=True)
    print("FIRST:", candles[0], flush=True)
    print("LAST:", candles[-1], flush=True)


if __name__ == "__main__":
    main()