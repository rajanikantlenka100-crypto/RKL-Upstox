# RKL Upstox Master Implementation Report

**Date:** 2026-09-10  
**Specification:** Signal Type 2 + independent multi-position contexts + guarded automatic entry + CCI/5R strategy exits + browser-first monitoring

## 1. Files Inspected

The implementation audit covered the runtime and test owners for configuration, broker integration, market data, candle aggregation, indicators, Type 1 breakout signals, RSI filtering, signal coordination, option resolution, order execution, positions, safety, stop-loss policy, SQLite persistence, terminal display, dashboard, existing reports, and the complete test suite.

Primary files inspected included `main.py`, `config.py`, `signals/breakout.py`, `signals/coordinator.py`, `signals/rsi_filter.py`, `market_data/candles.py`, `market_data/indicators.py`, `trading/positions.py`, `trading/safety.py`, `trading/stop_loss_policy.py`, `broker/order_manager.py`, `instruments/options.py`, `storage/sqlite_store.py`, `terminal_display.py`, `web_dashboard.py`, and the existing tests.

## 2. Files Modified

- `config.py`
- `main.py`
- `signals/breakout.py`
- `signals/coordinator.py`
- `trading/approval.py`
- `trading/positions.py`
- `storage/sqlite_store.py`
- `instruments/options.py`
- `terminal_display.py`
- `web_dashboard.py`
- `README.md`
- `tests/test_signal_replay.py`
- `tests/test_option_resolution.py`

## 3. Files Created

- `trading/exit_engine.py`
- `tests/test_signal_type2.py`
- `tests/test_exit_engine.py`
- `tests/test_multi_position_recovery.py`
- `MASTER_IMPLEMENTATION_REPORT_2026-09-10.md`

## 4. Signal Type 2

Added `Type2Engine` beside the existing `BreakoutEngine`. Type 1 logic was not rewritten.

Type 2 uses the existing `CandleEngine` data and evaluates:

- `Prev2`
- `Prev`
- `Running`
- small body at most 25% of range
- directional midpoint condition
- previous-versus-Prev2 condition
- previous-versus-running condition
- intrarunning breakout
- existing RSI filter result

CALL and PUT use the exact strict comparisons from the specification. Type 2 fires intrarunning, and duplicate suppression is enforced by running-candle timestamp plus direction.

The common `PutCallSignal` now explicitly carries:

- `signal_type` (`TYPE_1` or `TYPE_2`)
- `prev2_candle`
- `type2_conditions`

Signal type is included in audit records, runtime dashboard state, persisted payloads, and position context.

## 5. Multi-Position Support

The existing position dictionary remains keyed by independent `trade_id`; no singleton `current_position` was introduced.

Each position now carries independent:

- signal ID and signal type
- index and direction
- official option token/symbol/expiry/strike
- quantity
- entry price
- initial SL
- immutable initial risk
- CCI exit state
- 5R state
- exit reason
- strategy-exit state machine

Queued signals can now resolve independently instead of being lost when a primary/secondary slot is occupied.

Occupied option tokens are checked against both local runtime positions and broker-authoritative positions. The option resolver deterministically skips occupied official contracts and selects the next eligible official contract. It never fabricates an instrument key.

## 6. Automatic Entry

Added `AUTO_ENTRY_ENABLED`, defaulting to `ON`.

Valid signals now proceed through the existing option-resolution and safety pipeline without a normal manual approval wait. This does not bypass:

- `TRADING_MODE`
- `REAL_ORDERS_ENABLED`
- feed freshness
- history/intraday reconciliation
- option contract validation
- risk checks
- duplicate and unresolved-order checks
- database health
- fill confirmation
- protective SL confirmation
- static-IP controls

With the current safe configuration (`READ_ONLY`, real orders off), the system still cannot submit broker orders.

The normal approval and keyboard loops are not started when automatic entry is enabled. Manual approval support remains available only when automatic entry is explicitly disabled.

## 7. Exit Implementation

Created `StrategyExitState` in `trading/exit_engine.py`.

### CALL CCI exit

- CCI5 strictly greater than `100` arms the position.
- The trigger candle cannot confirm itself.
- A later candle confirms only when `current.low < previous.low`.

### PUT CCI exit

- CCI5 strictly less than `-100` arms the position.
- The trigger candle cannot confirm itself.
- A later candle confirms only when `current.high > previous.high`.

### 5R exit

- Initial risk is calculated once after confirmed fill as `entry_price - initial_sl`.
- The risk is stored per position.
- `5R = initial_risk * 5`.
- The running index candle triggers when `running.high - running.low > 5R`.
- The running candle may trigger intrabar.
- Each position uses its own risk and index.

Both strategy exits reuse the existing broker exit lifecycle: mark pending, cancel protective SL, submit SELL, confirm fill, and close only after broker confirmation.

## 8. Fixed Protective Stop

No trailing, breakeven, ATR trailing, profit locking, candle-based movement, or post-entry SL modification was added.

The protective stop remains fixed after placement. The 5R rule is an exit decision, not an SL modification.

Legacy CCI>150 and RSI>80 strategy exits were removed from the active candle-close path, and their configuration constants were removed.

## 9. External Exit and Recovery

Persisted positions are loaded before broker reconciliation. Multiple positions can be restored.

When broker state shows a local open position is closed, the position is marked:

```text
CLOSED
exit_reason=EXTERNAL_MANUAL_EXIT
```

No position is reopened, no new order is generated, and unrelated positions are not halted by that closure.

## 10. Database and Audit Changes

SQLite migrations add first-class fields to existing tables without deleting or resetting data.

Signal fields include signal type. Position fields include signal identity, contract identity, quantity, entry price, initial SL, initial risk, exit state, exit reason, and exit timestamps where available.

The existing JSON payload/audit path remains in place. New runtime events include Type 2 evaluation, CCI arm/confirmation, 5R trigger, and external manual exit classification.

## 11. Dashboard Changes

The active `web_dashboard.py` now exposes structured state for:

- signal history
- signal type
- Type 2 condition results
- automatic-entry status
- independent position details
- initial SL and initial risk
- 5R threshold/state
- CCI exit state
- protective SL state
- position state and exit reason

The browser remains view-only and has no normal manual-exit controls.

The dashboard continues to use the shared runtime snapshot and existing `/health`, `/ready`, `/state`, and `/events` endpoints.

## 12. Terminal Changes

The terminal no longer advertises normal approval/exit controls in the action display. Manual `X1..X4` and `EXITALL` keyboard execution paths were removed.

The terminal remains notification-oriented. Detailed position, signal, Type 2 trace, risk, and audit information belongs in the browser.

## 13. Tests Added or Updated

Added:

- Type 2 CALL/PUT positive and negative boundary tests.
- Intracandle duplicate suppression tests.
- CCI arm/later-candle confirmation tests.
- Strict CCI threshold tests.
- Strict 5R boundary tests.
- Direction-neutral and immutable-risk 5R tests.
- Multiple-position restore and external-close tests.
- Occupied-ATM deterministic fallback test.

Updated:

- Automatic-entry expectation in `test_signal_replay.py`.

## 14. Tests Executed

Focused validation included:

```powershell
py -m pytest -q tests/test_signal_type2.py
py -m pytest -q tests/test_exit_engine.py
py -m pytest -q tests/test_position_states.py tests/test_option_resolution.py
py -m pytest -q tests/test_multi_position_recovery.py
py -m pytest -q tests/test_dashboard_server.py tests/test_terminal_dashboard.py
```

Final full validation:

```powershell
py -m pytest -q
```

Final result:

```text
100 passed, 12 subtests passed in 3.96s
```

Diagnostics reported no errors in the modified runtime files.

## 15. Legacy-Path Review

The active Python implementation was searched for:

- CCI>150 and RSI>80 exits
- trailing and breakeven behavior
- SL modification behavior
- `current_position` singleton assumptions
- `X1..X4` and `EXITALL` execution
- old `_exit_underlying` and `_execute_exit_all` helpers

No active implementation path remains for those behaviors. Dated historical reports and unused dashboard copies still contain historical terminology; they are not runtime imports and should be treated as archival material.

## 16. Remaining Limitations

The following still require broker/account evidence and were not claimed as complete:

1. Real or sandbox broker-backed multi-order lifecycle verification.
2. Partial fills across multiple simultaneous positions.
3. Broker-backed stop-loss cancellation confirmation during strategy exit.
4. Broker-backed CCI and 5R exit fill confirmation.
5. Portfolio-stream validation for multiple independent positions.
6. Restart recovery with unresolved live orders and multiple open broker positions.
7. Static-IP registration and live order-IP matching.
8. Current Upstox token/account/session verification.
9. Dashboard authentication if Docker is exposed beyond a trusted local network.
10. Full browser automation coverage for live event rendering and filtering.

## 17. Safety Verdict

The implementation preserves the safe default. `AUTO_ENTRY_ENABLED=ON` means automatic progression through the guarded decision pipeline; it does not authorize live trading. `REAL_ORDERS_ENABLED=OFF` and `TRADING_MODE=READ_ONLY` continue to block broker order submission.

The repository is locally validated for the requested software behavior, but it is not evidence of production-ready real-money execution until controlled broker or sandbox validation covers the remaining order, stop, exit, reconciliation, and restart cases.
