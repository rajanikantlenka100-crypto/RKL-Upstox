# RKL Mobile Data and Security Report

**Date:** 2026-09-13

## Authority and data flow

```text
Upstox
  -> existing RKL broker/feed adapters
  -> candle, indicator, signal, option, order, position, reconciliation engines
  -> TerminalDisplay.snapshot() and SQLite persistence
  -> authenticated mobile API
  -> Flutter Android client
```

The Android application is a client only. It must never become the source of truth for signals, filters, option selection, fills, position calculations, execution mode, or broker state.

## Current data arrangement

| Data | Current authority | Mobile exposure | Notes |
|---|---|---|---|
| Execution mode | `config.py` and runtime display state | `/api/mobile/status` | Never hard-code in Android |
| Market ticks | Upstox feed and `TerminalDisplay` | `/api/mobile/market` | Includes latest tick and health state |
| Candles | `CandleStore` SQLite | `/api/mobile/market` | Current/previous display state exposed |
| Indicators | Existing candle/signal processing | Partial | Complete typed indicator payload still required |
| Options | Existing option selector and quote state | `/api/mobile/options` | Flutter must not select options |
| Signals | Existing signal coordinator/audit/state | `/api/mobile/signals` | Full condition trace still required |
| Orders | Existing order manager and reconciliation | `/api/mobile/orders` | Complete broker response serializer still required |
| Positions | Existing position manager and SQLite | `/api/mobile/positions` | Fills and P&L must remain broker-authoritative |
| Events | Existing display/observability state | `/api/mobile/notifications` | Full telemetry query/filter API still required |
| Daily reports | `daily_reports` SQLite table | `/api/mobile/reports` | Detail and date filtering still required |
| Sandbox | Mode-specific database architecture | `/api/mobile/sandbox` marker only | Analytics query layer still required |

## Database separation

The existing configuration selects a mode-specific database by default:

- `data/readonly.sqlite3`
- `data/backtest.sqlite3`
- `data/sandbox.sqlite3`
- `data/production.sqlite3`

The mobile API must preserve this separation. A sandbox client must never query production tables, and a read-only client must not receive production credentials or execution controls.

Relevant persistence domains include candles, signals, approvals, orders, fills, stop losses, positions, exits, reconciliation events, signal events, position events, stop orders, system events, order requests, raw market events, telemetry events, and daily reports.

## Security currently present

- Upstox credentials remain backend environment configuration.
- Mobile routes require `Authorization: Bearer <MOBILE_API_TOKEN>`.
- The mobile client does not receive Upstox access tokens, client secrets, AWS credentials, or SSH credentials.
- Existing execution modes and production preflight remain in the trading engine.
- No mobile start/stop/restart command has been exposed.
- The dashboard defaults to localhost binding.

## Security currently missing or development-only

- The bearer token is a bootstrap shared secret, not a multi-user identity system.
- No token expiry, refresh, revocation, device registration, or biometric unlock exists.
- No admin/operator/read-only/sandbox authorization roles exist.
- No HTTPS gateway, certificate automation, rate limiting, WAF, or API audit middleware is included.
- Existing `/state` and `/events` dashboard routes are local dashboard routes and are not a public mobile security boundary.
- Mobile API responses are not yet redacted/typed for every sensitive payload.
- No secure control API exists for start/stop/restart.

## Required production security arrangement

1. Keep port `8765` private on AWS.
2. Terminate HTTPS at a reverse proxy or load balancer.
3. Forward only authenticated API/WebSocket traffic to a dedicated API process or controlled adapter.
4. Use short-lived access tokens and rotating refresh tokens.
5. Bind sessions to registered devices and support revocation.
6. Enforce roles and least privilege on every endpoint.
7. Add immutable audit events for login, device changes, report access, sandbox access, and control requests.
8. Apply rate limits and payload-size limits.
9. Redact tokens, secrets, broker responses containing sensitive fields, and infrastructure details from client responses.
10. Store secrets in AWS secret management or protected environment configuration, never in Flutter source, APK assets, Git, or logs.
11. Require explicit confirmation and server-side safety checks for any future production-changing operation.
12. Run dependency, TLS, authentication, authorization, and mobile release security reviews before client distribution.

## Security acceptance tests

- Invalid, missing, expired, and revoked tokens are rejected.
- Read-only users cannot invoke control or order mutations.
- Sandbox users cannot read production data.
- Closing the app does not affect the RKL process.
- Backend remains safe when the Android client is offline or compromised.
- No broker or infrastructure credential is present in API responses, Flutter constants, APK strings, crash logs, or telemetry.
