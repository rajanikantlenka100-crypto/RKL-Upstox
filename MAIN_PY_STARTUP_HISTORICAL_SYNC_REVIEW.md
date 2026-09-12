# `main.py` Startup and Historical Sync Review

## Scope

Compared the current uncommitted `main.py` changes with `HEAD`, focusing on startup and historical synchronization responsibilities.

## Responsibility Review

| Responsibility | Result |
|---|---|
| Running candle restoration | Present, moved into `_backfill_index()` |
| Intraday reconciliation | Present, moved into `_backfill_index()` |
| Reconciliation blocking/unblocking | Present, shared state is updated as before |
| Historical synchronization status | Present, aggregate status is set after all indexes finish |
| REST/history status | Present, per-index success and failure status remain |
| Candle context update | Present, unchanged behavior |
| Indicator update | Present, unchanged behavior |
| Index engine seeding | Present, moved into `_backfill_index()` |
| Historical data validation | Present, including parsing, ordering, duplicates, finalized filtering, and warmup |
| Historical sync error handling | Present, per-index failures are handled and reported |

## Safety Concerns

- The original sequential backfill now runs per-index work concurrently through a thread pool. This changes execution ordering and shared-state access patterns.
- Intraday reconciliation can mark an index `MISMATCH`, after which the surrounding flow sets the same index back to `SYNCED`. This behavior already existed in `HEAD`.
- Dashboard startup now occurs earlier, before authentication and order/position reconciliation.
- Timing diagnostics are additive and report only index names and elapsed durations. They do not expose credentials, tokens, account data, or order information.

## Conclusion

The required historical synchronization responsibilities remain present, but the refactor changes execution structure and introduces concurrency. Those changes should be treated as the main production-safety review point before deployment.
