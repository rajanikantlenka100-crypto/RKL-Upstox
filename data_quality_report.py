"""Generate a daily Upstox raw-feed/candle/signal quality report."""

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from reports.data_quality import write_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat())
    parser.add_argument("--output", default=str(config.ROOT / "reports" / "daily_quality.json"))
    args = parser.parse_args()
    write_report(config.DATABASE_PATH, args.output, args.date)
    print(args.output)
