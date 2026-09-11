"""Non-secret public network diagnostics for read and order safety checks."""

import json
import ipaddress
import urllib.request

import config


class PublicIpError(RuntimeError):
    pass


def public_ipv4(timeout=5):
    try:
        request = urllib.request.Request(
            "https://api.ipify.org?format=json",
            headers={"User-Agent": "RKL-Algo/2.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        value = str(payload.get("ip", "")).strip()
        parts = value.split(".")
        if len(parts) != 4 or any(not part.isdigit() or int(part) > 255 for part in parts):
            raise PublicIpError("Public IPv4 response was invalid")
        return value
    except Exception as error:
        if isinstance(error, PublicIpError):
            raise
        raise PublicIpError(f"Public IPv4 unavailable: {error}") from error


def order_ip_allowed(current_ip, require_config=False):
    expected = config.ORDER_IP_WHITELIST
    if not expected:
        if require_config:
            return False, "ORDER IP POLICY NOT CONFIGURED"
        return True, "ORDER IP CHECK NOT CONFIGURED"
    try:
        expected = str(ipaddress.ip_address(expected))
        current_ip = str(ipaddress.ip_address(current_ip))
    except (TypeError, ValueError):
        return False, "ORDER IP POLICY INVALID"
    if current_ip == expected:
        return True, "ORDER IP MATCH"
    return False, "ORDER IP NOT WHITELISTED"
