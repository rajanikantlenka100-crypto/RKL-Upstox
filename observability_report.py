"""Generate or print the persisted SQLite observability report."""

import argparse
import json

import config
from observability import Observability
from storage.sqlite_store import CandleStore


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Local report date YYYY-MM-DD")
    args = parser.parse_args()
    store = CandleStore(config.DATABASE_PATH, mode=config.EXECUTION_MODE)
    try:
        print(json.dumps(Observability(store).daily_report(args.date), indent=2, default=str))
    finally:
        store.close()
