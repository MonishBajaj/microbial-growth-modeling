"""In-memory buffer for temperatures an Arduino POSTs to the server.

The board does not wait for the dashboard. It sends JSON to
POST /api/arduino/ingest (see app.arduino_ingest). record_reading() appends
each sample. When the user starts a push run, collect_temperature_data()
reads this buffer for the requested duration and returns the shared series
shape. The buffer lives in this process only; a restart drops it.

Auth for the POST is ARDUINO_PUSH_TOKEN (default microbial-lab-token), sent as
Authorization: Bearer or as a token field. PUBLIC_BASE_URL or
public_base_url.txt is the origin shown to the board. The returned series
uses the same field names as the MEATER and Signals collectors.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional

import numpy as np

from run_control import sleep_unless_stopped, stop_requested

LogFn = Optional[Callable[[str], None]]

# Shared secret for board POSTs. Override with ARDUINO_PUSH_TOKEN.
DEFAULT_PUSH_TOKEN = os.environ.get('ARDUINO_PUSH_TOKEN', 'microbial-lab-token')

# Optional public base URL shown in the dashboard / written for sketches.
# Prefer env PUBLIC_BASE_URL, else public_base_url.txt next to this package.
_BUFFER_LOCK = threading.Lock()
_READINGS: Deque[Dict] = deque(maxlen=20000)  # ~ several hours at 1 Hz
_LAST_BY_DEVICE: Dict[str, Dict] = {}
_URL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public_base_url.txt')


def _log(log: LogFn, message: str) -> None:
    if log:
        log(message)
    else:
        print(message)


def ingest_token() -> str:
    return os.environ.get('ARDUINO_PUSH_TOKEN', DEFAULT_PUSH_TOKEN)


def public_base_url() -> str:
    env = (os.environ.get('PUBLIC_BASE_URL') or '').rstrip('/')
    if env:
        return env
    try:
        with open(_URL_FILE, encoding='utf-8') as handle:
            return handle.read().strip().rstrip('/')
    except OSError:
        return ''


def write_public_base_url(url: str) -> None:
    """Persist tunnel/deploy base URL for the dashboard and sketches."""
    text = (url or '').strip().rstrip('/')
    with open(_URL_FILE, 'w', encoding='utf-8') as handle:
        handle.write(text + ('\n' if text else ''))


def ingest_path() -> str:
    return '/api/arduino/ingest'


def ingest_url() -> str:
    base = public_base_url()
    if not base:
        return ''
    return f'{base}{ingest_path()}'


def token_ok(authorization_header: Optional[str], query_token: Optional[str] = None) -> bool:
    expected = ingest_token()
    if query_token and hmac_compare(query_token, expected):
        return True
    if not authorization_header:
        return False
    parts = authorization_header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == 'bearer':
        return hmac_compare(parts[1].strip(), expected)
    return hmac_compare(authorization_header.strip(), expected)


def hmac_compare(left: str, right: str) -> bool:
    import hmac as _hmac
    return _hmac.compare_digest(left, right)


def record_reading(celsius: float, device_id: str = 'arduino') -> Dict:
    """Store one sample. Returns the stored record."""
    device_id = (device_id or 'arduino').strip() or 'arduino'
    record = {
        't': time.time(),
        'celsius': float(celsius),
        'device_id': device_id,
    }
    with _BUFFER_LOCK:
        _READINGS.append(record)
        _LAST_BY_DEVICE[device_id] = record
    return record


def status_snapshot() -> Dict:
    """Dashboard/status payload for push devices."""
    with _BUFFER_LOCK:
        latest = list(_LAST_BY_DEVICE.values())
        count = len(_READINGS)
        newest = _READINGS[-1] if _READINGS else None
    devices = []
    now = time.time()
    for item in sorted(latest, key=lambda r: r['t'], reverse=True):
        devices.append({
            'device_id': item['device_id'],
            'celsius': item['celsius'],
            'age_seconds': round(now - item['t'], 1),
            'timestamp': item['t'],
        })
    return {
        'readings_buffered': count,
        'devices': devices,
        'newest': newest,
        'ingest_path': ingest_path(),
        'ingest_url': ingest_url(),
        'public_base_url': public_base_url(),
        'token_hint': ingest_token()[:4] + '…' if ingest_token() else '',
    }


def collect_temperature_data(
    duration_hours: float,
    interval_seconds: float = 2,
    device_id: Optional[str] = None,
    log: LogFn = None,
    model=None,
    should_stop=None,
):
    """
    Collect from the push buffer for ``duration_hours``.

    ``model`` is an optional CorrectedMicrobialGrowthModel; when given, each
    reading line also shows the running population estimate.
    ``should_stop`` ends the run early; duration_hours may be
    run_control.CONTINUOUS to run until stopped.

    Waits for new samples when possible; also accepts recent buffered points
    that arrived just before the run started.
    """
    interval_seconds = max(float(interval_seconds), 1.0)
    duration_hours = max(float(duration_hours), interval_seconds / 3600.0)

    live = model.live_estimator() if model else None

    def pop(t_hours, celsius):
        return live.note(t_hours, celsius) if live else ''

    wanted = (device_id or '').strip() or None

    _log(log, '📡 Waiting for Arduino push readings…')
    if public_base_url():
        _log(log, f'   Ingest URL: {ingest_url()}')
    else:
        _log(log, f'   Ingest path: {ingest_path()} (set PUBLIC_BASE_URL for a full URL)')

    time_data: List[float] = []
    temps: List[float] = []
    used_device = wanted or 'arduino'

    start = time.time()
    end = start + duration_hours * 3600.0
    last_seen_t = start - 1.0

    # Include a reading that arrived in the last 15s so Quick Test can succeed
    # even if the board posted just before the run started.
    with _BUFFER_LOCK:
        for record in reversed(_READINGS):
            if wanted and record['device_id'] != wanted:
                continue
            if start - record['t'] <= 15.0:
                last_seen_t = record['t']
                used_device = record['device_id']
                time_data.append(0.0)
                temps.append(record['celsius'])
                _log(
                    log,
                    f"🌡️ Seed reading: {record['celsius']:.1f}°C from {used_device}"
                    + pop(0.0, record['celsius']),
                )
            break

    while time.time() < end and not stop_requested(should_stop):
        picked = None
        with _BUFFER_LOCK:
            for record in reversed(_READINGS):
                if record['t'] <= last_seen_t:
                    break
                if wanted and record['device_id'] != wanted:
                    continue
                picked = record
                break
            if picked is None and _READINGS:
                # No brand-new sample yet — reuse newest matching device.
                for record in reversed(_READINGS):
                    if wanted and record['device_id'] != wanted:
                        continue
                    if time.time() - record['t'] <= max(30.0, interval_seconds * 3):
                        picked = record
                    break

        if picked is not None and picked['t'] > last_seen_t:
            last_seen_t = picked['t']
            used_device = picked['device_id']
            elapsed = (time.time() - start) / 3600.0
            time_data.append(elapsed)
            temps.append(picked['celsius'])
            _log(
                log,
                f"🌡️ Reading #{len(temps)}: {picked['celsius']:.1f}°C "
                f"({used_device})" + pop(elapsed, picked['celsius']),
            )
        elif picked is not None and time_data:
            # Hold last value on the sampling grid so short runs still fill.
            elapsed = (time.time() - start) / 3600.0
            if not time_data or elapsed - time_data[-1] >= interval_seconds * 0.9 / 3600.0:
                time_data.append(elapsed)
                temps.append(picked['celsius'])
                last_seen_t = max(last_seen_t, picked['t'])
                _log(
                    log,
                    f"🌡️ Reading #{len(temps)}: {picked['celsius']:.1f}°C "
                    f"(held, {used_device})" + pop(elapsed, picked['celsius']),
                )

        if sleep_unless_stopped(interval_seconds, should_stop):
            break

    if not time_data:
        _log(log, '❌ No push readings arrived. Is the board POSTing to /api/arduino/ingest?')
        return None

    temperatures = np.array(temps, dtype=float)
    return {
        'time_hours': np.array(time_data, dtype=float),
        'ambient_temperature': temperatures,
        'internal_temperature': temperatures.copy(),
        'device_id': used_device,
        'readings_count': len(time_data),
    }
