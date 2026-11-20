"""Read Celsius readings from an Arduino over USB serial.

The board should print one temperature per line, for example ``22.50``.
A comma-separated line uses the first field. Opening the port resets many
Arduino boards, so collection waits two seconds before the first sample.
"""

import time

import numpy as np

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # pragma: no cover - handled at runtime
    serial = None


def _is_usb_serial(info):
    """True for USB serial devices such as an Arduino, not onboard ttyS ports."""
    device = info.device or ''
    if info.vid is not None:
        return True
    markers = ('ttyACM', 'ttyUSB', 'usbmodem', 'usbserial', 'wchusbserial')
    return any(marker in device for marker in markers)


def list_ports():
    """Return USB serial ports as ``{port, description}`` dicts."""
    if serial is None:
        return []
    ports = []
    for info in serial.tools.list_ports.comports():
        if not _is_usb_serial(info):
            continue
        description = info.description or info.device
        if description.lower() == 'n/a':
            description = info.device
        ports.append({
            'port': info.device,
            'description': description,
        })
    return ports


def _parse_celsius(line):
    """Return a plausible Celsius value from one serial line, or None."""
    token = line.strip().split(',')[0].strip()
    if not token:
        return None
    try:
        value = float(token)
    except ValueError:
        return None
    if value < -40 or value > 125:
        return None
    return value


def _read_latest(ser):
    """Return the newest complete temperature already buffered, or the next line."""
    latest = None
    while ser.in_waiting:
        raw = ser.readline().decode('utf-8', errors='ignore')
        value = _parse_celsius(raw)
        if value is not None:
            latest = value
    if latest is not None:
        return latest
    raw = ser.readline().decode('utf-8', errors='ignore')
    return _parse_celsius(raw)


def collect_temperature_data(port, duration_hours, interval_seconds=2, baud=9600, log=None):
    """Collect a time series in the same shape as the MEATER collector.

    ``log`` is an optional callable that receives progress strings.
    Returns None when the port cannot be opened or no readings arrive.
    """
    def _log(message):
        if log is not None:
            log(message)

    if serial is None:
        _log('❌ pyserial is not installed.')
        return None

    interval_seconds = max(interval_seconds, 1)
    time_data = []
    temps = []

    try:
        with serial.Serial(port, baud, timeout=2) as ser:
            _log(f'🔌 Opened {port}. Waiting for the board to reset...')
            time.sleep(2)
            ser.reset_input_buffer()

            start = time.time()
            end = start + (duration_hours * 3600)
            while time.time() < end:
                celsius = _read_latest(ser)
                if celsius is None:
                    continue
                elapsed_hours = (time.time() - start) / 3600
                time_data.append(elapsed_hours)
                temps.append(celsius)
                _log(f'🌡️ Reading #{len(temps)}: {celsius:.1f}°C')
                time.sleep(interval_seconds)
    except serial.SerialException as exc:
        _log(f'❌ Could not read {port}: {exc}')
        return None
    except OSError as exc:
        _log(f'❌ Could not read {port}: {exc}')
        return None

    if not time_data:
        _log('❌ No temperature readings arrived. Check the sketch and the port.')
        return None

    temperatures = np.array(temps)
    return {
        'time_hours': np.array(time_data),
        'ambient_temperature': temperatures,
        'internal_temperature': temperatures,
        'device_id': port,
        'readings_count': len(time_data),
    }
