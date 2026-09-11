#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/opt/rkl-upstox}"
CURRENT="$ROOT/current"
PREVIOUS="$(readlink -f "$CURRENT.prev" 2>/dev/null || true)"
if [[ -z "$PREVIOUS" || ! -d "$PREVIOUS" ]]; then
  echo "No previous release link found at $CURRENT.prev" >&2
  exit 1
fi
ln -sfn "$PREVIOUS" "$CURRENT"
sudo systemctl restart rkl-upstox
for attempt in $(seq 1 12); do
  if curl --fail --silent http://127.0.0.1:8765/ready >/dev/null; then
    echo "Rollback ready: $PREVIOUS"
    exit 0
  fi
  sleep 5
done
echo "Rollback failed readiness" >&2
exit 1
