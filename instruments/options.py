"""Select and validate live Upstox index option contracts."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import config
from instruments.resolver import load_records

OPTION_EXCHANGES = {"NSE_INDEX": "NSE_FO", "BSE_INDEX": "BSE_FO", "NSE": "NSE_FO", "BSE": "BSE_FO"}
IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class OptionContract:
    underlying: str
    expiry: str
    strike: float
    option_type: str
    tradingsymbol: str
    instrument_key: str
    exchange: str
    lotsize: int
    tick_size: float

    def __getitem__(self, key):
        aliases = {"symbol": "tradingsymbol", "token": "instrument_key", "lot_size": "lotsize"}
        return getattr(self, aliases.get(key, key))


def round_to_tick(price, tick_size):
    if price <= 0 or tick_size <= 0:
        raise ValueError("Price and tick size must be positive")
    steps = (Decimal(str(price)) / Decimal(str(tick_size))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(steps * Decimal(str(tick_size)))


def validate_option_candle_identity(candle, contract: OptionContract):
    values = candle if isinstance(candle, dict) else candle.__dict__
    if str(values.get("instrument_key", values.get("token"))) != contract.instrument_key:
        raise ValueError("OPTION_CANDLE_IDENTITY_MISMATCH: instrument key")
    if str(values.get("expiry")) != contract.expiry:
        raise ValueError("OPTION_CANDLE_IDENTITY_MISMATCH: expiry")
    try:
        strike = float(values.get("strike"))
    except (TypeError, ValueError):
        raise ValueError("OPTION_CANDLE_IDENTITY_MISMATCH: strike") from None
    if strike != contract.strike:
        raise ValueError("OPTION_CANDLE_IDENTITY_MISMATCH: strike")
    if str(values.get("option_type", "")).upper() != contract.option_type:
        raise ValueError("OPTION_CANDLE_IDENTITY_MISMATCH: option type")
    return True


def validate_option_candle(row, contract: OptionContract, *, timestamp, now=None,
                           timeframe="5m", max_age_seconds=600):
    if timeframe != "5m":
        raise ValueError("OPTION_CANDLE_TIMEFRAME_INVALID")
    if timestamp.tzinfo is None:
        raise ValueError("OPTION_CANDLE_TIMESTAMP_INVALID")
    now = now or datetime.now(IST)
    age = (now - timestamp.astimezone(IST)).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise ValueError("OPTION_CANDLE_STALE")
    if timestamp.astimezone(IST).minute % 5 != 0:
        raise ValueError("OPTION_CANDLE_TIMEFRAME_INVALID")
    if isinstance(row, dict) and row.get("status") == "RUNNING":
        raise ValueError("OPTION_CANDLE_RUNNING")
    return True


def _expiry_date(value):
    try:
        epoch_milliseconds = float(value)
    except (TypeError, ValueError):
        epoch_milliseconds = None
    if epoch_milliseconds is not None:
        try:
            return datetime.fromtimestamp(epoch_milliseconds / 1000, tz=IST).date()
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError(f"Invalid option expiry: {value!r}") from error
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return datetime.strptime(str(value).upper(), "%d%b%Y").date()


def select_atm_option(underlying, exchange, ltp, direction, records=None, underlying_key=None,
                      occupied_tokens=None, quote_data=None, require_live_quote=False):
    records = records if records is not None else load_records()
    segment = OPTION_EXCHANGES.get(exchange, exchange)
    rows = [row for row in records if str(row.get("segment", "")).upper() == segment
            and str(row.get("instrument_type", "")).upper() in {"CE", "PE"}
            and (underlying_key is None or str(row.get("underlying_key")) == underlying_key)]
    if not rows:
        rows = [row for row in records if str(row.get("segment", "")).upper() == segment
            and str(row.get("instrument_type", "")).upper() in {"OPTIDX", "OPTSTK"}
            and str(row.get("name", "")).upper() in {underlying.upper(), f"{underlying.upper()} 50", "NIFTY 50", "NIFTY BANK"}]
    today = datetime.now(IST).date()
    expiries = sorted({_expiry_date(row.get("expiry")) for row in rows if row.get("expiry")})
    valid_expiries = [expiry for expiry in expiries if expiry >= today]
    if not valid_expiries:
        raise RuntimeError(f"No current option expiry for {underlying}")
    expiry = valid_expiries[0]
    rows = [row for row in rows if _expiry_date(row.get("expiry")) == expiry]
    target = round(ltp / config.STRIKE_INTERVALS[underlying]) * config.STRIKE_INTERVALS[underlying]
    suffix = "CE" if direction == "CALL" else "PE"
    occupied_tokens = {str(token) for token in (occupied_tokens or set())}
    candidates = []
    for row in rows:
        if str(row.get("option_type", row.get("instrument_type", ""))).upper() != suffix:
            continue
        token = str(row.get("instrument_key"))
        if token in occupied_tokens:
            continue
        strike = float(row.get("strike_price", row.get("strike", 0)))
        if abs(strike - target) > 2 * config.STRIKE_INTERVALS[underlying]:
            continue
        quote = (quote_data or {}).get(token, {})
        ltp_value = quote.get("ltp", row.get("last_price"))
        volume = quote.get("volume", row.get("volume", 0)) or 0
        oi = quote.get("open_interest", row.get("open_interest", 0)) or 0
        bid = quote.get("bid", row.get("bid"))
        ask = quote.get("ask", row.get("ask"))
        try:
            spread_pct = ((float(ask) - float(bid)) / float(ltp_value) if ltp_value and bid is not None and ask is not None
                          and float(ask) >= float(bid) and float(ltp_value) > 0 else float("inf"))
        except (TypeError, ValueError):
            spread_pct = float("inf")
        try:
            valid_quote = bool(quote.get("fresh", not require_live_quote)
                               and ltp_value is not None and float(ltp_value) > 0)
        except (TypeError, ValueError):
            valid_quote = False
        if require_live_quote and not valid_quote:
            continue
        candidates.append((0 if valid_quote else 1, -float(volume), spread_pct, -float(oi),
                           abs(strike - target), strike, row))
    if not candidates:
        raise RuntimeError(f"No {direction} contract found for {underlying} expiry {expiry}")
    _, _, _, _, _, strike, row = min(candidates)
    lot_size = int(float(row.get("lot_size", row.get("lotsize", 0))))
    tick_size = float(row.get("tick_size", 0))
    if lot_size <= 0 or tick_size <= 0:
        raise ValueError(f"Invalid lot or tick size for {row.get('trading_symbol')}")
    return OptionContract(underlying, expiry.isoformat(), strike, suffix, str(row["trading_symbol"]), str(row["instrument_key"]), segment, lot_size, tick_size)


def select_candidate_options(underlying, exchange, ltp, direction, records=None, underlying_key=None,
                             occupied_tokens=None, count=5):
    records = records if records is not None else load_records()
    segment = OPTION_EXCHANGES.get(exchange, exchange)
    suffix = "CE" if direction == "CALL" else "PE"
    target = round(ltp / config.STRIKE_INTERVALS[underlying]) * config.STRIKE_INTERVALS[underlying]
    today = datetime.now(IST).date()
    rows = [row for row in records if str(row.get("segment", "")).upper() == segment
            and str(row.get("instrument_key")) not in {str(value) for value in (occupied_tokens or set())}
            and str(row.get("option_type", row.get("instrument_type", ""))).upper() == suffix
            and (underlying_key is None or str(row.get("underlying_key")) == underlying_key)
            and row.get("expiry") and _expiry_date(row["expiry"]) >= today]
    if not rows:
        return []
    expiry = min(_expiry_date(row["expiry"]) for row in rows)
    rows = [row for row in rows if _expiry_date(row["expiry"]) == expiry]
    step = config.STRIKE_INTERVALS[underlying]
    rows = sorted(rows, key=lambda row: abs(float(row.get("strike_price", row.get("strike", 0))) - target))
    contracts = []
    seen = set()
    for row in rows:
        strike = float(row.get("strike_price", row.get("strike", 0)))
        if abs(strike - target) > 2 * step or strike in seen:
            continue
        seen.add(strike)
        lot_size = int(float(row.get("lot_size", row.get("lotsize", 0))))
        tick_size = float(row.get("tick_size", 0))
        if lot_size <= 0 or tick_size <= 0:
            continue
        contracts.append(OptionContract(underlying, expiry.isoformat(), strike, suffix,
                                        str(row["trading_symbol"]), str(row["instrument_key"]),
                                        segment, lot_size, tick_size))
        if len(contracts) >= count:
            break
    return contracts


def validate_live_option_contract(contract, records=None):
    records = records if records is not None else load_records(force_refresh=True)
    for row in records:
        if (str(row.get("instrument_key")) == contract.instrument_key and str(row.get("trading_symbol")) == contract.tradingsymbol
                and str(row.get("expiry")) == contract.expiry and float(row.get("strike_price", row.get("strike", 0))) == contract.strike):
            if int(float(row.get("lot_size", row.get("lotsize", 0)))) != contract.lotsize or float(row.get("tick_size", 0)) != contract.tick_size:
                raise ValueError("Live option contract rules differ from frozen contract")
            return True
    raise ValueError("Frozen option contract is no longer present in Upstox instrument master")
