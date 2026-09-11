#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/opt/rkl-upstox}"
RELEASE="${RELEASE:-$ROOT/releases/$(date +%Y%m%d%H%M%S)}"
CURRENT="$ROOT/current"
VENV="$ROOT/venv"

mkdir -p "$RELEASE" "$ROOT/data" "$ROOT/logs"
if [[ -L "$CURRENT" ]]; then
  ln -sfn "$(readlink -f "$CURRENT")" "$CURRENT.prev"
fi
rsync -a --delete --exclude '.env' --exclude 'data/' --exclude 'logs/' ./ "$RELEASE/"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$RELEASE/requirements.txt"
cd "$RELEASE"
"$VENV/bin/python" -m pytest -q
"$VENV/bin/python" -m compileall -q .
ln -sfn "$RELEASE" "$CURRENT"
sudo systemctl daemon-reload
sudo systemctl restart rkl-upstox
for attempt in $(seq 1 12); do
  if curl --fail --silent http://127.0.0.1:8765/ready >/dev/null; then
    echo "Deployment ready: $RELEASE"
    exit 0
  fi
  sleep 5
done
echo "Deployment failed readiness; inspect journalctl -u rkl-upstox" >&2
exit 1
