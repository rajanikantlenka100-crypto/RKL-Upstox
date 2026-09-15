# RKL Mobile Change Report

**Date:** 2026-09-13  
**Scope:** First read-only Android client slice  
**Production engine:** Preserved as the authoritative source of truth

## Executive summary

A first mobile-client foundation has been added without changing strategy logic, broker credentials, systemd, production order gates, or the Upstox engine. The current implementation is suitable for local read-only development and architecture validation. It is **not yet a production-ready client distribution**.

The repository does not currently contain FastAPI, Flutter, or a client WebSocket server. The existing API surface is a Python standard-library dashboard server. The mobile implementation therefore uses a compatibility API over the existing authoritative dashboard snapshot instead of creating a second trading pipeline.

## Changes made

| Area | Change | State |
|---|---|---|
| Mobile configuration | Added `MOBILE_API_TOKEN` environment setting | Done |
| Mobile API | Added authenticated `/api/mobile/*` JSON reads | Done |
| Status | Exposes component state, execution mode, market state, preflight, heartbeat metadata | Done |
| Market | Exposes authoritative ticks, candles, health, and synchronization state | Done |
| Options | Exposes backend option universe, quotes, and active signal reference | Partial |
| Signals | Exposes active signal, queue, and signal history | Partial |
| Orders | Exposes current dashboard order state | Partial |
| Positions | Exposes current position state and details | Partial |
| Notifications | Exposes current dashboard event list | Partial |
| Reports | Exposes persisted daily reports from SQLite | Partial |
| Sandbox | Reports whether the current mode is SANDBOX; no analytics serializer yet | Partial |
| Authentication | Bearer token required for mobile API | Development-only |
| Flutter app | Added `mobile_app` read-only client shell | Development-only |
| Tests | Added mobile authorization tests and stabilized observability date test | Done |
| Editor diagnostics | Python workspace diagnostics now report no errors | Done |

## Files added or changed for this work

- `mobile_app/pubspec.yaml`
- `mobile_app/lib/main.dart`
- `mobile_app/README.md`
- `MOBILE_ARCHITECTURE.md`
- `MOBILE_CHANGE_REPORT.md`
- `MOBILE_COMPLETION_PLAN.md`
- `MOBILE_DATA_SECURITY_REPORT.md`
- `config.py`
- `.env.example`
- `main.py`
- `web_dashboard.py`
- `storage/sqlite_store.py`
- `tests/test_dashboard_server.py`
- `tests/test_observability.py`

Other modified or untracked files visible in Git status pre-date or belong to existing repository work and should not automatically be attributed to the mobile feature.

## Validation completed

- Python compilation: passed.
- Full Python tests: **149 passed, 14 expected subtests**.
- Dashboard and mobile API tests: passed.
- Bearer-token rejection test: passed.
- Authorized status read test: passed.
- Workspace diagnostics: no errors found.
- Flutter APK build: not run because Flutter is not installed on the current machine.

## Current limitations

1. The backend is not FastAPI. It is the existing standard-library HTTP server.
2. The client does not currently use a real WebSocket. The Flutter shell refreshes REST data periodically.
3. There is no login, refresh token, device registration, biometric unlock, role system, or session expiry.
4. The mobile API exposes dashboard-shaped state, not complete typed contracts for every requested screen.
5. Full signal condition evaluation, SMA filter results, rejection reasons, option liquidity, broker responses, fills, exits, and authoritative P&L are not fully serialized for mobile.
6. Sandbox test-period analytics, trade tables, win/loss metrics, and filtering are not implemented.
7. Start, stop, and restart control functions are intentionally not exposed.
8. The static token is not suitable as a public production credential.
9. HTTPS termination, rate limiting, audit middleware, and reverse-proxy deployment are not implemented in this repository.
10. Flutter UI tests, reconnect tests, Android release signing, and APK/AAB distribution tests remain outstanding.
