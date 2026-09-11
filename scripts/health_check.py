"""Readiness check suitable for deployment monitoring."""

import json
import os
import sys
import urllib.request

host = os.getenv("DASHBOARD_HEALTH_HOST", "127.0.0.1")
port = os.getenv("DASHBOARD_PORT", "8765")
request = urllib.request.Request(f"http://{host}:{port}/ready")
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    print(json.dumps(payload, indent=2))
    raise SystemExit(0 if payload.get("status") == "ok" else 1)
except Exception as error:
    print(f"health check failed: {error}", file=sys.stderr)
    raise SystemExit(1)
