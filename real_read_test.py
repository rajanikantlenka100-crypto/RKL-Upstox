"""Read-only Upstox smoke test for authentication, instruments, LTP, and history."""

import config
from broker.upstox import UpstoxAdapter
from instruments.resolver import resolve_indices


def main():
    config.validate_runtime()
    instruments = resolve_indices()
    adapter = UpstoxAdapter(lambda tick: None, lambda status: print(status, flush=True))
    adapter.authenticate()
    adapter.set_instruments(instruments)
    print(f"AUTH PASS; resolved {len(instruments)} index instruments", flush=True)
    for instrument in instruments.values():
        ltp = adapter.ltp(instrument)
        candles = adapter.fetch_historical(instrument, count=config.HISTORICAL_COUNT)
        if ltp <= 0 or len(candles) < config.RSI_PERIOD + config.RSI_SMA_PERIOD + config.RSI_LOOKBACK_PERIODS:
            raise RuntimeError(f"Readiness check failed for {instrument.name}: ltp={ltp}, candles={len(candles)}")
        print(f"{instrument.name}: LTP PASS; historical candles PASS ({len(candles)})", flush=True)
    print("READ-ONLY API READ PASS; no orders were submitted", flush=True)


if __name__ == "__main__":
    main()