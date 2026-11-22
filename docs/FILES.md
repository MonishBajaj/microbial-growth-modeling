# What each file does

Paths are relative to the `microbial_growth_modeling` directory, the one that contains `app.py`. Virtual environments (`.venv/`, `venv/`) and `__pycache__/` are installed packages and bytecode. They are not part of the program you edit.

Generated or secret files that `.gitignore` already excludes: `local_users.json`, `job_store/`, `public_base_url.txt`, `thermoworks_sidecar_url.txt`.

## How to read the tree

`app.py` is the only process the browser talks to. It imports the collectors and the model. Collectors do not import each other except `arduino_wifi.py`, which reuses the Celsius parser from `arduino_serial.py`. The model imports the catalog. Templates are HTML. `static/style.css` is the only stylesheet.

## Setup guides

| File | Responsibility |
|---|---|
| `docs/USER_GUIDE.md` | How a signed-in run moves from the form to the plot, and the HTTP each source sends. |
| `docs/ARDUINO_SETUP.md` | What to install, how to wire the DS18B20, what each port number means, and the sketches to paste into the Arduino IDE. |
| `docs/CONNECT_THERMOMETERS.md` | MEATER Cloud sign-in, ThermoWorks Signals, and how to load the Chrome extension. |
| `docs/README.md` | Points at those guides. |
| `README.md` | Short start at the project root. |

## Web application

| File | Responsibility |
|---|---|
| `app.py` | Flask routes, login gate, background threads for modes 1 to 3, the sample-data mode, the plot, and the status JSON. Binds `0.0.0.0:5000` when started directly. |
| `requirements.txt` | Python packages to install: numpy, scipy, matplotlib, requests, flask, pyserial, zeroconf, thermoworks-cloud, aiohttp, gunicorn. |
| `.gitignore` | Tells git to skip the account file, job JSON, tunnel URL files, both virtualenvs, and bytecode. |

### Routes in `app.py`

| Route | Responsibility |
|---|---|
| `GET /` | Sends an anonymous visitor to login, or a signed-in visitor to the dashboard. |
| `GET/POST /login` | Renders `login.html` and checks `local_accounts.verify_login`. |
| `GET/POST /register` | Creates a profile when the lab access code matches. |
| `GET/POST /forgot-password` | Resets a password with the same code. Sends no email. |
| `GET /logout` | Clears the session. |
| `GET /dashboard` | Renders the three-step form and the current user's jobs. |
| `POST /analyze` | Starts a run from `model_id`, `source`, and `mode`. |
| `GET /status/<task_id>` | Progress page, or the results page once the job has finished. Owner must match the session. |
| `GET /api/status/<task_id>` | JSON polled by the progress page. |
| `GET /api/jobs` | JSON list for the Your runs panel. |
| `GET /api/models` | Catalog grouped by bacterium for the two dropdowns. |
| `GET /api/arduino/ports` | USB serial ports on this computer. |
| `GET /api/arduino/wifi` | Boards announcing `_microbial._tcp`, plus an optional `host` lookup. |
| `POST /api/arduino/ingest` | Celsius JSON from a board. Token check, no browser session. |
| `GET /api/arduino/push_status` | Latest push devices, ingest URL, and token for the dashboard panel. |
| `POST /api/signals/devices` | ThermoWorks device list for the Signals panel. |
| `GET /thermoworks/appcheck` | Popup page that starts App Check minting. |
| `GET/POST /api/thermoworks/appcheck` | Stores a browser token, or reports bridge status. POST allows the ThermoWorks origin. |
| `GET /api/thermoworks/appcheck/status` | Poll used by the popup and the dashboard. |
| `POST /api/thermoworks/appcheck/bridge` | Mints a one-time bridge id. |

## Accounts and saved runs

| File | Responsibility |
|---|---|
| `local_accounts.py` | Loads and saves dashboard users, checks the lab access code, hashes passwords, and merges the three seed accounts. |
| `local_users.json` | The account file on disk. Email to `{name, password_hash}`. Do not commit it and do not put it in a public zip. |
| `job_store.py` | `JobRecord` and `JobLogs`. Writes one JSON file per run so another worker, or a later page load, can see status and the plot. |
| `job_store/` | Directory of those JSON files. One file per `task_id`. Run data, not source. |

## Growth model and catalog

| File | Responsibility |
|---|---|
| `pmp_catalog.py` | Every bacterium and food the menu can show. Ready entries hold coefficients. Pending entries hold a reason and `coeffs: null`. `get_model`, `list_models_for_api`, and `require_ready` are the functions other modules call. |
| `corrected_microbial_growth_model.py` | The integrator the web app runs. One-minute grid, cubic spline, Runge-Kutta for Q and for log population. `secondary_model` implements `legacy_quadratic` and `ratkowsky_sqrt_egr`. |
| `microbial_growth_model.py` | Older class with the Pseudomonas numbers fixed inside `__init__`. Growth rate is forced to 0 below 15 C. Used by `example_usage.py` only. |
| `test_model_catalog.py` | Prints PASS/FAIL for catalog honesty, the Pseudomonas regression, Juneja table checks, the Bacillus cereus test set, and the direction of two cooling profiles. No network and no hardware. |

## MEATER

| File | Responsibility |
|---|---|
| `enhanced_meater_api.py` | Client the web app uses. Login, device list, realtime read, stale-sample filter, and `collect_temperature_data_realtime`. |
| `meater_api.py` | Earlier client with a 30-second delay and no stale-sample filter. Imported by `example_usage.py`. |
| `example_usage.py` | Terminal demo of `meater_api.py` plus `microbial_growth_model.py`, including a sample-wave option. Contains a hardcoded MEATER login. Replace that login before running or sharing. |
| `enhanced_example_usage.py` | Terminal demo of the enhanced MEATER client plus `CorrectedMicrobialGrowthModel`, with its own plot window. The web app does not import it. |

## ThermoWorks

| File | Responsibility |
|---|---|
| `thermoworks_signals.py` | Lists devices and collects one channel. Uses `thermoworks-cloud` locally, or POSTs to the sidecar when `THERMOWORKS_SIDECAR_URL` is set. Puts the chosen channel in `ambient_temperature`. |
| `thermoworks_appcheck.py` | Stores browser-minted App Check tokens (including bridge ids) and, on a desktop, opens Chrome to mint one. Cache file defaults to `/tmp/microbial-thermoworks-appcheck-state.json`. |
| `thermoworks_sidecar_app.py` | Small Flask app for a lab PC. `GET /health`, `POST /v1/devices`, `POST /v1/collect`, authorized by `THERMOWORKS_SIDECAR_SECRET`. Forces local App Check so it will not proxy to itself. |
| `THERMOWORKS_SIDECAR.md` | Short procedure for the Chrome helper and for the lab-PC sidecar, including the Render environment variables. |
| `thermoworks_sidecar_url.txt` | Last Cloudflare origin written by `scripts/start_thermoworks_sidecar.sh`. Changes when the quick tunnel restarts. Gitignored. |
| `scripts/start_thermoworks_sidecar.sh` | Kills an old sidecar, starts `thermoworks_sidecar_app.py` on port 5055, waits for `/health`, starts `cloudflared`, prints the public URL and secret. |

### Chrome helper

Directory: `chrome_extension/thermoworks_appcheck/`. Load this folder in Chrome as an unpacked extension. Version in the manifest is 1.2.0.

| File | Responsibility |
|---|---|
| `manifest.json` | Manifest v3. Permissions: storage, tabs, scripting. Host access for ThermoWorks, Render, Firebase App Check, and localhost. |
| `background.js` | Service worker. Saves a 15-minute job, opens `cloud.thermoworks.com`, mints the token in the page, POSTs it to the dashboard `submitUrl`, then returns to `returnUrl`. |
| `dashboard_bridge.js` | Content script on the dashboard origin. Forwards `tw-appcheck-request` window messages to the service worker. |
| `thermoworks_content.js` | Marker left so an older install still has a file of this name. It does not mint. |
| `popup.html` | Toolbar popup. Tells you the installed version and to allow ThermoWorks and Google APIs through ad blockers. |
| `README.md` | Install steps and the ad-blocker failure mode (`ERR_BLOCKED_BY_CLIENT`). |
| `../thermoworks_appcheck.zip` | A packed copy of this extension. The unpacked folder is the one to load while you are changing it. |

## Arduino

| File | Responsibility |
|---|---|
| `arduino_serial.py` | Lists USB serial ports and reads one Celsius line at a time into the shared series dictionary. Baud 9600. Waits 2 seconds after open. |
| `arduino_wifi.py` | Browses `_microbial._tcp`, scans local subnets, and reads the same line protocol over TCP port 8080. |
| `arduino_push.py` | Token check, public URL helpers, the in-memory deque, and collection from that deque during a run. |
| `public_base_url.txt` | Origin written by the push-tunnel script, or by hand. Combined with `/api/arduino/ingest` to form the URL shown in the dashboard. Gitignored. |
| `scripts/start_push_tunnel.sh` | Starts `app.py` and a Cloudflare quick tunnel to port 5000, then writes `public_base_url.txt`. |
| `arduino/temperature_sensor/temperature_sensor.ino` | UNO R4 WiFi sketch for USB serial and for the on-LAN TCP/mDNS server. DS18B20 on pin 2. Contains Wi-Fi settings. |
| `arduino/temperature_push/temperature_push.ino` | UNO R4 WiFi sketch that POSTs JSON to `/api/arduino/ingest`. Contains Wi-Fi settings and `SERVER_HOST`. |
| `arduino/temperature_push/README.md` | Short push setup: libraries, tunnel script, and the fields to edit in the sketch. |

Libraries the sketches expect from the Arduino Library Manager: OneWire and DallasTemperature for both; ArduinoMDNS for the sensor sketch; ArduinoHttpClient (and the board's WiFiS3 / WiFiSSLClient) for the push sketch.

## Pages

Jinja templates. `base.html` is the shell. The others extend it, except `thermoworks_appcheck.html`, which is a small standalone popup.

| File | Responsibility |
|---|---|
| `templates/base.html` | Navbar, flashed messages, loading overlay, and the block where each page puts its content and scripts. |
| `templates/login.html` | Sign-in and create-profile tabs. |
| `templates/forgot_password.html` | Reset form: email, new password, lab access code. |
| `templates/dashboard.html` | Your runs, the three steps, and the browser script that fills models, ports, Wi-Fi boards, push status, and Signals devices. |
| `templates/status.html` | Progress bar and log. Polls `/api/status/<task_id>`. |
| `templates/results.html` | Error card, or the PNG, the stat cards, and the log. |
| `templates/thermoworks_appcheck.html` | Page that asks the helper or the console fallback to POST an App Check token for its `bridge_id`. |
| `static/style.css` | All visual rules for those pages: colors, step cards, source cards, job rows, login card, results grid. The app does not load `DESIGN.md`. |

## Older notes and outputs

| File | Responsibility |
|---|---|
| `microbial-growth-python.md` | Early writeup of the MATLAB-to-Python model and the MEATER client. The file tree at the bottom names modules that are not in this directory. The current behavior is `docs/USER_GUIDE.md`. |
| `DESIGN.md` | IBM Carbon token sheet (colors, type, buttons). Not imported by the app. The pages use `static/style.css`. |
| `microbial_growth_results.png` and `microbial_growth_results_*.png` | Plots saved from earlier command-line runs (dates in the filenames are in September 2025). The web app does not open them. |

## What talks to what

```text
Browser
  templates/*.html  +  static/style.css
        |  form POST /analyze, GET /api/...
        v
     app.py  ---- local_accounts.py ---- local_users.json
        |  \---- job_store.py -------- job_store/*.json
        |
        +-- enhanced_meater_api.py -------- MEATER Cloud HTTPS
        +-- thermoworks_signals.py
        |     +-- thermoworks_appcheck.py   (token from browser or local Chrome)
        |     +-- optional thermoworks_sidecar_app.py on port 5055
        +-- arduino_serial.py ------------- USB serial, 9600 baud
        +-- arduino_wifi.py --------------- TCP :8080 and mDNS
        +-- arduino_push.py <------------- POST /api/arduino/ingest
        |
        +-- corrected_microbial_growth_model.py
              +-- pmp_catalog.py
```

The Arduino sketches are the programs on the board. They are not imported by Python. `temperature_sensor.ino` is the other end of `arduino_serial.py` and `arduino_wifi.py`. `temperature_push.ino` is the other end of `POST /api/arduino/ingest`.
