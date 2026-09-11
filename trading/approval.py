"""Non-blocking approval presentation for a genuine live signal."""

import config
import math


def approval_summary(signal, option, option_ltp, option_previous_low, quantity):
    sl = option_previous_low - config.SL_BUFFER
    if not isinstance(option_ltp, (int, float)) or not math.isfinite(option_ltp):
        raise ValueError("OPTION_LTP_INVALID")
    if option_ltp <= 0:
        raise ValueError("OPTION_LTP_ZERO")
    if sl <= 0:
        raise ValueError("OPTION_SL_REFERENCE_INVALID")
    if sl >= option_ltp:
        raise ValueError("OPTION_SL_REFERENCE_ABOVE_LTP")
    capital = option_ltp * quantity
    risk = max(0.0, (option_ltp - sl) * quantity)
    return {
        "signal_type": signal.signal_type,
        "direction": signal.direction,
        "underlying": signal.underlying,
        "ltp": f"{signal.ltp:.2f}",
        "breakout": f"{signal.breakout_price:.2f}",
        "expiry": option["expiry"],
        "strike": option["strike"],
        "option": option["symbol"],
        "option_ltp": f"{option_ltp:.2f}",
        "sl": f"{sl:.2f}",
        "quantity": quantity,
        "capital": f"{capital:.2f}",
        "risk": f"{risk:.2f}",
        "status": "AUTO ENTRY PENDING" if config.AUTO_ENTRY_ENABLED else "APPROVAL REQUIRED",
    }
