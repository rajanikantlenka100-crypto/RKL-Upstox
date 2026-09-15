# RKL Mobile Performance Investigation and Recommendations

**Date:** 2026-09-15  
**Scope:** Flutter Android startup and skipped-frame investigation  
**Application:** `mobile_app`  
**Status:** Investigation remains open; severe startup frame drops are not considered fixed

## Executive Summary

The RKL Flutter client now builds, installs, launches, and passes static analysis and tests. The previous runtime failures have not reappeared in the observed emulator runs:

- RenderFlex/unbounded-height error: not observed.
- RenderBox/not-laid-out cascade: not observed.
- NavigationBar assertion: not observed.
- API and WebSocket architecture: preserved.
- Read-only behavior: preserved.

Severe Android startup frame drops remain. The latest observed run reported:

```text
Skipped 331 frames! The application may be doing too much work on its main thread.
Skipped 133 frames! The application may be doing too much work on its main thread.
Skipped 81 frames! The application may be doing too much work on its main thread.
```

The log also reported a long Android traversal:

```text
Davey! duration=1631ms
```

Earlier runs reported 404/174 and 415/287 skipped frames. The measurements vary across cold emulator starts, so the implemented Flutter changes have not demonstrated a reliable improvement yet.

## Current Runtime State

### Verified

- APK assembly succeeds.
- APK installation succeeds.
- Application launches on `emulator-5554`.
- Flutter analyzer passes.
- Flutter tests pass.
- Navigation structure remains valid.
- Scrollable Control Centre no longer produces the unbounded-flex layout exception.
- API base remains configurable through `RKL_API_BASE`.
- Bearer authentication and the existing WebSocket endpoint remain unchanged.

### Expected offline behavior

The local backend was not running during emulator testing. Therefore connection refusal to:

```text
10.0.2.2:8765
```

is expected. This is not being treated as a backend or API defect, and no backend modification is recommended as part of this client-only investigation.

### Unresolved

- Severe startup skipped frames.
- Exact split between Flutter build/layout/paint cost and Android emulator/GC/rendering cost.
- No controlled profile-mode frame timeline has yet isolated the dominant Dart or raster phase.

## Implemented Changes

Only `mobile_app/lib/main.dart` was changed for the targeted performance work.

### Startup scheduling

REST refresh, WebSocket setup, and the ten-second polling timer now start from `WidgetsBinding.instance.addPostFrameCallback`. This allows the initial Flutter frame to be submitted before network setup begins.

This is a scheduling improvement, not a data delay or business-logic change.

### WebSocket state handling

The client now:

- Marks the stream connected only after a valid payload arrives.
- Avoids offline `setState()` calls when the stream is already offline.
- Prevents duplicate reconnect timers.
- Routes asynchronous channel readiness failures through the existing reconnect path.

The endpoint, Bearer header, stream protocol, and reconnect behavior remain compatible with the existing API.

### Layout stabilization

The activity summary still uses horizontal `Expanded` widgets to divide card width. The `_CountCard` itself now uses intrinsic vertical sizing and no vertical flex child. The invalid vertical `Spacer` was replaced with fixed spacing.

The whole-page `AnimatedSwitcher` was removed so screen changes do not temporarily build two large scroll trees.

## Current Code Assessment

### `initState()`

The original synchronous startup wiring was a plausible contributor because it initiated REST, WebSocket, and timer work during the initial application lifecycle. It has now been moved after the first frame.

Remaining concern: the post-frame callback still starts eight REST requests and a WebSocket attempt close together. This is acceptable for correctness, but its impact should be measured with the backend running and with representative response sizes.

### REST refresh

The refresh path uses `Future.wait` for eight endpoints. Network I/O is asynchronous, but response decoding and `Map<String, dynamic>.from` conversion occur on the Dart isolate. If production responses become large, parsing can contribute to jank.

The current offline test cannot establish this cost because refused requests do not produce large JSON payloads.

### WebSocket reconnect

Reconnect attempts are guarded and spaced by eight seconds. This prevents a tight retry loop, but repeated connection failures still create asynchronous channel setup and exception paths. The channel readiness failure is now handled through the normal reconnect path.

### Widget tree

The active screen is selected through `_body()`, so all thirteen page bodies are not simultaneously inserted into the visible page tree. The Control Centre still contains a nested scroll view, grid cards, index cards, activity cards, status tiles, and recent-event cards, but this is not a large data table in the offline state.

The drawer is built as part of the `Scaffold`, but its list is lazily built. Its contribution should be measured before changing it.

### Build-time transformations

The client performs small map/list normalization operations such as `_map`, `_list`, `.entries`, `.take`, and `.reversed` during widget construction. These are safe for current payload sizes, but repeated cloning on every `setState` could become expensive with large signal, option, event, or report payloads.

No evidence currently justifies moving calculations into Flutter or inventing a cache. The backend remains authoritative.

### Animations

The whole-page `AnimatedSwitcher` has already been removed. No additional animation removal is recommended without a profile showing a specific animation or transition cost.

## Recommended Improvements

Recommendations are ordered by evidence and risk.

### Priority 1: Capture a real frame timeline

Run a profile-mode session with the emulator and inspect Flutter DevTools Performance:

```powershell
flutter run --profile -d emulator-5554 `
  --dart-define=RKL_API_BASE=http://10.0.2.2:8765 `
  --dart-define=RKL_API_TOKEN=YOUR_TOKEN
```

Capture at least:

1. Cold application launch.
2. First frame.
3. Transition from loading state to backend data state.
4. First WebSocket payload.
5. Opening the drawer.
6. Switching between Control Centre and Market.
7. Pull-to-refresh.

Inspect separately:

- UI thread/Dart frame time.
- Raster thread frame time.
- Layout and paint duration.
- Garbage collection pauses.
- Shader compilation and Impeller activity.
- Widget rebuild counts.

Do not make another broad code change until this identifies a dominant phase.

### Priority 2: Test with the backend running

The offline run is useful for connection and error-state behavior, but it does not exercise JSON parsing or realistic data rendering. A controlled local run should provide representative status, market, signals, options, notifications, orders, positions, and reports.

Compare:

- Backend offline.
- Backend online with empty datasets.
- Backend online with representative datasets.
- Backend online with large historical/event payloads.

This separates network failure overhead from response parsing and widget construction overhead.

### Priority 3: Add debug-only timing instrumentation

For diagnosis only, use Flutter timeline events around existing operations:

- REST response decode.
- `Future.wait` completion.
- State assignment.
- First post-refresh build.
- WebSocket payload normalization.

Instrumentation should be debug/profile-only and must not alter production behavior or suppress Android skipped-frame logs.

### Priority 4: Avoid repeated normalization when evidence supports it

If profiling shows `_map`/`_list` cloning or repeated `.entries` transformations are expensive, normalize each endpoint response once when it arrives and store typed presentation data in the state.

Constraints:

- Do not calculate indicators, signals, options, or P&L in the client.
- Do not fabricate missing values.
- Do not change API payloads.
- Preserve `UNKNOWN`, empty, stale, and error states.
- Keep the optimization limited to structural parsing and presentation data.

### Priority 5: Bound visible data collections

The current implementation already limits several screens to 40 records and recent events to four records. If real API payloads are larger, consider bounding work before widget construction:

- Keep the latest visible records for event feeds.
- Use explicit pagination or backend-supported limits if the API contract later provides them.
- Avoid sorting in Flutter unless the backend already supplies an authoritative order.
- Do not silently discard data from screens that require complete records.

Any pagination or API limit change would require an API-contract review and is outside this client-only task.

### Priority 6: Use const and stable widget subtrees selectively

A profile may show repeated rebuilding of static shell widgets. Safe candidates include:

- Static navigation destinations.
- Static read-only badges.
- Static empty-state icons and labels.
- Static app-bar configuration.
- Theme objects that are currently reconstructed in `RklApp.build`.

This should be done only where the profile identifies meaningful rebuild cost. It should not become a broad UI rewrite.

### Priority 7: Validate debug versus profile versus release

Debug mode includes additional instrumentation and slower execution. Compare startup behavior in:

```powershell
flutter run -d emulator-5554 --debug
flutter run --profile -d emulator-5554
flutter build apk --release
```

The release APK should be installed and measured separately. A debug-only skipped-frame result should not be treated as representative of production performance, although debug jank should still be investigated when it is severe.

## Approaches Not Recommended

The following approaches would hide symptoms or violate project boundaries:

- Suppressing skipped-frame logs.
- Removing required screens or data.
- Hardcoding a different API address.
- Disabling WebSocket updates.
- Moving signal, option, P&L, or trading calculations into Flutter.
- Adding arbitrary startup delays without measurement.
- Changing the backend only to make the emulator log quieter.
- Downgrading Flutter or packages.
- Replacing authoritative API values with fabricated placeholders.
- Introducing a second mobile data contract.

## Suggested Next Investigation Sequence

1. Start the existing RKL backend in its safe read-only configuration.
2. Run the app in profile mode on a warm emulator.
3. Capture a DevTools timeline for cold launch and first data render.
4. Repeat with backend offline to isolate connection-failure behavior.
5. Compare Dart/UI, raster, GC, and shader timings.
6. Patch only the measured dominant phase.
7. Re-run analyzer, tests, debug launch, profile launch, and release build.
8. Record before/after frame timings in a follow-up report.

## Validation Record

Commands completed after the latest targeted source change:

```powershell
flutter analyze
flutter test
flutter run -d emulator-5554 --dart-define=RKL_API_BASE=http://10.0.2.2:8765
```

Observed results:

| Check | Result |
|---|---|
| `flutter analyze` | Passed; no issues found |
| `flutter test` | Passed; 1 passed, 0 failed |
| APK build | Passed |
| APK install | Passed |
| App launch | Passed |
| RenderFlex error | Not observed |
| RenderBox cascade | Not observed |
| NavigationBar assertion | Not observed |
| WebSocket refusal | Expected when backend is offline |
| Skipped frames | Still severe; not fixed |

## Files Changed

For the latest targeted performance work:

- `mobile_app/lib/main.dart`
- This report file

No Python, backend, trading, API-contract, authentication, database, systemd, or production configuration files were changed.

## Conclusion

The client-side runtime errors are resolved and the application launches successfully. The latest targeted changes reduce avoidable startup and reconnect work, but the observed skipped-frame counts remain severe and variable. The next responsible step is controlled profile-mode measurement with the backend both online and offline, followed by a narrowly evidenced optimization.

Performance should not be declared fixed until a frame timeline demonstrates that startup UI/Dart/raster work fits the target frame budget on the target emulator or representative Android hardware.
