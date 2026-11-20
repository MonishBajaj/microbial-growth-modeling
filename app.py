"""
Microbial Growth Analyzer — Flask Web Application
Wraps the existing microbial growth analysis code with a web interface.
"""

import os
import io
import base64
import hmac
import uuid
import threading
import time
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend — must be set before pyplot import
import matplotlib.pyplot as plt
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from werkzeug.security import check_password_hash

from enhanced_meater_api import EnhancedMeaterAPI
from corrected_microbial_growth_model import CorrectedMicrobialGrowthModel
from arduino_serial import collect_temperature_data, list_ports
from arduino_wifi import (
    WIFI_NAME,
    collect_wifi_temperature_data,
    discovered_boards,
    discovery_error,
    lookup_board,
)
from thermoworks_signals import (
    collect_temperature_data as collect_signals_temperature_data,
    device_snapshot_for_api,
    list_devices as list_signals_devices,
)
from arduino_push import (
    collect_temperature_data as collect_push_temperature_data,
    ingest_path,
    ingest_token,
    ingest_url,
    public_base_url,
    record_reading,
    status_snapshot as push_status_snapshot,
    token_ok as push_token_ok,
)
from pmp_catalog import DEFAULT_MODEL_ID, list_models_for_api, require_ready

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.urandom(24)

# In-memory store for background tasks  {task_id: {status, result, logs, ...}}
background_tasks = {}

_SOURCE_LABELS = {
    'MEATER_REALTIME': 'MEATER',
    'ARDUINO': 'Arduino USB',
    'ARDUINO_WIFI': 'Arduino WiFi',
    'ARDUINO_PUSH': 'Arduino Push',
    'SIGNALS': 'ThermoWorks Signals',
    'SAMPLE_DATA': 'Sample Data',
}


def _source_label(data_source):
    """Human-readable name for a stored data-source key."""
    if data_source in _SOURCE_LABELS:
        return _SOURCE_LABELS[data_source]
    return str(data_source).replace('_', ' ').title()


# Local dashboard accounts. Passwords are stored only as hashes.
_LOCAL_USERS = {
    'bajajmonish0@gmail.com': (
        'pbkdf2:sha256:1000000$vTT6AXrrEBm77xNA$'
        '3a3813f741acf88a88d45ff46197c465f1a7135ce0baa73c60fe4c558a5927d8'
    ),
    'mishralabuga@gmail.com': (
        'pbkdf2:sha256:1000000$lUqC5MZOObykkvWl$'
        'afca0eb191db2c176d32c88d40026a217dccd71f67b1fe0d247f792875e3d1e7'
    ),
    'juan.gao@uga.edu': (
        'pbkdf2:sha256:1000000$h7Es0zpHGXnbXVeY$'
        '3618974f1e8459e959434c645b7aced4ea56cea7460aed5bc70c23688cd8ebac'
    ),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login_required(f):
    """Decorator that redirects unauthenticated users to the login page."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            flash('Please sign in first.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def _generate_plot(results):
    """Generate the microbial-growth plot and return it as a base64-encoded PNG."""
    fig, ax1 = plt.subplots(figsize=(12, 8))

    ylabel = results.get('population_label') or 'Population (Log CFU/g)'
    ax1.plot(results['time'], results['population'], 'b-', linewidth=2,
             label='Predicted Population')
    ax1.set_xlabel('Time (h)', fontsize=14)
    ax1.set_ylabel(ylabel, fontsize=14, color='blue')
    ax1.set_ylim(0, 10)
    ax1.tick_params(axis='y', labelcolor='blue')

    # Experimental overlay only for the MATLAB-matched Pseudomonas baseline.
    if results.get('show_pseudomonas_experiment'):
        Tv = np.array([0, 2, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48])
        Yv = np.array([2.514, 2.874, 3.239, 5.123, 5.096, 6.327, 7.314, 7.969,
                       8.048, 7.856, 8.124, 8.233, 8.093, 8.206])
        Err = np.array([0.229, 0.047, 0.282, 0.174, 0.143, 0.036, 0.136, 0.324,
                        0.203, 0.017, 0.026, 0.008, 0.028, 0.110])
        ax1.errorbar(Tv, Yv, yerr=Err, fmt='ro', capsize=5, capthick=2,
                     markersize=6, label='Experimental Data')
    ax1.legend()

    ax2 = ax1.twinx()
    data_source = results.get('data_source', 'UNKNOWN')
    live_sources = {'MEATER_REALTIME', 'ARDUINO', 'ARDUINO_WIFI', 'ARDUINO_PUSH', 'SIGNALS'}
    ls = '-' if data_source in live_sources else '--'
    ax2.plot(results['time'], results['temperature'], f'r{ls}', linewidth=2,
             label='Temperature')
    ax2.set_ylabel('Temperature (°C)', fontsize=14, color='red')
    tmin = float(np.min(results['temperature']))
    tmax = float(np.max(results['temperature']))
    pad = max(2.0, 0.05 * (tmax - tmin + 1e-9))
    ax2.set_ylim(min(10.0, tmin - pad), max(40.0, tmax + pad))
    ax2.tick_params(axis='y', labelcolor='red')

    bacteria = results.get('bacteria') or 'Microbial'
    model_label = results.get('model_label') or ''
    if data_source in live_sources and 'meater_data' in results:
        device_id = str(results['meater_data'].get('device_id', ''))
        dev = device_id[:8] if data_source == 'MEATER_REALTIME' else device_id
        cnt = results['meater_data'].get('readings_count', 0)
        source_label = _source_label(data_source)
        title = (
            f'{bacteria} — {source_label} '
            f'(Device: {dev}, {cnt} readings)'
        )
    else:
        title = f'{bacteria} — {_source_label(data_source)}'
    if model_label:
        title = f'{title}\n{model_label}'

    ax1.set_title(title, fontsize=14)
    ax1.grid(True, alpha=0.3)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def _build_stats(results):
    """Extract display statistics from simulation results."""
    stats = {
        'final_population': float(results['population'][-1]),
        'temp_min': float(np.min(results['temperature'])),
        'temp_max': float(np.max(results['temperature'])),
        'data_source': _source_label(results.get('data_source', 'Unknown')),
        'bacteria': results.get('bacteria') or '—',
        'model_label': results.get('model_label') or '—',
        'citation': results.get('citation') or '',
    }

    if 'meater_data' in results:
        md = results['meater_data']
        stats['readings'] = md.get('readings_count', 'N/A')
        t_arr = md.get('time_hours')
        if t_arr is not None and len(t_arr) > 0:
            stats['duration'] = f"{t_arr[-1]:.2f} hours"

    return stats


def _resolve_model(model_id):
    """Return a ready CorrectedMicrobialGrowthModel or (None, error)."""
    model_id = (model_id or DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID
    entry, err = require_ready(model_id)
    if err:
        return None, err
    try:
        return CorrectedMicrobialGrowthModel.from_catalog(model_id), None
    except ValueError as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Background-task runner (modes 1–3)
# ---------------------------------------------------------------------------

def _run_mode1(task_id, email, password):
    """Mode 1 — Quick Connection Test (background)."""
    info = background_tasks[task_id]
    info['logs'].append('🔐 Authenticating with MEATER Cloud API...')
    info['status'] = 'authenticating'

    api = EnhancedMeaterAPI()
    auth_ok = api.authenticate(email, password)

    if not auth_ok:
        info['logs'].append('❌ Authentication failed.')
        info['status'] = 'error'
        info['result'] = {'error': 'Authentication failed. Check your credentials.'}
        return

    info['logs'].append('✅ Authentication successful.')
    info['logs'].append('🔍 Searching for MEATER devices...')
    info['status'] = 'searching_devices'

    devices = api.get_devices()
    if not devices or not devices.get('data', {}).get('devices'):
        info['logs'].append('⚠️ No MEATER devices found.')
        info['status'] = 'done'
        info['result'] = {
            'connection_result': False,
            'readings_count': 0,
            'logs': info['logs'],
            'mode_name': 'Quick Connection Test',
        }
        return

    device_id = devices['data']['devices'][0]['id']
    info['logs'].append(f'📱 Testing device: {device_id[:8]}...')
    info['status'] = 'testing'

    # Collect a few readings over ~30 seconds
    end_time = time.time() + 30
    readings = 0
    temperatures = []

    while time.time() < end_time:
        dd = api.get_device_realtime(device_id)
        if dd and 'data' in dd and 'temperature' in dd['data']:
            readings += 1
            td = dd['data']['temperature']
            temperatures.append({'internal': td.get('internal', 0),
                                 'ambient': td.get('ambient', 0)})
            info['logs'].append(
                f"🌡️ Reading #{readings}: Internal {td.get('internal', 0):.1f}°C, "
                f"Ambient {td.get('ambient', 0):.1f}°C")
        time.sleep(2)

    avg_temps_str = ''
    if temperatures:
        ai = np.mean([t['internal'] for t in temperatures])
        aa = np.mean([t['ambient'] for t in temperatures])
        avg_temps_str = f"Int {ai:.1f}°C / Amb {aa:.1f}°C"

    info['logs'].append(f"✅ Test completed — {readings} readings collected.")
    info['status'] = 'done'
    info['result'] = {
        'connection_result': readings > 0,
        'readings_count': readings,
        'avg_temps': avg_temps_str,
        'logs': info['logs'],
        'mode_name': 'Quick Connection Test',
    }


def _run_mode2_3(
    task_id, email, password, duration_hours, interval_seconds, mode_name,
    model_id=DEFAULT_MODEL_ID,
):
    """Modes 2 & 3 — Real-time analysis (background)."""
    info = background_tasks[task_id]
    info['logs'].append('🔐 Authenticating...')
    info['status'] = 'authenticating'

    api = EnhancedMeaterAPI()
    if not api.authenticate(email, password):
        info['logs'].append('❌ Authentication failed.')
        info['status'] = 'error'
        info['result'] = {'error': 'Authentication failed.'}
        return

    info['logs'].append('✅ Authenticated. Searching for devices...')
    info['status'] = 'searching_devices'

    devices = api.get_devices()
    if not devices or not devices.get('data', {}).get('devices'):
        info['logs'].append('⚠️ No MEATER devices found.')
        info['status'] = 'error'
        info['result'] = {'error': 'No MEATER devices found.'}
        return

    device_id = devices['data']['devices'][0]['id']
    info['logs'].append(f'📡 Collecting data from device {device_id[:8]}...')
    info['status'] = 'collecting'

    temp_data = api.collect_temperature_data_realtime(
        device_id=device_id,
        duration_hours=duration_hours,
        interval_seconds=max(interval_seconds, 2),
    )

    if temp_data is None:
        info['logs'].append('❌ Failed to collect temperature data.')
        info['status'] = 'error'
        info['result'] = {'error': 'Failed to collect temperature data.'}
        return

    _finish_analysis(info, temp_data, 'MEATER_REALTIME', mode_name, model_id=model_id)


def _finish_analysis(info, temp_data, data_source, mode_name, model_id=DEFAULT_MODEL_ID):
    """Run the growth model on a collected temperature series and store the plot."""
    model, err = _resolve_model(model_id)
    if err:
        info['logs'].append(f'❌ Model unavailable: {err}')
        info['status'] = 'error'
        info['result'] = {'error': err}
        return

    info['logs'].append(
        f'🧮 Running {model.meta.get("bacteria", "growth")} simulation '
        f'({len(temp_data["time_hours"])} readings)...'
    )
    info['status'] = 'simulating'

    results = model.simulate_growth(temp_data['time_hours'], temp_data['ambient_temperature'])
    results['meater_data'] = temp_data
    results['data_source'] = data_source

    image_b64 = _generate_plot(results)
    stats = _build_stats(results)

    info['logs'].append('✅ Analysis complete!')
    info['status'] = 'done'
    info['result'] = {
        'image_data': image_b64,
        'stats': stats,
        'logs': info['logs'],
        'mode_name': mode_name,
    }


def _run_live_test(task_id, label, collect):
    """Mode 1 — quick connection test for USB or Wi-Fi."""
    info = background_tasks[task_id]
    info['logs'].append(f'🔍 Testing {label}...')
    info['status'] = 'testing'

    temp_data = collect(
        duration_hours=30 / 3600,
        interval_seconds=2,
        log=info['logs'].append,
    )

    if temp_data is None:
        info['status'] = 'done'
        info['result'] = {
            'connection_result': False,
            'readings_count': 0,
            'logs': info['logs'],
            'mode_name': 'Quick Connection Test',
        }
        return

    avg = float(np.mean(temp_data['ambient_temperature']))
    info['logs'].append(f"✅ Test completed — {temp_data['readings_count']} readings collected.")
    info['status'] = 'done'
    info['result'] = {
        'connection_result': True,
        'readings_count': temp_data['readings_count'],
        'avg_temps': f'{avg:.1f}°C',
        'logs': info['logs'],
        'mode_name': 'Quick Connection Test',
    }


def _run_live_analysis(
    task_id, label, data_source, duration_hours, interval_seconds, mode_name, collect,
    model_id=DEFAULT_MODEL_ID,
):
    """Modes 2 and 3 — collect USB or Wi-Fi temperatures and run the growth model."""
    info = background_tasks[task_id]
    info['logs'].append(f'📡 Collecting data from {label}...')
    info['status'] = 'collecting'

    temp_data = collect(
        duration_hours=duration_hours,
        interval_seconds=max(interval_seconds, 1),
        log=info['logs'].append,
    )

    if temp_data is None:
        info['logs'].append('❌ Failed to collect temperature data.')
        info['status'] = 'error'
        info['result'] = {'error': f'Failed to collect temperature data from {label}.'}
        return

    _finish_analysis(info, temp_data, data_source, mode_name, model_id=model_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if session.get('authenticated'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    if not email or not password:
        flash('Email and password are required.', 'error')
        return redirect(url_for('login'))

    email_key = email.lower()
    password_hash = None
    for stored_email, stored_hash in _LOCAL_USERS.items():
        if hmac.compare_digest(email_key, stored_email):
            password_hash = stored_hash
            break

    if password_hash and check_password_hash(password_hash, password):
        session['authenticated'] = True
        session['email'] = email
        session['password'] = password  # used later for optional MEATER analysis
        flash('Signed in successfully!', 'success')
        return redirect(url_for('dashboard'))

    flash('Authentication failed. Please check your email and password.', 'error')
    return redirect(url_for('login'))


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been signed out.', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/arduino/ports')
@login_required
def arduino_ports():
    """Serial ports the dashboard can offer for an Arduino USB connection."""
    return jsonify(list_ports())


@app.route('/api/arduino/wifi')
@login_required
def arduino_wifi_lookup():
    """List boards announcing the temperature service on this computer's network.

    A ``host`` query also checks that one typed address.
    """
    payload = {
        'boards': discovered_boards(),
        'error': discovery_error(),
    }
    host = request.args.get('host', '').strip()
    if host:
        payload['lookup'] = lookup_board(host)
    return jsonify(payload)


@app.route('/api/models')
@login_required
def api_models():
    """Bacteria → Model catalog for the dashboard pickers."""
    return jsonify(list_models_for_api())


@app.route('/api/signals/devices', methods=['POST'])
@login_required
def signals_devices():
    """List ThermoWorks Cloud devices for the Signals source panel."""
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or request.form.get('tw_email') or '').strip()
    password = (payload.get('password') or request.form.get('tw_password') or '').strip()
    if not email or not password:
        email = email or (session.get('tw_email') or session.get('email') or '')
        password = password or (session.get('tw_password') or session.get('password') or '')
    if not email or not password:
        return jsonify({'error': 'ThermoWorks email and password are required.', 'devices': []}), 400
    try:
        devices = list_signals_devices(email, password)
        session['tw_email'] = email
        session['tw_password'] = password
        return jsonify({'devices': device_snapshot_for_api(devices), 'error': None})
    except Exception as exc:
        return jsonify({'error': str(exc), 'devices': []}), 401


@app.route('/api/arduino/ingest', methods=['POST', 'OPTIONS'])
def arduino_ingest():
    """Accept Celsius posts from an Arduino (no browser login).

    Auth: ``Authorization: Bearer <token>`` or JSON/body field ``token``.
    Body JSON: ``{"celsius": 23.5, "device_id": "uno-r4-1"}``.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    payload = request.get_json(silent=True) or {}
    header = request.headers.get('Authorization')
    supplied = payload.get('token') or request.args.get('token')
    if not push_token_ok(header, supplied):
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401

    try:
        celsius = float(payload.get('celsius', payload.get('temperature')))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'celsius is required'}), 400
    if celsius < -40 or celsius > 125:
        return jsonify({'ok': False, 'error': 'celsius out of range'}), 400

    device_id = str(payload.get('device_id') or payload.get('device') or 'arduino')
    record = record_reading(celsius, device_id)
    return jsonify({'ok': True, 'stored': record})


@app.route('/api/arduino/push_status')
@login_required
def arduino_push_status():
    """Latest push devices + public ingest URL for the dashboard panel."""
    snap = push_status_snapshot()
    snap['token'] = ingest_token()  # lab convenience; change via ARDUINO_PUSH_TOKEN
    return jsonify(snap)


@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    mode = request.form.get('mode', '')
    source = request.form.get('source', 'meater')
    if source == 'arduino':
        source = 'arduino_usb'
    port = request.form.get('port', '').strip()
    wifi_host = request.form.get('wifi_host', '').strip() or WIFI_NAME
    push_device_id = request.form.get('push_device_id', '').strip()
    signals_serial = request.form.get('signals_serial', '').strip()
    try:
        signals_channel = int(request.form.get('signals_channel', '1') or '1')
    except ValueError:
        signals_channel = 1
    tw_email = request.form.get('tw_email', '').strip() or session.get('tw_email') or ''
    tw_password = request.form.get('tw_password', '').strip() or session.get('tw_password') or ''
    model_id = request.form.get('model_id', DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID
    email = session.get('email')
    password = session.get('password')

    if mode in ('2', '3', '4'):
        _, model_err = require_ready(model_id)
        if model_err:
            flash(model_err, 'error')
            return redirect(url_for('dashboard'))

    if mode == '4':
        # ---- Sample Data (synchronous) ----
        time_hours = np.arange(0, 51, 1)
        temperatures = 25 + 10 * np.sin(2 * np.pi * time_hours / 6)

        model, err = _resolve_model(model_id)
        if err:
            flash(err, 'error')
            return redirect(url_for('dashboard'))

        results = model.simulate_growth(time_hours, temperatures)
        results['data_source'] = 'SAMPLE_DATA'

        image_b64 = _generate_plot(results)
        stats = _build_stats(results)

        return render_template('results.html',
                               image_data=image_b64,
                               stats=stats,
                               mode_name='Sample Data Analysis')

    elif mode in ('1', '2', '3'):
        if source == 'arduino_usb' and not port:
            flash('Select an Arduino serial port.', 'error')
            return redirect(url_for('dashboard'))

        if source == 'signals':
            if not tw_email or not tw_password:
                tw_email = tw_email or email or ''
                tw_password = tw_password or password or ''
            if not tw_email or not tw_password:
                flash('Enter your ThermoWorks Cloud email and password for Signals.', 'error')
                return redirect(url_for('dashboard'))
            session['tw_email'] = tw_email
            session['tw_password'] = tw_password

        task_id = str(uuid.uuid4())
        background_tasks[task_id] = {
            'status': 'starting',
            'result': None,
            'logs': [],
        }

        if source == 'arduino_usb':
            label = f'Arduino USB on {port}'

            def collect_usb(**kwargs):
                return collect_temperature_data(port, **kwargs)

            if mode == '1':
                target, args = _run_live_test, (task_id, label, collect_usb)
            elif mode == '2':
                target, args = _run_live_analysis, (
                    task_id, label, 'ARDUINO', 0.1, 2, 'Short Real-time Analysis',
                    collect_usb, model_id,
                )
            else:
                target, args = _run_live_analysis, (
                    task_id, label, 'ARDUINO', 8.0, 60, 'Full Real-time Analysis',
                    collect_usb, model_id,
                )
        elif source == 'arduino_wifi':
            label = f'Arduino WiFi at {wifi_host}'

            def collect_wifi(**kwargs):
                return collect_wifi_temperature_data(wifi_host, **kwargs)

            if mode == '1':
                target, args = _run_live_test, (task_id, label, collect_wifi)
            elif mode == '2':
                target, args = _run_live_analysis, (
                    task_id, label, 'ARDUINO_WIFI', 0.1, 2, 'Short Real-time Analysis',
                    collect_wifi, model_id,
                )
            else:
                target, args = _run_live_analysis, (
                    task_id, label, 'ARDUINO_WIFI', 8.0, 60, 'Full Real-time Analysis',
                    collect_wifi, model_id,
                )
        elif source == 'arduino_push':
            label = f'Arduino Push {push_device_id or "(any device)"}'

            def collect_push(**kwargs):
                return collect_push_temperature_data(
                    device_id=push_device_id or None,
                    **kwargs,
                )

            if mode == '1':
                target, args = _run_live_test, (task_id, label, collect_push)
            elif mode == '2':
                target, args = _run_live_analysis, (
                    task_id, label, 'ARDUINO_PUSH', 0.1, 2, 'Short Real-time Analysis',
                    collect_push, model_id,
                )
            else:
                target, args = _run_live_analysis, (
                    task_id, label, 'ARDUINO_PUSH', 8.0, 60, 'Full Real-time Analysis',
                    collect_push, model_id,
                )
        elif source == 'signals':
            label = (
                f'ThermoWorks Signals {signals_serial or "(auto)"} '
                f'ch{signals_channel}'
            )

            def collect_signals(**kwargs):
                return collect_signals_temperature_data(
                    tw_email,
                    tw_password,
                    serial=signals_serial or None,
                    channel=signals_channel,
                    **kwargs,
                )

            if mode == '1':
                target, args = _run_live_test, (task_id, label, collect_signals)
            elif mode == '2':
                target, args = _run_live_analysis, (
                    task_id, label, 'SIGNALS', 0.1, 2, 'Short Real-time Analysis',
                    collect_signals, model_id,
                )
            else:
                target, args = _run_live_analysis, (
                    task_id, label, 'SIGNALS', 8.0, 60, 'Full Real-time Analysis',
                    collect_signals, model_id,
                )
        elif mode == '1':
            target, args = _run_mode1, (task_id, email, password)
        elif mode == '2':
            target, args = _run_mode2_3, (
                task_id, email, password, 0.1, 2, 'Short Real-time Analysis', model_id,
            )
        else:
            target, args = _run_mode2_3, (
                task_id, email, password, 8.0, 60, 'Full Real-time Analysis', model_id,
            )

        threading.Thread(target=target, args=args, daemon=True).start()
        return redirect(url_for('task_status_page', task_id=task_id))

    else:
        flash('Invalid analysis mode selected.', 'error')
        return redirect(url_for('dashboard'))


@app.route('/status/<task_id>')
@login_required
def task_status_page(task_id):
    """Render the status-polling page for a background task."""
    task = background_tasks.get(task_id)
    if not task:
        flash('Task not found.', 'error')
        return redirect(url_for('dashboard'))

    if task['status'] in ('done', 'error'):
        result = task.get('result', {})
        if 'error' in result:
            return render_template('results.html', error=result['error'],
                                   mode_name='Analysis')
        return render_template('results.html', **result)

    # Still running → render a status page that polls via JS
    return render_template('status.html', task_id=task_id,
                           status=task['status'], logs=task['logs'])


@app.route('/api/status/<task_id>')
@login_required
def api_task_status(task_id):
    """JSON endpoint polled by the status page."""
    task = background_tasks.get(task_id)
    if not task:
        return jsonify({'error': 'not_found'}), 404
    return jsonify({
        'status': task['status'],
        'logs': task['logs'],
        'done': task['status'] in ('done', 'error'),
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # 0.0.0.0 so LAN boards and tunnels can reach the ingest endpoint.
    print(f'Arduino push ingest: {ingest_path()}')
    if public_base_url():
        print(f'Public ingest URL: {ingest_url()}')
    print(f'Arduino push token: {ingest_token()}')
    app.run(debug=True, host='0.0.0.0', port=5000)
