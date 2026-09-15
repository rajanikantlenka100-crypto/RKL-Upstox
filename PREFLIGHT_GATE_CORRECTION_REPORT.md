# Preflight Gate Correction Report

## Scope

Reviewed and corrected the preflight lifecycle so startup readiness checks cannot open the real-order execution gate before live-feed validation.

## Correction

The startup path now uses readiness-only behavior for PRODUCTION and SANDBOX:

```python
config.set_preflight_passed(
    self.preflight_result.passed
    and config.EXECUTION_MODE not in {"PRODUCTION", "SANDBOX"}
)
```

This keeps `PREFLIGHT_PASSED=False` after a successful startup preflight in executable modes.

## Intended Lifecycle

```text
STARTUP PREFLIGHT PASS
    -> readiness only
    -> PREFLIGHT_PASSED remains False in PRODUCTION/SANDBOX
    -> order_execution_enabled() remains False

LIVE FEED PREFLIGHT PASS
    -> _try_activate_execution_preflight() uses require_live_feeds=True
    -> PREFLIGHT_PASSED becomes True
    -> execution gate can open
```

## Safety Properties

- Failed startup preflight keeps the gate closed.
- Failed live-feed preflight keeps the gate closed.
- PRODUCTION live-feed preflight success can open the gate.
- SANDBOX live-feed preflight success can open the gate.
- READ_ONLY and BACKTEST remain non-executable.
- `REAL_ORDERS_ENABLED=OFF` remains non-executable.
- `order_execution_enabled()` was not changed.
- `OrderExecutor.place_approved_buy()` still rejects execution when preflight has not passed.
- No strategy, signal, option, candle, stop-loss, exit, reconciliation, websocket, broker, or dashboard logic was changed.

## Tests Added or Updated

Focused execution-mode tests cover:

1. PRODUCTION startup preflight PASS remains readiness-only.
2. SANDBOX startup preflight PASS remains readiness-only.
3. PRODUCTION live-feed preflight PASS opens the execution gate.
4. PRODUCTION live-feed preflight FAIL keeps the gate closed.
5. SANDBOX live-feed preflight PASS opens the gate.
6. READ_ONLY and BACKTEST remain non-executable.
7. `REAL_ORDERS_ENABLED=OFF` remains non-executable.
8. The order boundary rejects execution when `PREFLIGHT_PASSED=False`.

## Results

Focused execution-mode tests:

```text
18 passed, 2 subtests passed in 0.62s
```

Complete suite:

```text
145 passed, 14 subtests passed in 5.26s
```

## Changed Files

- `tests/test_execution_modes.py`
- `PREFLIGHT_GATE_CORRECTION_REPORT.md`

The readiness-only startup assignment in `main.py` already matched the requested correction in the committed baseline; no additional production diff was required.

No commit or push was performed.
