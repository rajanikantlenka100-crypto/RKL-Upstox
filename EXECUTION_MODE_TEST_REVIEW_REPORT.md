# RKL Upstox Execution-Mode Test Review

## Review Scope

This report covers the current Git state and the uncommitted changes in `tests/test_execution_modes.py` after commit `f80430d`.

No commits or pushes were performed during this review.

## Git State

- Branch: `master`
- HEAD commit: `f80430d`
- HEAD message: `Harden production database and execution gating`
- Uncommitted file: `tests/test_execution_modes.py`
- `tests/test_dashboard_server.py`: unchanged

## Committed Production Change

The committed `config.py` change allows the PRODUCTION engine to start with real order execution disarmed, provided the environment remains live:

```python
if EXECUTION_MODE == "PRODUCTION" and ORDER_ENV != "live":
    raise RuntimeError("PRODUCTION requires ORDER_ENV=live")
```

The previous requirement that `REAL_ORDERS_ENABLED` be `ON` for PRODUCTION startup was removed.

## Uncommitted Test Coverage

### PRODUCTION with Real Orders Disabled

`test_production_mode_allows_real_orders_disabled` verifies that `validate_runtime()` accepts:

- `EXECUTION_MODE=PRODUCTION`
- `ORDER_ENV=live`
- `AUTO_TRADING_ENABLED=ON`
- `AUTO_ENTRY_ENABLED=ON`
- `ENABLE_REAL_ORDERS=False`

### PRODUCTION with Sandbox Environment

`test_production_mode_rejects_sandbox_environment` verifies that PRODUCTION with `ORDER_ENV=sandbox` remains invalid.

### READ_ONLY with Real Orders Enabled

`test_read_only_mode_rejects_real_orders` verifies that READ_ONLY mode still rejects `REAL_ORDERS_ENABLED=ON`.

### Production Database Mapping

`test_production_mode_uses_mode_specific_database_without_override` verifies that the PRODUCTION mode database mapping is:

```text
data/production.sqlite3
```

The local `.env` does not currently contain a `DATABASE_PATH` override, so the mode-specific mapping is used when configuration is loaded.

### Legacy Database Protection

`test_legacy_database_override_is_rejected_outside_read_only` verifies that an explicit `market_data.sqlite3` path remains rejected for PRODUCTION.

The existing validation rule remains intact:

```python
if _DATABASE_OVERRIDE and EXECUTION_MODE != "READ_ONLY" and DATABASE_PATH.name == "market_data.sqlite3":
    raise RuntimeError("Legacy shared database path is allowed only in READ_ONLY mode")
```

### Real-Order Gate

`test_order_gate_remains_disabled_when_real_orders_are_off` verifies that `order_execution_enabled()` remains `False` when:

- `EXECUTION_MODE=PRODUCTION`
- `PREFLIGHT_PASSED=True`
- `ENABLE_REAL_ORDERS=False`

The production order gate remains:

```python
return ENABLE_REAL_ORDERS and EXECUTION_MODE in {"SANDBOX", "PRODUCTION"} and PREFLIGHT_PASSED
```

Therefore, production engine startup and real-order execution remain separate states. `REAL_ORDERS_ENABLED=OFF` continues to block real order submission.

### Execution-Mode Database Mismatch

The existing `test_database_rejects_execution_mode_reuse` remains present and verifies that a database initialized for READ_ONLY cannot be reused in PRODUCTION mode.

## Safety-Gate Review

The test changes do not weaken or bypass any production safety gate. The following checks remain in production configuration:

- Live PRODUCTION requires `ORDER_ENV=live`.
- Live real orders require `UPSTOX_ORDER_IP`.
- Static IP syntax is validated.
- READ_ONLY and BACKTEST cannot enable real orders.
- SANDBOX requires `ORDER_ENV=sandbox` and real orders enabled.
- `ORDER_ENV=sandbox` requires SANDBOX execution mode.
- `LIVE_BROKER_VALIDATION=ON` requires real orders enabled.
- `AUTO_ENTRY_ENABLED` remains required to be ON.
- Historical synchronization remains required.
- `order_execution_enabled()` still requires real orders enabled, a live-capable execution mode, and passed preflight.

No strategy, signal, option-selection, candle, stop-loss, exit, broker API, dashboard, or order-management logic was changed by the uncommitted test work.

## Test Results

### Focused Execution-Mode Tests

```text
11 passed in 0.34s
```

### Full Pytest Suite

```text
137 passed, 12 subtests passed, 1 failed in 6.16s
```

The failure is in the existing dashboard test:

```text
tests/test_dashboard_server.py::DashboardServerTests::test_dashboard_health_endpoint
RuntimeError: Dashboard could not bind to 127.0.0.1:8765
[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions
```

This is a local dashboard port-binding failure. It is unrelated to the execution-mode tests, which pass.

## Diff Summary

```text
config.py                     |  4 ++--
tests/test_execution_modes.py | 49 +++++++++++++++++++++++++++++++++++++++++++
2 files changed, 51 insertions(+), 2 deletions(-)
```

The `config.py` change is already included in commit `f80430d`; the uncommitted work is limited to the test additions in `tests/test_execution_modes.py`.

## Commit Recommendation

The uncommitted execution-mode tests are relevant, focused, and pass independently. They should be committed only after the dashboard port-binding failure is resolved and the complete suite passes with zero failures.

No commit or push was performed.
