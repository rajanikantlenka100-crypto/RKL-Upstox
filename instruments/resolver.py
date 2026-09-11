"""Resolve Upstox index instruments from the daily JSON master."""

import gzip
import json
import time
import urllib.request
from dataclasses import dataclass

import config


@dataclass(frozen=True)
class Instrument:
    name: str
    symbol: str
    token: str
    exchange: str
    exchange_type: int = 0


def _records(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and value and all(str(key).isdigit() for key in value):
        return list(value.values())
    raise RuntimeError("Upstox instrument master is not a JSON record list")


def load_records(refresh_after_hours=24, force_refresh=False):
    path = config.INSTRUMENT_MASTER_PATH
    if force_refresh or not path.exists() or time.time() - path.stat().st_mtime > refresh_after_hours * 3600:
        request = urllib.request.Request(config.INSTRUMENT_MASTER_URL, headers={"User-Agent": "RKL-Upstox/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = gzip.decompress(response.read()).decode("utf-8")
        records = _records(json.loads(payload))
        path.write_text(json.dumps(records), encoding="utf-8")
    try:
        return _records(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as error:
        raise RuntimeError(f"Invalid Upstox instrument master cache: {error}") from error


def resolve_indices(records=None):
    records = records if records is not None else load_records()
    by_key = {str(row.get("instrument_key")): row for row in records}
    resolved = {}
    for name in config.INSTRUMENTS:
        key = config.INDEX_KEYS[name]
        row = by_key.get(key) or next((item for item in records if str(item.get("segment")) == config.INDEX_EXCHANGES[name] and str(item.get("name", "")).upper() == name), None)
        if row is None:
            raise RuntimeError(f"Could not resolve {name} from Upstox instrument master")
        token = str(row.get("instrument_key", "")).strip()
        if not token:
            raise RuntimeError(f"Resolved {name} has no instrument_key")
        resolved[name] = Instrument(name, str(row.get("trading_symbol", name)), token, str(row.get("segment")), 0)
    return resolved
