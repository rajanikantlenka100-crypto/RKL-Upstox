# RKL Upstox Preflight Lifecycle Review

## Scope

Reviewed the production preflight flow across `main.py`, `services/preflight.py`, `config.py`, the order execution boundary, and execution-mode tests.

## Defect

Startup previously evaluated the preflight result and then forced the execution flag off for PRODUCTION and SANDBOX:

```python
config.set_preflight_passed(
    self.preflight_result.passed and config.EXECUTION_MODE not in {"PRODUCTION", "SANDBOX"}
)
```

As a result, `PREFLIGHT_PASSED` remained `False` in the two modes that require preflight before real-order execution.

## Correction

The startup assignment now preserves the actual preflight result:

```python
config.set_preflight_passed(self.preflight_result.passed)
```

This is the smallest lifecycle correction. It does not bypass preflight or set the flag directly to `True`.

## Lifecycle Behavior

1. Startup calls `run_local_preflight()` after history synchronization and option-universe initialization.
2. The returned `PreflightResult.passed` value is stored through `config.set_preflight_passed()`.
3. A successful preflight sets `PREFLIGHT_PASSED=True`.
4. A failed preflight sets `PREFLIGHT_PASSED=False`.
5. `_try_activate_execution_preflight()` retains its existing fail-closed behavior for live feed activation.
6. `config.order_execution_enabled()` remains unchanged:

```python
return ENABLE_REAL_ORDERS and EXECUTION_MODE in {"SANDBOX", "PRODUCTION"} and PREFLIGHT_PASSED
```

7. `OrderExecutor.place_approved_buy()` continues to recheck this gate immediately before broker order placement.

## Safety Properties Preserved

- READ_ONLY and BACKTEST cannot execute real orders.
- SANDBOX requires the SANDBOX execution mode and environment checks.
- PRODUCTION requires the live order environment.
- Failed preflight keeps the execution gate closed.
- `REAL_ORDERS_ENABLED=OFF` keeps the order gate closed even when preflight passes.
- No direct/manual `PREFLIGHT_PASSED=True` override was introduced.
- No strategy, signal, option-selection, candle, stop-loss, exit, reconciliation, websocket, broker API, or dashboard behavior was changed.

## Focused Tests Added

The execution-mode tests now cover:

- PRODUCTION preflight PASS opens the execution gate.
- PRODUCTION preflight FAIL keeps the gate closed.
- SANDBOX preflight PASS opens the execution gate.
- READ_ONLY and BACKTEST remain unable to execute real orders.
- Existing execution-mode, database, and order-gate protections remain covered.

## Test Results

Focused execution-mode tests:

```text
15 passed, 2 subtests passed in 0.47s
```

Complete suite:

```text
142 passed, 14 subtests passed in 5.42s
```

Diagnostics reported no errors.

## Files Changed

- `main.py`
- `tests/test_execution_modes.py`
- `PREFLIGHT_LIFECYCLE_REVIEW_REPORT.md`

No commit or push was performed.
