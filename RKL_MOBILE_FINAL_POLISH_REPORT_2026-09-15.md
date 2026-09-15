# RKL Upstox Mobile Client
# Latest Updates and Changes

**Date:** 2026-09-15  
**Scope:** Flutter mobile client only  
**Current status:** Read-only client; real backend REST/WebSocket verification completed; release APK remains blocked by Windows policy

## Latest Changes

### Local WebSocket integration fix

The existing backend uses separate local ports:

- REST/dashboard API: `8876`
- Mobile WebSocket: `8877`

The Flutter client previously derived the WebSocket URL from the REST port and attempted to connect to the wrong local port.

`mobile_app/lib/main.dart` now:

- Preserves `/api/v1/mobile/stream`.
- Preserves Bearer authentication.
- Uses `RKL_API_WS_BASE` when explicitly provided.
- Automatically uses local REST port + 1 for `127.0.0.1`, `localhost`, and `10.0.2.2` when no explicit WS base is provided.
- Keeps production/shared-port deployments configurable.

No WebSocket protocol or API contract was changed.

### Market and data presentation

The latest UI keeps the premium terminal layout and presents:

- `MARKET CLOSED`
- `LIVE`
- `LAST KNOWN`
- `STALE`
- `NO DATA`
- `UNKNOWN`
- `CONNECTED`
- `OFFLINE`

Index cards use compact freshness badges instead of giving raw timestamps visual priority.

Visible record paths use scalar field whitelists rather than printing complete maps or lists. This applies to:

- Options
- Signals
- Notifications
- Orders
- Positions
- Reports
- System components
- Key/value status rows

Unsupported structured values display `NOT AVAILABLE`.

### Four themes

The existing centralized theme architecture remains in use:

- RKL DARK
- RKL LIGHT
- RKL PRO
- RKL NEON

Theme selection updates immediately and persists locally through `shared_preferences`. No second theme system or state-management framework was added.

### Runtime safeguards retained

- REST refresh overlap guard.
- Duplicate WebSocket reconnect guard.
- Post-frame startup network work.
- WebSocket connected state only after a valid payload.
- No whole-page `AnimatedSwitcher`.
- Intrinsic vertical sizing for `_CountCard`.
- Active-screen rendering through `_body()`.

## Real Backend Verification

The existing backend was started temporarily with process-local overrides:

```text
EXECUTION_MODE=READ_ONLY
REAL_ORDERS_ENABLED=OFF
DASHBOARD_PORT=8876
MOBILE_WS_PORT=8877
OPEN_BROWSER=OFF
```

The backend was stopped after validation. No backend source or production configuration was modified.

### REST API

Authenticated mobile endpoints returned HTTP 200:

- `/api/v1/mobile/status`
- `/api/v1/mobile/market`
- `/api/v1/mobile/signals`
- `/api/v1/mobile/options`
- `/api/v1/mobile/notifications`
- `/api/v1/mobile/orders`
- `/api/v1/mobile/positions`
- `/api/v1/mobile/reports`

Observed authoritative data summary:

- Execution mode: `READ_ONLY`
- Market status: `CLOSED`
- Startup phase: `READY: HISTORICAL DATA SYNC`
- System status: `UPSTOX FEED CONNECTED`
- WebSocket status: `UPSTOX FEED CONNECTED`
- Instruments: NIFTY, BANKNIFTY, SENSEX, MIDCPNIFTY
- Options: 40 universe records and 40 quote records
- Notifications: 5 events
- Reports: 1 report
- Orders: 0
- Positions: 0
- Signals: empty authoritative history/queue

### WebSocket

Authenticated WebSocket validation passed on the existing mobile WS port:

```text
WELCOME
sequence: 0
protocol: rkl.mobile.v1
```

No token or credential was printed.

## Validation Results

### Flutter validation

```text
flutter pub get       PASS
flutter analyze       PASS: No issues found
flutter test          PASS: 2 passed, 0 failed
```

### Profile Android validation

A profile APK previously built, installed, and launched successfully on `emulator-5554`.

The latest profile run before the WebSocket-port correction recorded:

```text
Skipped 30 frames
Skipped 104 frames
Davey! duration=1721ms
```

The post-correction profile invocation reached Gradle assembly but did not complete within the validation run and was stopped. A completed post-correction Android runtime measurement is still pending.

Performance is not claimed fixed.

### Release APK

```powershell
flutter build apk --release
```

Result: **Failed because Windows Application Control blocked Flutter `gen_snapshot.exe`.**

This is an operating-system security-policy blocker, not a Dart analyzer or application source error.

## Current Remaining Items

1. Complete a post-WebSocket-fix profile APK run through install and launch.
2. Manually verify all four themes on the emulator.
3. Restart the app and verify persisted theme selection.
4. Manually verify all drawer screens and five bottom-navigation destinations.
5. Capture a Flutter DevTools profile timeline for remaining skipped frames.
6. Retry the release APK from a trusted toolchain environment where `gen_snapshot.exe` is permitted.

## Safety Confirmation

The following were not modified:

- Python backend source.
- Trading engine.
- Strategy and signal logic.
- Options logic.
- Order manager and broker integration.
- Positions and safety logic.
- Database.
- AWS.
- systemd.
- Production configuration.
- API contracts.
- WebSocket protocol.

No mock or simulation data was added. The mobile client remains real-data and read-only.

## Latest Files Changed

- `mobile_app/lib/main.dart`

No Python or production trading files were changed.
