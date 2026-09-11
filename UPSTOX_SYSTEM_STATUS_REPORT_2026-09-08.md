# Upstox RKL Production Readiness Report

**Date:** 2026-09-08
**Status:** `PRODUCTION READY WITH BLOCKERS`

This status means the codebase has received the requested production-hardening implementation, but live account/sandbox verification is still required. It does not mean live orders are approved.

## A. Architecture Changes

The existing RKL strategy was preserved. The following existing components remain the owners of their behavior:

- `CandleEngine`: five-minute running/closed candle state.
- `BreakoutEngine`: ordered LOW -> HIGH CALL and HIGH -> LOW PUT sequence.
- `validate_rsi_entry`: closed-candle RSI14 versus RSI14 SMA5 filter over the last five eligible candles.
- CCI calculation and configured exit thresholds.
- `SignalCoordinator`: primary/secondary queue and 60-second expiry.
- Approval controller and keyboard controller.
- SQLite event/audit storage.
- Position and safety state machines.

The broker/data boundary was upgraded instead of creating a second signal engine.

## B. Official Upstox API/SDK Usage

Implemented current documented paths/capabilities:

- Official `upstox-python-sdk==2.30.0`.
- `MarketDataStreamerV3` for protobuf-decoded live market data.
- `PortfolioDataStreamer` for order/position updates when order execution is enabled.
- V3 historical candles: `/v3/historical-candle/:instrument_key/minutes/5/:to_date/:from_date`.
- V3 intraday candles: `/v3/historical-candle/intraday/:instrument_key/minutes/5`.
- V3 LTP quotes: `/v3/market-quote/ltp`.
- V2 option contracts: `/v2/option/contract`.
- V3 order placement: `https://api-hft.upstox.com/v3/order/place` by default.
- V2 order book, order details, order history, order trades, cancellation.
- V2 short-term positions.
- V2 registered static IP lookup: `/v2/user/ip`.
- OAuth token exchange.

The SDK was inspected locally and confirmed to expose `MarketDataStreamerV3` and `PortfolioDataStreamer`. The SDK internally decodes the V3 protobuf feed and sends a dictionary to the message callback.

## C. Runtime Modes and Whether Orders Can Be Sent

Configuration is explicit:

```text
TRADING_MODE=READ_ONLY
REAL_ORDERS_ENABLED=OFF
AUTO_TRADING_ENABLED=OFF
MANUAL_APPROVAL_ENABLED=ON
MARKET_DATA_MODE=websocket
WEBSOCKET_ENABLED=ON
```

### Current default

- Real order placement: **disabled**.
- Automatic trading: **disabled**.
- Manual approval: available when a verified signal reaches the approval queue.
- Market data: official Upstox V3 WebSocket is the primary source.
- REST polling: only an explicit fallback when `MARKET_DATA_MODE=polling`.

### Order behavior

A real order can only be attempted when all of these are true:

1. `TRADING_MODE=LIVE` or an explicitly configured execution mode.
2. `REAL_ORDERS_ENABLED=ON`.
3. `UPSTOX_ORDER_IP` is configured and valid.
4. Runtime public IP matches the Upstox registered static IP returned by `/v2/user/ip`.
5. Authentication succeeds.
6. Historical synchronization succeeds.
7. Intraday reconciliation has no unresolved mismatch.
8. Feed is fresh.
9. Signal is valid and less than 60 seconds old.
10. Option contract is resolved from official Upstox option data.
11. Option LTP and option candle data are valid.
12. Stop-loss validation passes.
13. No duplicate or unresolved order/position exists.
14. Database/audit storage is healthy.
15. Manual approval is received, or automatic mode is explicitly enabled.

A signal alone never sends an order.

## D. Market Data Flow

### WebSocket startup

1. Authenticate with Upstox.
2. Resolve configured index keys from the official instrument master.
3. Create `MarketDataStreamerV3` with `full` mode by default.
4. Subscribe to the configured index instrument keys.
5. Receive SDK-decoded feed dictionaries.
6. Extract the instrument key, LTP, exchange timestamp, cumulative volume where available, and raw payload.
7. Record the raw event before forwarding the normalized tick.
8. Send a `MarketTick` into the existing candle engine.

Supported default indexes:

```text
NIFTY
BANKNIFTY
FINNIFTY
MIDCPNIFTY
```

The list is configurable through `INSTRUMENTS`. SENSEX remains supported by the resolver when explicitly configured.

### Event provenance

Each normalized WebSocket event carries:

- `instrument_key`
- exchange/segment
- exchange timestamp
- local received timestamp
- LTP
- cumulative-volume delta where available
- source `UPSTOX_WEBSOCKET_V3`
- sequence number
- raw payload
- raw event ID

Missing LTP, missing exchange timestamp, and unknown instruments are stored as malformed/raw events and reported as feed errors. They are not silently discarded.

## E. Candle Verification

The existing `CandleEngine` remains the single candle authority.

For each instrument:

- Bucket = exact five-minute IST boundary.
- OPEN = first accepted tick in the bucket.
- HIGH = maximum accepted tick.
- LOW = minimum accepted tick.
- CLOSE = latest accepted tick before bucket transition.
- VOLUME = cumulative-volume delta supplied by the adapter where available.
- Out-of-order timestamps are rejected.
- A time gap larger than the configured timeframe resets the breakout sequence and forces recovery.

The current running candle and previous closed candle remain separate. The previous candle is produced only when a later bucket arrives.

Running candles are persisted with `status=RUNNING`. Finalized candles are persisted with `status=FINAL`. On restart, the current session running candle is restored if it belongs to the current IST date.

## F. Historical Synchronization

Before signals can be enabled:

1. Download V3 historical five-minute candles.
2. Parse timezone-aware timestamps.
3. Validate positive OHLC and non-negative volume.
4. Reject duplicate timestamps.
5. Reject non-chronological timestamps.
6. Ignore an unfinished current candle.
7. Require sufficient warm-up for RSI14, RSI SMA5, and the configured lookback.
8. Reconcile each candle with SQLite.
9. Seed the candle engine with finalized history.
10. Restore a current running candle if one exists.
11. Fetch official V3 intraday five-minute candles.
12. Compare completed historical and intraday candles.
13. Block signals on unresolved mismatch or failed reconciliation.

The service does not silently select one source when historical and intraday data disagree.

## G. Indicators

### RSI14

The implementation now uses Wilder-smoothed RSI:

- First valid value occurs after 14 price changes.
- Early values remain `None`.
- Average gains and losses are initialized from the first 14 changes.
- Subsequent values use Wilder smoothing.
- No running candle is used by the RSI entry filter.

### RSI14 SMA5

`rsi_sma_series` calculates a five-value simple moving average over the RSI14 series. It is not RSI5. Values remain unavailable until five valid RSI14 values exist.

### CCI

CCI uses:

- Typical price `(high + low + close) / 3`.
- Configured CCI period.
- Mean typical price.
- Mean deviation.
- Standard CCI constant `0.015`.
- CCI `0.0` for a mathematically constant-price window.

## H. Breakout and Signal Flow

The RKL sequence is preserved:

### CALL

```text
LOW crossed/reached first
then HIGH crossed/reached second
```

### PUT

```text
HIGH crossed/reached first
then LOW crossed/reached second
```

A signal requires:

- running and previous candle available,
- healthy fresh feed,
- no unresolved data reconciliation block,
- breakout sequence completed,
- RSI filter pass.

The signal is written to SQLite, audit JSONL, candidate trace JSONL, terminal state, dashboard state, and the approval queue.

The signal path can produce signals in a live read-only run. No live signal has been observed in this workspace because no Upstox account token was supplied.

## I. Option Selection

After RSI PASS:

1. Request option contracts from `/v2/option/contract` using the resolved underlying instrument key.
2. Select the nearest valid expiry.
3. Select the ATM strike interval configured for the underlying.
4. Select CE for CALL and PE for PUT.
5. Preserve the official `instrument_key`, `trading_symbol`, expiry, strike, lot size, and tick size.
6. Request fresh option LTP.
7. Request option five-minute history.
8. Validate option identity and data sufficiency.

The implementation does not construct an option instrument key manually.

## J. Stop-Loss and Approval

The existing stop-loss policy is preserved:

```text
trigger = previous option candle low - configured buffer
limit = trigger - configured limit offset
```

Both values are rounded to the official contract tick size. The system rejects:

- invalid contract tick size,
- non-positive prices,
- trigger/limit inversion,
- trigger at or above current option LTP,
- invalid risk values.

The approval item contains signal direction, index, option, expiry, strike, option LTP, quantity, previous option candle OHLC, stop-loss, and risk.

### Manual mode

```text
verified signal
-> option ready
-> approval required
-> A/REJECT terminal decision
-> same execution pipeline
```

### Automatic mode

```text
verified signal
-> option ready
-> automatic APPROVED decision
-> same execution pipeline
```

Automatic mode does not bypass validation. It only replaces the human decision event.

## K. Order State and Reconciliation

The order boundary tracks these independently:

- requested
- submitted/accepted
- rejected
- unknown
- filled
- partially filled
- position confirmed
- stop-loss placed
- stop-loss confirmed
- protected position

The adapter uses official Upstox response fields:

- `order_id`
- `status`
- `filled_quantity`
- `average_price`
- `pending_quantity`
- `instrument_token`
- `status_message`

The portfolio stream is used when execution is enabled. REST order book/details/history/trades remain the reconciliation fallback.

An unknown response does not trigger an automatic retry. Trading is halted until reconciliation.

## L. Persistence and Audit

SQLite now stores:

- finalized candles,
- running candles,
- raw market events,
- signals,
- approvals,
- order requests,
- orders,
- fills,
- positions,
- stop-losses,
- exits,
- reconciliation events,
- signal events,
- position events,
- system errors/events.

Run the daily report with:

```powershell
python data_quality_report.py --date YYYY-MM-DD
```

The report includes event counts, timestamp boundaries, duplicate/regression counts, candle counts, running/final counts, and generated signals.

## M. Cloud and Deployment

Added:

- `Dockerfile`
- `docker-compose.yml`
- `healthcheck.py`
- persistent data/log/report mounts
- explicit `Asia/Kolkata` timezone
- headless dashboard behavior
- `/health` endpoint

The dashboard is still a local read-only status surface and should not be exposed without authentication and network controls.

## N. Tests and Validation

Current validation:

```text
80 passed, 12 subtests passed
```

The expanded tests cover:

- official instrument-key resolution,
- official option-contract field selection,
- V3 order payload shape,
- historical row normalization,
- WebSocket event provenance,
- exchange versus receipt timestamps,
- raw event storage,
- running-candle restart restoration,
- RSI warm-up/alignment,
- breakout sequence,
- approval lifecycle,
- safety gate,
- order state helpers,
- stop-loss validation.

These tests are local/mocked. They do not prove live Upstox account behavior.

## O. Remaining Blockers

The following must be completed with a real or sandbox Upstox account before live enablement:

1. Read-only OAuth authentication.
2. Instrument master resolution against the current trading day.
3. Actual `MarketDataStreamerV3` connection and four-index delivery.
4. Actual protobuf-decoded message shape verification for the selected SDK version.
5. Exchange timestamp, LTP freshness, and cumulative-volume verification.
6. Historical/intraday/live candle comparison during market hours.
7. Option Contracts API verification for all configured underlyings.
8. Option LTP and option five-minute history verification.
9. Sandbox order placement.
10. Sandbox order status, trades, partial fill, rejection, cancellation, and exit verification.
11. Portfolio stream event verification.
12. Static-IP registration verification.
13. Stop-loss trigger/limit acceptance verification.
14. Process restart with an unresolved order and open position.
15. Cloud deployment and persistent-volume recovery test.
16. Live read-only signal verification report.

## P. Final Status

**PRODUCTION READY WITH BLOCKERS**

The implementation is no longer polling-only and now has the required production-oriented foundations. It must remain non-live until the account-level and sandbox validations above pass. Real orders are not sent by default.
