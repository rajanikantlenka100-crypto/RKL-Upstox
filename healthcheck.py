"""Container health check for the local dashboard health endpoint."""

import json
import urllib.request

import config


request = urllib.request.Request(f"http://{config.DASHBOARD_HEALTH_HOST}:{config.DASHBOARD_PORT}/ready")
try:
    with urllib.request.urlopen(request, timeout=4) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "ok":
        raise SystemExit(1)
except Exception:
    raise SystemExit(1)
