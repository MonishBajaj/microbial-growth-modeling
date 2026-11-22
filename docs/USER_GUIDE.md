# User guide

This app predicts a microbial population from a temperature history. You pick a model that already has coefficients, the app collects temperatures for a set length of time, and `corrected_microbial_growth_model.py` integrates that history. The result is a plot of log population and temperature, plus a few summary numbers.

The dashboard login, the MEATER cloud login, and the ThermoWorks cloud login are three different accounts. The first is stored by this app. The other two are sent to those vendors only when you choose that source.

## One run, from click to plot

The dashboard form posts to `POST /analyze` with three choices: `model_id`, `source`, and `mode`.

`app.py` checks that the model is Ready when the mode will actually simulate (modes 2, 3, and 4). It then starts a background thread for modes 1, 2, and 3, writes a job file under `job_store/`, and sends you to `/status/<task_id>`. That page polls `GET /api/status/<task_id>` until the job is `done` or `error`, then shows `templates/results.html`.

Mode 4 does not start a thread. It builds a sine-wave temperature series in the request and renders the plot immediately.

Every live collector returns the same dictionary:

| Field | Meaning |
|---|---|
| `time_hours` | Hours since collection started |
| `ambient_temperature` | The series the growth model integrates |
| `internal_temperature` | Second series, kept so the shape matches MEATER |
| `device_id` | Port, host, push id, MEATER id, or Signals `serial:chN` |
| `readings_count` | How many samples were kept |

`_finish_analysis` in `app.py` calls `simulate_growth(time_hours, ambient_temperature)`. For an Arduino, both temperature arrays are the same DS18B20 reading. For MEATER, ambient and internal are the two probe values, and the model uses ambient. For Signals, the channel you picked is stored as ambient.

The plot is a PNG encoded as base64. Population is the left axis (0 to 10 log CFU/g). Temperature is the right axis. The Pseudomonas baseline also draws the old experimental points. Other models do not.

## Dashboard account

Pages other than login, register, password reset, and the Arduino ingest URL require a session.

| Action | Request | What is checked |
|---|---|---|
| Sign in | `POST /login` with email and password | Hash in `local_users.json` via `local_accounts.verify_login` |
| Create profile | `POST /register` with name, email, password, confirm, access code | Email looks valid, password at least 8 characters, access code matches, email is new |
| Reset password | `POST /forgot-password` with email, new password, confirm, access code | Same code. No mail is sent. A missing email gets the same error text as a bad code |
| Sign out | `GET /logout` | Session is cleared |

The access code is the environment variable `LAB_ACCESS_CODE`. If that is unset, the code is `uga-microbial-lab`.

On a successful sign-in, `app.py` stores the email and the plaintext password in the Flask session. The password is there so a MEATER run can log in to MEATER Cloud with the same pair. ThermoWorks uses separate fields (`tw_email`, `tw_password`) and stores those in the session only after you use Signals.

Seed accounts for three lab emails are merged into `local_users.json` if they are missing. Hashes live in `local_accounts.py`. The file is gitignored.

`app.secret_key` is a new random value every time the process starts, so existing browser sessions die on restart.

## The three dashboard steps

### 1. Model

The page loads `GET /api/models`, which is `pmp_catalog.list_models_for_api()`. You pick a bacterium, then a food. The hidden field `model_id` is what the form submits.

A Ready entry has coefficients and can run. A pending entry is listed so the menu matches USDA PMP Online names, and `require_ready` refuses it. The default id is `pseudomonas_legacy_matlab`.

Ready entries in this tree:

| id | What it is |
|---|---|
| `pseudomonas_legacy_matlab` | Project baseline matched to the old MATLAB run. Temperature floor at 15 C. Experimental points are drawn on the plot. |
| `clostridium_perfringens_cooling_juneja_2001` | Juneja 2001 Ratkowsky EGR for C. perfringens in broth, applied to your measured T(t). |
| `clostridium_botulinum_cooling_juneja_2001` | Same paper, C. botulinum broth rates. |
| `Test_Parameter` | Bacillus cereus growth-from-spores coefficients supplied for this project. Label in the menu is `Test_Parameter`. |

Pending foods (broth polynomials, meat-specific cooling, heat inactivation, survival, transfer) have `coeffs: null`. Do not fill those with guessed numbers. Add a verified table as a new Ready entry. `python test_model_catalog.py` checks the Ready sets and that a known pending id still refuses to run.

### 2. Temperature source

The hidden field `source` is one of `meater` (the default), `signals`, `arduino_push`, `arduino_usb`, or `arduino_wifi`. The panels under the cards only collect the extra fields that source needs: serial port, Wi-Fi address, push device id, or Signals serial and channel.

### 3. Mode

| mode | Label | Duration | Interval | Model |
|---|---|---|---|---|
| 1 | Quick connection test | 30 seconds | 2 seconds | Not run. The job only reports whether readings arrived. |
| 2 | Short analysis | 0.1 hour (6 minutes) | 2 seconds | Run after collection |
| 3 | Full analysis | 8 hours | 60 seconds | Run after collection |
| 4 | Sample data | 0 to 50 hours, one point per hour | none | Run immediately on `25 + 10 * sin(2 * pi * t / 6)` degrees C |

Mode 1 for MEATER uses its own 30-second loop in `_run_mode1`. Mode 1 for Arduino and Signals calls the same collector with `duration_hours = 30/3600`.

Hardware setup, the sketches to paste, and the Chrome extension steps are in [ARDUINO_SETUP.md](ARDUINO_SETUP.md) and [CONNECT_THERMOMETERS.md](CONNECT_THERMOMETERS.md). This section is the request each source sends after that setup is done.

## How each source sends data

### MEATER

No extra form fields. The app uses the dashboard email and password.

1. `EnhancedMeaterAPI.authenticate` sends `POST https://public-api.cloud.meater.com/v1/login` with JSON `{"email", "password"}`.
2. The response token is sent as `Authorization: Bearer` on `GET /v1/devices` and `GET /v1/devices/{id}`.
3. The first device in the list is used. There is no device picker.
4. `extract_live_meater_reading` keeps a sample only when `updated_at` is present and younger than `MEATER_PROBE_MAX_AGE_SEC` (default 90 seconds, minimum 15), and both temperatures are between -40 C and 300 C. Set `MEATER_REQUIRE_COOK=1` if you also want to drop readings that have no active cook.
5. Ambient temperature is what the model sees.

The client waits at least 2 seconds between realtime calls. MEATER's published ceiling is 60 requests per 60 seconds, with 2 per 60 seconds recommended. An 8-hour run at a 60-second interval stays under the ceiling. The short run at 2 seconds is much faster than the recommendation.

`meater_api.py` is the older client. The web app does not import it. Its delay is 30 seconds, and it does not apply the stale-reading check.

### ThermoWorks Signals

The Signals panel posts `POST /api/signals/devices` with the ThermoWorks Cloud email and password. That lists devices. A later analysis posts `source=signals`, `signals_serial`, and `signals_channel` (1 to 4) to `/analyze`.

ThermoWorks rejects email/password sign-in unless the caller also presents a Firebase App Check token. The reCAPTCHA key for that token only works on `https://cloud.thermoworks.com`, so the Flask process cannot mint it by itself on a server with no desktop.

Path A, browser (the one to use on Render):

1. The dashboard opens `/thermoworks/appcheck?bridge_id=...` or asks the Chrome helper to do it.
2. Something running on `cloud.thermoworks.com` executes reCAPTCHA Enterprise with action `fire_app_check`, then exchanges that token at Firebase App Check.
3. The browser `POST`s JSON `{"token", "ttl", "bridge_id"}` to `/api/thermoworks/appcheck`. CORS allows that POST from `https://cloud.thermoworks.com`.
4. `thermoworks_appcheck.py` stores the token in memory and in `/tmp/microbial-thermoworks-appcheck-state.json` (override with `THERMOWORKS_APPCHECK_STATE`) so every gunicorn worker can see it. A bridge id lives about 15 minutes.
5. `thermoworks_signals.py` passes the token into `thermoworks-cloud`, which talks to ThermoWorks Cloud.

The Chrome helper is `chrome_extension/thermoworks_appcheck`. Load that folder unpacked. `dashboard_bridge.js` runs on the dashboard origin and forwards a page message to `background.js`. The service worker reuses the same tab, opens the ThermoWorks login, mints in the page, and POSTs the token to `submitUrl`. Ad blockers that stop `cloud.thermoworks.com` or `*.googleapis.com` prevent the mint. Tokens are reused for about an hour.

Path B, lab PC sidecar (optional):

1. On a machine with a display, `./scripts/start_thermoworks_sidecar.sh` starts `thermoworks_sidecar_app.py` on port 5055 and a Cloudflare quick tunnel.
2. The cloud app has `THERMOWORKS_SIDECAR_URL` set to that tunnel and `THERMOWORKS_SIDECAR_SECRET` set to the same secret (default `thermoworks-sidecar-secret`).
3. Device list becomes `POST {sidecar}/v1/devices` with `Authorization: Bearer <secret>` and JSON `{"email", "password"}`.
4. Collection becomes `POST {sidecar}/v1/collect` with duration, interval, serial, and channel. The sidecar returns the series as JSON lists, and the cloud app turns them back into arrays.
5. The sidecar sets `THERMOWORKS_FORCE_LOCAL=1` so it does not call itself. It opens local Chrome through `get_app_check_token` when it needs a token. `THERMOWORKS_APPCHECK_TOKEN` can supply one directly, with lifetime `THERMOWORKS_APPCHECK_TTL_SECONDS` (default 3000).

A Signals sample is kept only when the channel looks connected and the reading is younger than `THERMOWORKS_PROBE_MAX_AGE_SEC` (default 90 seconds, minimum 15). If you leave serial blank, the collector prefers a device whose type looks like Signals, smoke, RFX, or node, otherwise the first device. A missing channel falls back to the lowest channel number that exists.

`THERMOWORKS_SIDECAR.md` is the same sidecar procedure in shorter form, including the Render environment variables.

### Arduino USB

The board and the computer running Flask share a USB cable. The sketch `arduino/temperature_sensor/temperature_sensor.ino` prints one Celsius value per line at 9600 baud. A comma-separated line uses the first field. Values outside -40 C to 125 C are ignored.

The dashboard calls `GET /api/arduino/ports`. `arduino_serial.list_ports` returns USB serial devices (anything with a USB vendor id, or a name containing `ttyACM`, `ttyUSB`, `usbmodem`, `usbserial`, or `wchusbserial`). You submit `source=arduino_usb` and `port`.

`collect_temperature_data` opens that port, waits 2 seconds because opening the port resets many Arduino boards, then reads until the duration ends. `pyserial` has to be installed. This path only works on the machine that has the cable. A Flask process on Render cannot see your laptop's USB port.

### Arduino on the same Wi-Fi

Same sketch, second behavior. After the board joins Wi-Fi it advertises DNS-SD service `_microbial._tcp` and listens on TCP port 8080. A client that connects receives the same one-number line the USB path prints.

`GET /api/arduino/wifi` returns boards found by zeroconf, and also probes the local IPv4 subnets. `?host=` checks one typed address. The form field is `wifi_host`. The Python default name `arduino-temp.local` is only a fallback. The sketch actually names itself `temp-` plus the last two MAC bytes.

The dashboard computer and the board have to be on a network where that browse and that TCP connection work. A cloud host is the wrong place for this source.

### Arduino push

Use this when the board and the Flask process are not on the same LAN. The board opens the connection. The server never dials the board.

Sketch: `arduino/temperature_push/temperature_push.ino`, aimed at an Arduino UNO R4 WiFi.

Every `POST_EVERY_MS` (3 seconds in the sketch) it sends:

```http
POST /api/arduino/ingest HTTP/1.1
Host: <SERVER_HOST>
Authorization: Bearer <PUSH_TOKEN>
Content-Type: application/json

{"celsius": 23.5, "device_id": "uno-r4-1"}
```

`SERVER_PORT` 443 and `SERVER_USE_TLS` true are for an HTTPS tunnel or a deployed host. For a board on the same LAN as a laptop running `python app.py`, use port 5000 and TLS off. `SERVER_HOST` is the hostname only, with no `https://` and no path.

`app.arduino_ingest` does not require a browser login. It accepts the token as that Bearer header, as JSON `token`, or as `?token=`. The expected value is `ARDUINO_PUSH_TOKEN`, default `microbial-lab-token`. Celsius must be between -40 and 125. `device_id` defaults to `arduino`.

`record_reading` appends to an in-memory deque (20,000 samples) in `arduino_push.py`. When you start a push run, collection reads that deque for the mode's duration. A sample from the previous 15 seconds can seed a quick test. If a new POST does not arrive, a sample younger than about 30 seconds (or three intervals) is repeated so the time grid still fills. Restarting Flask clears the deque.

`GET /api/arduino/push_status` (login required) shows recent devices, the ingest URL, and the current token so you can copy them into the sketch.

`./scripts/start_push_tunnel.sh` starts `app.py` on port 5000, opens a Cloudflare quick tunnel to it, and writes the `https://….trycloudflare.com` origin into `public_base_url.txt`. That hostname changes every time the script runs. Update `SERVER_HOST` in the sketch, or set `PUBLIC_BASE_URL` on a real deploy and leave the sketch pointed at that stable host.

The ingest route is also printed when you start `python app.py` directly.

## What the model does with the series

`CorrectedMicrobialGrowthModel.from_catalog(model_id)` copies coefficients out of `pmp_catalog.MODELS`.

`simulate_growth` then:

1. Requires at least two samples.
2. Builds a time grid with a step of 1 minute (`dth = 1/60` hour) from the first sample to the last.
3. Fits a cubic spline through the coarse temperatures and evaluates it on that grid, then again on a grid twice as fine for the Runge-Kutta stages.
4. Sets the growth rate to 0 outside `[Tmin, Tmax]`, and also below `growth_floor_C` when that coefficient is set (the Pseudomonas entry uses 15 C).
5. Integrates `Q`, the log of the physiological-state variable, from `q0 = 1 / (exp(h0) - 1)`.
6. Integrates `y`, log10 population, from `y0` toward `ymax`, with the Baranyi adjustment factor `1 / (1 + exp(-Q))` and the capacity factor `1 - exp(y - ymax)`.

Two secondary formulas exist:

- `legacy_quadratic`: `a * (T - Tmin)^2 * (1 - exp(b * (T - Tmax)))`. Used by the Pseudomonas baseline and `Test_Parameter`.
- `ratkowsky_sqrt_egr`: `(a * (T - Tmin))^2 * (1 - exp(b * (T - Tmax)))`. Used by the two Juneja 2001 cooling entries. The rate is log10 CFU per hour.

`microbial_growth_model.py` is the earlier single-coefficient class. `example_usage.py` still imports it. The web app does not.

The results page shows final population, minimum and maximum temperature, reading count, duration, the model label, and the citation stored on the catalog entry. Connection-test jobs show whether any reading arrived, the count, and an average, and they have no plot.

## Jobs

`create_job` records owner (your email), status, label, mode, source, start time, and planned duration. Log lines append through `JobLogs`, which rewrites the JSON file. Status values you will see include `starting`, `authenticating`, `searching_devices`, `testing`, `collecting`, `simulating`, `done`, and `error`.

`GET /api/jobs` and the Your runs panel list the latest 30 jobs for the signed-in email. Opening one loads `/status/<task_id>` only if `owner` matches the session email.

The progress bar is elapsed time divided by the planned duration, capped at 95% until simulation, then 97% while simulating, then 100% when finished. It is a clock, not a count of HTTP calls completed.

Job JSON can contain the plot. Treat `job_store/` as run data, not as source code.

## Run it

Install `requirements.txt` (numpy, scipy, matplotlib, requests, flask, pyserial, zeroconf, thermoworks-cloud, aiohttp, gunicorn). Matplotlib is forced onto the `Agg` backend in `app.py` so a server with no display can still write the PNG.

Local:

```bash
python app.py
```

Listens on `0.0.0.0:5000` with the Flask debugger on. That bind is what lets a LAN board reach `/api/arduino/ingest`.

A production process is expected to be gunicorn in front of the same `app` object. Several workers can share jobs and App Check state because both are written to disk. The Arduino push buffer is not on disk, so all ingest traffic and the push collector need to hit the same process.

## Environment variables

| Variable | Default | Used for |
|---|---|---|
| `LAB_ACCESS_CODE` | `uga-microbial-lab` | Create profile and password reset |
| `LOCAL_USERS_FILE` | `local_users.json` next to the code | Account file |
| `JOB_STORE_DIR` | `job_store/` next to the code | Job JSON |
| `PUBLIC_BASE_URL` | empty, else `public_base_url.txt` | Origin shown for Arduino ingest |
| `RENDER_EXTERNAL_URL` | empty | Fallback origin on Render |
| `ARDUINO_PUSH_TOKEN` | `microbial-lab-token` | Bearer token on `/api/arduino/ingest` |
| `MEATER_PROBE_MAX_AGE_SEC` | 90 | Drop older MEATER samples |
| `MEATER_REQUIRE_COOK` | off | Also require an active MEATER cook |
| `THERMOWORKS_SIDECAR_URL` | empty | If set, Signals calls the lab PC instead of Cloud directly |
| `THERMOWORKS_SIDECAR_SECRET` | `thermoworks-sidecar-secret` | Bearer token for the sidecar |
| `THERMOWORKS_SIDECAR_PORT` | 5055 | Sidecar listen port |
| `THERMOWORKS_FORCE_LOCAL` | off (on inside the sidecar) | Ignore `THERMOWORKS_SIDECAR_URL` |
| `THERMOWORKS_APPCHECK_STATE` | `/tmp/microbial-thermoworks-appcheck-state.json` | Shared App Check file |
| `THERMOWORKS_APPCHECK_TOKEN` | empty | Skip Chrome and use this token |
| `THERMOWORKS_APPCHECK_TTL_SECONDS` | 3000 | Lifetime assumed for that token |
| `THERMOWORKS_PROBE_MAX_AGE_SEC` | 90 | Drop older Signals samples |

## Command-line scripts that are not the web app

`example_usage.py` runs the old model. The real-device function in that file has a MEATER login written in the source. Replace it before you run the file, and do not pass the file around with that login still in it.

`enhanced_example_usage.py` uses `EnhancedMeaterAPI` and `CorrectedMicrobialGrowthModel` from a terminal and can draw its own Matplotlib window. The web app does not import it.

`microbial-growth-python.md` is an early description. It names `growth_analyzer.py` and an `examples/` directory that are not in this folder. Use this guide for the current layout.

`DESIGN.md` is an IBM Carbon design-token dump. `static/style.css` is what the pages actually load. Nothing in `app.py` reads `DESIGN.md`.

PNG files named `microbial_growth_results*.png` in the project root are saved plots from earlier runs. The web app generates a new image per job and does not read those files.

## When a run fails

Authentication failed: the dashboard password was sent to MEATER and rejected, or the ThermoWorks email and password were rejected. Those are the vendor accounts, not a bug in the growth math.

No devices: the cloud account has no probe, or the USB port list is empty, or no push sample is in the buffer, or mDNS found nothing and the typed address did not answer on port 8080.

No temperature readings: the probe was stale, the sketch is not printing numbers, or the push token or host is wrong. The job log on the status page is the collector's own lines.

Model unavailable: the food you picked is still pending. Switch to a Ready row.

App Check or Chrome errors on Signals: the browser token never arrived, an ad blocker stopped reCAPTCHA, or the sidecar URL is stale after a tunnel restart. `THERMOWORKS_SIDECAR.md` and `chrome_extension/thermoworks_appcheck/README.md` cover that setup.
