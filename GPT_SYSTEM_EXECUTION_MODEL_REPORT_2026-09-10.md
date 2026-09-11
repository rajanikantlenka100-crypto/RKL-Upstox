# RKL Upstox System Execution Model and GPT Handoff Report

**Report date:** 2026-09-10  
**Scope:** Current Python implementation in this workspace, from startup to shutdown.  
**Purpose:** Give GPT or another engineer a complete operating model for timing, tick handling, candles, indicators, signals, option selection, risk controls, orders, exits, persistence, dashboard state, and failure recovery.

## 1. Executive Understanding

This is an Upstox index-feed and option-entry service. Its strategy observes index prices, builds 5-minute candles, calculates indicators from completed candles, detects Type 1 and Type 2 patterns, validates RSI, resolves an ATM option, calculates a fixed stop-loss, and only then reaches the broker order boundary.

The important safety principle is **fail closed**:

- A signal is not an order.
- A live index tick is not automatically valid for trading.
- A missing, stale, future, malformed, or unreconciled value blocks new signals or orders.
- A broker response that is uncertain is treated as unknown, not as rejected or safely absent.
- An open position without a confirmed protective stop halts further trading.
- Reconciliation is required before resuming after feed or broker uncertainty.

Current default configuration is effectively read-only for broker orders because `REAL_ORDERS_ENABLED=OFF`, but `AUTO_ENTRY_ENABLED=ON`. Therefore the logical signal path may automatically reach the order executor and then stop at the real-order-disabled boundary. This should be made explicit in deployment configuration or changed to a paper-order path.

## 2. Main Components and Ownership

| Area | Module or symbol | Responsibility |
|---|---|---|
| Configuration | `config.py` | Environment values, timeouts, instruments, periods, order mode |
| Startup/orchestration | `main.py`, `MarketDataService` | Auth, reconciliation, backfill, feed, signal and order flow |
| Broker adapter | `broker/upstox.py`, `UpstoxAdapter` | Authentication, WebSocket V3, REST polling, LTP, historical data |
| Tick model | `market_data/models.py` | `MarketTick` and `Candle` data contracts |
| Candle engine | `market_data/candles.py`, `CandleEngine` | Exchange-time 5-minute aggregation and rollover |
| Data health | `market_data/health.py`, `FeedHealth` | Last tick, stale status, signal eligibility |
| Indicators | `market_data/indicators.py` | CCI, Wilder RSI, RSI SMA |
| Type 1 signals | `signals/breakout.py`, `BreakoutEngine` | Low-first/high-second CALL or high-first/low-second PUT |
| Type 2 signals | `signals/breakout.py`, `Type2Engine` | Prev2/previous/running candle pattern |
| RSI filter | `signals/rsi_filter.py` | Five finalized candle comparisons |
| Coordinator | `signals/coordinator.py` | Primary/secondary slots, queuing, 60-second expiry |
| Option resolver | `instruments/options.py`, `main.py` | ATM contract, option LTP, option candle, stop reference |
| Safety | `trading/safety.py`, `SafetyGate` | Final fail-closed buy checks |
| Broker orders | `broker/order_manager.py`, `OrderExecutor` | Buy, stop, exit, confirmation, fill polling |
| Positions/exits | `trading/positions.py`, `trading/exit_engine.py` | Position state, protective stop, 5R and CCI exits |
| Persistence | `storage/sqlite_store.py` | Candles, raw feed, signals, orders, fills, positions, events |
| Reporting | `terminal_display.py`, `web_dashboard.py` | Shared read-only state and dashboard endpoints |

## 3. Configuration Defaults and Meaning

The active defaults in `config.py` are:

- Market data mode: `websocket`.
- WebSocket enabled: `ON`.
- WebSocket mode: `full`.
- WebSocket reconnect delay: 10 seconds.
- WebSocket reconnect attempts: 20.
- Polling interval: 1 second if REST fallback is used.
- Request timeout: 15 seconds.
- Candle timeframe: 5 minutes.
- Stale threshold: 15 seconds.
- CCI period: 5 candles.
- RSI period: 14 candles.
- RSI SMA period: 5 RSI values.
- RSI lookback: 5 finalized candles.
- Stop-loss buffer: 1.0 price unit.
- One current lot per new trade.
- Periodic REST reconciliation: every 7,200 seconds, or 2 hours.
- Historical request count: 100 candles.
- Real orders: `OFF` unless explicitly enabled.
- Auto entry: `ON`, and runtime validation requires it to remain `ON`.
- Active supported instruments: NIFTY, BANKNIFTY, SENSEX, MIDCPNIFTY. FINNIFTY is rejected by runtime validation.

Market time is Monday-Friday, from `09:15` inclusive to `15:30` exclusive in IST. Ticks outside that interval are logged and frozen for trading.

## 4. Full Startup Sequence

Startup is sequential. A failure in a required phase stops or halts the service.

1. Load configuration and validate runtime combinations.
2. Validate credentials and authenticate with Upstox.
3. Validate the access token with the user-profile API.
4. Check public IP. With real orders enabled, the IP must be allowed and registered at Upstox.
5. Initialize broker order and position clients.
6. Restore local position state and reconcile it against broker positions.
7. Reconcile outstanding order requests.
8. Fetch historical index candles.
9. Validate historical timestamps, duplicates, completed status, OHLC structure, and warm-up count.
10. Compare or repair stored historical candles.
11. Optionally compare historical and intraday REST candles.
12. Seed each candle engine and restore a persisted running candle when valid.
13. Require all configured instruments to be synchronized before normal running state.
14. Initialize the tracked option universe around the current underlying price.
15. Fetch option history where possible.
16. Start the market WebSocket or REST polling fallback.
17. Start the optional portfolio stream.
18. Start the dashboard and terminal display.
19. Mark signals ready only when safety state is `RUNNING` and recovery is complete.
20. Enter the 10-second service heartbeat loop, with a separate 1-second health/reconciliation loop.

Each startup phase records start, success/failure, elapsed time, and a display event. Startup elapsed time is not fixed: network authentication, instrument master, historical API, database, and option-universe calls dominate it.

## 5. Execution Time Model

### 5.1 Steady-state timing

| Activity | Frequency or deadline | Meaning |
|---|---:|---|
| WebSocket message | Exchange dependent | May contain zero or many instruments |
| REST fallback poll | 1 second by default | One LTP request per configured index per cycle |
| Stale-data test | 15 seconds | Beyond this, that index cannot generate signals |
| Dashboard refresh | Usually 500 ms in `web_dashboard.py` | Read-only state display |
| Periodic service heartbeat | 10 seconds | Lifecycle log, not a market decision |
| Health loop | 1 second | Refreshes feed health and dashboard sync state |
| Signal lifetime | 60 seconds | Coordinator active or queued signal expiry |
| Order fill polling | Every 2 seconds | Maximum 30 seconds before unknown outcome |
| REST reconciliation | Every 2 hours | Historical and broker-state consistency check |
| WebSocket reconnect | 10 seconds between attempts | Up to 20 configured attempts |

### 5.2 A typical tick path

For a valid index tick, the logical sequence is:

1. WebSocket receives the message.
2. Adapter normalizes LTP, exchange timestamp, volume delta, source, sequence, and event ID.
3. Raw event is journaled to SQLite.
4. `MarketDataService._on_tick()` checks market hours and known instrument.
5. Feed health is updated.
6. Candle engine inserts or updates the current 5-minute candle.
7. The running candle is persisted as `RUNNING`.
8. Dashboard latest tick and candle are updated.
9. Option universe refresh may be requested when the rounded ATM center changes.
10. Running exits are checked.
11. Type 1 breakout evaluation may run.
12. Type 1 RSI validation may run if a candidate appears.
13. Type 2 evaluation may run.
14. A passing signal is recorded, coordinated, resolved to an option, and sent through safety checks.

The implementation is callback/thread based. The exchange tick frequency is variable; a 5-minute candle does not mean the strategy waits five minutes to evaluate a breakout. Breakout conditions are evaluated on each valid tick inside the running candle. Indicators and RSI entry history use finalized candles only.

## 6. Tick Validation and Candle Construction

### 6.1 Tick requirements

A tick must have:

- A known configured index or a tracked option token.
- Positive LTP.
- A timezone-aware timestamp.
- A usable exchange timestamp for WebSocket data.
- A numeric LTP that can be converted to `float`.

The WebSocket adapter rejects and journals a feed event when LTP, exchange timestamp, or instrument identity is missing. Duplicate or non-increasing timestamps are ignored by the candle engine for that instrument.

### 6.2 Candle bucket formula

For timestamp $t$ and 5-minute timeframe:

$$
\text{bucket}(t) = t \text{ with minute } = 5 \times \left\lfloor\frac{\text{minute}(t)}{5}\right\rfloor,
$$

with seconds and microseconds set to zero.

Examples:

- `09:15:02` -> candle timestamp `09:15:00`.
- `09:19:59` -> `09:15:00`.
- `09:20:00` -> `09:20:00`.

### 6.3 OHLCV update

For the first tick in bucket $B$:

$$
O_B = H_B = L_B = C_B = \text{LTP}_1
$$

For each later tick:

$$
H_B = \max(H_B, \text{LTP}_i), \quad L_B = \min(L_B, \text{LTP}_i), \quad C_B = \text{LTP}_i
$$

The implementation adds non-negative incoming volume to the running volume. WebSocket cumulative volume is converted to a per-tick delta before reaching the candle engine.

The current candle is finalized only when a tick in a later bucket arrives. If the feed stops at 09:19:59, the 09:15 candle remains `RUNNING`; it is not falsely finalized just because wall-clock time passed.

A finalized candle is written/reconciled to SQLite and then used for indicators and closed-candle exits.

### 6.4 Gap behavior

If the new bucket is more than one configured timeframe after the current bucket, the system:

- Resets Type 1 and Type 2 sequence state.
- Disables signals.
- Marks recovery required.
- Degrades the safety gate.
- Records `UNSAFE_FEED_GAP`.
- Starts historical recovery/backfill.

This protects against interpreting a missing price interval as a continuous breakout sequence.

## 7. Indicator Formulas and Value Availability

Indicators are calculated from completed index candles unless explicitly stated otherwise.

### 7.1 Typical price

For candle $i$:

$$
TP_i = \frac{H_i + L_i + C_i}{3}
$$

### 7.2 CCI(5)

For the latest five candles:

$$
\overline{TP} = \frac{1}{5}\sum_{i=1}^{5} TP_i
$$

$$
MD = \frac{1}{5}\sum_{i=1}^{5}|TP_i - \overline{TP}|
$$

$$
CCI = \frac{TP_5 - \overline{TP}}{0.015 \times MD}
$$

If fewer than five candles exist, CCI is `None`. If mean deviation is zero, CCI is `0.0` to avoid division by zero.

CCI display examples:

- `CCI = 132.4`: CALL strategy exit can arm because it is strictly greater than 100.
- `CCI = -110.2`: PUT strategy exit can arm because it is strictly less than -100.
- `CCI = 100.0`: does not arm; threshold is strict.
- `CCI = None`: no CCI-based exit can arm.

### 7.3 Wilder RSI(14)

For each close change:

$$
\Delta_i = C_i - C_{i-1}
$$

$$
G_i = \max(\Delta_i, 0), \quad L_i = \max(-\Delta_i, 0)
$$

Initial averages over 14 changes:

$$
AvgGain_{14} = \frac{\sum_{i=1}^{14}G_i}{14}, \quad AvgLoss_{14} = \frac{\sum_{i=1}^{14}L_i}{14}
$$

Subsequent Wilder smoothing:

$$
AvgGain_t = \frac{AvgGain_{t-1}\times13 + G_t}{14}
$$

$$
AvgLoss_t = \frac{AvgLoss_{t-1}\times13 + L_t}{14}
$$

$$
RS = \frac{AvgGain_t}{AvgLoss_t}, \quad RSI = 100 - \frac{100}{1+RS}
$$

Special cases in the code:

- Average loss `0` and average gain positive -> RSI `100`.
- Both average loss and gain `0` -> RSI `50`.
- Not enough history -> `None`.

The implementation returns `None` for values before the RSI warm-up point. It does not use the running candle for the RSI filter.

### 7.4 RSI SMA(5)

The RSI moving average is:

$$
RSI\_SMA5_t = \frac{1}{5}\sum_{j=0}^{4} RSI_{t-j}
$$

It is `None` until five non-`None` RSI values exist.

### 7.5 Warm-up requirement

The startup backfill requires:

$$
14 + 5 + 5 = 24 \text{ completed candles minimum}
$$

This is the configured formula:

$$
\text{RSI period} + \text{RSI SMA period} + \text{RSI lookback period}
$$

In practice, more history is preferable because the first Wilder RSI values are initialization values, not a long-stabilized series.

## 8. Signal Logic

### 8.1 Type 1 breakout

Type 1 works inside the current running candle relative to the previous finalized candle.

A low cross is:

$$
LTP_{previous} > PreviousLow \quad \text{and} \quad LTP_{current} \le PreviousLow
$$

A high cross is:

$$
LTP_{previous} < PreviousHigh \quad \text{and} \quad LTP_{current} \ge PreviousHigh
$$

The engine records the first break side and waits for the opposite second break during the same running candle:

- Low first, then high -> `CALL`.
- High first, then low -> `PUT`.

The engine fires at most one CALL and one PUT per running candle and resets at a new candle or unsafe gap.

Example CALL:

- Previous high = 22,100; previous low = 22,000.
- Running candle starts at 21,990: low side is already seen.
- Tick sequence later reaches 22,001 after prior tick 21,999.
- Since the high condition is met at or above 22,100 only when that level is crossed, the second break creates a CALL.

Example with actual high cross:

- Prior tick = 22,099.
- Current tick = 22,101.
- Previous high = 22,100.
- Low was already the first side.
- Result: Type 1 CALL candidate at LTP 22,101.

A gap can invalidate this sequence even if the raw prices appear to cross both sides, because recovery resets the sequence.

### 8.2 Type 1 RSI filter

When a Type 1 candidate appears, the exact last five finalized candles are evaluated.

For each of those five candles:

- CALL match if `RSI14 < RSI14_SMA5`.
- PUT match if `RSI14 > RSI14_SMA5`.

All five RSI and SMA values must exist. The code returns:

- `PASS` if at least one of five periods matches.
- `REJECT` if all five are valid but zero match.
- `UNAVAILABLE` if a candle is non-final, history is not chronological/unique, fewer than five lookback candles exist, or an RSI/SMA value is missing.

A signal proceeds only for `PASS`.

Example CALL filter:

| Closed candle | RSI14 | RSI SMA5 | CALL condition |
|---|---:|---:|---|
| 1 | 42.0 | 45.0 | Pass |
| 2 | 44.0 | 43.0 | Fail |
| 3 | 41.0 | 44.0 | Pass |
| 4 | 46.0 | 45.0 | Fail |
| 5 | 40.0 | 43.0 | Pass |

Result: `PASS`, 3 of 5 matching periods. The running candle is excluded.

### 8.3 Type 2 signal

Type 2 uses `Prev2`, `Previous`, and `Running` candles. For CALL all of the following must be true:

1. Previous body is at most 25% of its range:
   $$|PreviousClose - PreviousOpen| \le 0.25 \times (PreviousHigh - PreviousLow)$$
2. Previous close is above its midpoint:
   $$PreviousClose > \frac{PreviousHigh + PreviousLow}{2}$$
3. Previous low is below Prev2 low.
4. Previous low is below running low.
5. Running high is above previous high.
6. RSI filter passes for CALL.

For PUT the directional inequalities are mirrored:

1. Small previous body.
2. Previous close below midpoint.
3. Previous high above Prev2 high.
4. Previous high above running high.
5. Running low below previous low.
6. RSI filter passes for PUT.

Type 2 can fire once per direction per running candle.

## 9. Signal Coordination and Expiry

Signals are assigned to slots:

- `PRIMARY`: NIFTY or SENSEX.
- `SECONDARY`: BANKNIFTY or MIDCPNIFTY.

One active signal is allowed in each slot. Additional signals wait in a priority queue. Priority is NIFTY, SENSEX, BANKNIFTY, MIDCPNIFTY.

Every signal expires after 60 seconds from creation. Expiry means no new entry should be created from that signal. A queued signal can be promoted only after the active signal is resolved.

The signal is recorded to:

- SQLite signal table.
- Signal event journal.
- Append-only signal audit JSONL.
- Candidate trace JSONL, when enabled.
- Dashboard state.

## 10. Option Resolution and Stop Reference

A valid index signal is still incomplete until an option is resolved.

The resolver checks or uses:

1. Underlying index identity.
2. Direction: CALL or PUT.
3. Current ATM strike interval.
4. Option contract master identity.
5. Occupied option tokens to avoid duplicate exposure.
6. Current option LTP.
7. Option LTP instrument identity.
8. Option LTP timestamp presence.
9. Option LTP freshness, using the 15-second stale threshold.
10. Previous option candle from live context, recent cache, or historical REST.
11. Option candle identity.
12. Option candle validity.
13. Previous option candle low for the initial stop reference.

Initial stop reference:

$$
SL_{reference} = OptionPreviousLow - SLBuffer
$$

With default buffer 1.0:

- Option previous low = 100.00.
- SL reference = 99.00.
- Option LTP = 110.00.
- Initial risk per unit = 110.00 - 99.00 = 11.00.
- One lot of 50 -> nominal risk = $11.00 \times 50 = 550.00$ price units.

The displayed capital is:

$$
Capital = OptionLTP \times LotSize
$$

The displayed initial risk is:

$$
Risk = \max(0, (OptionLTP - OptionPreviousLow + SLBuffer) \times LotSize)
$$

The selected contract quantity must equal exactly one current lot.

## 11. Entry Gate: Every Required Pass

Before a broker BUY, the system must pass all of these categories:

1. System state is exactly `RUNNING` and SafetyGate has no reasons.
2. Index feed is live and not stale.
3. Broker authentication is known valid.
4. Historical synchronization and reconciliation are complete.
5. Option contract is valid and belongs to the expected underlying, expiry, strike, and type.
6. Option LTP is fresh and its instrument identity matches the selected token.
7. Risk is valid and the protective stop is below confirmed entry risk.
8. Signal is valid and has not expired.
9. No duplicate or unresolved broker order exists.
10. No unknown broker position exists.
11. No unprotected local position exists.
12. SQLite/database journaling is available.
13. Order mode permits real execution.
14. Quantity is exactly one current lot.
15. Stop-loss values pass tick rounding and minimum-distance validation.

`SafetyGate.allow_buy()` returns `(False, reasons)` on any failure. The correct interpretation of a failed check is **do not submit the BUY**.

The order boundary itself additionally rejects orders when real orders are disabled. This is why read-only deployment should ideally disable auto-entry earlier and produce an explicit paper decision instead.

## 12. Order and Fill Timing

1. Reserve the logical order request and duplicate-check local and broker state.
2. Submit a market BUY.
3. If transport fails before certainty, classify as `ORDER_STATUS_UNKNOWN` and halt for reconciliation.
4. If broker explicitly rejects, record `ORDER_REJECTED`.
5. Poll order book every 2 seconds for up to 30 seconds.
6. Full fill -> create/open the position.
7. Partial fill -> create a partial position, place a stop for filled quantity, then halt for remaining-order reconciliation.
8. Fill timeout -> classify as unknown and do not retry blindly.
9. After full fill, submit the protective stop-loss.
10. Confirm stop order status is `OPEN` or `TRIGGER PENDING`.
11. Mark position `SL_ACTIVE` only after confirmation.

Position state progression normally is:

`PENDING_ENTRY -> OPEN -> SL_ACTIVE -> EXIT_PENDING -> CLOSED`

Failure states include `PARTIALLY_FILLED`, `UNPROTECTED`, `UNKNOWN`, and `ERROR`.

## 13. Protective Stop Formula and Validation

For a sell stop-loss:

- Trigger price and limit price must be positive.
- Contract must be an option contract with master-derived tick size.
- Both prices are rounded to the contract tick size.
- Limit price must be strictly below trigger price.
- Trigger must be at least `SL_MIN_TICK_DISTANCE` ticks below current option LTP.

If tick size is $0.05$, minimum distance is 2 ticks, current LTP is 110.00, then trigger must be below:

$$
110.00 - 2 \times 0.05 = 109.90
$$

If stop placement or confirmation fails after a fill, the position becomes unprotected and trading is halted. This is intentionally conservative; it requires manual or automated reconciliation before further entries.

## 14. Exit Logic

### 14.1 Protective broker stop

The protective stop is independent of strategy exits. It is intended to remain active at the broker after a confirmed entry.

### 14.2 Five-R exit

Initial risk is:

$$
R = EntryPrice - InitialSL
$$

Five-R threshold:

$$
5R = 5 \times R
$$

The running index candle triggers a strategy exit when:

$$
RunningHigh - RunningLow > 5R
$$

The comparison is strict `>`.

Example:

- Entry = 110.00.
- Initial SL = 99.00.
- $R = 11.00$.
- $5R = 55.00$.
- Running index range 55.01 -> exit pending.
- Running index range exactly 55.00 -> no trigger from this rule.

### 14.3 CCI exit

For a CALL position:

1. A closed candle with `CCI > 100` arms the exit.
2. A later closed candle must make a lower low than the prior comparison candle.
3. Then `CCI_CONFIRMATION` is triggered.

For a PUT position:

1. A closed candle with `CCI < -100` arms the exit.
2. A later closed candle must make a higher high than the prior comparison candle.
3. Then `CCI_CONFIRMATION` is triggered.

The arm candle cannot also be the confirmation candle. Missing CCI means no arm.

### 14.4 Exit execution

1. Mark position `EXIT_PENDING`.
2. Cancel the protective stop.
3. If cancellation is uncertain or rejected, mark the position unknown and halt.
4. Submit a market SELL.
5. Poll for fill.
6. Require full requested quantity.
7. Full fill -> mark `CLOSED`.
8. Partial, rejected, timeout, or unknown -> mark `UNKNOWN` and halt for reconciliation.

## 15. What Happens When a Tick Fails or Is Missed

### Case A: One WebSocket message has no LTP

- Raw event is recorded with `MISSING_LTP`.
- No `MarketTick` is created.
- No candle update occurs.
- No indicator update occurs.
- No signal is generated from that message.
- If later ticks continue within 15 seconds, the index can remain live.

### Case B: WebSocket message has no exchange timestamp

- Raw event is recorded with `MISSING_EXCHANGE_TIMESTAMP`.
- Tick is discarded.
- Feed error status is emitted.
- No candle or signal mutation occurs from that message.

### Case C: Unknown instrument key

- Raw event is recorded as `UNKNOWN_INSTRUMENT`.
- The token is ignored unless it is a tracked option token.

### Case D: Tick has malformed or non-numeric LTP

- WebSocket normalization can raise during `float(raw_ltp)`.
- The current explicit handling is stronger in REST LTP snapshots than in the WebSocket conversion path.
- Recommendation: wrap WebSocket numeric conversion and record `INVALID_LTP` without allowing one malformed feed item to escape the message loop.

### Case E: Tick timestamp is duplicated or goes backward

- `CandleEngine` ignores it for candle aggregation.
- It should not move OHLC state backward.

### Case F: A tick is missed briefly but the next tick is in the next normal bucket

- The prior candle finalizes when the next bucket tick arrives.
- The missing intra-candle ticks are unknowable; OHLC reflects only observed prices.
- Indicators can still calculate, but the candle may differ from official exchange OHLC.
- REST reconciliation can later detect a mismatch.

### Case G: A whole bucket or more is missed

- If the bucket jump is greater than one timeframe, breakout state resets.
- Signals pause.
- Safety degrades.
- Historical recovery starts.
- Signals resume only after all configured instruments are synchronized and safety is ready.

### Case H: No ticks for more than 15 seconds

- `FeedHealth` changes to `DATA_STALE`.
- `can_signal()` returns false.
- No new signal can be generated for that index.
- The 1-second health loop updates dashboard diagnostics.

### Case I: Future timestamp

- `FeedHealth.update()` marks the index `DATA_UNSAFE`.
- Current code updates health/display/candle path before the signal eligibility check, so a future tick may mutate running state even though it cannot safely generate a signal.
- Recommendation: reject future or otherwise unsafe ticks before candle and display mutation.

## 16. What Happens When an Index Value Is Missing

The system is index-specific. A missing NIFTY value does not automatically invalidate a healthy BANKNIFTY, SENSEX, or MIDCPNIFTY stream.

For the affected index:

- Its last tick age increases.
- It becomes stale after 15 seconds.
- Its signal engine is blocked.
- Its current candle remains at its last observed state.
- No fabricated close, high, low, or indicator is created.
- Other instruments can continue if their own health, history, and reconciliation are valid.

A historical missing candle is more severe:

- If the API returns insufficient warm-up, that instrument is `FAILED` for REST sync.
- The service does not consider all history ready.
- Startup remains halted or recovery remains incomplete.
- If intraday and historical OHLC disagree, the instrument becomes reconciliation-blocked and cannot produce a valid entry until repaired.

## 17. What Happens When Option Price Is Missing or Stale

The index signal may be created and queued, but option resolution can fail.

Failure examples:

- No candidate option contract.
- Option token already occupied.
- Option LTP missing, zero, malformed, or identity mismatch.
- Option LTP timestamp missing.
- Option LTP older than 15 seconds (`OPTION_LTP_STALE`).
- Previous option candle unavailable.
- Option candle identity or OHLC validation fails.
- Stop reference is invalid.

Result:

- No option BUY should be submitted.
- The coordinator signal is rejected.
- A validation event is recorded.
- An `OPTION RESOLUTION FAILED` status is emitted.
- The dashboard may need explicit pending-signal cleanup; current exception handling resolves the coordinator item but does not clearly remove every corresponding `pending_signals` UI entry. This is a cleanup gap to fix.

The safe operational result is **signal rejected, no trade**.

## 18. WebSocket Connection Failure and Recovery

### Initial SDK or connection failure

If the official SDK import or connection setup fails:

- Feed error is displayed.
- REST polling fallback starts.
- Poll fallback requests index LTP values every configured polling interval.
- Each successful REST value is converted into a tick using observation time.

### Runtime disconnect or error

On disconnect, reconnecting status, or feed error:

- Feed component becomes `STALE` or `RECOVERING`.
- `signals_enabled=False`.
- `recovery_required=True`.
- Safety gate becomes `DEGRADED`.
- New signals stop.
- WebSocket SDK auto-reconnects using 10-second delay and up to 20 attempts.

On reconnection:

1. Signals remain disabled.
2. Historical backfill/reconciliation runs.
3. Running and finalized candle state is reseeded/reconciled.
4. Recovery is considered successful only if all instruments are synchronized.
5. Safety returns to `RUNNING` if no hard halt remains.
6. Signals are re-enabled only after recovery and safety readiness.

A reconnect must therefore not immediately resume trading from the first post-reconnect tick; the historical gap must be checked first.

## 19. Database, Journal, and Persistence Failures

The system records raw market events, candles, signal events, audits, approvals, orders, fills, stops, exits, positions, and reconciliation events.

If raw market-event persistence fails, trading is halted. If candle persistence fails at close, trading is halted and a database failure event is recorded. If general journaling fails, the service sets `TRADING_HALTED` and displays a journal failure.

This is correct for auditability, but it means SQLite health is part of the trading control plane, not merely reporting. Backups, disk-space monitoring, WAL health, and recovery procedures are operational requirements.

## 20. Dashboard and Report Interpretation

The production startup imports `web_dashboard.py`, not `web_dashboard_fixed.py`. Tests also target `web_dashboard.py`.

Production dashboard endpoints include:

- `/health`: service health response.
- `/ready`: readiness response.
- `/state`: structured state snapshot.
- `/events`: recent event data.
- `/`: rendered UI.

The dashboard state is read-only and includes:

- Components and readiness.
- WebSocket status.
- Per-index ticks and candle context.
- CCI and RSI values.
- Feed age and status.
- Historical sync status.
- Signal and queue state.
- Option quote and resolution state.
- Order and position state.
- Recent events.

A displayed `--` for an indicator means the value is unavailable, not zero. A stale index can still show its last LTP; the health and age fields must be read together with that price.

Important maintenance warning: `web_dashboard_fixed.py` is a duplicate/inactive implementation according to current imports and tests. Changes there will not necessarily affect production behavior.

## 21. End-to-End Worked Example

Assume NIFTY is live at 09:25 inside the `09:25` running candle.

1. Previous finalized candle: high 22,100, low 22,000.
2. Running candle opened at 21,990, so the low side is first seen.
3. Valid ticks arrive: 21,999, then 22,101.
4. The second tick crosses previous high, creating Type 1 CALL candidate.
5. Last five finalized candles contain valid RSI/SMA values.
6. CALL comparison `RSI14 < RSI SMA5` matches 3 of 5 periods.
7. RSI result is `PASS`.
8. Signal is recorded and enters the PRIMARY slot with 60-second expiry.
9. ATM CE contract is selected, for example strike 22,100.
10. Fresh option LTP is 110.00.
11. Previous option low is 100.00 and buffer is 1.00.
12. Initial SL reference is 99.00.
13. One lot is 50, so displayed capital is 5,500 and nominal initial risk is 550.
14. Safety checks pass: live feed, broker auth, history, contract, option quote, risk, signal age, no duplicate order, no unknown/unprotected position, database ready.
15. If real orders are enabled, market BUY is sent for exactly 50.
16. Fill polling checks every 2 seconds for up to 30 seconds.
17. Full fill at 111.00 produces $R = 111 - 99 = 12$.
18. Stop trigger and limit are tick-rounded and validated.
19. Stop is confirmed open or trigger-pending.
20. Position becomes `SL_ACTIVE`.
21. Later, if running index range exceeds $5R = 60$, a strategy exit is requested; or if CALL CCI first exceeds 100 and a later candle breaks the prior low, CCI exit is requested.
22. Exit cancels stop, submits sell, requires a full fill, and then marks the position closed.

## 22. Status Meaning Guide

| Status | Meaning | Trading implication |
|---|---|---|
| `WAITING` | Startup or indicator history not ready | No signal |
| `LIVE` | Last tick is within stale threshold | Necessary but not sufficient |
| `DATA_STALE` | No recent tick | Block signal |
| `DATA_UNSAFE` | Timestamp is unsafe, e.g. future | Block signal; investigate mutation ordering |
| `RECOVERING` | Feed returned but history is being reconciled | Block signal |
| `DEGRADED` | Safety concern exists | Block buy |
| `RUNNING` | Safety state has no reasons | May pass buy gate |
| `TRADING_HALTED` | Hard safety or operational halt | No new entries |
| `OPTION DATA PENDING` | Index signal exists; option checks incomplete | No order yet |
| `AUTO ENTRY PENDING` | Option resolved and automatic entry path is selected | Still must pass final safety/order boundary |
| `SL_ACTIVE` | Position has confirmed protective stop | Normal protected position |
| `UNPROTECTED_POSITION` | Filled position lacks confirmed stop | Halt and reconcile |
| `UNKNOWN` | Broker result cannot be trusted | Halt and reconcile |
| `CLOSED` | Full exit confirmed | Position complete |

## 23. Current Risks and Recommendations

### Priority 1: Make read-only behavior unambiguous

Current defaults allow automatic logical entry to proceed until the real-order executor rejects because real orders are disabled. Add an explicit paper execution mode or require `AUTO_ENTRY_ENABLED=OFF` when real orders are disabled. Runtime validation currently requires auto-entry ON, so the architecture should be changed deliberately rather than relying on an exception.

### Priority 2: Reject unsafe ticks before mutation

Future timestamps are classified as unsafe, but `_on_tick()` updates some state before signal eligibility is evaluated. Validate timestamp, numeric values, market time, and feed safety before health, candle, storage, and dashboard mutation.

### Priority 3: Harden WebSocket numeric parsing

Wrap `float(raw_ltp)` and volume parsing in explicit error handling. Record a structured `INVALID_LTP` or `INVALID_VOLUME` raw-feed event and continue processing other instruments in the same message.

### Priority 4: Repair option-resolution UI cleanup

On option-resolution failure, remove or mark the related `pending_signals` entry and clear/update the displayed signal. Otherwise the UI may show an option-pending signal after the coordinator has rejected it.

### Priority 5: Add end-to-end failure tests

Existing unit coverage is strong for candles, RSI, breakout logic, safety, exits, network diagnostics, and dashboard boundaries. Add tests for:

- `_on_tick()` with future timestamps.
- Malformed WebSocket LTP.
- Whole-bucket feed gap and recovery.
- Option quote missing/stale/identity mismatch.
- Option-resolution failure cleanup.
- WebSocket reconnect followed by historical repair.
- Buy request unknown result.
- Partial fill with stop placement failure.
- Stop cancellation failure during exit.
- SQLite journal failure.
- Dashboard consistency after rejected option resolution.

### Priority 6: Consolidate dashboards

`web_dashboard.py`, `web_dashboard_fixed.py`, `web_dashboard_valid.py`, and `dashboard_tmp.py` create maintenance ambiguity. Keep one production implementation and one test target.

### Priority 7: Improve operational observability

Record for every decision:

- Exchange timestamp.
- Receive timestamp.
- Processing timestamp.
- Tick age.
- Current candle bucket.
- Previous and current LTP.
- Indicator values and `None` reasons.
- Every gate result.
- Signal age at option resolution.
- Option quote age.
- Broker request/response timestamps.
- Fill polling duration.
- Recovery start/end and instruments recovered.

## 24. GPT Handoff Instructions

When analyzing a future incident, GPT should ask in this order:

1. Was startup fully ready for every configured instrument?
2. What were exchange timestamp, receive timestamp, and processing timestamp?
3. Was the affected index `LIVE`, `DATA_STALE`, or `DATA_UNSAFE`?
4. Was the candle running or finalized?
5. Were previous, Prev2, and running candles present and chronological?
6. What were CCI, RSI14, RSI SMA5, and their exact availability reasons?
7. Did Type 1 require low-first/high-second or high-first/low-second?
8. Did Type 2 satisfy every condition?
9. Did the five-candle RSI filter return PASS, REJECT, or UNAVAILABLE?
10. Was the signal active, queued, expired, rejected, or auto-resolved?
11. Was option identity, LTP freshness, option candle, and stop reference valid?
12. Which SafetyGate check failed, if any?
13. Was a broker order submitted, rejected, partially filled, fully filled, or unknown?
14. Was a protective stop confirmed?
15. Was the position reconciled against broker state after the event?
16. Did database and audit writes succeed?

The correct final classification should separate:

- **Data failure:** missing, stale, unsafe, malformed, or unreconciled data.
- **Strategy rejection:** breakout or indicator conditions did not pass.
- **Safety rejection:** data or operational gate prevented entry.
- **Broker rejection:** broker explicitly rejected the request.
- **Broker unknown:** transport or status uncertainty requires reconciliation.
- **Position risk event:** a fill occurred but protection or exit status is uncertain.

## 25. Final System Verdict

The core execution model is conservative and auditable. It uses exchange timestamps, completed-candle indicators, explicit signal sequencing, option identity checks, fixed stop references, broker-authoritative reconciliation, and fail-closed state transitions.

The most important production improvements are not new indicators. They are boundary correctness and observability: prevent unsafe data from mutating state, make read-only mode explicit, harden malformed WebSocket parsing, clean up rejected signals in the UI, test reconnect and unknown-order cases end to end, and remove duplicate dashboard implementations.
