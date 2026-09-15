# RKL Mobile Client
## Detailed Implementation and Production Readiness Report

**Report date:** 2026-09-13  
**Repository:** RKL Upstox  
**Scope:** Read-only mobile client integration around the existing RKL production engine  
**Production behavior:** Existing production engine remains authoritative and fully enabled when its existing production configuration is active.

---

## 1. Executive summary

The RKL mobile client has been implemented as a read-only observer of the existing RKL runtime.

The Android client does not connect to Upstox, does not contain broker credentials, does not calculate signals, does not select options, does not calculate fills or P&L, and does not submit or modify orders.

The existing RKL engine remains responsible for:

- Upstox authentication
- Upstox market-data WebSocket
- historical synchronization
- candle creation
- indicator calculation
- signal generation
- option selection
- order execution
- broker reconciliation
- position state
- production execution gates
- observability
- SQLite persistence
- systemd lifecycle

The mobile layer reads the authoritative runtime state from the existing `TerminalDisplay.snapshot()` and selected backend persistence. It is a presentation and transport layer only.

### Current result

| Area | Status |
|---|---|
| Existing RKL engine | Preserved |
| Existing production execution | Preserved and not disabled by mobile work |
| Existing systemd | Not changed by mobile implementation |
| Existing Upstox credentials | Not changed or exposed |
| Versioned REST mobile API | Implemented |
| Authenticated mobile WebSocket | Implemented |
| WebSocket sequence and heartbeat envelope | Implemented |
| Flutter read-only client | Implemented as development client |
| Multi-user production authentication | Not implemented |
| HTTPS public deployment | Not implemented in this workspace |
| Flutter analyzer/APK build | Not run because Flutter is unavailable locally |
| Production distribution readiness | Not yet complete |

---

## 2. Existing authoritative architecture

```mermaid
flowchart TD
    UPREST[Upstox REST] --> ADAPTER[broker/upstox.py]
    UPWS[Upstox Market WebSocket] --> ADAPTER
    ADAPTER --> ENGINE[MarketDataService in main.py]
    ENGINE --> CANDLE[CandleEngine]
    CANDLE --> IND[Indicators]
    ENGINE --> SIGNAL[Signal engines and filters]
    ENGINE --> OPTION[Option selector]
    ENGINE --> ORDER[Order manager]
    ENGINE --> POSITION[Position manager and reconciliation]
    ENGINE --> SAFETY[Preflight and safety gates]
    ENGINE --> SNAP[TerminalDisplay.snapshot()]
    ENGINE --> SQLITE[(Mode-specific SQLite)]
    ENGINE --> OBS[Observability and audit logs]
    SNAP --> DASH[Existing dashboard HTTP server]
    SNAP --> API[Mobile read-only REST/WebSocket layer]
    API --> APP[Flutter Android client]
```

### Runtime source of truth

`TerminalDisplay.snapshot()` is the current in-memory read model. It contains runtime information including:

- instrument names
- latest ticks
- current and previous candles
- previous-2 candle context
- option universe
- option quotes
- indicators
- indicator timestamps and reasons
- feed health
- REST synchronization state
- system status
- WebSocket status
- reconnect count
- startup phase
- active signal
- signal history
- signal queue
- positions
- position details
- orders
- events
- preflight result
- execution mode
- market status

The mobile application consumes this state. It does not create another market-data or trading pipeline.

---

## 3. Files changed for the mobile implementation

### Backend and configuration

- `.env.example`
  - documents `MOBILE_API_TOKEN`
  - documents `MOBILE_WS_HOST`
  - documents `MOBILE_WS_PORT`
- `config.py`
  - loads mobile API token and WebSocket bind settings
- `main.py`
  - passes mobile transport configuration to the existing dashboard server
- `web_dashboard.py`
  - adds versioned mobile REST routes
  - adds authenticated WebSocket listener
  - serializes existing snapshot state
  - does not add trading mutations
- `requirements.txt`
  - adds the `websockets` dependency
- `storage/sqlite_store.py`
  - adds daily report read access for the mobile report view

### Tests

- `tests/test_dashboard_server.py`
  - mobile token rejection
  - authorized status access
  - versioned route access
  - authenticated WebSocket envelope
  - unauthenticated WebSocket policy closure
- `tests/test_observability.py`
  - stabilizes the report test date so it uses the date on which test events are created

### Flutter client

- `mobile_app/pubspec.yaml`
  - Flutter application metadata
  - HTTP dependency
  - WebSocket channel dependency
- `mobile_app/lib/main.dart`
  - read-only API client
  - live WebSocket client
  - reconnect handling
  - sequence-gap REST refresh
  - control centre
  - market view
  - index data
  - indicators
  - options
  - signals
  - notifications
  - orders
  - positions
  - sandbox state
  - reports
  - system health
  - settings/read-only state
- `mobile_app/README.md`
  - local installation
  - emulator run instructions
  - release build instructions
  - distribution guidance

### Important repository note

The worktree contains other modified and untracked files that were present as existing repository work, including broker, observability, execution-mode, and report files. They must be reviewed separately before commit. They are not automatically attributable to this mobile implementation.

---

## 4. API implementation

### Authentication

The current development/integration API uses:

```text
Authorization: Bearer <MOBILE_API_TOKEN>
```

Missing or invalid bearer tokens are rejected. The token is a backend setting and must not be an Upstox token.

This authentication is suitable for controlled development and integration only. It is not sufficient for public multi-user distribution.

### Versioned REST endpoints

Implemented read-only routes:

```text
GET /api/v1/mobile/status
GET /api/v1/mobile/market
GET /api/v1/mobile/indices/{index}
GET /api/v1/mobile/options/{index}
GET /api/v1/mobile/signals
GET /api/v1/mobile/signals/{signal_id}
GET /api/v1/mobile/notifications
GET /api/v1/mobile/orders
GET /api/v1/mobile/orders/{order_id}
GET /api/v1/mobile/positions
GET /api/v1/mobile/positions/{trade_id}
GET /api/v1/mobile/reports
GET /api/v1/mobile/reports/{date}
GET /api/v1/mobile/sandbox
```

Legacy `/api/mobile/*` compatibility routes remain available for existing local integration. The versioned `/api/v1/mobile/*` routes are the intended client contract.

### Endpoint behavior

| Endpoint | Current behavior | Authority |
|---|---|---|
| `/status` | Runtime components, mode, market state, preflight, startup, reconnects, server time | `TerminalDisplay.snapshot()` |
| `/market` | All configured indexes, ticks, candles, prior candles, health, synchronization | Runtime display state |
| `/indices/{index}` | One index market subset | Runtime display state |
| `/options/{index}` | Backend option universe, quotes, and active signal reference | Option selector/display state |
| `/signals` | Active signal, signal history, queue | Signal coordinator/display state |
| `/signals/{signal_id}` | Matching backend signal detail | Signal history/display state |
| `/notifications` | Current event list with category/severity query fields reserved | Display event state |
| `/orders` | Current order view | Display/order state |
| `/orders/{order_id}` | Matching order detail when present | Display/order state |
| `/positions` | Positions and position details | Position manager/display state |
| `/positions/{trade_id}` | Matching position detail when present | Position manager/display state |
| `/reports` | Persisted daily reports | `daily_reports` SQLite table |
| `/reports/{date}` | Matching persisted report | `daily_reports` SQLite table |
| `/sandbox` | Explicit no-data state in current implementation | Must be expanded with sandbox repository |

### Read-only guarantee

No mobile REST route implements:

- BUY
- SELL
- CANCEL
- order modification
- position modification
- strategy modification
- configuration modification
- systemd control
- broker credential access
- production database mutation

The mobile API reads state. It does not call `OrderExecutor` mutation methods.

---

## 5. WebSocket implementation

### Endpoint

```text
WS /api/v1/mobile/stream
```

The listener is configured independently from the dashboard HTTP port. Defaults are:

```text
MOBILE_WS_HOST=127.0.0.1
MOBILE_WS_PORT=8766
```

The listener is optional and non-fatal. If it cannot bind, the existing RKL engine and dashboard remain running.

### Message envelope

Messages contain the required protocol fields:

```json
{
  "protocol": "rkl.mobile.v1",
  "sequence": 1,
  "event_id": "snapshot-1",
  "event_type": "STATE_SNAPSHOT",
  "server_time": "2026-09-13T09:15:00+05:30",
  "source_timestamp": null,
  "payload": {}
}
```

Supported event types currently include:

- `WELCOME`
- `STATE_SNAPSHOT`
- `STATE_DELTA`
- `HEARTBEAT`

### Current behavior

1. Client authenticates with the bearer token.
2. Server sends a `WELCOME` message.
3. Server serializes the authoritative runtime snapshot.
4. Server sends a first state message.
5. Server sends a new state message when the snapshot changes.
6. Server emits a heartbeat when the state remains unchanged for the heartbeat interval.
7. Every message has a monotonically increasing connection sequence.
8. The Flutter client detects a sequence gap and calls REST refresh.
9. The Flutter client reconnects after stream closure or error.
10. Closing the app does not stop the RKL process.

### Current limitation

The current stream compares serialized full snapshots. It is a safe first observer implementation but is not yet an optimized semantic delta protocol. Before serving many clients, replace full serialized snapshot comparison with typed event/delta publishing and bounded replay/resynchronization.

---

## 6. Flutter client behavior

### Client responsibilities

The Flutter app:

- requests initial state through REST
- opens the authenticated WebSocket
- displays backend values
- shows backend unavailable errors
- reconnects after disconnect
- refreshes REST state after sequence gaps
- exposes read-only navigation
- displays explicit `NO SANDBOX DATA` when no sandbox result exists

### Client does not perform

The Flutter app does not:

- connect to Upstox
- store Upstox access tokens
- store Upstox client secrets
- access AWS credentials
- access SSH credentials
- read `.env`
- calculate indicators
- calculate signals
- select options
- calculate fills
- infer broker state
- calculate authoritative P&L
- place, cancel, or modify orders
- start, stop, or restart RKL

### Navigation

The current client provides:

- Control Centre
- Market
- Index Data
- Indicators
- Options
- Signals
- Notifications
- Orders
- Positions
- Sandbox
- Reports
- System Health
- Settings

The bottom navigation exposes the primary views. A drawer exposes the complete viewer section list.

### Current UI limitations

The current Flutter file is an intentionally compact first client and still needs:

- decomposition into feature folders
- typed DTO model classes
- production authentication screens
- secure token storage
- theme persistence
- biometric unlock
- accessibility review
- dedicated detail screens
- filtering controls
- pagination
- production-grade loading/error/stale states
- widget tests
- integration tests

---

## 7. Data authority by screen

| Screen | Authoritative source | Current mobile state |
|---|---|---|
| Control Centre | `TerminalDisplay.snapshot()`, preflight, service state | Implemented |
| Market | Upstox feed normalized by existing adapter and display state | Implemented |
| Index Data | Runtime instrument/candle state | Implemented basic view |
| Indicators | Backend indicator state | Partially exposed; needs typed indicator map |
| Options | `instruments/options.py`, instrument master, quote state | Basic exposure implemented |
| Signals | Breakout/Type2 engines, RSI filter, coordinator, audit/trace | History and active signal exposed; full detail needs expansion |
| Notifications | Display events and observability | Basic events exposed; category/severity filtering needs backend query |
| Orders | Order manager, order reconciliation, broker responses | Basic display list; complete normalized details need expansion |
| Positions | Position manager and broker reconciliation | Basic position state; authoritative P&L/detail serializer needed |
| Sandbox | `data/sandbox.sqlite3` | Explicit no-data state; query layer not complete |
| Reports | `daily_reports` SQLite table and observability reports | Report list/detail basic exposure |
| System Health | Components, feed status, preflight, telemetry, service state | Basic status exposure |
| Settings | Future session/device/preferences service | Read-only placeholder only |

The mobile layer must not recreate missing values by calculation. If an authoritative backend field is not currently available, the correct response is `null`, `UNKNOWN`, `NOT AVAILABLE`, or `NO DATA`, not an invented value.

---

## 8. Production configuration distinction

The mobile client being read-only is independent from the RKL engine execution mode.

When the existing production environment is active, the backend remains responsible for its existing production values, including the configured production mode, automatic entry, real-order gate, broker validation, and preflight rules.

The mobile implementation does not:

- set `EXECUTION_MODE`
- set `AUTO_TRADING_ENABLED`
- set `AUTO_ENTRY_ENABLED`
- set `REAL_ORDERS_ENABLED`
- set `LIVE_BROKER_VALIDATION`
- change `ORDER_ENV`
- change `DATABASE_PATH`
- bypass preflight
- open or close the order gate

The execution mode displayed in the app is read from backend state. It is never hard-coded in Flutter.

---

## 9. Security status

### Implemented

- Mobile routes require bearer authentication when configured.
- WebSocket requires bearer authentication.
- Broker and Upstox credentials remain backend-only.
- No mobile mutation routes exist.
- No control functions exist.
- The app does not receive systemd, SSH, AWS, or broker credentials.
- The mobile listener is configured separately from the dashboard port.
- WebSocket bind defaults to localhost.

### Development-only security

The static `MOBILE_API_TOKEN` is not a production identity system. It does not provide:

- user login
- refresh tokens
- logout/revocation
- device registration
- session expiration
- biometric unlock
- ADMIN role
- OPERATOR role
- READ_ONLY role enforcement
- SANDBOX_CLIENT role enforcement
- per-client audit identity

### Required production security

Before public mobile distribution:

1. Put the API and WebSocket behind HTTPS/WSS.
2. Keep ports 8765 and 8766 private.
3. Add login and short-lived access tokens.
4. Add rotating refresh tokens.
5. Add token revocation and logout.
6. Register devices and support device removal.
7. Add server-side roles and scopes.
8. Add authentication and API audit events.
9. Add request rate limits and connection limits.
10. Add response redaction and typed DTOs.
11. Store secrets in protected backend/AWS secret storage.
12. Never embed a master token in an APK.
13. Add TLS certificate management and renewal.
14. Restrict SSH to approved operator access.
15. Prevent direct Internet access to the dashboard port.

---

## 10. Sandbox and production isolation

The repository defines mode-specific database paths:

```text
data/readonly.sqlite3
data/backtest.sqlite3
data/sandbox.sqlite3
data/production.sqlite3
```

The existing `CandleStore` records the execution mode in `runtime_metadata` and rejects a mode mismatch when opening a database.

### Required sandbox guarantees

- Sandbox queries must explicitly open `data/sandbox.sqlite3`.
- The client must never submit a database path.
- Sandbox empty results must return `NO SANDBOX DATA`.
- Sandbox must never fallback to `data/production.sqlite3`.
- Sandbox users must not receive production credentials.
- Sandbox API responses must be filtered by server-side authorization.
- Production and sandbox tests must seed different records and prove no cross-read.
- Demo/client APKs should use a sandbox-scoped identity.

The current mobile endpoint reports a safe no-data state but does not yet expose the full sandbox analytics requested for client presentations.

---

## 11. Tests and validation

### Completed validation

The latest backend validation completed with:

```text
151 passed, 14 subtests passed
```

Also completed:

- Python compilation passed.
- Workspace diagnostics: no errors found.
- Dashboard tests passed.
- Missing-token rejection passed.
- Invalid-token rejection passed.
- Authorized mobile status read passed.
- Versioned route test passed.
- WebSocket authentication test passed.
- WebSocket welcome/state envelope test passed.
- WebSocket heartbeat implementation added.
- Git patch whitespace check passed.

### Required remaining tests

#### Backend

- Full typed contract tests for every endpoint.
- Order and position detail tests using broker-authoritative fixtures only.
- Signal condition and candidate-trace serialization tests.
- Indicator extensibility tests for SMA10/20/30/50, RSI14, RSI SMA5, CCI5.
- Notification category and severity filtering tests.
- Sandbox/production cross-read tests.
- Response redaction tests.
- Session, role, expiry, revocation, and device tests.

#### WebSocket

- Client reconnect after backend restart.
- Exponential backoff and jitter.
- Sequence gap replay.
- Full resynchronization after an unreplayable gap.
- Feed disconnected versus backend unavailable.
- Market closed state.
- Multiple concurrent clients.
- Slow-client backpressure.
- Maximum message size and connection limits.

#### Flutter

- `flutter analyze`
- `flutter test`
- widget tests
- integration tests
- authentication tests
- reconnect tests
- Android release build
- APK/AAB signing test
- physical-device test

Flutter and Dart were not available in the current environment, so the Flutter analyzer and APK build remain unverified.

---

## 12. Deployment instructions

### Local backend

Set a development token in `.env`:

```env
MOBILE_API_TOKEN=use-a-long-random-development-token
MOBILE_WS_HOST=127.0.0.1
MOBILE_WS_PORT=8766
```

Start the existing RKL service using its normal process and existing configuration. Do not replace production configuration with mobile-specific settings.

### Local Flutter client

From the Flutter directory:

```powershell
cd mobile_app
flutter pub get
flutter run --dart-define=RKL_API_BASE=http://10.0.2.2:8765 --dart-define=RKL_API_TOKEN=YOUR_TOKEN
```

`10.0.2.2` is the Android emulator's route to the host machine. A physical Android device requires a private reachable HTTPS endpoint or controlled development tunnel.

### Public deployment requirements

Do not expose ports 8765 or 8766 directly to the Internet.

Required arrangement:

```text
Android
  -> HTTPS/WSS on port 443
  -> reverse proxy/API edge
  -> localhost mobile REST/WebSocket listener
  -> existing RKL authoritative state
```

The existing dashboard may remain private and separate from the public mobile API.

### AWS resource decision

No additional AWS resource is currently demonstrated as necessary. A t3.medium should support the existing engine plus a low-volume read-only API/WebSocket layer if:

- the upstream Upstox connection remains single;
- mobile clients receive bounded messages;
- snapshot fanout is limited;
- SQLite queries are bounded and read-oriented;
- connection and request limits are enforced.

Measure before scaling:

- CPU utilization
- CPU credit balance
- memory and swap
- process RSS
- load average
- network bytes
- SQLite latency
- active WebSocket clients
- WebSocket send queues

Add another EC2, Redis, RDS, ALB, ECS, or Kubernetes only if measurements demonstrate a real capacity, availability, or isolation requirement.

---

## 13. APK build and distribution

### Development build

```powershell
flutter build apk --debug --dart-define=RKL_API_BASE=https://dev.example.com --dart-define=RKL_API_TOKEN=DEV_TOKEN
```

### Release build

```powershell
flutter build apk --release --dart-define=RKL_API_BASE=https://api.example.com
flutter build appbundle --release --dart-define=RKL_API_BASE=https://api.example.com
```

Do not put a production master token in `--dart-define` for a public APK. Use login and short-lived device-scoped sessions before client distribution.

### Distribution stages

1. Local emulator.
2. Internal signed APK.
3. Google Play Internal Testing.
4. Google Play Closed Testing with READ_ONLY or SANDBOX_CLIENT role.
5. Production Play release after security and integration acceptance.

The APK must never contain:

- Upstox access token
- Upstox client secret
- AWS credentials
- SSH credentials
- `.env` contents
- production database credentials
- systemd access
- production control secrets

---

## 14. Remaining work by priority

### Priority 1: Required before public live access

- Install Flutter and run analyzer/build.
- Implement HTTPS/WSS reverse proxy deployment.
- Replace static bearer token with login/session architecture.
- Add role and scope enforcement.
- Keep dashboard ports private.
- Add API response redaction.
- Add production API contract tests.
- Add reconnect/resync integration tests.

### Priority 2: Required for a complete professional client

- Typed DTO classes in backend and Flutter.
- Complete indicators endpoint.
- Complete signal detail endpoint with all conditions and rejection reasons.
- Complete options endpoint with selected and active position contracts.
- Complete order detail and broker lifecycle serialization.
- Complete position and broker-authoritative P&L serialization.
- Notifications filtering and pagination.
- Reports list/detail filtering.
- Sandbox query and performance reporting.
- Dedicated detail screens and UI tests.

### Priority 3: Future platform capabilities

- ADMIN, OPERATOR, READ_ONLY, and SANDBOX_CLIENT roles.
- Device registration and biometric unlock.
- Multiple client organizations.
- Typed semantic event bus.
- Bounded WebSocket replay.
- Client-specific subscriptions.
- Future secure control service, separately authorized from the viewer API.

---

## 15. Files that must remain protected

Mobile UI/API work must not change these areas unless a separate production-engineering change is explicitly approved and tested:

- `broker/upstox.py`
- `broker/order_manager.py`
- `signals/breakout.py`
- `signals/rsi_filter.py`
- `signals/coordinator.py`
- `instruments/options.py`
- `market_data/candles.py`
- `market_data/indicators.py`
- `trading/positions.py`
- `trading/safety.py`
- `trading/stop_loss_policy.py`
- live production SQLite data
- installed systemd unit
- Upstox credentials
- production execution environment

The mobile layer is complete only when it remains a viewer of these authoritative components rather than becoming a second implementation of them.

---

## 16. Final conclusion

The implementation now provides a real read-only mobile observer around the existing RKL runtime. It uses backend state, versioned REST routes, authenticated WebSocket messages, heartbeats, sequence numbers, reconnect handling, and a Flutter client.

The core production principle is preserved:

```text
RKL production engine remains fully enabled.
The Android client is read-only.
Closing Android does not stop RKL.
Reopening Android reads current backend state.
```

The implementation is ready for controlled local/integration testing. It is not yet ready for unrestricted public APK distribution until HTTPS/WSS, session authentication, roles, redaction, sandbox query isolation, Flutter build validation, and AWS deployment testing are completed.
