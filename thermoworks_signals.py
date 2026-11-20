"""
ThermoWorks Signals (and other Cloud-connected) thermometer collector.

Uses the unofficial thermoworks-cloud library against ThermoWorks Cloud
(Firestore). Returns the same temperature time-series shape as MEATER / Arduino.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

import numpy as np
from aiohttp import ClientSession, TraceConfig

from thermoworks_appcheck import get_app_check_token
from thermoworks_cloud import AuthFactory, ResourceNotFoundError, ThermoworksCloud
from thermoworks_cloud.auth import AuthenticationError

LogFn = Optional[Callable[[str], None]]


def _log(log: LogFn, message: str) -> None:
    if log:
        log(message)
    else:
        print(message)


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


def _channel_temp_c(channel) -> Optional[float]:
    return _to_celsius(getattr(channel, 'value', None), getattr(channel, 'units', None))


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
            channels.append({
                'number': ch.number or str(n),
                'label': ch.label or f'Channel {n}',
                'value': ch.value,
                'units': ch.units,
                'value_c': _channel_temp_c(ch),
                'status': ch.status,
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
    """Return (growth_c, companion_c). Growth is the selected Signals channel."""
    primary = await client.get_device_channel(serial, str(channel))
    growth_c = _channel_temp_c(primary)
    companion_c = growth_c
    if companion != channel:
        try:
            secondary = await client.get_device_channel(serial, str(companion))
            secondary_c = _channel_temp_c(secondary)
            if secondary_c is not None:
                companion_c = secondary_c
        except ResourceNotFoundError:
            pass
    return growth_c, companion_c


async def _collect_async(
    client: ThermoworksCloud,
    serial: str,
    channel: int,
    duration_hours: float,
    interval_seconds: float,
    log: LogFn,
):
    time_data = []
    ambient_data = []
    internal_data = []

    start = time.time()
    end = start + duration_hours * 3600.0
    reading = 0

    # Companion channel for MEATER-shaped internal_temperature display only.
    companion = 2 if channel == 1 else 1

    _log(
        log,
        f'📡 Collecting Signals channel {channel} on {serial} '
        f'for {duration_hours:.3f} h every {interval_seconds:.0f}s…',
    )

    while time.time() < end:
        try:
            growth_c, companion_c = await _read_pair(client, serial, channel, companion)
        except Exception as exc:
            _log(log, f'⚠️ Read failed: {exc}')
            await asyncio.sleep(interval_seconds)
            continue

        if growth_c is None:
            _log(log, '⚠️ No temperature on selected channel (disconnected probe?).')
            await asyncio.sleep(interval_seconds)
            continue

        elapsed_h = (time.time() - start) / 3600.0
        time_data.append(elapsed_h)
        ambient_data.append(growth_c)
        internal_data.append(companion_c if companion_c is not None else growth_c)
        reading += 1
        _log(
            log,
            f'🌡️ Reading #{reading}: Ch{channel} {growth_c:.1f}°C'
            + (f', companion {companion_c:.1f}°C' if companion_c is not None else ''),
        )
        await asyncio.sleep(interval_seconds)

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
):
    """
    Collect a live temperature series from ThermoWorks Cloud for one Signals channel.

    The selected channel becomes ambient_temperature (used by the growth model).
    """
    channel = max(1, int(channel))
    interval_seconds = max(float(interval_seconds), 1.0)

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
                }
                for c in d.get('channels', [])
            ],
        })
    return clean
