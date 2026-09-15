# RKL Upstox Mobile Client
# Latest Status Report

**Date:** 2026-09-15  
**Scope:** Flutter Android mobile client only  
**Application:** `mobile_app`  
**Backend:** Existing RKL backend remains authoritative

## Executive Status

The RKL Flutter mobile client is operationally buildable and launches on the Android emulator. The client remains read-only and continues to use the existing versioned mobile API and WebSocket contract.

Current status:

- Flutter dependencies: **Resolved**
- Flutter analyzer: **Passed**
- Flutter tests: **Passed**
- Android profile APK build through `flutter run --profile`: **Passed**
- Android APK installation: **Passed**
- Android app launch: **Passed**
- RenderFlex/unbounded-height error: **Not observed**
- RenderBox/not-laid-out cascade: **Not observed**
- NavigationBar assertion: **Not observed**
- WebSocket refusal to `10.0.2.2:8765`: **Expected while backend is offline**
- Severe profile skipped frames: **Still present; not fully resolved**

## Latest Implemented Changes

### Read-only terminal UI

The client retains the premium trading-terminal interface with the following screens:

- Control Centre
- Market
- Index Data
- Indicators
- Options
- Signals
- Notifications
- Orders
- Positions
- Reports
- Sandbox
- System Health
- Settings

The Control Centre remains the primary screen and presents engine state, market state, feed state, WebSocket state, heartbeat, sequence, latest update, index cards, activity counts, P&L when supplied, component health, and recent events.

Unavailable values remain authoritative-state placeholders such as `UNKNOWN`, `NO DATA`, or empty-state messages. The Flutter client does not fabricate market data or calculate trading signals, indicators, options, positions, or P&L.

### Four centralized themes

The app now supports exactly four themes:

1. **RKL DARK**
   - Default premium dark trading-terminal theme.
2. **RKL LIGHT**
   - Professional light daytime theme with contrast and borders.
3. **RKL PRO**
   - Dense institutional/quant presentation with compact visual density.
4. **RKL NEON**
   - Restrained futuristic dark theme with controlled cyan accents.

Theme selection is available from Settings, applies immediately without an app restart, and persists locally using `shared_preferences`.

No credentials, market data, trading state, or backend configuration is stored in the theme preference.

### Performance safeguards

The client currently applies targeted performance protections without removing screens or data:

- Initial REST refresh, WebSocket setup, and polling timer start after the first frame.
- REST refresh requests are guarded against overlap.
- WebSocket reconnect timers are guarded against duplication.
- WebSocket connection state becomes connected only after a valid payload is received.
- Offline stream handling avoids redundant `setState()` calls.
- WebSocket readiness failures are routed through the existing reconnect path.
- Only the active screen is built through `_body()`.
- Whole-page `AnimatedSwitcher` behavior was removed.
- The invalid vertical flex behavior in `_CountCard` was replaced with intrinsic vertical sizing.
- Existing horizontal `Expanded` usage remains for correctly constrained rows.

These changes preserve the API, WebSocket protocol, read-only boundary, and existing UI behavior.

## API and Security Boundaries

The following contracts remain unchanged:

```text
GET /api/v1/mobile/status
GET /api/v1/mobile/market
GET /api/v1/mobile/signals
GET /api/v1/mobile/orders
GET /api/v1/mobile/positions
GET /api/v1/mobile/options
GET /api/v1/mobile/notifications
GET /api/v1/mobile/reports
WS  /api/v1/mobile/stream
```

REST and WebSocket authentication continue to use:

```http
Authorization: Bearer <MOBILE_API_TOKEN>
```

The client does not contain or request:

- Upstox access tokens.
- Upstox client secrets.
- AWS credentials.
- SSH credentials.
- Broker credentials.
- Production database credentials.

The mobile app provides no order placement, order modification, order cancellation, position close, systemd control, SSH control, AWS control, or production database write capability.

## Android Configuration

The API base remains configurable through `dart-define`.

For the Android emulator host mapping:

```powershell
flutter run --profile -d emulator-5554 `
  --dart-define=RKL_API_BASE=http://10.0.2.2:8765 `
  --dart-define=RKL_API_TOKEN=YOUR_TOKEN
```

`10.0.2.2` is the Android emulator route to the development host. The backend must be running and reachable for REST and WebSocket data to become live.

The local backend was offline during the latest emulator run. Connection refusal was therefore expected and was not addressed by changing the backend or API contract.

## Validation Results

### Dependency resolution

Command:

```powershell
flutter pub get
```

Result: **Passed**

The latest dependency resolution includes `shared_preferences 2.5.5` for local theme persistence.

### Static analysis

Command:

```powershell
flutter analyze
```

Result: **Passed**

```text
No issues found!
```

### Flutter tests

Command:

```powershell
flutter test
```

Result: **Passed**

- Tests passed: **2**
- Tests failed: **0**

The tests cover the existing read-only root widget and the four-theme surface.

### Android profile run

Command:

```powershell
flutter run --profile -d emulator-5554 \
  --dart-define=RKL_API_BASE=http://10.0.2.2:8765
```

Observed:

- Profile APK built: **Yes**
- Profile APK size: **37.8 MB**
- APK installed: **Yes**
- App launched: **Yes**
- Impeller OpenGLES renderer: **Active**
- RenderFlex error: **Not observed**
- RenderBox cascade: **Not observed**
- NavigationBar assertion: **Not observed**

## Latest Performance Measurements

The latest profile-mode Android log reported:

```text
Skipped 30 frames! The application may be doing too much work on its main thread.
Skipped 155 frames! The application may be doing too much work on its main thread.
Davey! duration=932ms
```

Earlier debug/profile observations included:

```text
Skipped 100 frames
Skipped 331 frames
Skipped 133 frames
Skipped 81 frames
Skipped 404 frames
Skipped 174 frames
Skipped 415 frames
Skipped 287 frames
```

The latest profile run is better than the worst earlier measurements, but the remaining skipped frames and 932 ms traversal show that startup performance is not fully fixed.

The next responsible optimization step is a controlled Flutter profile timeline with the backend both online and offline, separating:

- Dart/UI build and layout time.
- Raster and paint time.
- Impeller/shader work.
- Android Surface and WindowInsets setup.
- Garbage collection.
- REST response decoding.
- WebSocket startup and reconnect handling.

No additional broad UI rewrite should be made without that evidence.

## Files Changed in the Latest Work

Application and validation files changed:

- `mobile_app/lib/main.dart`
- `mobile_app/pubspec.yaml`
- `mobile_app/pubspec.lock`
- `mobile_app/test/widget_test.dart`
- `mobile_app/README.md`

This report is additionally created as:

- `RKL_MOBILE_LATEST_STATUS_REPORT_2026-09-15.md`

No Python, backend, trading engine, broker, order, strategy, options, candle, indicator, position, safety, database, AWS, systemd, or production configuration files were changed.

## Remaining Problems

1. Severe startup skipped frames remain in profile mode.
2. The exact split between Flutter work and Android emulator/runtime work is not yet isolated.
3. Backend-offline connection refusals remain until the local RKL service is running.
4. Production distribution still requires the existing security and release controls, including HTTPS, scoped short-lived sessions, token rotation, device controls, audit logging, and signed release distribution.

## Final Assessment

The Flutter client is functionally stable enough for continued controlled Android testing. The read-only architecture and backend contract are preserved. Theme selection and persistence are implemented across the existing client shell, and the current app builds, installs, launches, analyzes, and tests successfully.

The app should not yet be described as fully performance-optimized because severe startup frame drops remain measurable in profile mode.
