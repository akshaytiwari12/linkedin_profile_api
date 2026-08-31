#!/usr/bin/env bash
# Start the API and expose it on a stable public URL.
#
# Both processes are supervised: if either exits, the script restarts it. That covers the common
# case of the API crashing or being restarted to pick up new configuration, without the tunnel
# going away with it.
#
# Usage:
#   NGROK_DOMAIN=your-name.ngrok-free.app ./scripts/serve.sh
#
# Requires `ngrok config add-authtoken <token>` to have been run once.

set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
NGROK_DOMAIN="${NGROK_DOMAIN:-}"
NGROK_BIN="${NGROK_BIN:-./ngrok}"

if [[ -z "$NGROK_DOMAIN" ]]; then
  echo "NGROK_DOMAIN is not set."
  echo "Claim your free static domain at https://dashboard.ngrok.com/domains, then:"
  echo "  NGROK_DOMAIN=your-name.ngrok-free.app $0"
  exit 2
fi

if [[ ! -f .env ]]; then
  echo ".env not found — copy .env.longrun.example and fill in the cookies first."
  exit 2
fi

cleanup() {
  echo
  echo "shutting down…"
  kill "${API_PID:-}" "${TUNNEL_PID:-}" 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap cleanup INT TERM

start_api() {
  python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >>logs/api.log 2>&1 &
  API_PID=$!
  echo "  api      pid $API_PID  → http://127.0.0.1:$PORT"
}

start_tunnel() {
  "$NGROK_BIN" http "$PORT" --domain="$NGROK_DOMAIN" --log=stdout >>logs/tunnel.log 2>&1 &
  TUNNEL_PID=$!
  echo "  tunnel   pid $TUNNEL_PID  → https://$NGROK_DOMAIN"
}

mkdir -p logs
echo "starting:"
start_api
start_tunnel

echo
echo "  docs     https://$NGROK_DOMAIN/docs"
echo "  status   https://$NGROK_DOMAIN/status"
echo
echo "logs in ./logs/ — Ctrl-C to stop both."

# Supervise: restart whichever process dies, so a crash or a config restart does not take the
# public URL down with it.
while true; do
  sleep 5
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "$(date -Is) api exited — restarting"
    start_api
  fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "$(date -Is) tunnel exited — restarting"
    start_tunnel
  fi
done
