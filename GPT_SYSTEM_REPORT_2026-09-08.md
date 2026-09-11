# RKL Upstox System Report

**Report date:** 2026-09-08  
**Purpose:** GPT-readable operational, safety, data-flow, and readiness report.  
**System mode at review:** `TRADING_MODE=READ_ONLY`, `REAL_ORDERS_ENABLED=OFF`, `ORDER_ENV=live`.

## Executive Status

The system currently operates as a real-data, read-only Upstox market-data service. It is not an order-executing system in the current environment.

Verified:

- Upstox login using the configured access token.
- Instrument resolution for NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY.
- REST LTP for all configured indexes.
- Historical 5-minute candles.
- Intraday 5-minute candles for the current trading date.
- Upstox market WebSocket connection and live ticks.
- Read-only broker positions and order-book requests.
- Local dashboard HTTP health endpoint.
- Indicator, signal, approval, safety-gate, order, position, stop-loss, and exit code paths by automated tests and static review.

Not live-verified and intentionally disabled:

- Real BUY orders.
- Real stop-loss orders.
- Real SELL/exit orders.
- Broker fill confirmation using a submitted order.
- Portfolio stream for live order updates.
- Static-IP validation.

## Current Live Read-Only Evidence

The latest read-only checks succeeded:

| Check | Result |
|---|---|
| Authentication | PASS |
| Index instruments | 4 resolved |
| NIFTY LTP | `23635.10` at the export snapshot |
| NIFTY current-day candles | 75 candles |
| NIFTY candle range | `09:15` to `15:25` IST |
| WebSocket | Connected, 4 ticks received during smoke test |
| Positions read | PASS, 0 rows |
| Order book read | PASS, 0 rows |
| Dashboard `/health` | HTTP 200 |
| Automated tests | `80 passed, 12 subtests passed` |

Current NIFTY files:

- `reports/nifty_ltp_2026-09-08.json`
- `reports/nifty_5m_candles_2026-09-08.json`
- `reports/nifty_5m_candles_2026-09-08.csv`

Today's candles use `UPSTOX_INTRADAY_V3`. Completed prior sessions use `UPSTOX_HISTORICAL_V3`.

## Dashboard

The dashboard is served by `web_dashboard.py` using `ThreadingHTTPServer`.

- URL: `http://127.0.0.1:8765`
- Health URL: `http://127.0.0.1:8765/health`
- State URL: `http://127.0.0.1:8765/state`
- Event stream: `http://127.0.0.1:8765/events`
- Structured authoritative state: `http://127.0.0.1:8765/state`
- Browser is view-only; it does not approve or place orders.
- Dashboard state is a snapshot of the terminal service state.

The dashboard is started after authentication, broker setup, reconciliation, and historical backfill. A bind failure is now reported as `DASHBOARD FAILED` rather than being hidden.

### Why the dashboard appeared to disappear

The terminal session showed `UPSTOX FEED DISCONNECTED` after `Ctrl+C`. This is expected shutdown behavior: `main.py` handles `SIGINT`, stops the feed, stops the dashboard, closes the database, and restores the terminal. The dashboard is not a permanent Windows service; it exists only while `python main.py` is running.

## Terminal Refresh, Throttling, and Errors

### Refresh behavior

`TerminalDisplay.render_loop()` calls `render_control()` every `DISPLAY_REFRESH_SECONDS`. The current default is `0.5` seconds, so the full control-center block is printed approximately twice per second.

`render_control()` does not clear the Windows console before printing. It appends repeated full screens to the terminal buffer. This causes:

- rapid scrolling;
- apparent terminal throttling or lag;
- duplicated status blocks;
- high console I/O volume;
- interleaving with status/event prints;
- difficulty reading the latest state.

This is UI output flooding, not evidence of an Upstox API rate-limit error.

### Additional output sources

The display also prints immediately from `set_status()` and `add_event()`. These writes can interleave with the periodic render loop. The keyboard loop polls every `0.05` seconds, but it does not print continuously.

### Actual terminal errors observed

- `^C` / `KeyboardInterrupt`: user interruption; it caused normal service shutdown.
- `UPSTOX FEED DISCONNECTED`: expected when the service is stopped or the WebSocket closes.
- Earlier WebSocket callback error: fixed. The installed SDK invokes lifecycle callbacks with arguments, while the old zero-argument callbacks rejected them. The callbacks now accept `*args`.
- No current dashboard bind error was observed. The health endpoint returned HTTP 200.
- No current Python diagnostics were reported for touched files.

### Implemented terminal fix

The terminal now uses one synchronized fixed-screen renderer, clears/replaces the screen on each render, stores status/events in the event buffer, and does not independently print every live event. The default refresh interval is now one second:

```text
DISPLAY_REFRESH_SECONDS=1.0
```

The renderer also shows MARKET OPEN/CLOSED, all configured index LTPs, last tick time, age, previous candle, running candle, and frozen-closed state. Outside market hours the shared snapshot reports `SIGNALS=BLOCKED-CLOSED` while preserving the last valid market values.

## Market Data and Login

### Login

The adapter supports:

1. Existing `UPSTOX_ACCESS_TOKEN` authentication.
2. Authorization-code exchange using `UPSTOX_CLIENT_ID`, `UPSTOX_CLIENT_SECRET`, `UPSTOX_REDIRECT_URI`, and single-use `UPSTOX_AUTH_CODE`.

The current token is temporary and must be regenerated according to Upstox token expiry rules. The service does not persist a newly exchanged token back into `.env`.

### Market data

- Live market data: official Upstox V3 WebSocket SDK.
- Fallback: REST polling when explicitly configured.
- LTP: Upstox V3 market quote endpoint.
- Historical candles: Upstox V3 historical candle endpoint.
- Current trading date candles: Upstox V3 intraday candle endpoint.
- Raw WebSocket events are persisted to SQLite.
- Running and finalized candles are separated and reconciled.
- Historical normalization now sorts the complete broker response before retaining the newest requested rows.

### Index coverage

Configured indexes:

- NIFTY: `NSE_INDEX|Nifty 50`
- BANKNIFTY: `NSE_INDEX|Nifty Bank`
- FINNIFTY: `NSE_INDEX|Nifty Fin Service`
- MIDCPNIFTY: `NSE_INDEX|NIFTY MID SELECT`

SENSEX is supported in the code but is not currently included in `.env` `INSTRUMENTS`.

## Candle, Indicator, and Signal Logic

### Candle engine

- Timeframe: 5 minutes by default.
- Market window: 09:15 through before 15:30 IST on weekdays.
- WebSocket ticks build a running candle.
- A completed candle is persisted and reconciled with broker REST data.
- Feed gaps disable signals and trigger historical recovery.
- Insufficient or non-chronological history blocks signal evaluation.

### Indicators

- CCI period: 5.
- RSI period: 14.
- RSI SMA period: 5.
- RSI lookback: 5 finalized candles.
- CCI and RSI are updated when a candle closes.
- Exit checks run on CCI and RSI thresholds.

### CALL signal

1. A previous and running candle must exist.
2. The running sequence first crosses or starts below the previous low.
3. It subsequently crosses the previous high.
4. A CALL candidate is emitted once for that sequence.
5. RSI validation requires the configured closed-candle relationship: `RSI14 < RSI14 SMA5` on at least one of the last five finalized candles.

### PUT signal

1. A previous and running candle must exist.
2. The running sequence first crosses or starts above the previous high.
3. It subsequently crosses the previous low.
4. A PUT candidate is emitted once for that sequence.
5. RSI validation requires `RSI14 > RSI14 SMA5` on at least one of the last five finalized candles.

Signals are traced and audited. A signal expires after 60 seconds. NIFTY and SENSEX use the primary queue slot; other indexes use the secondary slot.

## ATM Option Selection and Entry Price

For an accepted CALL or PUT candidate:

1. The system requests live option contracts from Upstox.
2. It chooses the nearest valid expiry that is not expired.
3. It rounds the index LTP to the configured strike interval.
4. CALL selects CE; PUT selects PE.
5. It selects the closest strike to that rounded ATM target.
6. It validates lot size and tick size from the instrument master.
7. It fetches the selected option LTP.
8. It fetches option history and verifies that the candle belongs to the selected contract.
9. Entry quantity is exactly one current contract lot.
10. Displayed capital is option LTP multiplied by lot size.

The actual broker entry order is a market BUY only after all approval and safety gates pass.

## RSI Filter

The RSI filter intentionally evaluates finalized candles only. It rejects or marks the signal unavailable if:

- any input candle is still running;
- timestamps are duplicated or not chronological;
- fewer than five finalized lookback candles exist;
- RSI14 or RSI14 SMA5 is not warmed up.

The system records evaluated timestamps, RSI values, SMA values, matching periods, and the reason in signal audit data.

## Stop-Loss Logic

The intended stop-loss formula is:

```text
trigger = round_to_tick(previous_option_candle_low - SL_BUFFER)
limit   = round_to_tick(trigger - SL_LIMIT_OFFSET)
```

The stop-loss is rejected if:

- contract tick size is missing or invalid;
- reference or option LTP is non-positive;
- trigger or limit is non-positive;
- limit is not below trigger;
- trigger is not below current option LTP;
- live contract identity or tick/lot rules changed.

The order manager also enforces a minimum tick distance from current option LTP.

### Consistency status

Approval, display, audit, and position persistence paths now use `config.SL_BUFFER`, matching the executable stop-loss builder. Focused stop-loss and signal tests pass after this correction.

## Manual System

Manual mode requires:

- `TRADING_MODE=MANUAL`;
- `MANUAL_APPROVAL_ENABLED=ON`;
- real orders and static IP configured before order execution can be enabled.

Flow:

1. Real signal is detected.
2. Option is resolved and shown.
3. Operator enters `A` or `A1..A4` to approve.
4. Operator enters `R` or `R1..R4` to reject.
5. Approval is valid only inside the 60-second signal lifetime.
6. Approved orders still pass every safety gate.
7. Reject, expiry, invalid option data, or stale data prevents entry.

Manual exits:

- `X1` through `X4`: exit the corresponding active position.
- `EXITALL`, followed by a second `EXITALL`: emergency exit all active positions.
- The browser dashboard cannot issue these commands.

## Automatic System

Automatic mode requires:

- `TRADING_MODE=AUTOMATIC`;
- `AUTO_TRADING_ENABLED=ON`;
- `REAL_ORDERS_ENABLED=ON`;
- `ORDER_ENV=live` for real orders or `ORDER_ENV=sandbox` for sandbox order testing;
- static IP and broker registration for live execution.

Automatic approval occurs after option resolution, but it does not bypass the safety gate, duplicate guard, contract validation, risk checks, database checks, order reservation, broker confirmation, or stop-loss protection.

The current environment does not run automatic execution.

## Broker Order, Position, and Exit Confirmation

### Entry

The intended broker-authoritative entry lifecycle is:

1. Reserve logical order request in SQLite.
2. Submit broker BUY.
3. Save broker order ID.
4. Poll broker order book until filled, rejected, cancelled, or timeout.
5. Handle partial fill separately.
6. Register filled position with broker fill price and quantity.
7. Submit protective stop-loss.
8. Confirm stop-loss status is OPEN or TRIGGER_PENDING.
9. Mark position `SL_ACTIVE`.

### Position reconciliation

At startup and periodically, the service reads broker positions. It blocks or halts when it finds:

- unknown external broker positions;
- local positions missing at broker;
- broker API failure;
- unknown or unresolved order states.

### Manual or automatic exit

1. Mark local position `EXIT_PENDING`.
2. Cancel existing stop-loss.
3. Submit broker SELL.
4. Wait for complete fill.
5. Require filled quantity to equal requested quantity.
6. Mark position `CLOSED` only after broker fill confirmation.

Rejected, partial, or transport-unknown exits mark the position unknown and halt trading for reconciliation.

### Indicator exits

When a finalized underlying candle closes:

- CCI above `CCI_EXIT_THRESHOLD` requests exits for that underlying.
- Otherwise RSI above `RSI_EXIT_THRESHOLD` requests exits for that underlying.

The current defaults are CCI above 150 or RSI above 80.

## Safety Gates and Blocking Conditions

The buy gate requires all of the following:

- system state is RUNNING;
- feed is healthy and not stale;
- broker authentication is READY;
- historical reconciliation is READY;
- option contract is valid;
- option LTP is fresh and positive;
- risk validation passes;
- signal has not expired;
- no unresolved order request exists;
- no unknown broker position exists;
- no unprotected position exists;
- database is healthy.

Additional blocks include:

- invalid runtime configuration;
- missing credentials;
- invalid instrument master;
- insufficient history;
- historical/intraday mismatch;
- unsafe feed gap;
- option contract identity mismatch;
- invalid lot size or tick size;
- duplicate local or broker position/order;
- static IP missing or not whitelisted for live orders;
- broker rejection;
- unknown transport result;
- partial fill requiring reconciliation;
- failed stop-loss confirmation.

## Current Configuration Blockers

The current environment intentionally has:

```text
TRADING_MODE=READ_ONLY
REAL_ORDERS_ENABLED=OFF
ORDER_ENV=live
UPSTOX_ORDER_IP=<empty>
```

Therefore:

- orders are disabled;
- no portfolio stream is started for order execution;
- no live BUY, stop-loss, or SELL can be submitted;
- static IP is not currently needed for market-data reads;
- a static IP and Upstox registered IP are required before live orders.

Sandbox routing exists, but sandbox credentials can only be used for supported sandbox order endpoints. Sandbox is not a source of live LTP, historical candles, or market WebSocket data.

## Findings Requiring Engineering Follow-up

1. Add explicit broker option-contract timeout and clearer retry/error classification; an option-contract request previously did not return a usable response during a read-only probe.
2. Add a real-account controlled order test only after static IP registration. Do not use live orders as an unbounded test.
3. Add broker-backed integration coverage for partial fills, rejected orders, stop-loss confirmation, exit fills, portfolio events, and restart reconciliation.
4. Add a token refresh/runbook because daily access-token expiry can stop the service before the next market session.
5. Expand market session states to explicitly distinguish PRE_MARKET, OPEN, CLOSING, CLOSED, DATA_RECOVERY, and FEED_DISCONNECTED. Current display distinguishes OPEN/CLOSED and frozen state.
6. Keep `.env` out of source control and rotate credentials if exposed.

## Final Acceptance Report

### A. Files changed

- `config.py`: one-second terminal default.
- `.env` and `.env.example`: one-second terminal refresh setting.
- `trading/approval.py`: authoritative `config.SL_BUFFER`.
- `main.py`: configured SL consistency and persisted tick restoration.
- `storage/sqlite_store.py`: latest raw market-event lookup.
- `terminal_display.py`: synchronized fixed-screen rendering, per-index data, market-close frozen state, and reduced stdout flooding.
- `web_dashboard.py`: `/state` structured runtime endpoint.
- `GPT_SYSTEM_REPORT_2026-09-08.md`: this report.

### B. Files not changed

The candle engine, indicator formulas, breakout strategy, option-selection rules, broker order manager, and safety-gate meaning were not replaced. Existing architecture was reused.

### C. Architecture changes

The dashboard and terminal consume the same `TerminalDisplay.snapshot()` state. The browser now has `/health`, `/state`, and `/events`; no duplicate market-data or signal engine was introduced.

### D. Data-flow changes

On restart, the latest persisted raw broker tick is reconstructed as a real `MarketTick` with original exchange timestamp, received timestamp, source, sequence, and event ID. No synthetic tick is generated.

### E. Dashboard changes

Dashboard health and state are available while the process runs. `/state` returned HTTP 200 and included NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY after an outside-hours restart.

### F. Terminal changes

The renderer now clears/replaces one screen approximately every second, keeps events in the buffer, and displays market status, LTP, age, last tick, previous 5-minute candle, running candle, signal state, positions, and health.

### G. Signal correctness verification

Breakout, CALL/PUT sequence, approval, expiry, RSI finalized-candle filtering, and safety-gate behavior are covered by the existing automated tests and static review. No live signal/order was generated during this review.

### H. Historical/live reconciliation results

Startup historical synchronization and prior live read-only checks passed. The service reports HISTORY READY and CANDLES READY. Current-day NIFTY intraday export returned 75 candles from 09:15 to 15:25 IST.

### I. Indicator verification results

RSI14, RSI14-SMA5, and CCI5 implementations and tests pass. RSI entry validation excludes running candles and requires finalized chronological history.

### J. Option/SL verification results

Option selection and option-candle identity tests pass. SL calculation tests pass, and configured `SL_BUFFER` is now shared by approval, display, audit, persistence, and execution paths.

### K. Test results

`80 passed, 12 subtests passed`. Modified runtime modules compile cleanly.

### L. Read-only live verification results

Authentication, four index resolution, LTP, historical/intraday candles, WebSocket connection/ticks, positions read, order-book read, dashboard health, and restart-state restoration passed. No order was submitted.

### M. Remaining blockers

Real order lifecycle, real fill confirmation, stop-loss broker confirmation, exit fill confirmation, portfolio stream behavior, static-IP matching, and controlled live validation remain unverified. Current configuration keeps orders disabled.

### N. Sandbox configuration

Use a separate sandbox order token and set:

```text
ORDER_ENV=sandbox
TRADING_MODE=SANDBOX
REAL_ORDERS_ENABLED=ON
SANDBOX_API_BASE=https://sandbox.upstox.com
SANDBOX_ACCESS_TOKEN=<sandbox token>
```

Sandbox routing is isolated to order/position clients. Live LTP, historical candles, and WebSocket data remain on the live market-data client.

### O. Required real-trading configuration

```text
ORDER_ENV=live
TRADING_MODE=MANUAL       # or AUTOMATIC after separate approval
REAL_ORDERS_ENABLED=ON
LIVE_BROKER_VALIDATION=ON
UPSTOX_ORDER_IP=<registered static IPv4>
AUTO_TRADING_ENABLED=OFF # ON only for reviewed automatic mode
MANUAL_APPROVAL_ENABLED=ON
```

The registered Upstox static IP, public IP, broker order behavior, fill lifecycle, stop-loss protection, and exit reconciliation must be verified before live enablement.

### P. Production readiness verdict

**Not production-ready for real order execution.** The read-only market-data and control-center layer is operationally verified, but critical broker execution, static-IP, order-state, fill, stop-loss, exit, and portfolio-stream evidence is still missing. The system remains correctly fail-closed with orders disabled.

## GPT Handoff Summary

This is a real-data Upstox trading service with read-only operation currently enabled. Market login, LTP, historical data, WebSocket, dashboard health, restart-state restoration, and read-only broker reconciliation have been verified. Signal generation supports CALL and PUT breakout sequences, RSI14/SMA5 filtering, live ATM option selection, one-lot entry sizing, consistent stop-loss construction, manual approval, automatic approval, broker fill confirmation, position reconciliation, manual exits, indicator exits, and emergency exit-all. Real execution is blocked by configuration and missing static IP. The terminal is now a fixed-screen renderer, and the authoritative state endpoint preserves last valid values after market close.