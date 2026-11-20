#!/usr/bin/env bash
# Start the lab-PC ThermoWorks sidecar + Cloudflare quick tunnel.
# Point Render at the printed URL with THERMOWORKS_SIDECAR_URL / SECRET.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.local/bin:${PATH}"
export THERMOWORKS_FORCE_LOCAL=1
export THERMOWORKS_SIDECAR_SECRET="${THERMOWORKS_SIDECAR_SECRET:-thermoworks-sidecar-secret}"
export THERMOWORKS_SIDECAR_PORT="${THERMOWORKS_SIDECAR_PORT:-5055}"

PYTHON="${ROOT}/.venv/bin/python"
[[ -x "${PYTHON}" ]] || PYTHON="${ROOT}/venv/bin/python"

pkill -f "thermoworks_sidecar_app.py" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://127.0.0.1:${THERMOWORKS_SIDECAR_PORT}" 2>/dev/null || true
sleep 1

: > /tmp/thermoworks_sidecar.log
: > /tmp/thermoworks_sidecar_tunnel.log

"${PYTHON}" thermoworks_sidecar_app.py > /tmp/thermoworks_sidecar.log 2>&1 &
SIDECAR_PID=$!

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${THERMOWORKS_SIDECAR_PORT}/health" >/dev/null; then
    break
  fi
  sleep 0.5
done

if ! curl -sf "http://127.0.0.1:${THERMOWORKS_SIDECAR_PORT}/health" >/dev/null; then
  echo "Sidecar failed to start. See /tmp/thermoworks_sidecar.log" >&2
  tail -n 40 /tmp/thermoworks_sidecar.log >&2 || true
  exit 1
fi

cloudflared tunnel --url "http://127.0.0.1:${THERMOWORKS_SIDECAR_PORT}" \
  > /tmp/thermoworks_sidecar_tunnel.log 2>&1 &
CF_PID=$!

URL=""
for _ in $(seq 1 60); do
  URL="$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' /tmp/thermoworks_sidecar_tunnel.log | head -1 || true)"
  if [[ -n "${URL}" ]]; then
    break
  fi
  sleep 0.5
done

if [[ -z "${URL}" ]]; then
  echo "Failed to obtain Cloudflare URL. See /tmp/thermoworks_sidecar_tunnel.log" >&2
  tail -n 40 /tmp/thermoworks_sidecar_tunnel.log >&2 || true
  exit 1
fi

printf '%s\n' "${URL}" > "${ROOT}/thermoworks_sidecar_url.txt"

cat <<EOF
ThermoWorks sidecar is running.

  Sidecar PID:     ${SIDECAR_PID}
  cloudflared PID: ${CF_PID}
  Public URL:      ${URL}
  Secret:          ${THERMOWORKS_SIDECAR_SECRET}

On Render (Environment), set:
  THERMOWORKS_SIDECAR_URL=${URL}
  THERMOWORKS_SIDECAR_SECRET=${THERMOWORKS_SIDECAR_SECRET}

Keep this lab PC awake. Re-run this script if the quick tunnel URL changes,
then update THERMOWORKS_SIDECAR_URL on Render.
EOF
