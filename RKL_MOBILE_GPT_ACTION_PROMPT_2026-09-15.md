# RKL Upstox Mobile AWS Integration
# Final GPT Prompt / Report

**Date:** 2026-09-15  
**Objective:** Connect the existing Flutter RKL Upstox mobile observer app to the live AWS-hosted backend without changing production trading safety, behavior, or credentials.

## Current Verified Repository State

- The repo already contains mobile REST support in `web_dashboard.py`.
- The repo already contains mobile WebSocket support in `web_dashboard.py`.
- The repo already contains authenticated mobile API routes under `/api/mobile/*` and `/api/v1/mobile/*`.
- The repo already contains the mobile WebSocket endpoint `/api/v1/mobile/stream`.
- The repo already contains mobile client configuration in `mobile_app/lib/main.dart` using `RKL_API_BASE`, `RKL_API_WS_BASE`, and `RKL_API_TOKEN`.
- Current checked-in config shows:
  - `DASHBOARD_PORT=8876`
  - `MOBILE_WS_PORT=8766`
  - `MOBILE_API_TOKEN` already present
- The checked-in repo does not support the assumption that `8765` is the mobile dashboard port.
- The Flutter app has already passed:
  - `flutter pub get`
  - `flutter analyze`
  - `flutter test` (2 passed, 0 failed)

## Important Safety Requirements

This AWS machine runs the real trading engine. The following must remain unchanged:

- trading strategy
- signal engine
- option selection
- order manager
- broker execution
- position management
- production preflight
- Upstox credentials
- Upstox access token
- `UPSTOX_ORDER_IP`
- production `.env`
- existing systemd service definition
- existing dashboard behavior
- existing port `8765` behavior

Do NOT:

- stop the production service
- restart the production service unless absolutely unavoidable and explicitly reported first
- modify systemd
- modify production trading configuration
- disable real-order protection
- place an order
- cancel an order
- modify a position
- expose the Upstox token
- expose AWS credentials
- expose SSH credentials
- expose the production SQLite database directly
- expose port `8765` directly to the Internet
- expose `8876/8877` directly to the Internet

The mobile app must remain READ_ONLY.

## Required Investigation Flow

### Phase 1 — Inspect the live AWS state

Run:

- `sudo systemctl is-active rkl-upstox.service`
- `sudo systemctl status rkl-upstox.service --no-pager -l`
- `sudo ss -lntp | grep -E ':8765|:8876|:8877|:8766'`

Then inspect the current configuration without changing it:

- `.env`
- `config.py`
- `main.py`
- `web_dashboard.py`

Determine:

1. Which process owns port `8765`.
2. Whether mobile REST endpoints are already implemented.
3. Whether mobile REST is served by the existing dashboard server.
4. Whether mobile WebSocket is already implemented.
5. Which port the mobile WebSocket actually uses.
6. Whether a separate mobile gateway is required.
7. Whether the existing dashboard server can safely serve mobile API requests without changing its trading behavior.

### Phase 2 — Test existing mobile API locally on AWS

Before creating any new service, test the existing API through localhost.

Use the actual existing dashboard port found from the live inspection and source, not assumptions.

Test examples:

- `curl -i http://127.0.0.1:<actual-dashboard-port>/api/v1/mobile/status`

If authentication is required, use the existing mobile authentication mechanism.

NEVER print the token.

If the mobile API is available on the existing dashboard port:

- do not create another HTTP server unnecessarily
- use the existing server

If mobile API is not available on the existing dashboard, determine the correct existing startup path from the source code.

### Phase 3 — Verify mobile authentication

Test:

1. unauthenticated request
2. authenticated request

Expected:

- unauthenticated => rejected
- authenticated => successful

Do not expose the token in terminal output.

Verify the response contains no:

- Upstox access token
- AWS credential
- SSH credential
- broker secret
- database password

### Phase 4 — Verify mobile data

Using the existing mobile API, validate:

- `/api/v1/mobile/status`
- `/api/v1/mobile/market`
- `/api/v1/mobile/signals`
- `/api/v1/mobile/options`
- `/api/v1/mobile/orders`
- `/api/v1/mobile/positions`
- `/api/v1/mobile/notifications`
- `/api/v1/mobile/reports`

Do not fabricate data.

Use the actual authoritative backend data.

It is acceptable for orders/positions/signals to be empty.

Confirm that:

- market state is authoritative
- index data is authoritative
- options data is authoritative
- orders are read-only
- positions are read-only
- P&L is read-only
- notifications are read-only

### Phase 5 — Verify WebSocket

Inspect the actual implementation to determine the correct WebSocket port.

Do NOT assume `8877`.

Inspect the checked-in source first; the repo currently points to `8766` for `MOBILE_WS_PORT`.

Test the existing WebSocket endpoint using localhost.

Expected mobile protocol:

- `rkl.mobile.v1`

Verify:

- valid authentication connects
- invalid authentication is rejected
- messages are valid JSON
- sequence numbers are valid
- no secrets are sent
- no order/write operation is available

### Phase 6 — Do not change the production engine

At this point:

- stop if mobile API already works through the existing dashboard
- do not modify `main.py` just to create another server
- do not modify the trading engine
- do not modify systemd
- do not change production `.env`

If a separate mobile gateway is genuinely required, create it as an independent READ_ONLY process.

The gateway must:

- bind to `127.0.0.1` only
- expose only the mobile REST/WS interface
- have no broker execution capability
- have no order placement capability
- have no access to credentials except the minimum required mobile authentication configuration
- read authoritative data from the existing backend
- never expose the production database directly
- never accept trading commands

### Phase 7 — Public phone access

Only after localhost mobile REST + WebSocket validation succeeds.

We need a temporary public HTTPS/WSS endpoint for physical-phone testing.

Preferred temporary architecture:

Android Phone -> HTTPS / WSS -> Cloudflare Quick Tunnel -> 127.0.0.1 -> existing RKL backend

Do NOT expose port `8765` directly.

Do NOT open AWS Security Group ports to the Internet.

Do NOT expose SSH.

Do NOT expose Upstox.

If cloudflared is already installed, use it.

If not installed, first check:

- `which cloudflared`

Do not install anything without first reporting what is required.

If the existing mobile API is safely served on the existing dashboard port, do NOT create an unnecessary duplicate service.

### Phase 8 — Verify the public endpoint

After Cloudflare provides a temporary HTTPS hostname:

- test `https://<generated-host>/api/v1/mobile/status` with valid mobile authentication
- test `wss://<generated-host>/<actual-mobile-websocket-path>`

Verify:

- HTTPS => PASS
- WSS => PASS
- authentication => PASS
- invalid authentication => REJECTED

Do not print the token.

### Phase 9 — Configure the Flutter app

Inspect:

- `mobile_app/lib/main.dart`
- existing API configuration mechanism

Do not hard-code credentials.

Do not hard-code a temporary tunnel URL into permanent production source.

Use a build/runtime configuration mechanism.

For the physical phone, configure:

- `RKL_API_BASE=https://<actual-generated-host>`
- `RKL_API_WS_BASE=wss://<actual-generated-host>`

Use the correct WebSocket path already implemented by the application.

Do not use:

- `localhost`
- `127.0.0.1`
- `10.0.2.2`

for the physical phone.

### Phase 10 — Build profile APK

On the development PC, verify:

- `flutter pub get`
- `flutter analyze`
- `flutter test`

Then build the existing PROFILE APK.

Do NOT attempt to bypass Windows Application Control.

If `gen_snapshot.exe` is blocked again:

- stop
- report `RELEASE BUILD BLOCKED BY WINDOWS APPLICATION CONTROL`

Do not disable Windows security globally.

A profile/debug build is acceptable for physical testing.

### Phase 11 — Physical phone test

Install the profile APK on the real Android phone.

Use mobile data / 4G / 5G.

Do not rely only on local Wi-Fi.

Verify:

1. App launches.
2. Authentication works.
3. Control Centre loads.
4. Market screen loads.
5. NIFTY data loads.
6. BANKNIFTY data loads.
7. SENSEX data loads.
8. MIDCPNIFTY data loads.
9. Market status is correct.
10. Freshness timestamps work.
11. Signals load.
12. Options load.
13. Orders load.
14. Positions load.
15. Notifications load.
16. Reports load.
17. WebSocket connects.
18. WebSocket updates arrive.
19. WebSocket reconnect works.
20. Dark theme works.
21. Light theme works.
22. PRO theme works.
23. NEON theme works.
24. Theme persistence works.
25. No raw map/list dumps appear.
26. No fake market data appears.
27. No trading/write controls are exposed.

### Phase 12 — Performance

Observe the physical phone.

Check for:

- crashes
- RenderFlex overflow
- RenderBox errors
- excessive REST calls
- repeated WebSocket reconnects
- frozen UI
- stale data
- high CPU usage
- unnecessary screen rebuilds

Do not perform unrelated UI refactoring.

### Phase 13 — Production safety verification

After testing, verify:

- `sudo systemctl is-active rkl-upstox.service`

Expected:

- `active`

Verify:

- `sudo ss -lntp | grep -E ':8765|:8876|:8877|:8766'`

Confirm the original trading service remains running.

Do not restart it merely for reporting.

## Final Report Format

Return this exact structure:

1. AWS ENGINE
RUNNING / NOT RUNNING

2. EXISTING DASHBOARD
WORKING / NOT WORKING

3. MOBILE REST
PORT:
STATUS:
AUTH:
DATA:

4. MOBILE WEBSOCKET
PORT:
STATUS:
AUTH:
PROTOCOL:

5. PUBLIC HTTPS
CREATED / NOT CREATED
URL:
Do not include credentials.

6. PUBLIC WSS
PASS / FAIL

7. FLUTTER
PUB GET:
ANALYZE:
TEST:
PROFILE APK:

8. PHYSICAL PHONE
CONNECTED / NOT CONNECTED
4G/5G TEST:
REST:
WSS:
MARKET:
SIGNALS:
OPTIONS:
ORDERS:
POSITIONS:
NOTIFICATIONS:
REPORTS:
THEMES:

9. SECURITY
AUTHENTICATION:
SECRETS EXPOSED:
PRODUCTION DATABASE EXPOSED:
PUBLIC TRADING PORTS EXPOSED:

10. PRODUCTION SAFETY
SYSTEMD CHANGED: YES/NO
PRODUCTION .ENV CHANGED: YES/NO
TRADING ENGINE CHANGED: YES/NO
STRATEGY CHANGED: YES/NO
ORDER MANAGER CHANGED: YES/NO
REAL ORDER PLACED: YES/NO
LIVE POSITION MODIFIED: YES/NO

11. FINAL STATUS

Use exactly one:

- `MOBILE AWS INTEGRATION READY FOR PHONE TEST`
- `MOBILE AWS INTEGRATION BLOCKED`
- `PHYSICAL PHONE VALIDATION PASSED`
- `PHYSICAL PHONE VALIDATION BLOCKED`

## IMPORTANT EXECUTION RULES

- Do not claim PASS unless actually tested.
- Do not commit or push anything unless explicitly instructed.
- Do not assume `8765` or `8877` is correct; inspect the actual running service and source configuration first.
- The checked-in repo currently indicates the mobile API already exists on the existing dashboard server and the WebSocket already exists on `8766`.
- If localhost validation already passes through the existing dashboard, do not create a duplicate server.
