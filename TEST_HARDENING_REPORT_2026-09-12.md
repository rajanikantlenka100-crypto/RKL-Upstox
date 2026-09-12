# RKL Upstox Test Hardening Report

**Report date:** 2026-09-12  
**Repository baseline:** `fc5d4d7`  
**Scope:** deterministic local tests and production-safety verification  
**Deployment activity:** none  
**Live trading activity:** none

## 1. Executive Summary

The latest work corrected the six reported test/environment failures without changing production runtime code, trading strategy, broker behavior, or safety gates.

The changes are limited to four test files. They make tests independent of:

- the current calendar date for option-expiry fixtures;
- the presence of the real generated instrument master;
- desktop GUI availability;
- ambient credential environment variables; and
- live Upstox network access.

The full test suite passed twice with the same result:

```text
119 passed, 0 failed, 0 skipped, 12 subtests passed
```

The repository is **not** declared production-ready for unrestricted real-order execution. Broker-backed validation remains outstanding.

## 2. Original Failure Root Causes

### 2.1 Dashboard browser-open test

**Affected test:** `tests/test_dashboard_server.py::test_browser_open_attempt_uses_dashboard_url`

The active dashboard implementation already separates service startup from browser launching:

- `DashboardServer.start(open_browser=True)` starts and health-checks the HTTP service;
- `_open_browser()` attempts a browser only when the environment supports it;
- non-Windows headless environments without `DISPLAY` return without calling `webbrowser.open()`;
- `main.py` controls the startup option through `config.OPEN_BROWSER`.

The failure was caused by treating browser opening as unconditional in an environment where no local GUI is available. The dashboard service itself must remain usable on AWS/headless Linux, so production behavior was preserved.

A regression test now verifies that headless startup succeeds and does not call `webbrowser.open()`.

### 2.2 Read-only preflight and instrument master

**Affected test:** `tests/test_execution_modes.py::test_read_only_preflight_does_not_require_order_client`

The preflight correctly checks `config.INSTRUMENT_MASTER_PATH.exists()`. Read-only mode does not require an order client, but the runtime still depends on valid instrument data for index resolution and market functionality.

The test did not provide the generated runtime file, which is intentionally excluded from Git because it is large and refreshed runtime data. The test now creates a temporary deterministic instrument-master fixture and patches only the configured path for the test.

Production preflight was not weakened. No fake instrument data was added to production code, and `instrument_master.json` remains ignored.

### 2.3 Option-resolution fixtures expired

**Affected tests:**

- `test_entry_selection_rejects_missing_live_quote`
- `test_liquidity_ranking_prefers_fresh_high_volume_candidate`
- `test_occupied_atm_contract_uses_deterministic_next_eligible_contract`

The selector correctly rejects all contracts whose expiry is earlier than the current IST date. The fixtures used `2026-09-10`, while the test run occurred after that date.

The valid option fixtures now use a date seven days after the current IST date. This preserves the production expiry check while preventing tests from aging into failure.

The tests still exercise the intended behaviors:

- missing live quote rejection;
- liquidity ranking;
- occupied-contract deterministic fallback;
- bounded candidate selection.

A new regression test explicitly verifies that an expired contract is rejected.

### 2.4 Authentication test made a real HTTP request

**Affected test:** `tests/test_upstox_system.py::test_authentication_status_does_not_claim_token_is_valid`

The test patched `config.require_credentials()` but left the network boundary real. When no access token was available, `UpstoxAdapter.authenticate()` correctly attempted the authorization-token endpoint.

The test now:

- forces the access-token branch to be empty for deterministic setup;
- patches only `broker.upstox.UpstoxClient.request`;
- returns a non-sensitive unit-test response at that boundary;
- asserts that the authorization endpoint was invoked through the client boundary; and
- verifies that authentication emits credential-loaded status but does not claim `AUTHENTICATED`.

Real authentication behavior was not changed. No credentials were added or printed.

## 3. Files Changed

### `tests/test_dashboard_server.py`

Added `test_headless_start_does_not_attempt_browser_open`.

This verifies that the dashboard remains available in a simulated headless POSIX environment while browser launching is skipped safely.

### `tests/test_execution_modes.py`

Added a temporary JSON instrument-master fixture containing the four active index keys and patched `config.INSTRUMENT_MASTER_PATH` only for the read-only preflight test.

This retains the production availability check and tests the correct distinction between read-only order safety and runtime instrument-data availability.

### `tests/test_option_resolution.py`

Added a timezone-aware dynamic future expiry for resolver fixtures and a regression test for expired contracts.

The existing fixed-date candle-identity tests remain intentionally fixed because they test candle identity and timestamp validation, not current option selection.

### `tests/test_upstox_system.py`

Isolated the authentication test at `UpstoxClient.request`, forced the access-token exchange path, and asserted the expected authorization endpoint call.

## 4. Exact Behavioral Changes

No production behavior changed.

The test suite now explicitly documents these existing contracts:

1. Dashboard HTTP service startup is independent from browser availability.
2. Headless AWS/server execution must not require a local browser.
3. Read-only mode does not require an order client.
4. Runtime instrument-master availability remains a preflight requirement.
5. Expired option contracts remain invalid.
6. Valid option fixtures must be future-dated relative to the test clock.
7. Occupied option tokens are skipped deterministically.
8. Liquidity ranking continues to consider quote validity, volume, spread, open interest, distance, and strike tie-breaking.
9. Unit tests must isolate the Upstox network boundary.
10. Authentication status must not claim token validity merely because credentials were loaded.

## 5. Validation Evidence

### Focused validation

```text
25 passed in 3.36s
```

Command:

```powershell
python -m pytest -q tests/test_dashboard_server.py tests/test_execution_modes.py tests/test_option_resolution.py tests/test_upstox_system.py
```

### Full validation run 1

```text
119 passed, 12 subtests passed in 4.92s
```

### Full validation run 2

```text
119 passed, 12 subtests passed in 4.13s
```

No test warnings were emitted. No failures or skips were reported.

## 6. Network and Broker Safety

The latest unit-test run did not make real Upstox authentication or order calls.

The authentication test patches the smallest relevant network boundary rather than replacing the entire adapter. Other broker tests use client mocks or injected responses at their existing boundaries.

No order can be sent by the local test suite under the verified defaults.

Verified local safety state:

```text
EXECUTION_MODE=READ_ONLY
REAL_ORDERS_ENABLED=OFF
AUTO_TRADING_ENABLED=False
ORDER_GATE=False
```

No credentials, tokens, secrets, or `.env` contents were read into the report.

The following runtime artifacts remain Git-ignored:

- `instrument_master.json`
- `*.sqlite3`, including `market_data.sqlite3`
- `.env`
- `logs/`
- `.venv/`

## 7. Strategy and Production-Code Preservation

The following were not modified:

- Signal Type 1;
- Signal Type 2;
- finalized-candle RSI14/SMA5 filtering;
- breakout sequencing;
- official Upstox instrument and option identity handling;
- multiple independent positions;
- liquidity-ranking architecture;
- fixed protective stop-loss behavior;
- CCI exits;
- 5R exits;
- broker-authoritative lifecycle handling;
- duplicate-order protection;
- fail-closed safety gates;
- retry behavior;
- production mode defaults; and
- hot-reload behavior.

No production simulation path or fabricated market data was introduced.

## 8. Focused Production-Readiness Review

The latest change did not expose a new defect in the reviewed ownership boundaries. Existing reports and source review continue to indicate that the local software test layer covers the following areas:

- configuration and execution-mode boundaries;
- broker authentication classification;
- WebSocket normalization, reconnect, and polling fallback paths;
- historical and intraday reconciliation;
- finalized candle authority;
- official option resolution and live-data validation;
- Type 1 and Type 2 signals;
- RSI filtering;
- stop-loss and risk validation;
- entry and protective-stop state handling;
- CCI and 5R exits;
- manual/external exit reconciliation;
- multiple positions;
- duplicate orders;
- partial, rejected, and unknown broker responses;
- feed staleness;
- restart recovery;
- database persistence;
- dashboard health/readiness;
- audit logging; and
- fail-closed error handling.

Passing unit tests do not prove the complete real broker lifecycle. The following still require an authorized broker-backed validation environment:

1. Current Upstox authentication and token expiry behavior.
2. Market-data WebSocket connectivity and reconnect behavior during market hours.
3. Current official index and option instrument resolution.
4. Live option quote, completed OHLC, spread, and liquidity behavior.
5. Controlled entry order acknowledgement and fill behavior.
6. Protective stop placement and broker confirmation.
7. Partial fills, rejected orders, unknown responses, and timeout reconciliation.
8. Protective-stop cancellation before strategy exits.
9. CCI and 5R broker exit lifecycle.
10. External/manual exit detection and restart recovery.
11. Portfolio stream behavior and REST reconciliation consistency.
12. Static order-IP and account-level production controls.

These validations must be performed separately and must not enable live trading during ordinary development or pytest execution.

## 9. Git Status

The working tree contains only the four intended test modifications plus this report:

```text
M tests/test_dashboard_server.py
M tests/test_execution_modes.py
M tests/test_option_resolution.py
M tests/test_upstox_system.py
?? TEST_HARDENING_REPORT_2026-09-12.md
```

No commit, push, AWS modification, deployment, or production configuration change was performed.

## 10. Final Assessment

The reported test and environment failures are resolved with deterministic, narrowly scoped test changes. The local suite is repeatably green and no production safety gate was weakened.

This result supports continued read-only development and controlled validation. It does not by itself authorize production deployment or real-order execution.
