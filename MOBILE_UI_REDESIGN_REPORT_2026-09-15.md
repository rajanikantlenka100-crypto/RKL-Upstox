# RKL Mobile UI Redesign Report

**Date:** 2026-09-15  
**Scope:** Flutter Android read-only UI redesign and runtime stabilization  
**Application:** `mobile_app`  
**Backend:** Preserved as the authoritative source of truth

## Executive Summary

The RKL Flutter client was redesigned from a basic demonstration shell into a compact trading-terminal-style interface for Android phone screens. The redesign stays strictly read-only and continues to consume the existing versioned mobile API and authenticated WebSocket stream.

No Python backend, trading engine, strategy, broker integration, order workflow, database, systemd configuration, production API contract, or credential source was changed.

The redesigned client now has:

- A professional dark terminal visual language.
- A strong Control Centre home screen.
- All required read-only screens.
- Structurally valid bottom navigation and drawer navigation.
- Emulator-safe configurable API addressing.
- Explicit live, read-only, offline, unknown, empty, stale-capable, and error presentation states.
- Lower-frequency REST polling and guarded refreshes to reduce unnecessary UI-thread work.

## Latest Update

**Latest checked state:** 2026-09-15

The latest Flutter source includes a targeted startup/reconnect performance adjustment in `mobile_app/lib/main.dart`. REST refresh, WebSocket setup, and the polling timer now begin after the first frame. The client marks the stream connected only after receiving a valid payload and avoids redundant offline `setState()` calls and duplicate reconnect timers.

The latest validation completed successfully:

- `flutter analyze`: passed with no issues.
- `flutter test`: passed, 1 test passed and 0 failed.
- `flutter run -d emulator-5554 --dart-define=RKL_API_BASE=http://10.0.2.2:8765`: APK built, installed, and launched successfully.
- RenderFlex/unbounded-constraint error: not observed.
- RenderBox layout cascade: not observed.
- NavigationBar assertion: not observed.

The runtime investigation remains open because the latest Android run still reported severe skipped frames. The code change reduced avoidable startup/reconnect work, but the measured log did not prove a performance improvement.

## Current Problems

### Severe Android skipped frames

The latest emulator run reported:

```text
Skipped 415 frames! The application may be doing too much work on its main thread.
Skipped 287 frames! The application may be doing too much work on its main thread.
```

An Android runtime/GC pause was also recorded:

```text
GC ... 769.012ms total 1.462s
```

The earlier baseline reported 404 and 174 skipped frames, so the latest run does not demonstrate improvement. The measurements vary across cold emulator runs. The current evidence points to a combination of Android emulator startup/rendering/GC work and application startup/network activity; the performance problem is not considered solved.

### Expected backend connection refusal

The local RKL backend was not running during the emulator test. The app therefore continued to report connection refusal to `10.0.2.2:8765` for the WebSocket and REST paths. This is expected offline behavior and is not being treated as a backend or API defect in this report.

### Remaining validation gap

The app was confirmed to build, install, and launch, but no performance profile or frame timeline has yet isolated the exact percentage of startup work attributable to Flutter widget construction versus Android emulator/GC/rendering overhead. A profile-mode trace with the backend running and a second controlled cold-start comparison is still required before claiming a performance fix.

## Follow-up Runtime Stabilization

After the redesign was exercised on Android, Flutter reported:

```text
RenderFlex children have non-zero flex but incoming height constraints are unbounded.
```

The reported widget path was:

```text
Column <- Padding <- DecoratedBox <- ConstrainedBox <- Container
   <- _TerminalCard <- _CountCard <- Expanded <- Row <- Column
   <- RepaintBoundary <- IndexedSemantics
```

The cause was the `Spacer` inside `_CountCard`. `_CountCard` is one of the three horizontally expanded activity cards in `_activitySummary`, which itself is a child of the vertically scrollable Control Centre `ListView`. The horizontal `Expanded` widgets correctly divide the available row width, but the nested `Column` receives unbounded vertical height from the scroll view. Its vertical `Spacer` therefore attempted to consume a flex share of an undefined height.

The fix was intentionally narrow:

- Replaced the vertical `Spacer` in `_CountCard` with `SizedBox(height: 14)`.
- Preserved legitimate horizontal `Expanded` widgets in the activity row, drawer, data rows, and indicator/value rows.
- Removed the whole-page `AnimatedSwitcher` so startup and screen changes do not temporarily build two large scroll trees at once.
- Kept the Control Centre vertically scrollable and responsive for narrow Android screens.
- Kept `RKL_API_BASE`, Bearer authentication, the WebSocket endpoint, and all backend data handling unchanged.

This removes the source of the RenderBox/not-laid-out cascade. The expected connection refusal on `10.0.2.2:8765` when the local RKL backend is stopped remains an ordinary offline state and was not changed by this fix.

## Targeted Performance Investigation

### Investigation scope

The investigation was limited to `mobile_app/lib/main.dart`. The following startup and rebuild paths were inspected:

- `initState()` startup work.
- Initial REST refresh and its eight concurrent API requests.
- WebSocket connection and reconnect handling.
- `setState()` call sites.
- Ten-second refresh timer.
- JSON decoding and map/list normalization.
- Widget construction inside `build()` and `_body()`.
- Activity/index/system-health loops and collection transformations.
- Animation and transition widgets.
- Existing flex layout behavior.

No trading calculation, signal calculation, option calculation, API contract, authentication mechanism, or WebSocket protocol was moved into or changed in the mobile client.

### Confirmed app-level contributors

The original startup path invoked all of the following directly from `initState()`:

```dart
refresh();
connectStream();
refreshTimer = Timer.periodic(...);
```

Although the HTTP calls are asynchronous, starting the REST batch and WebSocket channel setup during the first frame competes with Android's initial Flutter/Surface setup. The WebSocket path also marked the feed connected immediately after creating the channel, before receiving a valid message. When the backend was offline, each refused attempt could cause redundant connection-state updates and reconnect scheduling.

### Targeted changes

Only `mobile_app/lib/main.dart` was changed:

1. Initial REST refresh, WebSocket setup, and the periodic timer now start from `addPostFrameCallback`, allowing the first frame to render before network startup begins.
2. `streamConnected` is set to `true` only after a valid WebSocket payload is received.
3. Offline stream handling avoids calling `setState()` when the stream is already offline.
4. Reconnect scheduling is guarded so a refused connection cannot create duplicate reconnect timers.
5. The existing ten-second polling interval, endpoint, Bearer header, payload handling, and screens remain unchanged.

### Runtime comparison

The baseline emulator run before the performance change showed:

```text
Skipped 404 frames! The application may be doing too much work on its main thread.
Skipped 174 frames! The application may be doing too much work on its main thread.
```

The post-change emulator run was executed with:

```powershell
flutter run -d emulator-5554 --dart-define=RKL_API_BASE=http://10.0.2.2:8765
```

The post-change log showed:

```text
Skipped 415 frames! The application may be doing too much work on its main thread.
Skipped 287 frames! The application may be doing too much work on its main thread.
```

The Android log also contained a platform/runtime pause:

```text
GC ... 769.012ms total 1.462s
```

The comparison does **not** demonstrate an improvement. The skipped-frame issue remains unresolved. The measurements vary between cold emulator runs, and the log indicates Android rendering/GC startup work in addition to the app's network startup path. No further speculative UI or business-logic changes were made.

The same run successfully built, installed, and launched the APK. It showed the expected WebSocket connection refusal to `10.0.2.2:8765` because the local backend was not running. It did not show a RenderFlex/unbounded-constraint error, RenderBox cascade, or NavigationBar assertion.

## Problems Addressed

### NavigationBar assertion

The original state used one `tab` value for thirteen drawer screens while the `NavigationBar` contained only five destinations. Selecting a drawer screen such as Reports or Settings could therefore pass an index outside the five-destination range to `NavigationBar`.

The new implementation separates the concepts structurally:

```dart
static const _bottomTabs = [0, 1, 5, 7, 8];
```

The five bottom destinations map to:

| Bottom destination | Screen index |
|---|---:|
| Control | Control Centre |
| Market | Market |
| Signals | Signals |
| Orders | Orders |
| Positions | Positions |

`selectedIndex` is derived from the current screen through `_bottomIndex`. When a drawer-only screen is active, the selected bottom index safely falls back to `0`, so it always remains within `0..4`.

### Android emulator loopback address

The previous default was:

```text
http://127.0.0.1:8765
```

On an Android emulator, `127.0.0.1` refers to the emulator itself rather than the development host. The default is now:

```text
http://10.0.2.2:8765
```

The API remains configurable and can still be overridden for every environment:

```powershell
flutter run -d emulator-5554 `
  --dart-define=RKL_API_BASE=http://10.0.2.2:8765 `
  --dart-define=RKL_API_TOKEN=YOUR_TOKEN
```

Physical devices should use a reachable HTTPS development or production endpoint rather than the emulator alias.

### Repeated WebSocket connection attempts

The client continues to use the existing authenticated endpoint:

```text
/api/v1/mobile/stream
```

Bearer authentication is preserved in the WebSocket handshake. Connection state is shown as connected or offline, and reconnect attempts use an eight-second delay rather than creating an immediate retry loop.

REST requests have a twelve-second timeout. A refresh guard prevents overlapping eight-endpoint refresh batches when a timer, pull-to-refresh gesture, and sequence-gap resync happen close together.

### Excessive UI work

The original UI created every page widget in a list on each build, even though only one screen was visible. The redesign builds only the active screen through `_body()` and uses the drawer for the full screen catalogue.

Other changes intended to reduce unnecessary work:

- REST polling changed from every three seconds to every ten seconds.
- Concurrent refresh calls are ignored while an existing refresh is active.
- The active page is rendered through a focused switch rather than a full page list.
- Data presentation uses small reusable widgets instead of deeply repeated inline layouts.
- Refresh and reconnect timers are cancelled during disposal.
- WebSocket subscriptions are explicitly cancelled during disposal.

## UI Structure

### Application shell

- Dark ink background with raised navy panels.
- Mint used for healthy/live/positive states.
- Red reserved for errors, offline state, and negative P&L.
- Amber used for unknown, waiting, closed, or cautionary state.
- Blue used for read-only and informational state.
- Rounded cards with restrained borders rather than decorative card nesting.
- Compact typography, uppercase terminal labels, and consistent spacing.
- Pull-to-refresh on every data screen.
- App-bar title follows the active screen.
- Drawer contains all thirteen required screens.
- Bottom navigation contains the five highest-frequency workflows.

### Control Centre

The Control Centre is the primary screen and contains:

1. **Engine header**
   - RKL Control Centre identity.
   - Read-only badge.
   - Execution mode.
   - Startup phase.
   - Last update time.
   - WebSocket sequence number.

2. **Engine snapshot**
   - Engine/system status.
   - Market status.
   - Feed/WebSocket status.
   - Heartbeat/last update.

3. **Index monitor**
   - NIFTY.
   - BANKNIFTY.
   - SENSEX.
   - MIDCPNIFTY.
   - LTP.
   - Backend-provided change/net-change/change-percent when available.
   - 5-minute candle context.
   - 3-minute context when available.
   - RSI14 and CCI5 when present in the authoritative payload.
   - SMA information when present.

4. **Activity summary**
   - Active signal count.
   - Position count.
   - P&L display using backend-provided P&L keys only.

5. **System components**
   - Component readiness tiles and detailed health list.

6. **Recent events**
   - Recent notification/event records.
   - Explicit no-event state when the backend has not published events.

The client does not calculate indicators, signals, positions, or P&L. It displays values supplied by the existing RKL API and uses `UNKNOWN` when a value is absent.

## Required Screens

| Screen | Implementation | Data source |
|---|---|---|
| Control Centre | Engine snapshot, index monitor, activity, health, recent events | `status`, `market`, `signals`, `positions`, `notifications` |
| Market | Index cards and market context | `market` |
| Index Data | Detailed index cards | `market` |
| Indicators | RSI14, RSI14 SMA, CCI5 chips per instrument | `market.indicators` |
| Options | Read-only option universe records | `options.option_universe` |
| Signals | Read-only signal history records | `signals.signal_history` |
| Notifications | Read-only event records | `notifications.events` |
| Orders | Read-only order records | `orders.orders` |
| Positions | Read-only position detail records | `positions.position_details` |
| Reports | Read-only report records | `reports.reports` |
| Sandbox | Explicit no-data/read-only state | No mutation surface added |
| System Health | Component matrix and transport information | `status.components`, `status` |
| Settings | Endpoint, authentication posture, and write policy | Client configuration |

## Data and API Preservation

The Flutter client continues to use the existing endpoints:

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

Every REST request includes:

```http
Authorization: Bearer <RKL_API_TOKEN>
Accept: application/json
```

The WebSocket handshake includes the same Bearer header. No Upstox token, AWS credential, SSH credential, or broker secret is introduced into Flutter.

The client continues to treat backend state as authoritative. It does not invent fallback market values. The only fallback index names are the existing four known RKL instruments used to render an empty/loading market shell; missing values are rendered as `UNKNOWN`.

## Read-Only Boundary

The redesign intentionally adds no mutation API or control surface. It does not provide:

- Order placement.
- Order modification.
- Order cancellation.
- Position close actions.
- Systemd start/stop/restart controls.
- Strategy configuration.
- Broker authentication.
- Production database writes.
- Sandbox execution.

The Settings screen explicitly communicates that writes are disabled and credentials remain outside the client.

## Files Changed

This UI redesign and follow-up runtime stabilization changed only:

- `mobile_app/lib/main.dart`

No Python or production trading files were changed for this task.

The existing Flutter project metadata and test setup remained in place from the previous validation task. `flutter pub get` was rerun successfully after the redesign.

## Validation Results

### Dependency resolution

Command:

```powershell
flutter pub get
```

Result: **Passed**

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

- Tests passed: **1**
- Tests failed: **0**

### Follow-up layout validation

The targeted layout correction was validated with the same project checks:

```powershell
flutter analyze
flutter test
```

Results:

- Analyzer: **Passed; no issues found**.
- Tests: **Passed; 1 passed, 0 failed**.
- Backend files changed: **None**.
- API contract changed: **No**.

### Targeted performance validation

Results after the startup/reconnect changes:

- `flutter analyze`: **Passed; no issues found**.
- `flutter test`: **Passed; 1 passed, 0 failed**.
- Android APK build: **Passed**.
- Android APK installation: **Passed**.
- Android app launch: **Passed**.
- RenderFlex/unbounded constraint error: **Not observed**.
- RenderBox cascade: **Not observed**.
- NavigationBar assertion: **Not observed**.
- WebSocket refusal: **Observed and expected** while the backend was stopped.
- Severe skipped frames: **Still observed; performance not confirmed fixed**.

### Android launch

Command executed from `mobile_app`:

```powershell
flutter run -d emulator-5554
```

Result:

- Emulator detected: **Yes**
- Dart/Flutter compilation: **Passed**
- APK assembly: **Passed**
- APK path: `build/app/outputs/flutter-apk/app-debug.apk`
- APK installation: **Stalled during ADB installation**
- Application running confirmation: **Not received**

The failure occurred after successful APK construction, during emulator installation. No Dart compile error, analyzer error, or Gradle build error was reported.

## Known Operational Requirements

For local Android emulator use, the RKL backend must be reachable from the emulator at `10.0.2.2:8765`, and the app must receive a valid token through `RKL_API_TOKEN`.

Example:

```powershell
flutter run -d emulator-5554 `
  --dart-define=RKL_API_BASE=http://10.0.2.2:8765 `
  --dart-define=RKL_API_TOKEN=YOUR_TOKEN
```

The Android emulator must also be healthy enough for ADB package installation. The observed install stall is an emulator/ADB environment issue after a successful Flutter build, not a mobile Dart compilation failure.

## Production Readiness Notes

This redesign improves the client presentation and local runtime behavior, but it does not make the mobile platform production-secure by itself. Production deployment still requires the existing security work described in the mobile architecture and data-security reports, including:

- HTTPS termination.
- Short-lived sessions instead of a bootstrap token.
- Token rotation and revocation.
- Device registration.
- Role enforcement.
- API rate limiting.
- Audit logging.
- Response redaction and typed contract coverage.
- Release signing and controlled distribution.
- Network-loss, stale-state, reconnect, and token-expiry integration tests.

The RKL engine remains the authoritative production boundary, and the mobile client remains read-only.
