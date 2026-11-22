"""Lab-PC ThermoWorks sidecar.

Run this on a desktop machine that can open Chrome for Firebase App Check.
Your Render (or any cloud) dashboard calls these endpoints with a shared secret
so Signals works without Chrome on the cloud host.

  THERMOWORKS_SIDECAR_SECRET=...  .venv/bin/python thermoworks_sidecar_app.py
"""

from __future__ import annotations

import os

# Never proxy back to ourselves if SIDECAR_URL is also set on this machine.
os.environ['THERMOWORKS_FORCE_LOCAL'] = '1'

from flask import Flask, jsonify, request

from thermoworks_signals import (
    collect_temperature_data,
    device_snapshot_for_api,
    list_devices,
)

app = Flask(__name__)

DEFAULT_SECRET = 'thermoworks-sidecar-secret'
SIDECAR_PORT = int(os.environ.get('THERMOWORKS_SIDECAR_PORT', '5055'))


def _secret() -> str:
    return os.environ.get('THERMOWORKS_SIDECAR_SECRET', DEFAULT_SECRET)


def _authorized() -> bool:
    expected = _secret()
    header = request.headers.get('Authorization') or ''
    if header.lower().startswith('bearer '):
        return header.split(None, 1)[1].strip() == expected
    body = request.get_json(silent=True) or {}
    return (body.get('secret') or request.args.get('secret') or '') == expected


@app.get('/health')
def health():
    return jsonify({
        'ok': True,
        'service': 'thermoworks-sidecar',
        'display': bool(os.environ.get('DISPLAY')),
    })


@app.post('/v1/devices')
def devices():
    if not _authorized():
        return jsonify({'error': 'Unauthorized sidecar call.', 'devices': []}), 401
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip()
    password = (payload.get('password') or '').strip()
    if not email or not password:
        return jsonify({'error': 'email and password are required.', 'devices': []}), 400
    try:
        devices = list_devices(email, password)
        return jsonify({'devices': device_snapshot_for_api(devices), 'error': None})
    except Exception as exc:
        return jsonify({'error': str(exc), 'devices': []}), 502


def _live_rate_model(model_id):
    """Catalog model for the live population estimate, or None if it cannot be built."""
    model_id = (model_id or '').strip() if isinstance(model_id, str) else ''
    if not model_id:
        return None
    try:
        from corrected_microbial_growth_model import CorrectedMicrobialGrowthModel
        return CorrectedMicrobialGrowthModel.from_catalog(model_id)
    except Exception:
        return None


@app.post('/v1/collect')
def collect():
    if not _authorized():
        return jsonify({'error': 'Unauthorized sidecar call.'}), 401
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip()
    password = (payload.get('password') or '').strip()
    if not email or not password:
        return jsonify({'error': 'email and password are required.'}), 400
    try:
        duration_hours = float(payload.get('duration_hours', 0.1))
        interval_seconds = float(payload.get('interval_seconds', 2))
        channel = int(payload.get('channel', 1) or 1)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid duration, interval, or channel.'}), 400
    serial = (payload.get('serial') or '').strip() or None
    model = _live_rate_model(payload.get('model_id'))
    logs = []
    temp_data = collect_temperature_data(
        email,
        password,
        duration_hours=duration_hours,
        interval_seconds=interval_seconds,
        serial=serial,
        channel=channel,
        log=logs.append,
        model=model,
    )
    if temp_data is None:
        return jsonify({'error': 'No temperature readings collected.', 'logs': logs}), 502
    return jsonify({
        'error': None,
        'logs': logs,
        'data': {
            'time_hours': temp_data['time_hours'].tolist(),
            'ambient_temperature': temp_data['ambient_temperature'].tolist(),
            'internal_temperature': temp_data['internal_temperature'].tolist(),
            'device_id': temp_data.get('device_id'),
            'readings_count': temp_data.get('readings_count'),
            'serial': temp_data.get('serial'),
            'channel': temp_data.get('channel'),
        },
    })


if __name__ == '__main__':
    print(f'ThermoWorks sidecar on 0.0.0.0:{SIDECAR_PORT}')
    print(f'Secret: {_secret()}')
    print('Expose this host to Render via Cloudflare tunnel, then set:')
    print('  THERMOWORKS_SIDECAR_URL=https://<tunnel-host>')
    print('  THERMOWORKS_SIDECAR_SECRET=<same secret>')
    app.run(host='0.0.0.0', port=SIDECAR_PORT, debug=False, threaded=True)
