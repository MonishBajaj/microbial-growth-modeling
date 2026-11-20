#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.local/bin:${PATH}"

PYTHON="${ROOT}/.venv/bin/python"
[[ -x "${PYTHON}" ]] || PYTHON="${ROOT}/venv/bin/python"

pkill -f "${ROOT}/.*/bin/python app.py" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://127.0.0.1:5000" 2>/dev/null || true
sleep 1

: > /tmp/microbial_cloudflared.log
"${PYTHON}" app.py > /tmp/microbial_flask.log 2>&1 &
FLASK_PID=$!

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:5000/login" >/dev/null; then
    break
  fi
  sleep 0.5
done

cloudflared tunnel --url http://127.0.0.1:5000 > /tmp/microbial_cloudflared.log 2>&1 &
CF_PID=$!

URL=""
for _ in $(seq 1 60); do
  URL="$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' /tmp/microbial_cloudflared.log | head -1 || true)"
  if [[ -n "${URL}" ]]; then
    break
  fi
  sleep 0.5
done

if [[ -z "${URL}" ]]; then
  echo "Failed to obtain Cloudflare URL. See /tmp/microbial_cloudflared.log" >&2
  tail -n 40 /tmp/microbial_cloudflared.log >&2 || true
  exit 1
fi

printf '%s\n' "${URL}" > "${ROOT}/public_base_url.txt"
echo "Flask PID: ${FLASK_PID}"
echo "cloudflared PID: ${CF_PID}"
echo "Public base URL: ${URL}"
echo "Ingest URL: ${URL}/api/arduino/ingest"
echo "Token: microbial-lab-token"
