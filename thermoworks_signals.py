"""
ThermoWorks Signals collector.

Reads devices through the thermoworks-cloud library (ThermoWorks Cloud /
Firestore). Sign-in needs a Firebase App Check token from thermoworks_appcheck.py.
If THERMOWORKS_SIDECAR_URL is set, list and collect calls are POSTed to the lab
PC sidecar instead, because a cloud host cannot open Chrome to mint that token.

The selected channel is stored as ambient_temperature, which is the series the
growth model integrates. A companion channel, when it has a live reading, is
stored as internal_temperature for the plot only.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, Optional

import numpy as np
import requests
from aiohttp import ClientSession, TraceConfig

from run_control import (
    async_sleep_unless_stopped,
    is_continuous,
    sleep_unless_stopped,
    stop_requested,
)
from thermoworks_appcheck import get_app_check_token
from thermoworks_cloud import AuthFactory, ResourceNotFoundError, ThermoworksCloud
from thermoworks_cloud.auth import AuthenticationError

LogFn = Optional[Callable[[str], None]]


def _sidecar_url() -> str:
    if os.environ.get('THERMOWORKS_FORCE_LOCAL', '').lower() in ('1', 'true', 'yes'):
        return ''
    return (os.environ.get('THERMOWORKS_SIDECAR_URL') or '').strip().rstrip('/')


def uses_sidecar() -> bool:
    """True when collection goes through the lab sidecar, which mints its own App Check."""
    return bool(_sidecar_url())


def _sidecar_secret() -> str:
    return os.environ.get('THERMOWORKS_SIDECAR_SECRET', 'thermoworks-sidecar-secret')


def _sidecar_headers() -> dict:
    return {
        'Authorization': f'Bearer {_sidecar_secret()}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def _list_devices_via_sidecar(email: str, password: str, log: LogFn = None) -> list:
    base = _sidecar_url()
    _log(log, f'🔐 Asking lab ThermoWorks sidecar at {base}…')
    response = requests.post(
        f'{base}/v1/devices',
        headers=_sidecar_headers(),
        json={'email': email, 'password': password},
        timeout=180,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f'Sidecar returned non-JSON ({response.status_code}). Is it running?'
        ) from exc
    if response.status_code >= 400:
        raise RuntimeError(payload.get('error') or f'Sidecar error HTTP {response.status_code}')
    devices = payload.get('devices') or []
    _log(log, f'✅ Sidecar found {len(devices)} ThermoWorks device(s).')
    return devices


def _collect_via_sidecar(
    email: str,
    password: str,
    duration_hours: float,
    interval_seconds: float,
    serial: Optional[str],
    channel: int,
    log: LogFn = None,
    model_id: Optional[str] = None,
):
    base = _sidecar_url()
    _log(log, f'📡 Collecting via lab ThermoWorks sidecar at {base}…')
    # Long runs need a long timeout (full analysis ~8h).
    timeout = max(duration_hours * 3600.0 + 120.0, 300.0)
    response = requests.post(
        f'{base}/v1/collect',
        headers=_sidecar_headers(),
        json={
            'email': email,
            'password': password,
            'duration_hours': duration_hours,
            'interval_seconds': interval_seconds,
            'serial': serial,
            'channel': channel,
            # Sidecar rebuilds the same catalog model for the live population estimate.
            'model_id': model_id,
        },
        timeout=timeout,
    )
    try:
        payload = response.json()
    except ValueError:
        _log(log, f'❌ Sidecar returned non-JSON ({response.status_code}).')
        return None
    for line in payload.get('logs') or []:
        _log(log, line)
    if response.status_code >= 400 or not payload.get('data'):
        _log(log, f"❌ Sidecar collect failed: {payload.get('error') or response.status_code}")
        return None
    data = payload['data']
    return {
        'time_hours': np.array(data.get('time_hours') or [], dtype=float),
        'ambient_temperature': np.array(data.get('ambient_temperature') or [], dtype=float),
        'internal_temperature': np.array(data.get('internal_temperature') or [], dtype=float),
        'device_id': data.get('device_id'),
        'readings_count': data.get('readings_count') or 0,
        'serial': data.get('serial'),
        'channel': data.get('channel'),
    }


SIDECAR_CHUNK_HOURS = 5 / 60.0


def _collect_via_sidecar_chunked(
    email: str,
    password: str,
    duration_hours: float,
    interval_seconds: float,
    serial: Optional[str],
    channel: int,
    log: LogFn = None,
    model=None,
    should_stop=None,
):
    """Repeat short sidecar collections until stopped or ``duration_hours`` is reached.

    One sidecar call is a single blocking HTTP request that cannot be stopped
    midway, so a stoppable run asks for SIDECAR_CHUNK_HOURS at a time. Each
    chunk's times are shifted onto one clock. Reading lines (with the running
    population estimate) are written here, so numbering and the estimate carry
    across chunks; the sidecar's own reading lines are dropped.
    """
    live = model.live_estimator() if model else None
    run_start = time.time()
    end = run_start + duration_hours * 3600.0
    time_data, ambient, internal = [], [], []
    device_id = serial_used = channel_used = None
    chunk = 0

    while time.time() < end and not stop_requested(should_stop):
        chunk += 1
        chunk_hours = min(SIDECAR_CHUNK_HOURS, max((end - time.time()) / 3600.0, interval_seconds / 3600.0))
        offset_h = (time.time() - run_start) / 3600.0
        lines = []
        data = _collect_via_sidecar(
            email, password, chunk_hours, interval_seconds, serial, channel, log=lines.append,
        )
        for line in lines:
            if not line.startswith('🌡️ Reading'):
                _log(log, line)
        if data is None or len(data['time_hours']) == 0:
            _log(log, f'⚠️ Sidecar chunk {chunk} returned no readings.')
            if not time_data:
                return None
            # Sidecar may be restarting; wait before asking again.
            sleep_unless_stopped(max(30.0, interval_seconds), should_stop)
            continue
        device_id = data.get('device_id') or device_id
        serial_used = data.get('serial') or serial_used
        channel_used = data.get('channel') or channel_used
        for t_h, amb, inn in zip(data['time_hours'], data['ambient_temperature'], data['internal_temperature']):
            t_abs = offset_h + float(t_h)
            if time_data and t_abs <= time_data[-1]:
                continue
            time_data.append(t_abs)
            ambient.append(float(amb))
            internal.append(float(inn))
            _log(
                log,
                f'🌡️ Reading #{len(time_data)}: Ch{channel_used or channel} {float(amb):.1f}°C (live probe)'
                + (live.note(t_abs, float(amb)) if live else ''),
            )

    if not time_data:
        return None
    return {
        'time_hours': np.array(time_data, dtype=float),
        'ambient_temperature': np.array(ambient, dtype=float),
        'internal_temperature': np.array(internal, dtype=float),
        'device_id': device_id,
        'readings_count': len(time_data),
        'serial': serial_used,
        'channel': channel_used,
    }


def _log(log: LogFn, message: str) -> None:
    if log:
        log(message)
    else:
        print(message)


def _probe_max_age_sec() -> float:
    """Reject channel readings older than this (stale / unplugged leftovers)."""
    try:
        return max(float(os.environ.get('THERMOWORKS_PROBE_MAX_AGE_SEC') or '90'), 15.0)
    except ValueError:
        return 90.0


_BAD_STATUS_TOKENS = (
    'no probe',
    'noprobe',
    'no_probe',
    'disconnected',
    'unplugged',
    'offline',
    'not connected',
    'unavailable',
    'error',
    'fail',
)


def _status_looks_connected(status: Optional[str]) -> bool:
    text = (status or '').strip().lower().replace('_', ' ').replace('-', ' ')
    if not text:
        # Missing status: still allow if telemetry is fresh (checked separately).
        return True
    return not any(token in text for token in _BAD_STATUS_TOKENS)


def _channel_last_seen_age_sec(channel) -> Optional[float]:
    """Seconds since ThermoWorks last saw this channel, or None if unknown."""
    for attr in ('last_seen', 'last_telemetry_saved'):
        stamp = getattr(channel, attr, None)
        if stamp is None:
            continue
        try:
            # datetime from API is usually timezone-aware UTC.
            ts = stamp.timestamp() if hasattr(stamp, 'timestamp') else float(stamp)
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        return max(0.0, time.time() - ts)
    return None


def _to_celsius(value: Optional[float], units: Optional[str]) -> Optional[float]:
    """Convert a channel reading to °C. Humidity ('H') is rejected."""
    if value is None:
        return None
    u = (units or 'C').strip().upper()
    if u in ('H', 'RH', '%'):
        return None
    if u in ('F', '°F', 'FAHRENHEIT'):
        return (float(value) - 32.0) * 5.0 / 9.0
    return float(value)


def _channel_probe_reading(channel) -> tuple[Optional[float], str]:
    """Return (°C, reason). reason is '' when the reading is accepted as a live probe."""
    if channel is None:
        return None, 'missing channel'
    if not _status_looks_connected(getattr(channel, 'status', None)):
        return None, f"status={getattr(channel, 'status', None)!r} (not a live probe)"
    age = _channel_last_seen_age_sec(channel)
    max_age = _probe_max_age_sec()
    if age is not None and age > max_age:
        return None, f'stale telemetry ({age:.0f}s old; max {max_age:.0f}s)'
    temp_c = _to_celsius(getattr(channel, 'value', None), getattr(channel, 'units', None))
    if temp_c is None:
        return None, 'no temperature value'
    # Sanity band for food-lab probes (°C). Reject absurd leftovers.
    if temp_c < -40.0 or temp_c > 300.0:
        return None, f'out-of-range reading ({temp_c:.1f}°C)'
    return temp_c, ''


def _channel_temp_c(channel) -> Optional[float]:
    temp_c, _reason = _channel_probe_reading(channel)
    return temp_c


def _auth_message(exc: AuthenticationError) -> str:
    reason = getattr(getattr(exc, "reason", None), "value", "") or str(exc)
    if reason == "INVALID_PASSWORD":
        return "ThermoWorks rejected that password."
    if reason == "EMAIL_NOT_FOUND":
        return "No ThermoWorks Cloud account uses that email."
    if reason == "USER_DISABLED":
        return "That ThermoWorks Cloud account is disabled."
    return f"ThermoWorks sign-in failed ({reason})."


async def _with_client(email: str, password: str, work):
    trace = TraceConfig()

    async def _attach_app_check(session, context, params):
        params.headers["X-Firebase-AppCheck"] = await get_app_check_token()

    trace.on_request_start.append(_attach_app_check)
    async with ClientSession(trace_configs=[trace]) as session:
        try:
            auth = await AuthFactory(session).build_auth(email, password)
        except AuthenticationError as exc:
            raise RuntimeError(_auth_message(exc)) from exc
        client = ThermoworksCloud(auth)
        return await work(client)


def _run(coro):
    """Run an async coroutine from sync Flask worker threads."""
    return asyncio.run(coro)


async def _list_devices_async(client: ThermoworksCloud):
    user = await client.get_user()
    if not user.account_id:
        raise RuntimeError('ThermoWorks account has no account_id.')
    devices = await client.get_devices(user.account_id)
    result = []
    for device in devices:
        if not device.serial:
            continue
        channels = []
        for n in range(1, 10):
            try:
                ch = await client.get_device_channel(device.serial, str(n))
            except ResourceNotFoundError:
                break
            except Exception:
                continue
            temp_c, reason = _channel_probe_reading(ch)
            age = _channel_last_seen_age_sec(ch)
            channels.append({
                'number': ch.number or str(n),
                'label': ch.label or f'Channel {n}',
                'value': ch.value,
                'units': ch.units,
                'value_c': temp_c,
                'status': ch.status,
                'live': temp_c is not None,
                'reject_reason': reason or None,
                'age_sec': None if age is None else int(age),
            })
        result.append({
            'serial': device.serial,
            'label': device.label or device.device_name or device.serial,
            'type': device.type or 'unknown',
            'status': device.status,
            'battery': device.battery,
            'channels': channels,
        })
    return result


def list_devices(email: str, password: str, log: LogFn = None) -> list:
    """Authenticate and return ThermoWorks Cloud devices with channel snapshots."""
    if _sidecar_url():
        try:
            return _list_devices_via_sidecar(email, password, log=log)
        except Exception as exc:
            _log(log, f'❌ ThermoWorks sidecar device list failed: {exc}')
            raise

    _log(log, '🔐 Authenticating with ThermoWorks Cloud...')

    async def work(client):
        return await _list_devices_async(client)

    try:
        devices = _run(_with_client(email, password, work))
    except Exception as exc:
        _log(log, f'❌ ThermoWorks authentication or device list failed: {exc}')
        raise

    _log(log, f'✅ Found {len(devices)} ThermoWorks device(s).')
    return devices


async def _read_pair(client: ThermoworksCloud, serial: str, channel: int, companion: int):
    """Return (growth_c, companion_c, growth_reason). Only live probe values count."""
    primary = await client.get_device_channel(serial, str(channel))
    growth_c, growth_reason = _channel_probe_reading(primary)
    companion_c = None
    if companion != channel:
        try:
            secondary = await client.get_device_channel(serial, str(companion))
            secondary_c, _ = _channel_probe_reading(secondary)
            if secondary_c is not None:
                companion_c = secondary_c
        except ResourceNotFoundError:
            pass
    return growth_c, companion_c, growth_reason


async def _collect_async(
    client: ThermoworksCloud,
    serial: str,
    channel: int,
    duration_hours: float,
    interval_seconds: float,
    log: LogFn,
    model=None,
    should_stop=None,
):
    time_data = []
    ambient_data = []
    internal_data = []

    start = time.time()
    end = start + duration_hours * 3600.0
    reading = 0
    live = model.live_estimator() if model else None

    # Companion channel for MEATER-shaped internal_temperature display only.
    companion = 2 if channel == 1 else 1

    span = 'until stopped' if is_continuous(duration_hours) else f'for {duration_hours:.3f} h'
    _log(
        log,
        f'📡 Collecting Signals channel {channel} on {serial} '
        f'{span} every {interval_seconds:.0f}s…',
    )

    # Consecutive failed reads. A long outage (e.g. an expired App Check token)
    # logs the first failure, any new error text, and every 10th repeat, not
    # one identical line per interval.
    fail_streak = 0
    last_error = ''

    while time.time() < end and not stop_requested(should_stop):
        try:
            growth_c, companion_c, growth_reason = await _read_pair(
                client, serial, channel, companion,
            )
        except Exception as exc:
            fail_streak += 1
            message = str(exc)
            if fail_streak == 1 or message != last_error or fail_streak % 10 == 0:
                _log(
                    log,
                    f'⚠️ Read failed: {message}'
                    + (f' ({fail_streak} failures in a row)' if fail_streak > 1 else ''),
                )
            last_error = message
            if await async_sleep_unless_stopped(interval_seconds, should_stop):
                break
            continue

        if fail_streak:
            _log(log, f'✅ ThermoWorks reads working again after {fail_streak} failed attempt(s).')
            fail_streak = 0
            last_error = ''

        if growth_c is None:
            _log(
                log,
                '⚠️ Skipping Ch'
                + str(channel)
                + ' — not a live probe reading'
                + (f' ({growth_reason})' if growth_reason else '')
                + '.',
            )
            if await async_sleep_unless_stopped(interval_seconds, should_stop):
                break
            continue

        elapsed_h = (time.time() - start) / 3600.0
        time_data.append(elapsed_h)
        ambient_data.append(growth_c)
        # Companion is optional display-only; never invent it from a dead channel.
        internal_data.append(companion_c if companion_c is not None else growth_c)
        reading += 1
        _log(
            log,
            f'🌡️ Reading #{reading}: Ch{channel} {growth_c:.1f}°C (live probe)'
            + (
                f', companion {companion_c:.1f}°C'
                if companion_c is not None
                else ', companion unavailable'
            )
            + (live.note(elapsed_h, growth_c) if live else ''),
        )
        if await async_sleep_unless_stopped(interval_seconds, should_stop):
            break

    if not time_data:
        return None

    return {
        'time_hours': np.array(time_data),
        'internal_temperature': np.array(internal_data),
        'ambient_temperature': np.array(ambient_data),
        'device_id': f'{serial}:ch{channel}',
        'readings_count': len(time_data),
        'serial': serial,
        'channel': channel,
    }


def collect_temperature_data(
    email: str,
    password: str,
    duration_hours: float,
    interval_seconds: float = 2,
    serial: Optional[str] = None,
    channel: int = 1,
    log: LogFn = None,
    model=None,
    should_stop=None,
):
    """
    Collect a live temperature series from ThermoWorks Cloud for one Signals channel.

    The selected channel becomes ambient_temperature (used by the growth model).
    ``model`` is an optional CorrectedMicrobialGrowthModel; when given, each
    reading line also shows the running population estimate for the selected channel.
    ``should_stop`` ends the run early; duration_hours may be
    run_control.CONTINUOUS to run until stopped. Through the sidecar, such a
    run is collected in chunks and a stop takes effect at the end of a chunk.
    """
    channel = max(1, int(channel))
    interval_seconds = max(float(interval_seconds), 1.0)

    if _sidecar_url():
        if should_stop is not None or is_continuous(duration_hours):
            return _collect_via_sidecar_chunked(
                email, password, duration_hours, interval_seconds, serial, channel,
                log=log, model=model, should_stop=should_stop,
            )
        return _collect_via_sidecar(
            email, password, duration_hours, interval_seconds, serial, channel, log=log,
            model_id=getattr(model, 'model_id', None),
        )

    async def work(client):
        devices = await _list_devices_async(client)
        if not devices:
            _log(log, '⚠️ No ThermoWorks devices found on this account.')
            return None

        chosen = None
        if serial:
            for d in devices:
                if d['serial'] == serial:
                    chosen = d
                    break
            if chosen is None:
                _log(log, f'⚠️ Device {serial} not found; using first available.')
        if chosen is None:
            # Prefer a Signals-type device when unlabeled serials are present.
            signals = [d for d in devices if (d.get('type') or '').lower() in
                       ('signals', 'signal', 'smoke', 'rfx', 'node')]
            chosen = signals[0] if signals else devices[0]

        use_serial = chosen['serial']
        available = {int(c['number']) for c in chosen.get('channels', []) if c.get('number')}
        if available and channel not in available:
            _log(log, f'⚠️ Channel {channel} missing; falling back to channel {min(available)}.')
            use_channel = min(available)
        else:
            use_channel = channel

        _log(log, f"📱 Using {chosen.get('label')} ({use_serial}), channel {use_channel}.")
        return await _collect_async(
            client, use_serial, use_channel, duration_hours, interval_seconds, log,
            model=model, should_stop=should_stop,
        )

    try:
        return _run(_with_client(email, password, work))
    except Exception as exc:
        _log(log, f'❌ Signals collection failed: {exc}')
        return None


def device_snapshot_for_api(devices: list) -> list:
    """Strip None-heavy fields for JSON responses."""
    clean = []
    for d in devices:
        clean.append({
            'serial': d.get('serial'),
            'label': d.get('label'),
            'type': d.get('type'),
            'status': d.get('status'),
            'battery': d.get('battery'),
            'channels': [
                {
                    'number': c.get('number'),
                    'label': c.get('label'),
                    'value_c': c.get('value_c'),
                    'units': c.get('units'),
                    'status': c.get('status'),
                    'live': bool(c.get('live')),
                    'reject_reason': c.get('reject_reason'),
                    'age_sec': c.get('age_sec'),
                }
                for c in d.get('channels', [])
            ],
        })
    return clean
