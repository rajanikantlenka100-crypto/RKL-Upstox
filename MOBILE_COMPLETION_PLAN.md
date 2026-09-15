# RKL Mobile Completion Plan

**Target:** Complete the Android client without changing trading behavior

## Current state legend

- **DONE:** Implemented and tested in the repository.
- **PARTIAL:** A read-only first version exists, but it is not complete enough for production.
- **MISSING:** Must be designed and implemented.
- **BLOCKED:** Requires an environment, infrastructure, or security decision.

## Phase 1: Read-only contract hardening

| Work | State | Required completion evidence |
|---|---|---|
| Typed status DTO | PARTIAL | Contract test for every status field and null state |
| Typed market DTO | PARTIAL | Tests for all four indexes, closed market, stale feed, timestamps |
| Typed indicator DTO | MISSING | SMA10/20/30, SMA50, RSI14, RSI SMA5, CCI5 with backend timestamps |
| Typed option DTO | PARTIAL | ATM, expiry, strike, CE/PE, instrument key, LTP, OHLC, liquidity, active position |
| Typed signal DTO | PARTIAL | Signal 1/2/3 extensibility, conditions, filters, rejection and candidate trace |
| Typed order DTO | PARTIAL | Order ID, broker response, quantity, price, status, rejection reason |
| Typed position DTO | PARTIAL | Broker-authoritative fills, current LTP, P&L, SL, risk, R:R, exit state |
| Typed event DTO | PARTIAL | All required event categories and severity filtering |
| Typed report DTO | PARTIAL | Daily report list/detail and section-level statistics |
| Sandbox DTO | MISSING | Date/index/signal/strategy/result filters and trade analytics |

## Phase 2: Secure API architecture

1. Keep the trading engine and systemd service unchanged.
2. Run a dedicated API process or safely mount an API application over the existing state read model.
3. Put it behind an HTTPS reverse proxy or cloud load balancer.
4. Replace the bootstrap token with login and short-lived access/refresh sessions.
5. Add roles: admin, operator, read-only client, sandbox client.
6. Add device registration, token revocation, session expiry, and audit records.
7. Add rate limits, request validation, response limits, structured security logs, and correlation IDs.
8. Keep broker tokens, client secrets, SSH keys, and AWS credentials exclusively on the backend.
9. Expose control functions only through separate authorized commands with confirmation, idempotency, and server-side safety checks.

## Phase 3: Live transport

1. Use REST for initial state, reports, and historical screens.
2. Add a real authenticated WebSocket gateway for state deltas.
3. Publish backend snapshots or deltas; do not calculate signals or options in Flutter.
4. Add heartbeat, sequence number, reconnect backoff, stale-state detection, and resync-after-gap behavior.
5. Test network loss, backend restart, AWS unavailability, market closed state, and token expiry.

## Phase 4: Flutter completion

| Screen | State | Remaining work |
|---|---|---|
| Control centre | PARTIAL | Complete health matrix, heartbeat age, backend time, explicit stale states |
| Market | PARTIAL | OHLC/candle detail, timeframe selector, backend timestamps, responsive live stream |
| Index data | MISSING | Dedicated index comparison and historical view |
| Indicators | MISSING | Complete backend indicator table with PASS/FAIL context |
| Options | MISSING | Selected/active option details and liquidity display |
| Signals | PARTIAL | Detail page with all backend evaluations and candidate trace |
| Notifications | MISSING | Category filters, severity, unread state, detail view |
| Orders | PARTIAL | Complete order detail and broker response view |
| Positions | PARTIAL | Complete position detail, authoritative P&L and exit lifecycle |
| Sandbox | MISSING | Search/filter, trade table, metrics and performance report |
| Reports | MISSING | Date list, report detail, latency/errors/order sections |
| System health | PARTIAL | Component matrix, recent critical events, service state |
| Settings | MISSING | API endpoint, session, theme, device information, logout |
| Secure controls | MISSING | Confirmation flow and role-gated commands only after backend implementation |

## Phase 5: Quality gates

### Backend

- Full Python suite remains green.
- API contract tests cover every endpoint and error response.
- Authorization tests cover unauthenticated, expired, read-only, operator, admin, and sandbox roles.
- No mobile request can place an order or mutate trading state without an explicit approved control contract.
- Sandbox queries cannot read production tables.
- No credentials appear in responses or logs.

### Mobile

- Flutter analyzer passes.
- Unit tests cover DTO parsing, null states, stale data, and reconnect backoff.
- Widget tests cover all screen states and accessibility labels.
- Integration tests cover login, logout, token expiry, backend unavailable, network loss, reconnect, and market closed.
- Android release build produces a signed APK and AAB.
- Manual test confirms closing the app does not stop RKL.

## Completion definition

The mobile project is complete only when all MISSING items above have an implementation and test, the API is deployed behind HTTPS, session/role controls are audited, the Flutter release build is signed, and a controlled internal distribution has passed production-readiness review. The trading engine, strategy behavior, systemd unit, broker credentials, and production gating must remain unchanged.
