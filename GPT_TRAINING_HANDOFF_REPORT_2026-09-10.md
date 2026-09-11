# RKL Upstox GPT Training and Modification Handoff Report

**Report date:** 2026-09-10  
**Repository:** RKL Upstox  
**Purpose:** Give a future GPT or engineer enough context to understand the system, the work completed so far, the safety model, current evidence, remaining risks, and the correct places to modify behavior.

## 1. Executive Summary

RKL Upstox is a real-data Upstox market-data and signal service for index breakout trading. It consumes live Upstox V3 market data, builds five-minute candles, validates historical data, evaluates breakout and RSI conditions, resolves an ATM option, presents an approval payload, and has guarded broker order, position, stop-loss, exit, and reconciliation code.

The intended operational posture is fail-closed:

- Default mode is `TRADING_MODE=READ_ONLY`.
- Default real order switch is `REAL_ORDERS_ENABLED=OFF`.
- Live market data uses the official Upstox V3 WebSocket SDK.
- Historical synchronization and intraday reconciliation are required before signals are enabled.
- Browser dashboard is view-only.
- Manual approval is terminal-controlled and still subject to every final safety gate.
- Unknown broker responses are not retried automatically; they require reconciliation.

The read-only market-data/control layer has been implemented and tested. Real BUY, stop-loss, SELL, fill, exit, portfolio-stream, static-IP, and complete sandbox/live broker execution behavior have not been proven in this repository. The system must remain non-live until those validations are completed deliberately.

## 2. Current Evidence and Status

### Fresh validation on 2026-09-10

Command executed:

```powershell
py -m pytest -q
```

Result:

```text
87 passed, 12 subtests passed in 4.05s
```

The repository’s older reports dated 2026-09-08 state `80 passed, 12 subtests passed`. The fresh run supersedes that test-count claim.

### Previously documented read-only evidence

The existing 2026-09-08 reports document successful checks for:

- Upstox access-token authentication.
- Resolution of NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY.
- Index LTP reads.
- Historical and current-day intraday five-minute candles.
- Upstox V3 market WebSocket connection and live ticks.
- Read-only positions and order-book requests.
- Dashboard `/health` response.
- Local signal, indicator, approval, safety, order-state, position, stop-loss, and dashboard tests.

Those account-level checks are historical evidence, not a guarantee that the current token, market session, network, SDK, or account will behave identically today.

### Current readiness verdict

**Read-only market-data service:** operationally implemented and locally validated.  
**Signal and safety logic:** locally tested, with live signal generation still account/session dependent.  
**Real order execution:** not approved; broker-level blockers remain.  
**Production readiness:** not ready for unrestricted real order execution.

## 3. System Purpose and Boundaries

The system is designed to:

1. Authenticate with Upstox.
2. Resolve official index and option instruments.
3. Receive real-time index ticks.
4. Store raw feed provenance.
5. Aggregate ticks into five-minute candles.
6. Reconcile live candles with broker history.
7. Detect ordered breakout sequences.
8. Filter candidates with finalized-candle RSI logic.
9. Select a live ATM CE or PE contract.
10. Calculate and validate a protective stop-loss.
11. Queue a signal for manual or automatic approval according to configuration.
12. Execute only when all safety, broker, database, risk, freshness, and reconciliation conditions pass.
13. Reconcile orders and positions with broker-authoritative data.
14. Expose a local read-only terminal and HTTP dashboard.

The system is not a backtesting engine, not a guaranteed profit system, and not a substitute for broker or exchange confirmation. Historical OHLC data cannot prove the intrabar order of two levels when both are touched in one candle.

## 4. Repository Map and Ownership

### Entry and configuration

- `main.py`: `MarketDataService`, lifecycle orchestration, tick routing, candle-close handling, signal-to-option flow, approval execution, recovery, and shutdown.
- `config.py`: environment loading, defaults, mode validation, market hours, strategy parameters, paths, and order safety configuration.
- `README.md`: setup, modes, operational commands, and high-level safety expectations.

### Broker boundary

- `broker/upstox.py`: REST client and SDK adapter. Owns authentication, profile validation, LTP, candles, option contracts, positions, order queries, cancellation, WebSocket startup/reconnect, polling fallback, portfolio stream, timestamp normalization, and raw event forwarding.
- `broker/order_manager.py`: `OrderExecutor`. Owns broker entry, fill polling, duplicate guards, stop-loss placement/confirmation, exits, partial/rejected/unknown handling, and order lifecycle classification.
- `broker/validation_report.py`: controlled broker-validation result persistence.

### Instruments

- `instruments/resolver.py`: resolves configured index names to official instrument keys using the instrument master.
- `instruments/options.py`: ATM strike selection, expiry selection, contract identity, lot/tick validation, and option-candle identity validation.

### Market data

- `market_data/models.py`: `MarketTick`, `Candle`, and related data models.
- `market_data/candles.py`: five-minute candle engine, running/final states, timestamp ordering, persistence, restart restoration, and close callbacks.
- `market_data/historical.py`: broker candle parsing and OHLCV validation.
- `market_data/indicators.py`: Wilder RSI, RSI SMA, and CCI.
- `market_data/health.py`: fresh/stale feed state.

### Signals

- `signals/breakout.py`: ordered LOW-to-HIGH CALL and HIGH-to-LOW PUT sequence engine.
- `signals/rsi_filter.py`: finalized-candle RSI14 versus RSI14 SMA5 entry filter.
- `signals/coordinator.py`: primary/secondary queue slots, expiry, approval controller, and keyboard controller.
- `signals/candidate_trace.py`: JSONL candidate-level trace.
- `signals/audit.py`: signal audit persistence.

### Trading state

- `trading/safety.py`: fail-closed system state and buy gate.
- `trading/positions.py`: position lifecycle and reconciliation states.
- `trading/stop_loss_policy.py`: tick-aligned stop-loss construction and validation.
- `trading/approval.py`: approval payload and stop-loss presentation.

### Storage and presentation

- `storage/sqlite_store.py`: SQLite schema and persistence for candles, events, signals, approvals, orders, fills, positions, stops, exits, reconciliation, and errors.
- `terminal_display.py`: synchronized terminal snapshot and fixed-screen renderer.
- `web_dashboard.py`: local HTTP dashboard and `/health`, `/ready`, `/state`, and `/events` endpoints.

### Operations and diagnostics

- `real_read_test.py`: read-only authentication, instrument, quote, and history smoke test.
- `data_quality_report.py`: daily raw-feed, candle, and signal quality report.
- `historical_signal_replay.py`: broker-isolated historical signal replay.
- `signal_audit_report.py`: human-readable audit output.
- `healthcheck.py`: dashboard health check.
- `network_diagnostics.py`: public IP and static order-IP checks.
- `run.bat`, `install.bat`, `test_01_config.bat` through `test_04_safe_tests.bat`: Windows operational helpers.
- `Dockerfile`, `docker-compose.yml`: container deployment and persistent mounts.

Runtime imports `web_dashboard.py`. `web_dashboard_fixed.py`, `web_dashboard_valid.py`, and `dashboard_tmp.py` appear to be historical or experimental copies and should not be treated as active runtime owners without checking imports.

## 5. Startup and Runtime Lifecycle

`MarketDataService.start()` follows this order:

1. Resolve configured indexes from the cached or downloaded instrument master.
2. Open SQLite and restore the latest persisted raw tick for outside-hours visibility.
3. Validate all runtime mode and safety configuration.
4. Authenticate and validate the Upstox token through the profile endpoint.
5. Check public/registered order IP when real orders are enabled.
6. Construct `OrderExecutor` and `PositionManager`.
7. Reconcile broker positions against local state.
8. Reconcile unfinished local order requests.
9. Backfill historical five-minute candles.
10. Reconcile completed history with current-day intraday candles.
11. Seed candle engines and restore an eligible running candle.
12. Enable the safety gate only when history and reconciliation are ready.
13. Start the WebSocket or explicitly configured REST polling fallback.
14. Start the portfolio stream only when live order execution requires it.
15. Start the dashboard.
16. Start approval and keyboard controllers.
17. Run periodic reconciliation and the service heartbeat loop.

Important lifecycle symbols in `main.py` include `start`, `_authenticate_and_validate`, `_check_public_ip`, `_backfill`, `_reconcile_positions`, `_reconcile_order_requests`, `_recover_after_reconnect`, `_on_tick`, `_on_candle_closed`, `_execute_approved_order`, and `stop`.

Shutdown on `SIGINT` or `SIGTERM` stops feeds and controllers, stops the dashboard, closes SQLite, restores the terminal, and records a lifecycle reason.

## 6. Market Data and Candle Contract

### Tick provenance

Each normalized feed tick can carry:

- instrument key and logical instrument name;
- exchange timestamp;
- local receipt timestamp;
- LTP;
- cumulative-volume delta when available;
- source, normally `UPSTOX_WEBSOCKET_V3`;
- sequence number;
- raw payload and raw event ID.

Malformed, unknown-instrument, missing-LTP, and missing-timestamp events are recorded as feed errors/raw events instead of being silently accepted.

### Five-minute candle rules

`CandleEngine` is the single candle authority:

- Bucket boundaries are five-minute IST boundaries by default.
- First accepted tick sets open.
- Highest and lowest accepted prices set high and low.
- Latest accepted tick sets close.
- Volume uses the adapter’s cumulative-volume delta where available.
- Naive, non-positive, stale/future, and out-of-order data is rejected according to the engine’s validation rules.
- A bucket transition finalizes the prior running candle.
- Running candles persist as `RUNNING`; completed candles persist as final.
- A current-session running candle can be restored after restart.
- A gap larger than the configured timeframe resets breakout state, disables signals, degrades safety, and requests historical recovery.

### Historical validation

Historical parsing requires a six-field candle shape, parseable timestamps, IST normalization, positive OHLC, valid OHLC geometry, and non-negative volume. Duplicate or non-chronological data is rejected. An unfinished current candle is not used as finalized indicator history.

## 7. Strategy and Signal Logic

### Breakout sequence

The strategy is sequence-sensitive, not merely a test of whether both levels were touched.

CALL:

```text
previous/running context available
-> running price reaches or crosses previous LOW first
-> later reaches or crosses previous HIGH
-> emit one CALL candidate for that running candle
```

PUT:

```text
previous/running context available
-> running price reaches or crosses previous HIGH first
-> later reaches or crosses previous LOW
-> emit one PUT candidate for that running candle
```

The engine resets sequence state on a new running candle and unsafe feed gaps. It suppresses duplicate signals per direction per running candle. Opening outside the previous range can count as the first break.

### RSI entry filter

Defaults:

- RSI period: 14.
- RSI SMA period: 5.
- Finalized-candle lookback: 5.

CALL requires at least one eligible lookback period where `RSI14 < RSI14 SMA5`. PUT requires at least one where `RSI14 > RSI14 SMA5`.

The filter rejects or returns unavailable for running candles, duplicate timestamps, non-chronological history, insufficient lookback, and indicator warm-up insufficiency. It records evaluated timestamps, values, matching periods, and the decision reason in audit data.

### Other indicators and exits

CCI uses the configured period, default `CCI_PERIOD=5`. On finalized underlying candle close, exit checks use:

- CCI above `CCI_EXIT_THRESHOLD`, default `150`; otherwise
- RSI above `RSI_EXIT_THRESHOLD`, default `80`.

## 8. Option Resolution and Entry Payload

After a valid breakout plus RSI pass, `main.py._resolve_signal_option`:

1. Requests official Upstox option contracts.
2. Selects the nearest valid non-expired expiry.
3. Rounds the underlying LTP using the configured strike interval.
4. Selects CE for CALL or PE for PUT.
5. Preserves the official contract identity; it does not construct a key manually.
6. Validates lot size and tick size.
7. Fetches fresh option LTP.
8. Fetches option history.
9. Confirms the history belongs to the selected contract.
10. Builds the approval payload and queues it.

Default index instruments are NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY. SENSEX is supported if explicitly configured. Default strike intervals are NIFTY 50, BANKNIFTY 100, FINNIFTY 50, MIDCPNIFTY 25, and SENSEX 100.

Entry quantity is one current contract lot by default. Displayed capital is option LTP multiplied by lot size.

## 9. Stop-Loss Policy

The executable policy in `trading/stop_loss_policy.py` is conceptually:

```text
trigger = round_to_tick(previous_option_candle_low - SL_BUFFER)
limit   = round_to_tick(trigger - SL_LIMIT_OFFSET)
```

Defaults are `SL_BUFFER=1.0`, `SL_LIMIT_OFFSET=0.05`, and `SL_MIN_TICK_DISTANCE=2`.

The policy rejects missing/invalid tick size, non-positive prices, invalid OHLC, non-positive trigger or limit, limit not below trigger, trigger at or above current option LTP, and contract identity/tick/lot inconsistencies. Approval, display, audit, persistence, and execution paths were aligned to use the configured `SL_BUFFER`.

## 10. Approval, Order, Position, and Exit Flow

### Queue and approval

`SignalCoordinator` maintains:

- one primary slot for NIFTY/SENSEX;
- one secondary slot for other indexes;
- queued additional candidates by priority;
- 60-second signal expiry.

`ApprovalController` accepts `A` or `A1..A4` to approve and `R` or `R1..R4` to reject. `KeyboardController` accepts `X1..X4` for exits and double `EXITALL` for emergency exit-all. The browser dashboard cannot approve, reject, or place orders.

### Entry lifecycle

The intended broker-authoritative entry sequence is:

1. Reserve a local order request in SQLite.
2. Submit broker BUY.
3. Save broker order ID.
4. Poll broker status until filled, rejected, cancelled, partial, or timeout.
5. Treat partial and unknown outcomes explicitly.
6. Register a confirmed filled position.
7. Submit the protective stop-loss.
8. Confirm stop-loss is `OPEN` or `TRIGGER_PENDING`.
9. Mark the position `SL_ACTIVE`.

Transport ambiguity becomes `ORDER_STATUS_UNKNOWN`; automatic retry is intentionally avoided.

### Position states

Position lifecycle states include `PENDING_ENTRY`, `PARTIALLY_FILLED`, `OPEN`, `SL_PENDING`, `SL_ACTIVE`, `UNPROTECTED_POSITION`, `EXIT_PENDING`, `CLOSED`, `ERROR`, and `UNKNOWN`.

### Exit lifecycle

The intended exit sequence is:

1. Mark the position `EXIT_PENDING`.
2. Cancel the existing stop-loss.
3. Submit broker SELL.
4. Wait for complete fill.
5. Require requested quantity to equal filled quantity.
6. Mark `CLOSED` only after broker confirmation.

Rejected, partial, or unknown exit results require reconciliation and can halt trading.

## 11. Safety Model

`SafetyGate` states include:

- `RUNNING`;
- `DEGRADED`;
- `TRADING_HALTED`;
- `EMERGENCY`;
- `SHUTTING_DOWN`.

The final buy path requires all of the following:

- running system state;
- fresh healthy feed;
- authenticated broker;
- successful historical/intraday reconciliation;
- valid option contract identity;
- fresh positive option LTP;
- valid risk result;
- unexpired signal;
- no unresolved order request;
- no unknown broker position;
- no unprotected position;
- healthy database/audit storage;
- matching registered order IP when required;
- manual approval or explicitly enabled automatic approval.

Any failed condition blocks the action. Feed gaps, history mismatches, invalid contract data, duplicate positions/orders, broker rejection, unknown transport result, failed stop-loss confirmation, and reconciliation failures are blocking events.

## 12. Configuration and Modes

`config.py` loads `.env` values first where present and otherwise reads process environment variables. Important defaults are:

```text
ORDER_ENV=live
MARKET_DATA_MODE=websocket
TRADING_MODE=READ_ONLY
REAL_ORDERS_ENABLED=OFF
AUTO_TRADING_ENABLED=OFF
MANUAL_APPROVAL_ENABLED=ON
WEBSOCKET_ENABLED=ON
HISTORICAL_SYNC_ENABLED=ON
TIMEFRAME_MINUTES=5
MARKET_OPEN=09:15
MARKET_CLOSE=15:30
HISTORICAL_LOOKBACK_DAYS=10
HISTORICAL_COUNT=100
STALE_DATA_SECONDS=15
DATABASE_PATH=market_data.sqlite3
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8765
```

Supported trading modes are `READ_ONLY`, `MANUAL`, `AUTOMATIC`, `LIVE`, and `SANDBOX`.

Runtime validation enforces:

- legal modes and positive timing/history values;
- valid market hours;
- WebSocket/polling consistency;
- automatic mode requires `AUTO_TRADING_ENABLED=ON`;
- manual mode requires `MANUAL_APPROVAL_ENABLED=ON`;
- live orders require `TRADING_MODE=LIVE`, `REAL_ORDERS_ENABLED=ON`, and a valid `UPSTOX_ORDER_IP`;
- sandbox mode requires `ORDER_ENV=sandbox`, sandbox credentials, and real order enablement;
- historical synchronization cannot be disabled;
- live broker validation requires real orders.

Never commit `.env`, access tokens, client secrets, or raw broker responses.

## 13. Persistence, Audit, and Recovery

SQLite runs with WAL mode, busy timeout, and locking. It stores:

- running and finalized candles;
- raw market events;
- signals and signal events;
- approvals;
- order requests, orders, fills, and stop orders;
- positions and position events;
- exits;
- reconciliation events;
- system events and errors.

JSONL outputs include signal candidate trace, signal audit, and controlled live-broker validation. These artifacts are important for explaining why a candidate was accepted, rejected, expired, or blocked.

On restart, the service restores the latest real persisted tick for display and can restore a valid current running candle. It must not create synthetic market ticks. Unresolved order or position state should remain blocking until broker reconciliation resolves it.

## 14. Terminal and Dashboard

The terminal and dashboard consume the same `TerminalDisplay.snapshot()` state. The terminal uses a synchronized fixed-screen renderer rather than continuously appending full screens. It displays market state, per-index LTP, age, last tick, previous/running candles, signal state, positions, health, and events.

The local dashboard defaults to:

```text
http://127.0.0.1:8765
```

Endpoints:

- `/health`: process and component health.
- `/ready`: readiness response, HTTP 200 or 503.
- `/state`: structured authoritative runtime snapshot.
- `/events`: server-sent event stream.
- `/`: view-only HTML dashboard.

The Docker configuration binds the dashboard to `0.0.0.0`; this is unsafe for an exposed deployment without authentication and network controls. The dashboard should remain a status surface, not an execution control plane.

## 15. Test Coverage

The test suite covers:

- authentication boundaries, instrument keys, option identity, order payloads, and history normalization;
- WebSocket timestamp/provenance handling and raw event storage;
- candle validation, rollover, live updates, persistence, and restart restoration;
- historical parser validation and replay behavior;
- Wilder RSI, RSI SMA, CCI, breakout sequence, duplicate suppression, and gap reset;
- RSI filter pass/reject/unavailable cases and audit alignment;
- option resolution, strike rounding, and option-candle identity;
- approval numbering, ignored keys, queue promotion, and expiry;
- safety gate conditions and state transitions;
- stop-loss tick alignment and invalid trigger rejection;
- fills, partial fills, stop-loss and unprotected position states;
- network/static-IP policy;
- signal audit, live validation report, terminal rendering, and dashboard health.

The suite is primarily local/mocked. Passing tests prove code behavior under tested fixtures; they do not prove current Upstox account behavior or exchange execution.

## 16. Work Completed So Far

The major work represented by the current repository includes:

1. Moved the system toward official Upstox SDK/V3 market-data usage.
2. Added normalized WebSocket feed handling with exchange and receipt timestamps.
3. Added raw event provenance and SQLite persistence.
4. Preserved one candle authority for live and historical data.
5. Added running-candle persistence and restart restoration.
6. Added historical/intraday reconciliation before signals.
7. Implemented Wilder RSI and finalized-candle RSI filtering.
8. Preserved ordered breakout semantics and duplicate suppression.
9. Added official option contract resolution and identity checks.
10. Added consistent tick-aligned stop-loss construction.
11. Added approval queues, expiry, keyboard controls, and emergency exit confirmation.
12. Added explicit order, position, fill, stop-loss, exit, and unknown states.
13. Added fail-closed safety and duplicate/reconciliation guards.
14. Added signal trace, audit, validation reports, and daily data-quality tooling.
15. Reworked the terminal into a synchronized fixed-screen renderer.
16. Added structured dashboard health/state/event endpoints.
17. Added Docker deployment files, healthcheck, and persistent data mounts.
18. Added broad local tests and verified the current suite at 87 passed plus 12 subtests.

## 17. Known Limitations and Risks

These are the most important facts to preserve during future modification:

1. Real broker order lifecycle has not been demonstrated end to end.
2. Partial fills, rejected orders, stop-loss activation, exit fills, cancellations, portfolio events, and restart recovery with an open order need broker-backed testing.
3. Unknown broker responses halt rather than retry; operational reconciliation is required.
4. Access tokens can expire; there is no complete persistent token-refresh workflow.
5. Option contract/history requests need clearer timeout, retry, and failure classification.
6. Historical OHLC replay cannot determine intrabar level order when both levels occur in one candle.
7. `MAX_RISK_PER_TRADE=0` disables the maximum-risk cap by default and must be reviewed before execution.
8. Docker dashboard exposure has no built-in authentication.
9. Dashboard HTML interpolation is intended for a trusted local/network environment.
10. Multiple dashboard copies and dated reports can drift from runtime code.
11. Historical read-only evidence from 2026-09-08 should not be presented as fresh verification.
12. `real_read_test.py` does not exercise option resolution, live signal generation, order placement, or exits.
13. Sandbox routing exists for orders/positions, but live market data remains on the live market-data client; sandbox is not a substitute for live market-feed validation.

## 18. Recommended Modification Order

Future changes should follow this order to preserve safety:

1. Add or update a focused test for the behavior being changed.
2. Modify the owning abstraction only: broker, candle, signal, safety, position, storage, or presentation layer.
3. Keep `main.py` as orchestration; do not duplicate candle, signal, or order logic there unnecessarily.
4. Preserve raw timestamps, contract identity, audit reasons, and broker-authoritative status.
5. Keep unknown, stale, mismatched, partial, and unprotected states fail-closed.
6. Run the narrow test first, then the full suite.
7. Re-check README and this report when configuration or operational behavior changes.

Highest-value next engineering work:

- Build a controlled sandbox validation script for order submission, status, trades, partial fills, rejection, cancellation, stop-loss, exit, and restart recovery.
- Add broker-backed integration tests around `broker/order_manager.py`.
- Add token refresh/runbook support.
- Add explicit timeout/retry classes for option contract and option-history requests.
- Add persistent restoration and reconciliation tests for open positions and unresolved orders.
- Restrict or authenticate the Docker dashboard.
- Expand market session states to distinguish pre-market, open, closing, closed, feed-disconnected, and data-recovery.
- Align all test documentation with the actual preferred runner (`py -m pytest -q` on this Windows environment).
- Remove or clearly label obsolete dashboard copies.

## 19. GPT Modification Rules

When modifying this system, a future GPT should assume:

- The default is read-only and must remain read-only unless the user explicitly requests a controlled execution change.
- A signal is not an order; it is only a candidate that must pass option, freshness, risk, approval, reconciliation, and safety checks.
- Upstox official contract identity must be preserved; never manufacture option keys.
- Finalized candle history is required for indicators; do not use a running candle for RSI entry validation.
- Broker status is authoritative for fills, positions, stops, and exits.
- Unknown broker outcomes must not be blindly retried.
- Every new state transition should be persisted and auditable.
- A feed gap or historical mismatch should disable signal generation until recovery completes.
- Browser UI must remain view-only unless a separately reviewed authenticated control plane is explicitly requested.
- Changes to `config.py`, `broker/order_manager.py`, `trading/safety.py`, `trading/positions.py`, or `main.py` have high safety impact and require focused tests plus the full suite.
- Do not claim live readiness from local tests alone.

## 20. Source Reports and Operational References

This handoff consolidates the following existing material:

- `README.md`
- `GPT_SYSTEM_REPORT_2026-09-08.md`
- `UPSTOX_SYSTEM_STATUS_REPORT_2026-09-08.md`
- `reports/nifty_ltp_2026-09-08.json`
- `reports/nifty_5m_candles_2026-09-08.json`
- `reports/nifty_5m_candles_2026-09-08.csv`

Useful commands:

```powershell
py -m pip install -r requirements.txt
py -m pytest -q
py real_read_test.py
py data_quality_report.py --date YYYY-MM-DD
py signal_audit_report.py
py healthcheck.py
py main.py
```

Before any live execution configuration, perform read-only verification, controlled sandbox validation where supported, static-IP verification, broker order lifecycle verification, stop-loss confirmation, exit confirmation, restart recovery, and an explicit operator review.

## Final Handoff Statement

RKL Upstox is a guarded, real-data trading workflow with substantial production-oriented foundations. The repository currently provides a coherent path from Upstox feed to verified signal to approval and guarded execution, with persistence, audit, reconciliation, safety states, and operator visibility. The implementation should be modified incrementally around its existing ownership boundaries. The next meaningful milestone is not more strategy complexity; it is broker-backed evidence for the already-implemented order, protection, exit, portfolio, and recovery lifecycles while keeping the default configuration fail-closed.