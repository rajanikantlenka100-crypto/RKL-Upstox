"""Non-blocking approval presentation for a genuine live signal."""

import config


def approval_summary(signal, option, quantity):
    return {
        "signal_type": signal.signal_type,
        "direction": signal.direction,
        "underlying": signal.underlying,
        "ltp": f"{signal.ltp:.2f}",
        "breakout": f"{signal.breakout_price:.2f}",
        "expiry": option["expiry"],
        "strike": option["strike"],
        "option": option["symbol"],
        "quantity": quantity,
        "status": "AUTO ENTRY PENDING" if config.AUTO_ENTRY_ENABLED else "APPROVAL REQUIRED",
    }
