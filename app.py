"""
Web app for the microbial growth analyzer.

A signed-in user picks a catalog model, a temperature source, and a run mode.
This file starts that run, stores it as a background job, and serves the pages
and JSON the dashboard polls.

Temperature collectors all hand back the same series shape:
time_hours, ambient_temperature, internal_temperature, device_id, readings_count.
The growth model is fed ambient_temperature. See docs/USER_GUIDE.md for the
full path, including how each device sends those numbers.
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
from enhanced_meater_api import (
    MEATER_NOT_LISTED_HELP,
    EnhancedMeaterAPI,
    extract_live_meater_reading,
)
from local_accounts import create_profile, reset_password, verify_login
from job_store import (
    clear_stop,
    create_job,
    get_job,
    job_summary,
    list_jobs,
    request_stop,
    stop_requested,
)
from run_control import CONTINUOUS
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
    SIDECAR_CHUNK_HOURS,
    collect_temperature_data as collect_signals_temperature_data,
    device_snapshot_for_api,
    list_devices as list_signals_devices,
    uses_sidecar as signals_uses_sidecar,
)
from thermoworks_appcheck import (
    appcheck_status,
    bridge_status,
    complete_bridge,
    create_bridge,
    store_browser_token,
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

# Legacy name kept for existing runners; jobs are JobRecord instances (disk-backed).
background_tasks = {}


def _bind_job(task_id: str):
    """Return the job record, loading from disk into background_tasks if needed."""
    # Prefer the process-local object while a runner is active on this worker.
    local = background_tasks.get(task_id)
    job = get_job(task_id, prefer_cache=local is not None)
    if job is not None:
        background_tasks[task_id] = job
    return job

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login_required(f):
    """Decorator that redirects unauthenticated users to the login page."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            wants_json = (
                request.path.startswith('/api/')
                or request.accept_mimetypes.best == 'application/json'
                or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or (request.content_type or '').startswith('application/json')
            )
            if wants_json:
                return jsonify({'error': 'Please sign in again.', 'devices': []}), 401
            flash('Please sign in first.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def _generate_plot(results):
    """Generate the microbial-growth plot and return it as a base64-encoded PNG."""
    fig, ax1 = plt.subplots(figsize=(12, 8))

    # Runs shorter than an hour are drawn in minutes so 6 min reads as 0–6, not 0–0.1.
    t_hours = np.asarray(results['time'], dtype=float)
    span_h = float(t_hours[-1] - t_hours[0]) if t_hours.size else 0.0
    if span_h < 1.0:
        t_scale, t_unit = 60.0, 'min'
    else:
        t_scale, t_unit = 1.0, 'h'
    t_plot = t_hours * t_scale

    ylabel = results.get('population_label') or 'Population (Log CFU/g)'
    ax1.plot(t_plot, results['population'], 'b-', linewidth=2,
             label='Predicted Population')
    ax1.set_xlabel(f'Time ({t_unit})', fontsize=14)
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
        ax1.errorbar(Tv * t_scale, Yv, yerr=Err, fmt='ro', capsize=5, capthick=2,
                     markersize=6, label='Experimental Data')
    ax1.legend()
    # Fit the time axis to the run itself; overlay points outside it are clipped.
    if t_plot.size and t_plot[-1] > t_plot[0]:
        ax1.set_xlim(t_plot[0], t_plot[-1])

    ax2 = ax1.twinx()
    data_source = results.get('data_source', 'UNKNOWN')
    live_sources = {'MEATER_REALTIME', 'ARDUINO', 'ARDUINO_WIFI', 'ARDUINO_PUSH', 'SIGNALS'}
    ls = '-' if data_source in live_sources else '--'
    ax2.plot(t_plot, results['temperature'], f'r{ls}', linewidth=2,
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


def _live_rate_model(model_id=None):
    """Model whose running population estimate is printed beside quick-test readings.

    Uses the selected model when it is ready, otherwise the default
    Pseudomonas entry. Returns None only if neither can be built.
    """
    model, err = _resolve_model(model_id)
    if err:
        model, _ = _resolve_model(DEFAULT_MODEL_ID)
    return model


def _model_unavailable(info, err):
    info['logs'].append(f'❌ Model unavailable: {err}')
    info['status'] = 'error'
    info['result'] = {'error': err}


# Collection modes that end in a growth simulation:
# mode -> (duration_hours, interval_seconds, mode_name shown on the results page)
LIVE_RUNS = {
    '2': (0.1, 2, 'Short Real-time Analysis'),
    '3': (8.0, 60, 'Full Real-time Analysis'),
    # Runs until the user presses Stop on the status page.
    '5': (CONTINUOUS, 30, 'Continuous Monitoring'),
}


def _stop_check(task_id):
    """Callable the collectors poll; True once Stop was pressed for this job."""
    return lambda: stop_requested(task_id)


def _note_if_stopped(info, task_id, temp_data):
    """Log an early stop and remove the stop marker."""
    if stop_requested(task_id):
        count = temp_data['readings_count'] if temp_data else 0
        info['logs'].append(
            f'⏹ Stopped after {count} readings. '
            + ('Running the growth model on everything collected.' if count else '')
        )
    clear_stop(task_id)


# ---------------------------------------------------------------------------
# Background-task runner (modes 1–3)
# ---------------------------------------------------------------------------

def _meater_auth_error(api):
    """Run-log message for a failed MEATER sign-in, with MEATER's reason when known."""
    reason = getattr(api, 'last_error', '') or 'check your credentials'
    return f'MEATER sign-in failed: {reason}'


def _run_mode1(task_id, email, password, model_id=None):
    """Mode 1 — Quick Connection Test (background)."""
    info = _bind_job(task_id)
    if info is None:
        return
    model = _live_rate_model(model_id)
    live = model.live_estimator() if model else None
    info['logs'].append('🔐 Authenticating with MEATER Cloud API...')
    info['status'] = 'authenticating'

    api = EnhancedMeaterAPI()
    auth_ok = api.authenticate(email, password)

    if not auth_ok:
        msg = _meater_auth_error(api)
        info['logs'].append(f'❌ {msg}')
        info['status'] = 'error'
        info['result'] = {'error': msg}
        return

    info['logs'].append('✅ Authentication successful.')
    info['logs'].append('🔍 Searching for MEATER devices...')
    info['status'] = 'searching_devices'

    device_id = api.find_device(log=info['logs'].append)
    if not device_id:
        info['logs'].append('⚠️ No MEATER devices found.')
        info['status'] = 'done'
        info['result'] = {
            'connection_result': False,
            'readings_count': 0,
            'logs': info['logs'],
            'mode_name': 'Quick Connection Test',
        }
        return

    info['logs'].append(f'📱 Testing device: {device_id[:8]}...')
    info['status'] = 'testing'

    # Collect a few readings over ~30 seconds
    start_time = time.time()
    end_time = start_time + 30
    readings = 0
    temperatures = []

    while time.time() < end_time:
        dd = api.get_device_realtime(device_id)
        internal_c, ambient_c, meta = extract_live_meater_reading(dd) if dd else (None, None, {})
        if internal_c is not None:
            readings += 1
            temperatures.append({'internal': internal_c, 'ambient': ambient_c})
            info['logs'].append(
                f"🌡️ Reading #{readings}: Internal {internal_c:.1f}°C, "
                f"Ambient {ambient_c:.1f}°C (live probe)"
                + (live.note((time.time() - start_time) / 3600, ambient_c) if live else '')
            )
        else:
            reason = (meta or {}).get('reason') or api.last_reject_reason or 'not a live probe'
            info['logs'].append(f'⚠️ Skipping MEATER sample — {reason}.')
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
    """Modes 2, 3 and 5 — MEATER real-time analysis (background)."""
    info = _bind_job(task_id)
    if info is None:
        return
    model, err = _resolve_model(model_id)
    if err:
        _model_unavailable(info, err)
        return
    info['logs'].append('🔐 Authenticating...')
    info['status'] = 'authenticating'

    api = EnhancedMeaterAPI()
    if not api.authenticate(email, password):
        msg = _meater_auth_error(api)
        info['logs'].append(f'❌ {msg}')
        info['status'] = 'error'
        info['result'] = {'error': msg}
        return

    info['logs'].append('✅ Authenticated. Searching for devices...')
    info['status'] = 'searching_devices'

    device_id = api.find_device(log=info['logs'].append, should_stop=_stop_check(task_id))
    if not device_id:
        info['logs'].append('⚠️ No MEATER devices found.')
        info['status'] = 'error'
        info['result'] = {'error': 'No MEATER devices found. ' + MEATER_NOT_LISTED_HELP}
        return

    info['logs'].append(f'📡 Collecting data from device {device_id[:8]}...')
    info['status'] = 'collecting'

    temp_data = api.collect_temperature_data_realtime(
        device_id=device_id,
        duration_hours=duration_hours,
        interval_seconds=max(interval_seconds, 2),
        model=model,
        log=info['logs'].append,
        should_stop=_stop_check(task_id),
    )
    _note_if_stopped(info, task_id, temp_data)

    if temp_data is None:
        info['logs'].append('❌ Failed to collect temperature data.')
        info['status'] = 'error'
        info['result'] = {'error': 'Failed to collect temperature data.'}
        return

    _finish_analysis(info, temp_data, 'MEATER_REALTIME', mode_name, model=model)


def _finish_analysis(
    info, temp_data, data_source, mode_name, model_id=DEFAULT_MODEL_ID, model=None,
):
    """Run the growth model on a collected temperature series and store the plot.

    Pass ``model`` to reuse the instance built before collection.
    """
    if model is None:
        model, err = _resolve_model(model_id)
        if err:
            _model_unavailable(info, err)
            return

    if len(temp_data['time_hours']) < 2:
        msg = 'Need at least two temperature readings to simulate growth.'
        info['logs'].append(f'❌ {msg}')
        info['status'] = 'error'
        info['result'] = {'error': msg}
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


def _run_live_test(task_id, label, collect, model_id=None):
    """Mode 1 — quick connection test for USB or Wi-Fi."""
    info = _bind_job(task_id)
    if info is None:
        return
    model = _live_rate_model(model_id)
    info['logs'].append(f'🔍 Testing {label}...')
    info['status'] = 'testing'

    temp_data = collect(
        duration_hours=30 / 3600,
        interval_seconds=2,
        log=info['logs'].append,
        model=model,
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
    """Modes 2, 3 and 5 — collect device temperatures and run the growth model."""
    info = _bind_job(task_id)
    if info is None:
        return
    model, err = _resolve_model(model_id)
    if err:
        _model_unavailable(info, err)
        return
    info['logs'].append(f'📡 Collecting data from {label}...')
    info['status'] = 'collecting'

    temp_data = collect(
        duration_hours=duration_hours,
        interval_seconds=max(interval_seconds, 1),
        log=info['logs'].append,
        model=model,
        should_stop=_stop_check(task_id),
    )
    _note_if_stopped(info, task_id, temp_data)

    if temp_data is None:
        info['logs'].append('❌ Failed to collect temperature data.')
        info['status'] = 'error'
        info['result'] = {'error': f'Failed to collect temperature data from {label}.'}
        return

    _finish_analysis(info, temp_data, data_source, mode_name, model=model)


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
    if session.get('authenticated'):
        return redirect(url_for('dashboard'))
    if request.method == 'GET':
        return render_template('login.html', active_tab='signin')

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    if not email or not password:
        flash('Email and password are required.', 'error')
        return redirect(url_for('login'))

    if verify_login(email, password):
        session['authenticated'] = True
        session['email'] = email.lower()
        session['password'] = password  # used later for optional MEATER analysis
        flash('Signed in successfully!', 'success')
        return redirect(url_for('dashboard'))

    flash('Authentication failed. Please check your email and password.', 'error')
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Create profile tab — new dashboard account."""
    if session.get('authenticated'):
        return redirect(url_for('dashboard'))
    if request.method == 'GET':
        return render_template('login.html', active_tab='register')

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')
    access_code = request.form.get('access_code', '').strip()

    if password != confirm:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('register'))
    try:
        create_profile(name, email, password, access_code)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('register'))

    session['authenticated'] = True
    session['email'] = email.lower()
    session['password'] = password
    flash('Profile created. You are signed in.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Reset password using email + lab access code (no email server required)."""
    if session.get('authenticated'):
        return redirect(url_for('dashboard'))
    if request.method == 'GET':
        return render_template('forgot_password.html')

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')
    access_code = request.form.get('access_code', '').strip()

    if password != confirm:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('forgot_password'))
    try:
        reset_password(email, password, access_code)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('forgot_password'))

    flash('Password updated. Sign in with your new password.', 'success')
    return redirect(url_for('login'))


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been signed out.', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    owner = (session.get('email') or '').lower()
    jobs = [_with_data_watch(job_summary(job)) for job in list_jobs(owner)]
    return render_template('dashboard.html', jobs=jobs)


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


def _public_app_base() -> str:
    """HTTPS base URL for browser → server callbacks (Render / tunnel / local)."""
    env = (os.environ.get('PUBLIC_BASE_URL') or os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
    if env:
        return env
    # Prefer the host the browser used (works behind Cloudflare / Render proxies).
    proto = (request.headers.get('X-Forwarded-Proto') or request.scheme or 'https').split(',')[0].strip()
    host = (request.headers.get('X-Forwarded-Host') or request.host or '').split(',')[0].strip()
    if host:
        return f'{proto}://{host}'.rstrip('/')
    return (public_base_url() or request.url_root.rstrip('/'))


@app.route('/thermoworks/appcheck')
@login_required
def thermoworks_appcheck_page():
    """Popup page that mints Firebase App Check in the visitor's browser."""
    bridge_id = request.args.get('bridge_id') or create_bridge()
    base = _public_app_base()
    return render_template(
        'thermoworks_appcheck.html',
        bridge_id=bridge_id,
        submit_url=f'{base}/api/thermoworks/appcheck',
        status_url=f'{base}/api/thermoworks/appcheck/status',
        return_url=f'{base}/thermoworks/appcheck?done=1&bridge_id={bridge_id}',
        done=request.args.get('done') == '1',
    )


@app.route('/api/thermoworks/appcheck', methods=['GET', 'POST', 'OPTIONS'])
def thermoworks_appcheck_submit():
    """Store a browser-minted App Check token (session or bridge_id)."""
    if request.method == 'OPTIONS':
        response = app.make_response(('', 204))
        response.headers['Access-Control-Allow-Origin'] = 'https://cloud.thermoworks.com'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept'
        response.headers['Access-Control-Max-Age'] = '86400'
        return response

    if request.method == 'GET':
        if not session.get('authenticated'):
            return jsonify({'error': 'Please sign in again.', 'ready': False}), 401
        bridge_id = request.args.get('bridge_id', '').strip()
        if bridge_id:
            return jsonify(bridge_status(bridge_id))
        return jsonify(appcheck_status())

    payload = request.get_json(silent=True) or {}
    token = (payload.get('token') or '').strip()
    ttl = payload.get('ttl') or '3600s'
    bridge_id = (payload.get('bridge_id') or '').strip()

    try:
        if bridge_id:
            ttl_seconds = complete_bridge(bridge_id, token, ttl)
        else:
            if not session.get('authenticated'):
                return jsonify({'error': 'Please sign in again.'}), 401
            ttl_seconds = store_browser_token(token, ttl)
    except ValueError as exc:
        response = jsonify({'error': str(exc), 'ok': False})
        response.status_code = 400
        response.headers['Access-Control-Allow-Origin'] = 'https://cloud.thermoworks.com'
        return response

    response = jsonify({'ok': True, 'expires_in': int(ttl_seconds)})
    # Allow the ThermoWorks console fallback script to POST the token.
    response.headers['Access-Control-Allow-Origin'] = 'https://cloud.thermoworks.com'
    return response


@app.route('/api/thermoworks/appcheck/status')
@login_required
def thermoworks_appcheck_status():
    """Poll whether browser App Check completed for this session/bridge."""
    bridge_id = request.args.get('bridge_id', '').strip()
    if bridge_id:
        return jsonify(bridge_status(bridge_id))
    return jsonify(appcheck_status())


@app.route('/api/thermoworks/appcheck/bridge', methods=['POST'])
@login_required
def thermoworks_appcheck_bridge():
    """Create a bridge id used by the App Check popup / console fallback."""
    return jsonify({'bridge_id': create_bridge()})


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
        message = str(exc)
        status = 503 if (
            'App Check' in message or 'Chrome' in message or 'browser' in message.lower()
        ) else 401
        return jsonify({'error': message, 'devices': []}), status


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

    if mode in ('2', '3', '4', '5'):
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

    elif mode == '1' or mode in LIVE_RUNS:
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

        # Collection window by mode (simulation after collect is usually short).
        if mode == '1':
            duration_seconds = 30
            mode_label = 'Quick connection test'
        else:
            run_hours, run_interval, run_name = LIVE_RUNS[mode]
            mode_label = {
                '2': 'Short analysis',
                '3': 'Full analysis',
                '5': 'Continuous monitoring',
            }[mode]
            # 0 marks an open-ended run: no countdown, ends when Stop is pressed.
            duration_seconds = 0 if mode == '5' else int(run_hours * 3600)

        task_id = str(uuid.uuid4())
        owner = (session.get('email') or email or '').lower()
        source_label = {
            'arduino_usb': 'Arduino USB',
            'arduino_wifi': 'Arduino Wi‑Fi',
            'arduino_push': 'Arduino Push',
            'signals': SIGNALS_SOURCE,
            'meater': 'MEATER',
        }.get(source, source or 'MEATER')

        def device_run(label, data_source, collect):
            """Quick test or a LIVE_RUNS analysis for one non-MEATER source."""
            if mode == '1':
                return _run_live_test, (task_id, label, collect, model_id)
            return _run_live_analysis, (
                task_id, label, data_source, run_hours, run_interval, run_name,
                collect, model_id,
            )

        if source == 'arduino_usb':
            label = f'Arduino USB on {port}'

            def collect_usb(**kwargs):
                return collect_temperature_data(port, **kwargs)

            target, args = device_run(label, 'ARDUINO', collect_usb)
        elif source == 'arduino_wifi':
            label = f'Arduino WiFi at {wifi_host}'

            def collect_wifi(**kwargs):
                return collect_wifi_temperature_data(wifi_host, **kwargs)

            target, args = device_run(label, 'ARDUINO_WIFI', collect_wifi)
        elif source == 'arduino_push':
            label = f'Arduino Push {push_device_id or "(any device)"}'

            def collect_push(**kwargs):
                return collect_push_temperature_data(
                    device_id=push_device_id or None,
                    **kwargs,
                )

            target, args = device_run(label, 'ARDUINO_PUSH', collect_push)
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

            target, args = device_run(label, 'SIGNALS', collect_signals)
        else:
            label = 'MEATER Cloud'
            if mode == '1':
                target, args = _run_mode1, (task_id, email, password, model_id)
            else:
                target, args = _run_mode2_3, (
                    task_id, email, password, run_hours, run_interval, run_name, model_id,
                )

        job = create_job(
            task_id,
            owner=owner,
            mode_label=mode_label,
            duration_seconds=duration_seconds,
            label=label,
            source=source_label,
            # Quick test samples every 2 s (see _run_live_test).
            interval_seconds=2 if mode == '1' else run_interval,
        )
        background_tasks[task_id] = job

        threading.Thread(target=target, args=args, daemon=True).start()
        flash(
            'Run started in the background. You can return to the dashboard and open it anytime from Your runs.',
            'info',
        )
        return redirect(url_for('task_status_page', task_id=task_id))

    else:
        flash('Invalid analysis mode selected.', 'error')
        return redirect(url_for('dashboard'))


def _job_owned_by_session(task) -> bool:
    owner = (task.get('owner') or '').lower()
    email = (session.get('email') or '').lower()
    return bool(owner) and owner == email


@app.route('/status/<task_id>')
@login_required
def task_status_page(task_id):
    """Render the status-polling page for a background task."""
    task = _bind_job(task_id)
    if not task or not _job_owned_by_session(task):
        flash('Run not found.', 'error')
        return redirect(url_for('dashboard'))

    if task['status'] in ('done', 'error'):
        result = task.get('result') or {}
        if isinstance(result, dict) and result.get('logs') is None:
            result = dict(result)
            result['logs'] = list(task.get('logs') or [])
        if 'error' in result:
            return render_template(
                'results.html',
                error=result['error'],
                mode_name=result.get('mode_name') or task.get('mode_label') or 'Analysis',
                task_id=task_id,
            )
        return render_template('results.html', task_id=task_id, **result)

    return render_template(
        'status.html',
        task_id=task_id,
        status=task['status'],
        logs=list(task['logs'])[-STATUS_LOG_LINES:],
        mode_label=task.get('mode_label') or '',
        label=task.get('label') or '',
        continuous=int(task.get('duration_seconds') or 0) == 0,
        stop_pending=stop_requested(task_id),
    )


# Status polls send only the newest log lines: a continuous run can collect for
# days, and the page refreshes every 2 seconds. The full log stays in the job file.
STATUS_LOG_LINES = 500


@app.route('/api/status/<task_id>')
@login_required
def api_task_status(task_id):
    """JSON endpoint polled by the status page."""
    task = _bind_job(task_id)
    if not task or not _job_owned_by_session(task):
        return jsonify({'error': 'not_found'}), 404

    started_at = float(task.get('started_at') or time.time())
    duration_seconds = int(task.get('duration_seconds') or 0)
    elapsed = max(0.0, time.time() - started_at)
    remaining = max(0, int(duration_seconds - elapsed)) if duration_seconds else None
    if duration_seconds > 0:
        progress_pct = min(95.0, (elapsed / duration_seconds) * 100.0)
    else:
        progress_pct = 10.0
    if task['status'] == 'simulating':
        remaining = 0
        progress_pct = 97.0
    if task['status'] in ('done', 'error'):
        remaining = 0
        progress_pct = 100.0

    all_logs = list(task.get('logs') or [])
    return jsonify({
        'status': task['status'],
        'logs': all_logs[-STATUS_LOG_LINES:],
        'logs_total': len(all_logs),
        'continuous': duration_seconds == 0,
        'stop_requested': stop_requested(task_id),
        'done': task['status'] in ('done', 'error'),
        'mode_label': task.get('mode_label') or '',
        'label': task.get('label') or '',
        'started_at': started_at,
        'duration_seconds': duration_seconds,
        'elapsed_seconds': int(elapsed),
        'remaining_seconds': remaining,
        'progress_pct': round(progress_pct, 1),
    })


@app.route('/api/stop/<task_id>', methods=['POST'])
@login_required
def api_stop_task(task_id):
    """Stop collecting for a run; the runner then simulates what it has."""
    task = _bind_job(task_id)
    if not task or not _job_owned_by_session(task):
        return jsonify({'error': 'not_found'}), 404
    if task['status'] in ('done', 'error'):
        return jsonify({'ok': True, 'already_finished': True})
    request_stop(task_id)
    return jsonify({'ok': True})


@app.route('/api/jobs')
@login_required
def api_jobs():
    """JSON list of this user's runs for the dashboard panel."""
    owner = (session.get('email') or '').lower()
    return jsonify({'jobs': [_with_data_watch(job_summary(job)) for job in list_jobs(owner)]})


# A collecting run counts as "not sending data" once nothing new has arrived for
# STALL_INTERVALS sampling intervals, and never sooner than STALL_MIN_SECONDS so
# one slow cloud reply is not reported. static/run_watch.js shows the alert.
STALL_INTERVALS = 4
STALL_MIN_SECONDS = 120
SIGNALS_SOURCE = 'ThermoWorks Signals'


def _stall_after_seconds(summary) -> float:
    interval = float(summary.get('interval_seconds') or 0) or 30.0
    limit = max(STALL_INTERVALS * interval, STALL_MIN_SECONDS)
    if summary.get('source') == SIGNALS_SOURCE and signals_uses_sidecar():
        # The sidecar hands back readings in chunks, not one at a time.
        limit = max(limit, SIDECAR_CHUNK_HOURS * 3600 + 180)
    return limit


def _with_data_watch(summary) -> dict:
    """Add data-watch fields to a job summary.

    stalled: collecting, not stopping, and no new reading for stall_after_seconds
    (counted from the start of the run until the first reading arrives).
    needs_appcheck: a running ThermoWorks run that relies on browser-minted App
    Check tokens, so open pages should keep the token renewed.
    """
    now = time.time()
    since = now - float(summary.get('last_reading_at') or summary.get('started_at') or now)
    stall_after = _stall_after_seconds(summary)
    collecting = summary.get('status') == 'collecting' and not stop_requested(summary['task_id'])
    summary['seconds_since_data'] = int(max(since, 0))
    summary['stall_after_seconds'] = int(stall_after)
    summary['stalled'] = bool(collecting and since > stall_after)
    summary['needs_appcheck'] = bool(
        summary.get('running')
        and summary.get('source') == SIGNALS_SOURCE
        and not signals_uses_sidecar()
    )
    return summary


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
