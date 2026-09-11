"""Validated stop-loss prices for a master-derived option contract."""

from instruments.options import round_to_tick


def build_stop_loss(contract, reference, current_ltp, buffer=1.0, limit_offset=0.05):
    if not contract or not getattr(contract, "tick_size", 0):
        raise ValueError("SL requires a valid contract tick size")
    if reference <= 0 or current_ltp <= 0 or buffer < 0 or limit_offset <= 0:
        raise ValueError("Invalid stop-loss policy inputs")
    raw_trigger = reference - buffer
    raw_limit = raw_trigger - limit_offset
    trigger = round_to_tick(raw_trigger, contract.tick_size)
    limit = round_to_tick(raw_limit, contract.tick_size)
    if limit >= trigger:
        limit = trigger - contract.tick_size
        limit = round_to_tick(limit, contract.tick_size)
    if trigger <= 0 or limit <= 0 or limit >= trigger:
        raise ValueError("Invalid stop-loss trigger/limit relationship")
    minimum_distance = 2 * contract.tick_size
    if trigger >= current_ltp - minimum_distance:
        raise ValueError("Stop-loss trigger is too close to current option LTP")
    return trigger, limit
