# RKL Upstox Production Readiness Report

**Date:** 2026-09-10  
**Current local mode:** `READ_ONLY`  
**Real orders:** Disabled  
**Production status:** Productionization implemented, but live deployment is not yet authorized or account-verified.

## 1. Work Completed

The existing architecture was preserved. No strategy rules were rewritten, no dummy market data or simulated fills were added, and real orders remained disabled during development and testing.

Implemented:

- Explicit execution modes: `READ_ONLY`, `BACKTEST`, `SANDBOX`, `PRODUCTION`.
- Legacy `TRADING_MODE=LIVE` compatibility mapping to `PRODUCTION`.
- Mode-specific database defaults:
  - `data/readonly.sqlite3`
  - `data/backtest.sqlite3`
  - `data/sandbox.sqlite3`
  - `data/production.sqlite3`
- SQLite execution-mode metadata and mismatch protection.
- Central order gate requiring:
  - executable mode,
  - real orders enabled,
  - passed preflight.
- Production automatic-entry requirement.
- Runtime preflight result with individual checks and failure reasons.
- Preflight state exposed through the authoritative dashboard snapshot.
- `/health` retained as liveness endpoint.
- `/ready` used for deployment readiness and degraded-state reporting.
- Container healthcheck changed to readiness.
- Read-only, backtest, sandbox, and production environment templates.
- DigitalOcean deployment package with systemd, Nginx, deploy, rollback, and health-check files.
- Historical replay default moved to the backtest database.
- Existing active-index and safety architecture retained.

## 2. Files Changed

- `config.py`
- `main.py`
- `storage/sqlite_store.py`
- `services/preflight.py`
- `services/__init__.py`
- `web_dashboard.py`
- `healthcheck.py`
- `Dockerfile`
- `docker-compose.yml`
- `historical_signal_replay.py`
- `README.md`
- `.env.example`
- `tests/test_signal_replay.py`

## 3. Files Created

- `.env.readonly.example`
- `.env.backtest.example`
- `.env.sandbox.example`
- `.env.production.example`
- `tests/test_execution_modes.py`
- `deployment/digitalocean/README.md`
- `deployment/digitalocean/env.example`
- `deployment/digitalocean/systemd/rkl-upstox.service`
- `deployment/digitalocean/nginx/rkl-upstox.conf`
- `deployment/digitalocean/deploy.sh`
- `deployment/digitalocean/rollback.sh`
- `scripts/health_check.py`
- `PRODUCTION_READINESS_REPORT_2026-09-10.md`

No project files were moved. Imports and the existing runtime layout were preserved.

## 4. Mode Contract

### READ_ONLY

- Real Upstox market data is allowed.
- Signals, indicators, option resolution, and dashboard state are allowed.
- Broker BUY, protective SL, cancellation, and SELL methods are blocked.
- Default local mode remains `READ_ONLY`.

### BACKTEST

- Intended for historical replay.
- Real orders are rejected by configuration.
- WebSocket mode is rejected.
- Default database is `data/backtest.sqlite3`.
- Replay script defaults to the backtest database.

### SANDBOX

- Requires `EXECUTION_MODE=SANDBOX`.
- Requires `REAL_ORDERS_ENABLED=ON`.
- Requires `ORDER_ENV=sandbox` and sandbox credentials.
- Uses the existing sandbox client routing.
- Requires broker-supported sandbox endpoint and account verification before use.

### PRODUCTION

- Requires `EXECUTION_MODE=PRODUCTION`.
- Requires `REAL_ORDERS_ENABLED=ON`.
- Requires `AUTO_TRADING_ENABLED=ON`.
- Requires `ORDER_ENV=live`.
- Requires a configured static order IP.
- Requires a passed runtime preflight before the order gate can open.
- Uses the real configured Upstox order client; no simulation path was added.

The legacy `TRADING_MODE=LIVE` value maps to `PRODUCTION` for migration compatibility. New deployments should use `EXECUTION_MODE` directly.

## 5. Real-Order Gate

`config.order_execution_enabled()` now returns true only when all of the following are true:

1. Real orders are enabled.
2. Execution mode is `SANDBOX` or `PRODUCTION`.
3. Runtime preflight has passed.

All existing `OrderExecutor` BUY, stop-loss, cancellation, and exit methods continue to call this gate. A configuration switch alone does not bypass preflight.

The current local result is:

```text
EXECUTION_MODE = READ_ONLY
REAL_ORDERS_ENABLED = OFF
ORDER_GATE = False
```

## 6. Production Preflight

The new preflight records individual checks and an exact summary. It checks:

- mode policy,
- real-order policy,
- order environment,
- database health and path,
- instrument master availability,
- IST timezone availability,
- active index resolution,
- historical synchronization,
- broker authentication state,
- position reconciliation state,
- order reconciliation state,
- unknown/unprotected positions,
- static order IP in executable live mode,
- order client availability where executable.

A failed preflight sets the dashboard component to `FAILED`, keeps the order gate closed, and halts executable modes.

The preflight is intentionally conservative. It does not submit a test order. It cannot prove broker fill, stop, cancellation, or exit behavior without an authorized broker-backed test environment.

## 7. Existing Trading Safety Preserved

The following existing protections remain active:

- fresh per-index feed requirement,
- historical reconciliation,
- option identity validation,
- fresh option LTP requirement,
- completed option OHLC requirement,
- tick-size and lot-size validation,
- fixed stop-loss validation,
- initial-risk validation,
- duplicate order protection,
- unknown-position protection,
- unprotected-position protection,
- broker-authoritative fill polling,
- broker-authoritative stop cancellation before strategy SELL,
- position reconciliation,
- SQLite audit persistence,
- no trailing SL,
- no breakeven SL.

No Type 1, Type 2, RSI, CCI, or 5R strategy condition was changed.

## 8. BUY and SL Flow

The existing flow remains:

```text
SIGNAL
-> RSI PASS
-> OPTION SELECTION
-> OPTION IDENTITY VALIDATION
-> LIVE OPTION LTP VALIDATION
-> COMPLETED OPTION OHLC VALIDATION
-> FIXED SL CALCULATION
-> RISK VALIDATION
-> SAFETY GATE
-> REAL BUY ONLY IF MODE/PREFLIGHT ALLOW
-> CONFIRMED FILL
-> IMMEDIATE PROTECTIVE SL
-> BROKER SL CONFIRMATION
-> SL_ACTIVE
```

The option stop reference is still based on the previous completed option candle low minus the configured buffer. Stop prices are tick aligned and validated before submission.

## 9. Exit Flow

The existing safe exit correction remains active:

```text
EXIT CONDITION
-> POSITION EXIT LOCK
-> CANCEL PROTECTIVE SL
-> WAIT FOR BROKER ORDER-BOOK CONFIRMATION
-> VERIFY CANCELLED STATUS
-> MARKET SELL
-> CONFIRM FULL SELL FILL
-> CLOSED
```

If cancellation is rejected, unknown, timed out, still open, or already completed by a stop fill, market SELL is not submitted blindly. Reconciliation is required.

## 10. Multi-Position and P&L

Independent position state remains keyed by `trade_id`. Each position owns its own:

- entry,
- fixed SL,
- initial risk,
- CCI state,
- 5R state,
- exit lock,
- exit order,
- quantity,
- P&L.

The current changes expose separate `unrealized_pnl`, `realized_pnl`, and P&L state fields. Portfolio events trigger position reconciliation.

## 11. Dashboard and Health

The canonical dashboard remains `web_dashboard.py`.

- `/health` is liveness-oriented.
- `/ready` is deployment readiness-oriented.
- Readiness considers authentication, database, history, broker, preflight, and halted state.
- The dashboard snapshot exposes execution mode and preflight details.
- The browser remains the detailed surface.
- The terminal remains notification-oriented.

The repository still contains older duplicate dashboard files. They are not imported by the production service or current dashboard tests. They should be archived or removed in a separately reviewed cleanup change.

## 12. Deployment Package

Added DigitalOcean-oriented artifacts:

- non-root `rkl-upstox.service`,
- protected environment template,
- readiness-gated `deploy.sh`,
- previous-release link and `rollback.sh`,
- localhost-bound Nginx reverse-proxy template with HTTPS/auth placeholders,
- `scripts/health_check.py`,
- deployment README.

The deployment scripts install dependencies, run tests, compile the project, restart the service, and require `/ready` before reporting success. They do not place orders.

Operational requirements still include:

- Ubuntu LTS host,
- non-root service user,
- reserved/static public IP,
- firewall policy,
- protected secret environment file,
- TLS and authentication before remote dashboard access,
- database backup/restore procedure,
- log rotation and monitoring.

## 13. Tests

Final result:

```text
117 passed, 12 subtests passed
```

Diagnostics reported no errors in the edited productionization files.

New regression coverage includes:

- mode and order-gate contract,
- database execution-mode mismatch protection,
- read-only preflight without an order client.

Existing coverage continues to cover candles, Prev2/Previous/Running, Type 1, Type 2, RSI, CCI, option selection, option OHLC, fixed SL, exit cancellation ordering, WebSocket normalization, positions, dashboard, and reconciliation boundaries.

## 14. Current Read-Only Verification

Verified locally:

```text
MODE              : READ_ONLY
REAL ORDERS       : OFF
DATABASE          : market_data.sqlite3 (explicit existing local override)
ACTIVE INDEXES    : NIFTY, BANKNIFTY, SENSEX, MIDCPNIFTY
ORDER GATE        : False
```

The current local environment was not switched to production and no broker order was sent.

## 15. Not Verified and Remaining Blockers

These cannot be honestly claimed from local tests alone:

1. Valid production Upstox authentication during market hours.
2. Production WebSocket and portfolio stream stability on the deployment host.
3. Registered static production order IP verification.
4. Actual Upstox sandbox endpoint and credentials.
5. Broker-backed sandbox BUY, fill, protective SL, cancellation, and SELL lifecycle.
6. Actual production order API behavior under an authorized procedure.
7. Partial-fill recovery against the broker.
8. Stop reconstruction after process restart.
9. Full active-position option subscription removal/reconciliation lifecycle.
10. DigitalOcean host, firewall, TLS, authentication, backup, and rollback execution.
11. External monitoring and log rotation.

Therefore the correct release status is:

```text
READ_ONLY: LOCALLY VALIDATED
BACKTEST: REPLAY PATH EXISTS, MODE ISOLATED
SANDBOX: CONFIGURATION STRUCTURE EXISTS, BROKER VERIFICATION REQUIRED
PRODUCTION: EXPLICITLY IMPLEMENTED, NOT ACCOUNT-VERIFIED OR AUTHORIZED
```

## 16. Safe Next Deployment Sequence

1. Keep `EXECUTION_MODE=READ_ONLY` and `REAL_ORDERS_ENABLED=OFF`.
2. Run the application with valid read-only credentials during market hours.
3. Verify all four indexes, historical sync, WebSocket freshness, option feed, dashboard readiness, and restart recovery.
4. Configure and validate the supported Upstox sandbox separately, if available.
5. Test broker lifecycle behavior through the authorized sandbox procedure.
6. Deploy read-only to the DigitalOcean host and verify firewall, TLS, authentication, backups, and rollback.
7. Only after documented operator approval and successful preflight, configure `EXECUTION_MODE=PRODUCTION` and production secrets on the host.
8. Confirm the startup preflight output is `PASS` before considering real order execution available.

No production order should be placed as part of this implementation task.
