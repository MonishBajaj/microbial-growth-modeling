"""
MEATER Cloud client used by the web app.

Login is POST https://public-api.cloud.meater.com/v1/login with the dashboard
account email and password. Device reads are GET /devices and GET /devices/{id}
with the returned bearer token. extract_live_meater_reading drops samples that
are stale, missing a timestamp, or outside a sane Celsius range, so a leftover
cloud value is not treated as a live probe.

The web app calls collect_temperature_data_realtime. The returned arrays use
the shared series shape (time_hours, internal_temperature, ambient_temperature).
The growth model later uses the ambient series.
"""

import os
import requests
import time
import json
import numpy as np
from datetime import datetime
import threading
import sys

from run_control import is_continuous, sleep_unless_stopped, stop_requested


def _meater_probe_max_age_sec():
    try:
        return max(float(os.environ.get('MEATER_PROBE_MAX_AGE_SEC') or '90'), 15.0)
    except ValueError:
        return 90.0


def extract_live_meater_reading(device_payload):
    """Return (internal_c, ambient_c, meta) only for a fresh live MEATER probe.

    MEATER Cloud can keep returning leftover numbers; we require a recent
    ``updated_at`` and sane Celsius values before accepting a sample.
    """
    if not isinstance(device_payload, dict):
        return None, None, {'live': False, 'reason': 'no device payload'}

    device = device_payload.get('data')
    if not isinstance(device, dict):
        # Already a bare device object (e.g. from /devices list entry).
        device = device_payload if 'temperature' in device_payload else None
    if not isinstance(device, dict):
        return None, None, {'live': False, 'reason': 'no device payload'}

    temp = device.get('temperature')
    if not isinstance(temp, dict):
        return None, None, {'live': False, 'reason': 'no temperature object'}

    updated_at = device.get('updated_at')
    try:
        updated_at = float(updated_at)
    except (TypeError, ValueError):
        updated_at = None

    age = None if updated_at is None else max(0.0, time.time() - updated_at)
    max_age = _meater_probe_max_age_sec()
    if age is not None and age > max_age:
        return None, None, {
            'live': False,
            'reason': f'stale telemetry ({age:.0f}s old; max {max_age:.0f}s)',
            'updated_at': updated_at,
            'age_sec': int(age),
            'cook': device.get('cook'),
        }
    if updated_at is None:
        return None, None, {'live': False, 'reason': 'missing updated_at timestamp'}

    try:
        internal = float(temp.get('internal'))
        ambient = float(temp.get('ambient'))
    except (TypeError, ValueError):
        return None, None, {'live': False, 'reason': 'non-numeric temperature'}

    if internal < -40.0 or internal > 300.0 or ambient < -40.0 or ambient > 300.0:
        return None, None, {
            'live': False,
            'reason': f'out-of-range reading (int {internal:.1f}°C / amb {ambient:.1f}°C)',
        }

    require_cook = os.environ.get('MEATER_REQUIRE_COOK', '').lower() in ('1', 'true', 'yes')
    if require_cook and not device.get('cook'):
        return None, None, {
            'live': False,
            'reason': 'no active cook (set MEATER_REQUIRE_COOK=0 to allow ambient-only)',
            'cook': None,
        }

    return internal, ambient, {
        'live': True,
        'reason': '',
        'updated_at': updated_at,
        'age_sec': None if age is None else int(age),
        'cook': device.get('cook'),
        'device_id': device.get('id'),
    }


def describe_meater_http_error(status_code, body_text=''):
    """One line for the run log explaining a failed MEATER Cloud call."""
    hints = {
        401: 'MEATER Cloud rejected the sign-in. The dashboard email and password '
             'must be the same as your MEATER app account.',
        429: 'MEATER Cloud is rate-limiting this account (too many requests). '
             'Another run or app may be polling the same account; wait a minute.',
    }
    hint = hints.get(status_code)
    if hint is None and status_code >= 500:
        hint = 'MEATER Cloud is having trouble; try again shortly.'
    detail = (body_text or '').strip().replace('\n', ' ')[:160]
    return f'HTTP {status_code}' + (f' — {hint}' if hint else '') + (f' ({detail})' if detail and not hint else '')


# Why GET /devices can be empty, from MEATER's API README.
MEATER_NOT_LISTED_HELP = (
    'MEATER Cloud only lists a probe while the MEATER phone app (or Block) has a '
    'Bluetooth connection to it AND MEATER Cloud is switched on and signed in '
    'inside the app (MEATER app → Settings → MEATER Cloud). Keep the phone near '
    'the probe with the app open, and make sure this probe has done at least one '
    'cook while connected to MEATER Cloud.'
)


class EnhancedMeaterAPI:
    """
    Enhanced MEATER Cloud REST API client with real-time terminal display
    """

    def __init__(self):
        """Initialize enhanced MEATER API client"""
        self.base_url = "https://public-api.cloud.meater.com/v1"
        self.token = None
        self.rate_limit_delay = 2  # seconds between requests (recommended: 2 req/60s)
        self.is_connected = False
        self.current_device_id = None
        self.last_reject_reason = ''
        # Why the last authenticate()/get_devices() failed, for the run log.
        self.last_error = ''

    def authenticate(self, email, password):
        """
        Authenticate with MEATER Cloud API with enhanced feedback

        Parameters:
        email: MEATER account email
        password: MEATER account password

        Returns:
        bool: True if authentication successful
        """
        print("\n🔐 Authenticating with MEATER Cloud API...")
        print(f"Email: {email}")

        login_url = f"{self.base_url}/login"

        login_data = {
            "email": email,
            "password": password
        }

        headers = {
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(login_url, json=login_data, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                self.token = data['data']['token']
                print("✅ Authentication successful!")
                print(f"Token received: {self.token[:20]}...")
                return True
            else:
                print(f"❌ Authentication failed: {response.status_code}")
                print(f"Response: {response.text}")
                self.last_error = describe_meater_http_error(response.status_code, response.text)
                return False

        except requests.exceptions.RequestException as e:
            print(f"❌ Network error during authentication: {e}")
            self.last_error = f'could not reach MEATER Cloud ({e})'
            return False
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            self.last_error = str(e)
            return False

    def get_devices(self):
        """
        Get all connected MEATER devices with detailed feedback

        Returns:
        dict: Device information or None if error
        """
        if not self.token:
            print("❌ Not authenticated. Please call authenticate() first.")
            return None

        print("\n🔍 Searching for MEATER devices...")
        devices_url = f"{self.base_url}/devices"

        headers = {
            "Authorization": f"Bearer {self.token}"
        }

        try:
            response = requests.get(devices_url, headers=headers, timeout=10)

            if response.status_code == 200:
                self.last_error = ''
                devices_data = response.json()
                devices = devices_data.get('data', {}).get('devices', [])

                if devices:
                    print(f"✅ Found {len(devices)} MEATER device(s):")
                    for i, device in enumerate(devices):
                        print(f"   Device {i+1}: {device['id']}")
                        print(f"   Status: {device.get('updated_at', 'Unknown')}")
                else:
                    print("⚠️  No MEATER devices found!")
                    print("   - Make sure your MEATER is charged and connected")
                    print("   - Check if device is paired with the MEATER app")
                    print("   - Ensure device has internet connectivity")

                return devices_data
            else:
                print(f"❌ Failed to get devices: {response.status_code}")
                print(f"Response: {response.text}")
                self.last_error = describe_meater_http_error(response.status_code, response.text)
                return None

        except requests.exceptions.RequestException as e:
            print(f"❌ Network error getting devices: {e}")
            self.last_error = f'could not reach MEATER Cloud ({e})'
            return None
        except Exception as e:
            print(f"❌ Error getting devices: {e}")
            self.last_error = str(e)
            return None

    def find_device(self, log=None, wait_seconds=60, poll_seconds=10, should_stop=None):
        """Return the first listed probe id, retrying while MEATER Cloud catches up.

        MEATER's docs say a probe can take a while to appear in GET /devices.
        Polls every ``poll_seconds`` (6/min, under the 60/min API limit) for up
        to ``wait_seconds`` and logs why the list came back empty or failed.
        Returns None when nothing is listed in time.
        """
        def _log(message):
            if log is not None:
                log(message)

        deadline = time.time() + max(wait_seconds, 0)
        explained = False
        last_logged = None
        while True:
            data = self.get_devices()
            devices = (data or {}).get('data', {}).get('devices') or []
            if devices:
                return devices[0]['id']
            if data is None:
                reason = self.last_error or 'unknown error'
                if reason != last_logged:
                    _log(f'⚠️ MEATER device lookup failed: {reason}')
                    last_logged = reason
            elif not explained:
                _log('⚠️ MEATER Cloud lists no probes for this account yet. ' + MEATER_NOT_LISTED_HELP)
                explained = True
            if time.time() + poll_seconds > deadline:
                return None
            _log(f'🔁 Checking MEATER Cloud again in {poll_seconds:.0f}s…')
            if sleep_unless_stopped(poll_seconds, should_stop):
                return None

    def get_device_realtime(self, device_id):
        """
        Get specific device information with real-time temperature display

        Parameters:
        device_id: ID of the MEATER device

        Returns:
        dict: Device information or None if error
        """
        if not self.token:
            return None

        device_url = f"{self.base_url}/devices/{device_id}"

        headers = {
            "Authorization": f"Bearer {self.token}"
        }

        try:
            response = requests.get(device_url, headers=headers, timeout=5)

            if response.status_code == 200:
                device_data = response.json()
                internal_temp, ambient_temp, meta = extract_live_meater_reading(device_data)
                if internal_temp is None:
                    self.is_connected = False
                    self.last_reject_reason = meta.get('reason') or 'not a live probe'
                    print(
                        f"\r⚠️  {datetime.now().strftime('%H:%M:%S')} | "
                        f"Skipping MEATER {device_id[:8]} — {self.last_reject_reason}",
                        end="",
                        flush=True,
                    )
                    return None

                timestamp = datetime.now().strftime("%H:%M:%S")
                print(
                    f"\r🌡️  {timestamp} | Internal: {internal_temp:>6.1f}°C | "
                    f"Ambient: {ambient_temp:>6.1f}°C | Device: {device_id[:8]} (live)",
                    end="",
                    flush=True,
                )
                self.is_connected = True
                self.last_reject_reason = ''
                return device_data

            print(f"\r❌ {datetime.now().strftime('%H:%M:%S')} | Device error: {response.status_code}", end="", flush=True)
            return None

        except requests.exceptions.Timeout:
            print(f"\r⏰ {datetime.now().strftime('%H:%M:%S')} | Request timeout - device may be offline", end="", flush=True)
            return None
        except Exception as e:
            print(f"\r❌ {datetime.now().strftime('%H:%M:%S')} | Error: {e}", end="", flush=True)
            return None

    def collect_temperature_data_realtime(
        self, device_id=None, duration_hours=2, interval_seconds=1, model=None, log=None,
        should_stop=None,
    ):
        """
        Collect temperature data with enhanced real-time display

        Parameters:
        device_id: ID of specific device (if None, uses first available)
        duration_hours: How long to collect data (hours)
        interval_seconds: How often to collect data (seconds, minimum 2)
        model: optional CorrectedMicrobialGrowthModel; each live reading also
            shows the running population estimate from the ambient series
        log: optional callable that receives one line per live reading
        should_stop: optional callable; when it returns True collection ends
            early. duration_hours may be run_control.CONTINUOUS to run until stopped.

        Returns:
        dict: Time series temperature data
        """
        if not self.token:
            print("❌ Not authenticated. Please call authenticate() first.")
            return None

        # Ensure minimum interval to respect rate limits
        interval_seconds = max(interval_seconds, 2)

        # If no device_id specified, get first available device
        if device_id is None:
            devices_response = self.get_devices()
            if not devices_response or not devices_response.get('data', {}).get('devices'):
                print("\n❌ No devices available for data collection")
                return None
            device_id = devices_response['data']['devices'][0]['id']
            print(f"\n🎯 Selected device: {device_id}")

        self.current_device_id = device_id

        print(f"\n📊 Starting real-time data collection:")
        continuous = is_continuous(duration_hours)
        print("   Duration: until stopped" if continuous else f"   Duration: {duration_hours} hours")
        print(f"   Interval: {interval_seconds} seconds")
        print(f"   Device ID: {device_id}")
        if not continuous:
            print(f"   Total readings: ~{int(duration_hours * 3600 / interval_seconds)}")
        print("\n🔴 LIVE DATA (Press Ctrl+C to stop early):")
        print("=" * 80)

        time_data = []
        internal_temp_data = []
        ambient_temp_data = []

        start_time = time.time()
        end_time = start_time + (duration_hours * 3600)
        reading_count = 0
        live = model.live_estimator() if model else None

        skipped = 0
        try:
            while time.time() < end_time and not stop_requested(should_stop):
                device_data = self.get_device_realtime(device_id)
                internal_temp, ambient_temp, meta = extract_live_meater_reading(device_data) if device_data else (None, None, {})

                if internal_temp is not None:
                    current_time = (time.time() - start_time) / 3600  # Hours since start
                    time_data.append(current_time)
                    internal_temp_data.append(internal_temp)
                    ambient_temp_data.append(ambient_temp)
                    reading_count += 1
                    pop_note = live.note(current_time, ambient_temp) if live else ""
                    sys.stdout.write(f" | #{reading_count}{pop_note}")
                    sys.stdout.flush()
                    if log is not None:
                        log(
                            f"🌡️ Reading #{reading_count}: Internal {internal_temp:.1f}°C, "
                            f"Ambient {ambient_temp:.1f}°C (live probe)" + pop_note
                        )
                else:
                    skipped += 1
                    reason = (meta or {}).get('reason') or self.last_reject_reason or 'not live'
                    print(f"\n⚠️  Skipped non-live MEATER sample ({reason})")

                if sleep_unless_stopped(interval_seconds, should_stop):
                    break

        except KeyboardInterrupt:
            print(f"\n\n⏹️  Data collection stopped by user after {len(time_data)} readings")
        except Exception as e:
            print(f"\n\n❌ Data collection error: {e}")

        print("\n" + "=" * 80)
        print(f"✅ Data collection completed!")
        print(f"   Total readings: {len(time_data)}")
        print(f"   Duration: {time_data[-1]:.2f} hours" if time_data else "   Duration: 0 hours")
        print(f"   Temperature range: {np.min(ambient_temp_data):.1f}°C to {np.max(ambient_temp_data):.1f}°C" if ambient_temp_data else "   No temperature data")

        if not time_data:
            return None

        return {
            'time_hours': np.array(time_data),
            'internal_temperature': np.array(internal_temp_data),
            'ambient_temperature': np.array(ambient_temp_data),
            'device_id': device_id,
            'readings_count': len(time_data)
        }

    def test_connection(self, device_id=None):
        """
        Test MEATER device connection with detailed diagnostics

        Parameters:
        device_id: Specific device to test (optional)

        Returns:
        bool: True if connection successful
        """
        print("\n🧪 Testing MEATER device connection...")

        if not self.token:
            print("❌ Not authenticated")
            return False

        # Get devices
        devices_response = self.get_devices()
        if not devices_response:
            return False

        devices = devices_response.get('data', {}).get('devices', [])
        if not devices:
            print("❌ No devices found")
            return False

        # Use specified device or first available
        test_device_id = device_id or devices[0]['id']

        print(f"\n🎯 Testing device: {test_device_id}")
        print("   Attempting to get temperature reading...")

        # Try to get device data
        device_data = self.get_device_realtime(test_device_id)

        if device_data:
            print("\n✅ Connection test successful!")
            print("   MEATER device is connected and responding")
            return True
        else:
            print("\n❌ Connection test failed!")
            print("   Device is not responding or no temperature data available")
            return False
