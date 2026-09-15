# Preflight Gate Order Review

## Scope

Reviewed the current preflight lifecycle across `main.py`, `services/preflight.py`, `config.py`, and `broker/order_manager.py`.

## Verdict

The current lifecycle does **not** guarantee that startup preflight is readiness-only for PRODUCTION and SANDBOX.

A successful startup preflight can set `PREFLIGHT_PASSED=True` before the `require_live_feeds=True` validation runs.

## Current Startup Flow

After history synchronization and option-universe initialization, startup calls:

```python
self.preflight_result = run_local_preflight(
    store=self.store,
    instruments=self.instruments,
    display=self.display,
    position_manager=self.position_manager,
    order_manager=self.order_manager,
    public_ip=self.public_ip,
)
```

The `require_live_feeds` argument is omitted, so `services/preflight.py` uses its default:

```python
require_live_feeds=False
```

That startup check does not require all index feeds to be live or option quotes to be present.

Startup then executes:

```python
config.set_preflight_passed(self.preflight_result.passed)
```

Therefore a successful startup preflight immediately sets `PREFLIGHT_PASSED=True`.

## Safety-State Timing

Before startup preflight, successful history synchronization calls:

```python
self.safety.running()
self.trading_state = SystemState.RUNNING
```

A passing startup preflight leaves the service in `RUNNING` state. At that point, the preflight flag and the safety state can both indicate readiness before live-feed validation has occurred.

## Execution Gate

The gate remains:

```python
return ENABLE_REAL_ORDERS and EXECUTION_MODE in {"SANDBOX", "PRODUCTION"} and PREFLIGHT_PASSED
```

Consequently, with real orders enabled, a passing startup preflight is sufficient to make `order_execution_enabled()` return `True` before live-feed validation.

## Live-Feed Activation Method

`_try_activate_execution_preflight()` requests the stricter check:

```python
result = run_local_preflight(
    ...,
    require_live_feeds=True,
)
```

However, it exits immediately when the flag is already true:

```python
if config.EXECUTION_MODE not in {"PRODUCTION", "SANDBOX"} or config.PREFLIGHT_PASSED:
    return
```

Thus, if startup set `PREFLIGHT_PASSED=True`, the live-feed validation is skipped entirely.

## Activation Call Sites

`_try_activate_execution_preflight()` is called from `_on_tick()`:

1. For option ticks, after updating the option engine and quote state.
2. For index ticks, after updating the index engine, health state, candle context, and display state.

Both calls occur after the adapter starts. Neither call can perform live-feed validation if startup already set `PREFLIGHT_PASSED=True`.

## Order Boundary

`OrderExecutor.place_approved_buy()` independently checks:

```python
if not config.order_execution_enabled():
    raise RuntimeError("Real orders are disabled; ...")
```

The main order path also checks the broader `SafetyGate.allow_buy()` conditions before calling the order executor.

This preserves the `ENABLE_REAL_ORDERS` requirement, but it does not correct the ordering problem: the preflight portion of the gate may already be open before live-feed validation.

## Exact Unsafe Path

```text
history synchronization passes
    -> safety.running()
    -> startup run_local_preflight(require_live_feeds=False)
    -> startup preflight passes
    -> config.set_preflight_passed(True)
    -> order_execution_enabled() can return True
    -> adapter starts
    -> first tick calls _try_activate_execution_preflight()
    -> method returns because PREFLIGHT_PASSED is already True
    -> require_live_feeds=True validation is skipped
```

## Smallest Safe Correction

Keep startup preflight readiness-only for executable modes:

```python
config.set_preflight_passed(
    self.preflight_result.passed
    and config.EXECUTION_MODE not in {"PRODUCTION", "SANDBOX"}
)
```

Then the intended lifecycle is restored:

```text
startup preflight PASS
    -> PREFLIGHT_PASSED remains False for PRODUCTION/SANDBOX
    -> order_execution_enabled() remains False
    -> live tick calls _try_activate_execution_preflight()
    -> require_live_feeds=True validation runs
    -> failed live-feed preflight keeps the gate closed
    -> successful live-feed preflight calls set_preflight_passed(True)
    -> execution gate opens
```

This correction does not bypass preflight, does not hard-code `PREFLIGHT_PASSED=True`, and does not alter strategy or order logic.

## Preserved Behavior

- READ_ONLY and BACKTEST remain non-executable.
- `ENABLE_REAL_ORDERS` remains required by the order gate.
- `PREFLIGHT_PASSED` remains required by the order gate.
- Failed preflight keeps the gate closed.
- The order executor retains its immediate gate check.
- No strategy, signal, option-selection, candle, stop-loss, exit, reconciliation, websocket, broker API, or dashboard behavior is changed by the proposed correction.
