# RKL Upstox Trading System

This is the Upstox-only version of the RKL signal workflow. It uses the official Upstox Python SDK for Market Data Feed V3 and Portfolio Stream, Upstox instrument keys, OAuth access tokens, V3 historical/intraday candles, V3 LTP quotes, V3 order placement, and REST order/position reconciliation.

## Safety defaults

- `EXECUTION_MODE=READ_ONLY` and `REAL_ORDERS_ENABLED=OFF` are the defaults.
- `MARKET_DATA_MODE=websocket` is the default. REST polling is an explicit diagnostic fallback only.
- Signals still require historical reconciliation, a healthy feed, and RSI validation. Valid signals enter the guarded automatic-entry pipeline by default; `READ_ONLY` and `REAL_ORDERS_ENABLED=OFF` still prohibit broker orders.
- Every V3 feed event stores exchange timestamp, receipt timestamp, source, sequence, LTP, volume, and raw payload.
- Running candles are stored and restored after restart; finalized candles are reconciled against official intraday candles.
- Live order mode additionally requires `UPSTOX_ORDER_IP` and `LIVE_BROKER_VALIDATION=ON` requires live orders.
- Never commit `.env`, access tokens, client secrets, or broker responses.

## Login setup

1. Create an Upstox Developer App and register the exact redirect URI.
2. Copy `.env.example` to `.env`.
3. Use either a manually generated `UPSTOX_ACCESS_TOKEN`, or provide `UPSTOX_CLIENT_ID`, `UPSTOX_CLIENT_SECRET`, `UPSTOX_REDIRECT_URI`, and a single-use `UPSTOX_AUTH_CODE`.
4. Keep `REAL_ORDERS_ENABLED=OFF` while validating read-only authentication, instrument resolution, quotes, and history.

## Run

```powershell
python -m pip install -r requirements.txt
python main.py
```

The primary feed uses the official `upstox_client.MarketDataStreamerV3`, which decodes the official protobuf feed and emits normalized events into the existing candle/signal engine. `UPSTOX_POLL_SECONDS` is used only when `MARKET_DATA_MODE=polling`.

The official `PortfolioDataStreamer` is started when order execution is enabled. REST order details/history/trades remain the authoritative reconciliation fallback.

## Modes

`EXECUTION_MODE` supports `READ_ONLY`, `BACKTEST`, `SANDBOX`, and `PRODUCTION`. `LIVE` remains accepted as a legacy alias for `PRODUCTION`. The safe default is `READ_ONLY`; mode-specific database defaults prevent replay and sandbox data from sharing production storage. Production requires explicit real orders, automatic entry, live order environment, static order IP, and a passed runtime preflight.

`AUTO_ENTRY_ENABLED=ON` is the default signal-flow setting. It removes the normal approval wait but does not bypass `TRADING_MODE`, `REAL_ORDERS_ENABLED`, option validation, risk checks, reconciliation, fill confirmation, or protective stop-loss confirmation. Strategy exits are per-position CCI confirmation or running-index 5R exits; protective stop-loss orders remain fixed after entry.

## Operational reports

Generate the daily raw-feed, candle, and signal quality report with:

```powershell
python data_quality_report.py --date 2026-09-08
```

The local dashboard exposes `/health` for container/process health checks. Docker deployment files are included, but live production status still requires account-level read-only and controlled broker verification.

## Tests

```powershell
python -m pytest -q
```

The local suite covers authentication boundaries, WebSocket normalization, historical OHLCV validation, candle persistence and recovery, indicators, signal gating, orders, positions, stop-loss policy, and dashboard health. Run the read-only broker smoke test with `test_03_real_read.bat` only after `.env` contains valid credentials.

## Production status

**Deployment status:** the code has explicit mode separation and a fail-closed production preflight, but live readiness remains account and environment dependent. Before enabling `EXECUTION_MODE=PRODUCTION`, run the read-only smoke test, verify the WebSocket and portfolio streams during market hours, confirm historical/intraday reconciliation for every configured index, and perform an authorized broker validation with the registered order IP. The repository does not fabricate market data or simulate order execution.
