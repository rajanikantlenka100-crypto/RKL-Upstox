# RKL Mobile Architecture Assessment

## Current repository facts

The production path is a Python service started by `main.py`. It owns Upstox authentication, market WebSocket normalization, candles, historical reconciliation, indicators, signals, option selection, order execution, position reconciliation, safety gates, observability, and SQLite persistence. `TerminalDisplay.snapshot()` is the current authoritative read model used by `web_dashboard.py`.

The repository currently has no FastAPI application, no Flutter project, and no WebSocket endpoint for clients. The dashboard is a standard-library HTTP server with `/health`, `/ready`, `/state`, and an unauthenticated server-sent-events `/events` stream. The mobile API added here is a compatibility layer over the existing snapshot; it does not create a second trading pipeline.

## API and data mapping

- `/api/mobile/status`: execution mode, market state, component states, preflight, heartbeat metadata.
- `/api/mobile/market` and `/api/mobile/indices`: authoritative ticks, current/previous candles, health, and synchronization state.
- `/api/mobile/options`: backend option universe, option quotes, and active signal selection.
- `/api/mobile/signals`: signal history, queue, and active signal.
- `/api/mobile/orders`: existing dashboard order state.
- `/api/mobile/positions`: existing position state and position details.
- `/api/mobile/notifications`: existing event stream state.
- `/api/mobile/reports`: persisted daily reports from SQLite.
- `/api/mobile/sandbox`: explicit sandbox availability marker; no production data is fabricated.

All mobile routes require `Authorization: Bearer <MOBILE_API_TOKEN>`. The token is backend configuration and is never read from Upstox credentials.

## Security and deployment

Keep `DASHBOARD_HOST=127.0.0.1` and do not expose port 8765 directly. Put an HTTPS reverse proxy/API gateway in front of a dedicated mobile API process or private tunnel, enforce TLS, authentication, role authorization, rate limiting, request-size limits, audit logging, and short-lived device-scoped sessions. Control operations such as start/stop/restart are deliberately not exposed by this first read-only slice. They must be separate authenticated commands with explicit confirmation and server-side authorization checks.

## Implementation plan

1. Validate the read-only contract locally with `READ_ONLY` and no real orders.
2. Replace the bootstrap bearer token with login, device registration, session expiry, admin/operator/read-only/sandbox roles, and audit records.
3. Add a real WebSocket gateway that publishes snapshot deltas from the existing state; keep REST for initial load and reports.
4. Add backend serializers for full signal evaluation, filter outcomes, option details, broker order responses, authoritative fills, and sandbox trade tables.
5. Add Android reconnect, offline/error states, biometric unlock, and UI tests.
6. Deploy the API behind HTTPS without changing systemd or the trading engine; then build a signed APK/AAB.

## Risks and required tests

The current snapshot contains some display-oriented strings and does not yet expose every requested detail, especially complete filter evaluation, broker response payloads, sandbox trade analytics, and service-control authorization. Those should be added as read-only serializers backed by existing tables/events, never recalculated in Flutter.

Required checks include full pytest, mobile API authorization, API unavailable state, stale/closed market state, reconnect after network loss, WebSocket gateway reconnect once introduced, sandbox database separation, role permissions, audit logging, and release build validation. No production order behavior or systemd unit should change as part of mobile work.
