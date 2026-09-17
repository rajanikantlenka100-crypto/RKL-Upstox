# RKL UPSTOX — CANONICAL STRATEGY SPECIFICATION

Status: documentation-only, no production strategy code changed.

This document is the repository source-of-truth specification for the currently approved index-based trading strategy. It is intentionally written to be precise enough to allow later edits to one rule, threshold, filter, exit, timeframe, or option-selection step without ambiguity.

This specification was derived from the current repository implementation and from the explicit strategy contract supplied in the canonical request. Where code and contract differ, the mismatch is identified explicitly and not hidden.

---

## 0. Scope and source of truth

This strategy is:

- index-driven
- 5-minute candle based
- executed in options
- evaluated using finalized index candles only
- isolated per underlying index

Primary implementation files reviewed for this specification:

- `config.py`
- `main.py`
- `market_data/indicators.py`
- `signals/breakout.py`
- `signals/rsi_filter.py`
- `trading/exit_engine.py`
- `tests/test_stochastic_strategy.py`
- `tests/test_signal_type2.py`

This document is the canonical contract. Future strategy changes must update:

1. this specification
2. implementation code
3. unit tests
4. replay tests
5. sandbox validation

No production strategy logic is modified during this documentation pass.

---

## 1. Market / timeframe

### 1.1 Primary strategy timeframe

- Candle timeframe: 5-minute index candles
- Decision maker: INDEX
- Execution instrument: OPTION
- Option candles / option indicators are not strategy decision inputs
- Strategy session boundary: 09:15 to 15:15 (India time, as configured in the repo)
- Exchange trading session is distinct from strategy session and is not a new exit rule

### 1.2 Supported indexes

Supported active indexes in repository configuration:

- NIFTY
- BANKNIFTY
- SENSEX
- MIDCPNIFTY

The repository configuration restricts active indices to these values, and rejects unsupported values.

### 1.3 Instrument-level rule mapping

| Index | Exchange | Strike interval | ATM selection rule | Expiry rule | CE/PE mapping | Lot-size source | Quantity rule |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NIFTY | NSE_INDEX | 50 | nearest interval ATM around current index LTP | nearest valid expiry >= today | CALL -> CE, PUT -> PE | Upstox instrument master row `lot_size` / `lotsize` | `contract lot_size * LOT_COUNT` |
| BANKNIFTY | NSE_INDEX | 100 | nearest interval ATM around current index LTP | nearest valid expiry >= today | CALL -> CE, PUT -> PE | Upstox instrument master row `lot_size` / `lotsize` | `contract lot_size * LOT_COUNT` |
| SENSEX | BSE_INDEX | 100 | nearest interval ATM around current index LTP | nearest valid expiry >= today | CALL -> CE, PUT -> PE | Upstox instrument master row `lot_size` / `lotsize` | `contract lot_size * LOT_COUNT` |
| MIDCPNIFTY | NSE_INDEX | 25 | nearest interval ATM around current index LTP | nearest valid expiry >= today | CALL -> CE, PUT -> PE | Upstox instrument master row `lot_size` / `lotsize` | `contract lot_size * LOT_COUNT` |

### 1.4 ATM and expiry selection

The execution path is:

1. signal underlying + direction
2. nearest valid expiry
3. ATM strike selected using configured interval
4. correct CE / PE option
5. official Upstox instrument identity
6. lot size and tick validation
7. quantity derived from lot size

The ATM rule is implemented as:

- `target = round(ltp / strike_interval) * strike_interval`
- then select the closest valid contract to that strike within the valid expiry

The valid expiry is the earliest valid expiry on or after the current date. No option candle history is used in this step.

### 1.5 Instrument identity and data isolation

- Indicator history is stored and evaluated per underlying symbol
- NIFTY indicator history must never be reused for SENSEX
- strategy decision inputs are only closed index candles, never option candles

---

## 2. Market session

### 2.1 Strategy session boundary

The active strategy session boundary is:

- market open: 09:15
- market close: 15:15

This is the strategy window. It is not an additional exit rule and must not be confused with the exchange session definition or other schedule logic.

### 2.2 Exchange session distinction

The repo configuration distinguishes:

- `MARKET_OPEN` / `MARKET_CLOSE`: strategy session boundary
- exchange market status: an operational status, not a new strategy trigger

No new exit rule is introduced by this session definition.

---

## 3. Indicators

All strategy indicators are calculated from finalized index candles only. Running candles are never used as strategy entry inputs for the main filters.

### 3.1 Common rule

- Indicator data source: finalized index candles only
- Option candles: never used for indicator computation
- History must be isolated by underlying symbol
- Minimum history is defined per indicator below
- Equality does not qualify for trend-based filters
- Insufficient history yields unavailable state rather than pass

### 3.2 SMA8 / SMA13 / SMA21

Formula:

- SMA(period) = arithmetic mean of the last `period` finalized closes

Required alignment:

- closed candle requirement: all candles in the window must be `FINAL`
- running candle usage: not used
- minimum history: at least 21 finalized candles for a valid 8/13/21 comparison
- underlying-specific history: each index maintains its own closed-candle history; no cross-index smoothing

Strict entry filter rule:

- CALL: `SMA8 > SMA13 > SMA21`
- PUT: `SMA8 < SMA13 < SMA21`
- equality: not valid
- insufficient history: not valid

### 3.3 RSI14 and RSI14-SMA5

The repo uses Wilder RSI14.

Formula summary:

- step 1: compute close-to-close changes for each period
- step 2: separate gains and losses
- step 3: compute average gain and average loss over the first 14 change periods
- step 4: compute RSI = `100 - 100 / (1 + avg_gain/avg_loss)` when average loss > 0
- step 5: when average loss is zero, RSI is `100` if average gain > 0 else `50`
- step 6: continue updating average gain/loss as subsequent closes arrive

The filter is:

- CALL: `RSI14 < RSI14_SMA5`
- PUT: `RSI14 > RSI14_SMA5`

The strategy uses finalized closed-candle history only. The last 5 finalized RSI/SMA pairs are evaluated for the entry condition, and insufficient history is `UNAVAILABLE` rather than `PASS`.

### 3.4 CCI5

Formula:

- Typical Price = `(high + low + close) / 3`
- Mean = arithmetic mean of the last 5 typical prices
- Mean deviation = average absolute deviation from the mean
- CCI = `(TP - mean) / (0.015 * mean_deviation)`

Requirements:

- finalized index candles only
- minimum history: at least 5 finalized candles
- can be used as a running signal or closed-candle confirmation depending on exit rule

### 3.5 Fast Stochastic14

Exact formula:

- `Stochastic %K = 100 * (close - lowest_low_14) / (highest_high_14 - lowest_low_14)`

Rules:

- Fast %K only
- no slow stochastic
- only closed index candles
- running candle must not be used for stochastic entry filtering
- if fewer than 14 usable closed candles exist, stochastic is unavailable
- if the 14-period range is zero, stochastic is unavailable
- history must be isolated by underlying symbol

For the signal engine, the latest 5 closed values are used for the stochastic exception rule.

---

## 4. Fast Stochastic14 details

### 4.1 Exact formula

For a finalized candle index `i` with a 14-candle closed window:

- `lowest_low_14 = min(low over last 14 finalized candles)`
- `highest_high_14 = max(high over last 14 finalized candles)`
- `closed_close = close of candle i`

Then:

`100 * (closed_close - lowest_low_14) / (highest_high_14 - lowest_low_14)`

### 4.2 Requirements and exclusions

- only closed index candles are valid
- running candle cannot satisfy the entry filter stochastic requirement
- `highest_high_14 == lowest_low_14` => stochastic unavailable
- fewer than 14 usable finalized candles => stochastic unavailable
- per-underlying isolation is mandatory

### 4.3 Strict interpretation from canonical contract

- Stochastic histories never cross between NIFTY and SENSEX
- The stochastic computation must not use any option data

---

## 5. SMA entry filter

The strict SMA trend filter is:

- CALL: `SMA8 > SMA13 > SMA21`
- PUT: `SMA8 < SMA13 < SMA21`
- equality does not qualify
- insufficient history does not qualify

The canonical contract treats any non-strict trending relationship as blocked or unavailable, not as a valid entry condition.

---

## 6. Stochastic SMA exception

This is an entry-filter exception only. It does not alter the global SMA state.

### 6.1 CALL exception

If the normal call SMA trend fails because:

- `SMA8 < SMA13 < SMA21`

then CALL may still qualify when any of the latest 5 closed Fast Stochastic14 values is strictly:

- `< 10`

Exact `10` does not qualify.

### 6.2 PUT exception

If the normal put SMA trend fails because:

- `SMA8 > SMA13 > SMA21`

then PUT may still qualify when any of the latest 5 closed Fast Stochastic14 values is strictly:

- `> 90`

Exact `90` does not qualify.

### 6.3 Recordkeeping required

The entry result must record:

- `entry_filter = sma_normal` or `entry_filter = stochastic_exception`
- the relevant stochastic values used to qualify the exception
- the latest 5 closed stochastic values and the matching subset

The repository implementation stores this as the `stochastic_values` and `entry_filter` values on the signal artifact.

---

## 7. RSI filter

The RSI entry rule is:

- CALL: `RSI14 < RSI14_SMA5`
- PUT: `RSI14 > RSI14_SMA5`

Implementation requirements:

- approved Wilder RSI14 calculation
- only finalized index candles
- running candle cannot satisfy RSI filter
- insufficient history is `UNAVAILABLE`
- filter is determined from the latest 5 finalized candle periods in the repository implementation

---

## 8. Type 1

Type 1 is a running-candle breakout signal built from a prior candle and the current running candle.

### 8.1 CALL condition

CALL Type 1 requires:

1. running price reaches or crosses previous candle low first
2. later running price reaches or crosses previous candle high
3. only one candidate per candle sequence

The expected event pattern is:

- low breakout first
- later high breakout second
- valid only when direction is CALL

### 8.2 PUT condition

PUT Type 1 is the mirror condition:

- running price reaches or crosses previous candle high first
- later running price reaches or crosses previous candle low

### 8.3 Trigger and ordering requirement

- trigger is the running price crossing the previous candle boundary
- ordering must be low-first then high-second for CALL, and high-first then low-second for PUT
- a late counter-direction breakout is not valid for the same sequence

### 8.4 Duplicate suppression

- one candidate only per candle timestamp sequence
- duplicates are suppressed by engine state (`call_fired`, `put_fired`, `candle_timestamp`)

### 8.5 New-candle reset

When a new candle timestamp is seen, the breakout state is reset for that sequence. This ensures only one Type 1 candidate per new candle sequence is emitted.

### 8.6 Gap handling

The implementation uses the previous LTP and current LTP transition to detect crossing events. If the sequence has no first-break event or second-break event, no signal is emitted.

### 8.7 Entry filter requirements

Type 1 entry uses the same finalized-candle entry decision as other signal types:

- RSI pass required
- SMA pass required OR stochastic exception allowed

### 8.8 Option selection

Type 1 signals select the nearest valid option expiry and ATM strike based on the underlying signal and direction, without using any option indicator history.

---

## 9. Type 2

Type 2 is a breakout-squeeze pattern with a strict-body requirement.

### 9.1 CALL Type 2 conditions

CALL Type 2 requires all of the following:

1. `abs(previous.close - previous.open) <= 25% of previous candle range`
2. `previous.close > previous candle midpoint`
3. `previous.low < previous2.low`
4. `previous.low < running.low`
5. `running.high > previous.high`
6. RSI filter passes
7. SMA filter passes, or the stochastic exception qualifies if normal SMA trend fails

This is the repository contract, and the canonical rule is applied consistently for all signal types.

### 9.2 PUT Type 2 conditions

PUT Type 2 is the exact mirror:

1. `abs(previous.close - previous.open) <= 25% of previous candle range`
2. `previous.close < previous candle midpoint`
3. `previous.high > previous2.high`
4. `previous.high > running.high`
5. `running.low < previous.low`
6. RSI filter passes
7. SMA filter passes, or the stochastic exception qualifies if normal SMA trend fails

### 9.3 Type 2 strictness

- body condition is strict and must be at most 25% of the previous-range size
- no duplicate candidate in the same running candle sequence
- signal is not emitted if any required condition fails

---

## 10. Type 3

Type 3 retains the Type 2 state pattern but removes the body-size constraint.

### 10.1 CALL Type 3 conditions

CALL Type 3 requires:

1. `previous.close > previous candle midpoint`
2. `previous.low < previous2.low`
3. `previous.low < running.low`
4. `running.high > previous.high`
5. `running.low < previous.close`
6. RSI filter passes
7. SMA filter passes, or stochastic exception qualifies if normal SMA trend fails

### 10.2 PUT Type 3 conditions

PUT Type 3 requires:

1. `previous.close < previous candle midpoint`
2. `previous.high > previous2.high`
3. `previous.high > running.high`
4. `running.low < previous.low`
5. `running.high > previous.close`
6. RSI filter passes
7. SMA filter passes, or stochastic exception qualifies if normal SMA trend fails

### 10.3 Type 3 note

The body-size test is removed in Type 3, but the entry filter and the stochastic exception remain mandatory by contract.

---

## 11. Option selection

The signal is:

- index
- direction

Then the implementation picks:

- nearest valid expiry
- ATM strike
- correct CE/PE side
- official Upstox instrument identity
- lot size
- tick validation
- quantity

The option contract is the execution instrument only. Strategy indicators are never computed from option candles.

---

## 12. Quantity

The contract quantity is:

- `quantity = contract lot_size * LOT_COUNT`

Default:

- `LOT_COUNT = 1`

This must remain a valid whole-number contract quantity. Fractional lots are not valid.

---

## 13. Exit conditions

A position may exit on the first valid exit event that occurs while the position is open.

### 13.1 Existing exits in repository contract

A. CALL previous-low exit

- condition: `running.low < previous.low`

B. PUT previous-high exit

- condition: `running.high > previous.high`

These are the baseline exit triggers.

---

## 14. CCI exit

### 14.1 CALL CCI exit

- After entry, the first time running CCI5 is greater than `+100`, the exit state arms
- After arming, newly closed qualifying green index candles are tracked
- the latest qualifying green candle becomes the reference candle
- exit when `running.low < latest qualifying green candle.low`
- the arm candle cannot confirm itself
- repeated intrabar overshoots do not re-arm

### 14.2 PUT CCI exit

- After entry, the first time running CCI5 is less than `-100`, the exit state arms
- After arming, newly closed qualifying red index candles are tracked
- the latest qualifying red candle becomes the reference candle
- exit when `running.high > latest qualifying red candle.high`

### 14.3 Qualification rule for reference candle

A qualifying reference candle must be directionally colored and sufficiently decisive for the active direction:

- CALL: green candle, body is meaningful, and closes above open
- PUT: red candle, body is meaningful, and closes below open

The implementation tracks only qualified reference candles, and the arm candle itself cannot be used as confirmation.

---

## 15. Candle-size exit

The standard candle is the index candle immediately preceding the entry running candle.

### 15.1 CALL candle-size exit

Exit when the running or closed green index candle range is strictly greater than:

- `3 * standard_range`

### 15.2 PUT candle-size exit

Exit when the running or closed red index candle range is strictly greater than:

- `3 * standard_range`

### 15.3 Equality rule

Exactly `3x` does not trigger.

---

## 16. Stochastic reversal exit

This exit is based on closed index candles only. A running stochastic value must never trigger this exit.

### 16.1 CALL reversal exit

- First closed Stochastic14 greater than 90 arms the state
- The arm candle cannot trigger its own reversal
- After arming, if current closed stochastic is lower than the immediately preceding closed stochastic, exit occurs

Examples:

- `80 -> 93 -> 89 = EXIT`
- `80 -> 93 -> 96 = NO EXIT`
- `80 -> 93 -> 93 = NO EXIT`
- `80 -> 93 -> 96 -> 91 = EXIT`
- `93 -> 96 -> 94 = EXIT`

### 16.2 PUT reversal exit

- First closed Stochastic14 lower than 10 arms the state
- After arming, if current closed stochastic is higher than the immediately preceding closed stochastic, exit occurs

Examples:

- `20 -> 7 -> 11 = EXIT`
- `20 -> 7 -> 5 = NO EXIT`
- `20 -> 7 -> 7 = NO EXIT`
- `20 -> 7 -> 5 -> 12 = EXIT`

### 16.3 Implementation semantics

The exit condition uses a strict threshold and an immediate-previous-value comparison. The state is per-position, not global.

---

## 17. Position isolation

Every position must have its own lifecycle and exit state. This includes:

- `trade_id`
- `signal_id`
- `underlying`
- `direction`
- `option contract`
- `broker order ID`
- `entry fill`
- `exit order ID`
- `exit reason`
- `P&L`
- `own StrategyExitState`
- `CCI state`
- `stochastic state`
- `standard candle`

Important constraints:

- Position A must never inherit Position B's exit state
- NIFTY positions must never use SENSEX indicator history
- per-position exit state must not be shared across underlyings or trade IDs

---

## 18. Position lifecycle

The repository lifecycle states are:

- `PENDING_ENTRY`
- `PARTIALLY_FILLED`
- `OPEN`
- `EXIT_PENDING`
- `CLOSED`
- `ERROR`
- `UNKNOWN`

Important rules:

- unknown broker outcomes remain `UNKNOWN`
- never fabricate fills
- never create duplicate SELL orders

---

## 19. Signal lineage

Required lineage:

- `signal_id`
- `signal type`
- `direction`
- `entry filter`
- `index`
- `selected option`
- `instrument token`
- `broker order`
- `fill`
- `trade_id`
- `position`
- `exit state`
- `exit order`
- `exit fill`
- `realized P&L`

This is the trace chain for auditability and reconciliation.

---

## 20. Strategy configuration

The following values are the active configuration levers in the repo and should be treated as configurable parameters only when explicitly required by the implementation contract.

### 20.1 CONFIGURABLE PARAMETERS

| Name | Default | Allowed range / type | Meaning | Affected rules |
| --- | --- | --- | --- | --- |
| TIMEFRAME | 5 minutes | positive integer minutes | base candlestick resolution | all index decisions |
| SESSION OPEN | 09:15 | `HH:MM` time | strategy entry window start | session gating |
| SESSION CLOSE | 15:15 | `HH:MM` time | strategy entry window end | session gating |
| SMA PERIODS | 8/13/21 | positive ints | trend filter configuration | SMA entry filter |
| RSI PERIOD | 14 | positive int | RSI window | RSI filter |
| RSI SMA PERIOD | 5 | positive int | smoothed RSI baseline | RSI filter |
| CCI PERIOD | 5 | positive int | CCI calculation | CCI exit |
| STOCHASTIC PERIOD | 14 | positive int | stochastic window | stochastic entry / exit |
| STOCHASTIC ENTRY THRESHOLDS | 10 / 90 | numeric threshold values | stochastic exception gating | stochastic SMA exception |
| STOCHASTIC EXIT THRESHOLDS | 90 / 10 | numeric threshold values | reversal arm/trigger threshold | stochastic reversal exit |
| TYPE 2 BODY PERCENT | 25% | numeric fraction / percent | maximum small-body tolerance | Type 2 condition |
| CANDLE SIZE MULTIPLIER | 3 | positive numeric multiplier | range expansion alarm threshold | candle-size exit |
| LOT_COUNT | 1 | positive integer | lot multiplier for quantity | quantity calculation |
| INDEX STRIKE INTERVALS | NIFTY 50, BANKNIFTY 100, SENSEX 100, MIDCPNIFTY 25 | positive numeric map | ATM strike step size | option selection |

No arbitrary values are added to the config surface without this contract update.

---

## 21. Change control

This specification is the canonical strategy source-of-truth.

Any future strategy modification must update, in order:

1. this specification
2. implementation code
3. unit tests
4. replay tests
5. sandbox validation

No strategy code change may be made without an accompanying specification update.

---

## 22. Exact existing implementation summary

The current repository implementation directly includes the following active rules:

- `config.py` defines active indexes and session boundaries
- `config.LOT_COUNT` is enforced as a positive integer and used in quantity sizing
- `market_data/indicators.py` calculates SMA, RSI, CCI, and Fast Stochastic with finalized-candle-only logic
- `signals/breakout.py` defines Type 1, Type 2, and Type 3 trigger patterns
- `signals/rsi_filter.py` applies the finalized-candle RSI rule
- `main.py` unifies all signal types under a single entry decision (`_entry_sma_result`) and a single RSI filter check
- `trading/exit_engine.py` implements the per-position exit state, CCI exit, candle-size exit, and stochastic reversal exit

The implementation is point-in-time behavior and the canonical specification above is the permanent contract.

---

## 23. Exact canonical specification summary

The canonical strategy is:

- 5-minute index-candle strategy operating on finalized index candles only
- decisions from NIFTY, BANKNIFTY, SENSEX, MIDCPNIFTY only
- trade execution in options using nearest valid expiry + ATM strike + CE/PE mapping
- strict MA trend with direction-specific ordering and equality rejection
- stochastic exception allowed only for the opposite SMA ordering and only when a strict threshold is hit in the last 5 closed stochastic values
- RSI filter on Wilder RSI14 vs RSI14-SMA5
- Type 1/2/3 breakout triggers with duplicate suppression and finalized-candle filters
- per-position exit states with independent CCI and stochastic reversal tracking
- exit triggers for previous-candle break, CCI confirmation, candle-size expansion, and stochastic reversal

---

## 24. Mismatch / missing rule / ambiguity review

### 24.1 Current implementation status

The current repository code is largely consistent with the canonical contract described above, especially in:

- finalized-candle indicator isolation
- stochastic threshold semantics
- per-position exit state isolation
- CCI and stochastic exit logic
- flow of `LOT_COUNT` into contract quantity calculations

### 24.2 Mismatch to watch explicitly

The only significant risk is not a silent code change but a documentation ambiguity if the strategy is later reinterpreted: the contract requires the entry-filter exception to behave identically for every signal type, and any future change to that rule must be reflected in both the specification and the signal admission logic.

The repository code implements that logic in `main.py` via `_entry_sma_result()` and applies it across all signal types, which is the correct canonical behavior in the current repository state.

### 24.3 Missing rule identification

No material rules are silently invented in this document. Where the repository is silent or ambiguous, this document records the requirement as a canonical contract only when it is explicitly required by the attached strategy specification or by the active implementation.

### 24.4 Ambiguity

The repository does not contain a conflicting production implementation for the approved logic in the current branch. The only ambiguity expressed in historical review notes is a mismatch between an earlier summary and the present code path; that ambiguity is resolved here by favoring the actual current implementation and the explicit canonical contract.

---

## 25. Final status

This document is the canonical strategy specification for the active repository state and includes:

- exact market/timeframe rules
- exact indicator formulas and gating
- exact Type 1/2/3 trigger rules
- exact option selection and quantity rules
- exact exit rules and lifecycle rules
- explicit configuration parameter list
- explicit mismatch and ambiguity review

No production strategy code was modified during this documentation pass.
