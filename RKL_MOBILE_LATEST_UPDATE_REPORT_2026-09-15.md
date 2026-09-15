# RKL Upstox Mobile Client
# GPT Action Handoff Report

**Date:** 2026-09-15  
**Scope:** Flutter mobile client, backend accessibility, and deployment-readiness validation  
**Status:** Mobile client changes are in place; backend/public phone deployment remains unverified in this environment

## Current Verified State

- The Flutter client remains a read-only observer using the existing authenticated mobile REST and WebSocket contracts.
- The latest client source includes the UI polish and raw-data cleanup in `mobile_app/lib/main.dart`.
- The app remains free of fabricated market, signal, option, position, or P&L data.
- The expected RKL backend is not currently running on the expected mobile ports.
- The requested public AWS/phone deployment path has not been completed in this environment.

## Latest Changes

### Flutter mobile client

- Premium dark/light/pro/neon theme framework with persisted theme selection.
- Immediate theme switching from Settings using `shared_preferences`.
- Compact market presentation with freshness labels for index cards.
- Whitelisted scalar rendering for record cards instead of raw map/list dumps.
- Guarded REST refresh and WebSocket reconnect behavior.
- Fixed vertical-flex layout behavior in the Control Centre.

### WebSocket local-port handling

- Client-side WebSocket logic now recognizes local-host situations and adjusts the listening port where applicable.
- The existing backend contract and `Authorization: Bearer <TOKEN>` behavior are preserved.

## Current Errors and Blockers

### 1) Backend offline on expected mobile ports

Fresh validation results:

- `127.0.0.1:8876` — closed
- `127.0.0.1:8877` — closed
- `127.0.0.1:8765` — open, but this is a different service already present in the environment

Because the expected mobile backend is not running, the authenticated mobile endpoints are not currently reachable.

### 2) Public AWS/mobile deployment is not yet verified

The requested real remote phone path is still pending because this environment does not provide:

- a verified AWS backend instance already running in the required read-only mode,
- a confirmed public HTTPS/WSS endpoint,
- Cloudflare Quick Tunnel or similar public exposure,
- access to a real physical Android device over 4G/5G.

### 3) Release APK build is blocked by environment policy

The release build attempt failed because Windows Application Control blocked Flutter's `gen_snapshot.exe`.

This is an environment security policy issue, not a Dart or Flutter source-code failure.

## Latest Validation Results

### Passed

```text
flutter pub get       PASS
flutter analyze       PASS: No issues found
flutter test          PASS: 2 passed, 0 failed
```

### Pending real-data validation

The backend was checked directly and the expected mobile server was not listening on the configured ports.

The following real-data checks remain pending:

- live Control Centre data,
- live Market screen data,
- real `MARKET CLOSED` and freshness states,
- live signals, options, orders, positions, notifications, and reports,
- real WebSocket payload validation.

## Suggestions and Next Actions

### Priority 1: Start the existing backend safely

Bring up the existing backend only in its established read-only configuration, then validate the authenticated mobile endpoints on the expected ports.

### Priority 2: Expose the backend publicly for the phone

Use AWS or another public tunnel solution to expose the existing mobile API and WebSocket endpoints, then set:

- `RKL_API_BASE=https://<public-host>`
- `RKL_API_WS_BASE=wss://<public-host>`

The phone must use the public URL, not `localhost`, `127.0.0.1`, or `10.0.2.2`.

### Priority 3: Validate on a real phone over mobile data

After the public endpoint is live, run the Android app on a real device over 4G/5G and verify:

- REST access,
- WebSocket connectivity,
- read-only behavior,
- control-centre and market data loading,
- theme selection and persistence.

### Priority 4: Resolve release signing/build policy

Retry the release APK build in an approved environment where Flutter's `gen_snapshot.exe` is allowed.

Do not disable security policy globally; use a trusted SDK location or an approved build environment instead.

### Priority 5: Keep the app read-only and credential-safe

The app must continue to use only the backend-issued mobile token and must not receive or store:

- Upstox tokens,
- AWS credentials,
- SSH credentials,
- broker secrets,
- production database credentials.

## Scope and Security Confirmation

The following remain unchanged:

- backend Python service,
- trading engine,
- strategy logic,
- options logic,
- order manager,
- broker integration,
- signal logic,
- production API contract.

The client remains read-only and contains no production credentials.

## Files Changed in the Latest Update

- `mobile_app/lib/main.dart`
- `mobile_app/pubspec.yaml`
- `mobile_app/pubspec.lock`
- `mobile_app/test/widget_test.dart`
- `mobile_app/README.md`

## Final Assessment for GPT

The Flutter mobile app is functionally improved and analyzer/test checks are passing, but the real backend and remote phone deployment path are still blocked by the current environment state. The immediate next required action is to bring up the existing backend in its correct read-only mode, expose it publicly, and validate the app on a real phone over mobile data.

This report intentionally replaces the prior accumulated update content so it can serve as the single current handoff document.

## Action Summary

**Ready for:** controlled profile-mode Android testing once the backend is online.  
**Not yet verified:** production-style mobile deployment, live real-data screens, and release APK distribution.  
**Production safety:** preserved.
