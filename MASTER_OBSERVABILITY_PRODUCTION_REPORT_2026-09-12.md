# RKL Upstox
## Monday Full-Day Production Observability Report

**Report date:** 2026-09-12  
**Prepared for:** Full-market-session production execution test  
**Execution safety:** Preserved  
**Strategy logic:** Unchanged  
**Order safety and preflight:** Preserved  
**Commit/push:** Not performed

---

## 1. Executive Summary

A centralized persistent observability layer has been added to the existing SQLite architecture. The service now records operational telemetry in the same database used for candles, signals, orders, reconciliation, and runtime events.

The implementation provides:

- Append-only-style telemetry records with timestamp, severity, component, event type, message, exception, system state, recovery action, resolution, and JSON payload.
- Authentication lifecycle and broker REST API timing/error events.
- Websocket/feed status events, raw market-event persistence, tick counters, last-tick timestamps, and feed freshness diagnostics.
- Historical synchronization timing, candle counts, reconciliation status, and failures.
- Completed candle OHLC and reconciliation telemetry.
- Candidate trace forwarding for accepted and rejected signal candidates.
- Option-resolution event classification.
- Order request, broker acceptance, rejection, unknown-result, and fill telemetry.
- Periodic heartbeat snapshots for the major runtime components.
- Persistent daily reports with explicit `PASS`, `FAILED`, `NOT TESTED`, and `NOT OBSERVED` values.
- A command-line report generator for later operational use and dashboard/mobile integration.

The complete existing test suite passed: **147 tests, 0 failures, 0 errors**.

---

## 2. Scope and Safety Constraints

The following constraints were maintained:

| Constraint | Result |
|---|---|
| Do not change strategy logic | Preserved |
| Do not change trading rules | Preserved |
| Do not weaken preflight | Preserved |
| Do not change order safety | Preserved |
| Maintain fail-closed execution | Preserved |
| Use existing SQLite/storage architecture | Implemented |
| Persist data beyond terminal output | Implemented |
| Avoid incompatible reporting system | Implemented through existing SQLite store |
| No source hot reload | No hot-reload mechanism added |
| No unrelated refactoring | Changes kept to observability boundaries |
| Do not commit or push | Confirmed |

Telemetry is observational. It does not authorize orders, bypass safety gates, alter signal predicates, or change broker request parameters.

---

## 3. Architecture

### 3.1 Persistent storage

The existing `CandleStore` now creates and manages two additional SQLite tables:

### `telemetry_events`

| Column | Purpose |
|---|---|
| `event_id` | Unique telemetry event identifier |
| `timestamp` | Event timestamp with timezone information |
| `severity` | `INFO`, `WARNING`, `ERROR`, `CRITICAL`, `HALT`, or `RECOVERY` |
| `component` | Runtime owner such as `AUTH`, `BROKER`, `WEBSOCKET`, `HISTORY`, `CANDLES`, `SIGNALS`, `OPTIONS`, `ORDERS`, or `SYSTEM` |
| `event_type` | Machine-readable event classification |
| `message` | Human-readable event message |
| `exception` | Exception representation when applicable |
| `system_state` | Trading/runtime state at event time |
| `recovery_action` | Recovery action, when applicable |
| `resolution` | `OBSERVED`, `UNRESOLVED`, or another lifecycle resolution value |
| `payload` | JSON details including identifiers, timing, OHLC, broker responses, and diagnostics |

### `daily_reports`

| Column | Purpose |
|---|---|
| `report_date` | Local report date, primary key |
| `generated_at` | Report generation timestamp |
| `status` | Overall report status |
| `payload` | Complete JSON report |

The existing tables remain the authoritative domain records for candles, signals, approvals, orders, fills, stops, positions, exits, errors, reconciliation events, signal events, system events, order requests, and raw market events.

### 3.2 Service integration

`MarketDataService` owns a single `Observability` instance connected to its existing `CandleStore`. Existing runtime event routing through `_record_event` now also emits centralized telemetry while retaining the existing domain-table records.

`CandidateTrace` accepts an optional callback. The existing JSONL trace remains available, while every candidate trace record is also forwarded to SQLite telemetry.

`UpstoxClient` accepts an optional telemetry callback. REST responses and errors record method, URL, success/error state, and latency in milliseconds without storing credentials or secrets.

---

## 4. Coverage Matrix

### 4.1 Authentication and broker API

Implemented events and data:

- `AUTH_START`
- `AUTH_END`
- Authentication success/failure
- Token status such as `TOKEN VALID`, `TOKEN EXPIRED`, `TOKEN REJECTED`, or missing-token classification
- Authentication-code API timing
- Broker REST API response timing
- Broker REST API HTTP/network errors
- Broker API failure messages

Authentication failures are persisted before startup is blocked. A failed authentication lifecycle therefore remains visible in the daily report.

### 4.2 Websocket and market feed

Implemented:

- Feed connected/disconnected/reconnecting/error status telemetry
- Raw market-event persistence in the existing `raw_market_events` table
- Tick count
- Last tick timestamp
- Per-instrument feed health diagnostics
- Stale-feed age in seconds
- Unsafe feed-gap handling remains fail-closed and continues to disable signals
- Market-data processing failures remain visible as runtime errors

The heartbeat payload includes the latest tick count, last tick timestamp, and per-index feed-health diagnostics.

### 4.3 Historical data

Implemented:

- Historical fetch timing
- Total backfill timing
- Number of finalized candles received
- Duplicate timestamp rejection
- Out-of-order timestamp rejection
- Insufficient warm-up rejection
- Historical/local reconciliation result
- Historical/intraday mismatch events
- Synchronization status
- Failure reason and instrument identity

Historical synchronization telemetry is emitted in the `HISTORY` component and is compatible with existing lightweight test fixtures.

### 4.4 Candle engine

Every completed candle emits `CANDLE_COMPLETED` with:

- Instrument
- Expected timestamp
- Actual timestamp
- Open
- High
- Low
- Close
- Volume
- Store reconciliation result

Existing candle validation and five-minute aggregation rules are unchanged. Existing gap handling remains fail-closed.

### 4.5 Signal engine

Every candidate trace record is forwarded to persistent telemetry, including rejected candidates. This includes existing reason codes and payload fields from the breakout/type-2 engines.

The existing RSI path continues to persist:

- RSI pass/rejection/unavailable result
- Matching periods
- Evaluated timestamps
- RSI values
- SMA values
- Reason

Signal events remain in the existing signal tables and audit files, while centralized telemetry provides a unified operational stream.

### 4.6 Option selection

Option-related runtime events are classified under `OPTIONS`, including:

- Option history unavailable
- Option universe unavailable
- Option universe refresh
- Option resolution failure
- ATM center and instrument context where included by the existing event payload
- Official token/instrument identity through existing option and validation payloads

Existing option contract validation, expiry validation, liquidity selection, live quote freshness checks, and identity checks remain unchanged.

### 4.7 Order execution

The existing order lifecycle remains authoritative and is supplemented with centralized events:

- Approval and safety-gate events
- `ORDER_REQUEST_SENT`
- `ORDER_ACCEPTED`
- `ORDER_REJECTED`
- Unknown-result/timeout classification through existing `BUY_UNKNOWN` and `ORDER_STATUS_UNKNOWN` paths
- `ORDER_FILLED`
- Existing partial-fill, stop-loss, and position events
- Signal-to-order latency observation
- Broker response payload and order ID where available

Duplicate prevention remains enforced by the existing order request reservation and duplicate guards. The telemetry layer does not modify those checks.

---

## 5. Broker Rejection and Fill Semantics

The report explicitly distinguishes request delivery from broker acceptance and fill.

For a zero-balance or similar broker rejection:

```text
ORDER REQUEST REACHED BROKER = PASS
BROKER ACCEPTED/FILLED = FAILED
SL/FILL LIFECYCLE = NOT TESTED
REASON = broker response
```

The implementation does not infer a fill from a submitted request. `ORDER_FILLED` is only emitted after the existing fill-confirmation path reports a fill.

If no fill occurs, the SL/fill lifecycle is reported as `NOT TESTED`, not as a successful lifecycle.

---

## 6. Runtime Incidents and Severity

Centralized events support:

- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`
- `HALT`
- `RECOVERY`

Each event can include:

- Timestamp
- Component
- Event type
- Message
- Exception
- System state
- Recovery action
- Resolution status
- Structured JSON payload

Existing trading halts remain fail-closed. A halt prevents signal processing and order execution through the existing safety state. The daily report collects halts, recoveries, broker errors, and runtime errors separately.

---

## 7. Heartbeat

The periodic service loop now persists heartbeat snapshots containing:

- `AUTH`
- `DATABASE`
- `WEBSOCKET`
- `HISTORY`
- `CANDLES`
- `SIGNALS`
- `OPTIONS`
- `ORDERS`
- `SYSTEM`
- Tick count
- Last tick timestamp
- Per-instrument feed-health diagnostics

Heartbeats are rate-limited to one event per second by the observability layer to avoid uncontrolled database growth while retaining periodic operational state.

---

## 8. End-of-Day Report

The report generator persists a JSON report in `daily_reports` and returns the same structure to callers.

Report contents include:

- Report date and generation time
- System uptime
- Overall status
- Component statuses
- Event counts by component and event type
- Order verification status
- Latency observations
- Broker errors
- Runtime errors
- Halts and recoveries

Each component uses the required status vocabulary:

- `PASS`
- `FAILED`
- `NOT TESTED`
- `NOT OBSERVED`

A report is generated automatically during service shutdown before the SQLite connection closes.

### Manual report command

```powershell
python observability_report.py
```

For a specific local date:

```powershell
python observability_report.py --date 2026-09-12
```

The command uses the configured execution-mode database and prints the persisted report as JSON. The same `daily_reports` record is available to the web dashboard or Android application through a future read-only API without creating a second reporting database.

---

## 9. Tests Added and Executed

### Focused observability tests

`tests/test_observability.py` verifies:

1. Telemetry events persist in SQLite.
2. Daily reports persist and can be regenerated.
3. Authentication section status becomes `PASS` when its lifecycle is complete.
4. Broker request/acceptance/fill distinctions are correct for a rejected order.
5. SL/fill lifecycle is `NOT TESTED` when no fill occurs.
6. Candidate trace forwards every candidate, including rejected candidates.

### Focused regression results

- Observability, signal, and execution-mode tests: **23 passed**
- Static diagnostics on touched Python files: **No errors**

### Complete suite result

```text
Ran 147 tests in 3.166s
OK
```

No existing test failures or errors remain.

---

## 10. Exact Implementation Files

### New files

- [observability.py](observability.py)
- [observability_report.py](observability_report.py)
- [tests/test_observability.py](tests/test_observability.py)
- [MASTER_OBSERVABILITY_PRODUCTION_REPORT_2026-09-12.md](MASTER_OBSERVABILITY_PRODUCTION_REPORT_2026-09-12.md)

### Modified files

- [broker/upstox.py](broker/upstox.py)
- [main.py](main.py)
- [signals/candidate_trace.py](signals/candidate_trace.py)
- [storage/sqlite_store.py](storage/sqlite_store.py)

### Existing unrelated workspace changes

The workspace also contains existing changes/artifacts that were not created or reverted as part of this observability work:

- `tests/test_execution_modes.py`
- `EXECUTION_MODE_TEST_REVIEW_REPORT.md`
- `PREFLIGHT_GATE_CORRECTION_REPORT.md`
- `PREFLIGHT_GATE_ORDER_REVIEW.md`
- `PREFLIGHT_LIFECYCLE_REVIEW_REPORT.md`
- `tatuspython -m unittest discover -s tests -v`

These were left untouched.

---

## 11. Operational Readiness Assessment

### Ready

- Persistent SQLite telemetry storage
- Runtime event centralization
- Authentication and broker API timing/error capture
- Feed/candle/history telemetry
- Candidate trace persistence
- Order request/rejection/fill distinction
- Heartbeat persistence
- Daily report persistence
- Full test-suite validation
- Fail-closed order safety preserved

### NOT OBSERVED until the live session

The following cannot be truthfully marked as observed until the Monday full-market session runs:

- Actual live websocket connection and reconnect sequence
- Actual live tick volume and stale-feed interval
- Actual broker authentication latency under production network conditions
- Actual historical API latency and reconciliation counts
- Actual signal candidate volume and rejection distribution
- Actual option liquidity outcomes
- Actual broker order acceptance or rejection response
- Actual fill and SL lifecycle
- Actual end-of-day uptime and latency distributions

The implementation is prepared to record these values, but the report must retain `NOT OBSERVED` or `NOT TESTED` where the live session produces no corresponding event.

---

## 12. Recommended Monday Procedure

1. Start the service using the approved production configuration and existing preflight process.
2. Confirm the production database path is the intended mode-specific SQLite database.
3. Confirm the dashboard and service remain running through the full market session.
4. Do not infer fills from order submission messages.
5. At shutdown, allow the service to generate the daily report before terminating the process.
6. Run:

```powershell
python observability_report.py --date 2026-09-14
```

7. Archive the SQLite database and generated JSON report as the session evidence.
8. Review all `ERROR`, `CRITICAL`, `HALT`, `RECOVERY`, `ORDER_REJECTED`, and `BUY_UNKNOWN` events before declaring the execution test complete.

---

## Final Verification

**Implementation status:** COMPLETE  
**Production-session observation status:** PENDING LIVE SESSION  
**Test status:** PASS, 147/147  
**Safety status:** PRESERVED  
**Strategy status:** UNCHANGED  
**Commit/push status:** NOT PERFORMED
