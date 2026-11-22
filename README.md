# Microbial growth analyzer

This folder is a Flask web app that takes a temperature series and runs a Baranyi-Roberts growth model on it. Temperature can come from a MEATER probe, a ThermoWorks Signals device, an Arduino, or a built-in sample wave.

Start here, then read:

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) explains how a run works and how each device sends data.
- [docs/ARDUINO_SETUP.md](docs/ARDUINO_SETUP.md) is how to wire a DS18B20, what to install, which port is which, and the sketches to paste into the Arduino IDE.
- [docs/CONNECT_THERMOMETERS.md](docs/CONNECT_THERMOMETERS.md) is how to attach a MEATER, a ThermoWorks Signals unit, and the Chrome extension.
- [docs/FILES.md](docs/FILES.md) says what every file in this folder is for.

Each source file also has a comment at the top for someone reading the code.

## Run the dashboard on this computer

From this directory, with the packages in `requirements.txt` installed:

```bash
python app.py
```

Open `http://127.0.0.1:5000`. Sign in with a dashboard account. New accounts need the lab access code (`LAB_ACCESS_CODE`, or `uga-microbial-lab` if that variable is unset).

Port 5000 is also what an Arduino push sketch and `scripts/start_push_tunnel.sh` expect.

## What you do in the browser

1. Choose a bacteria and a food. Only rows marked Ready can be simulated.
2. Choose where the temperature comes from.
3. Choose a run: about 30 seconds (device check only), about 6 minutes, about 8 hours, or the sample wave (no device).

Live runs continue after you leave the status page. Open them again from Your runs.

## Before you hand this folder to someone else

`example_usage.py` contains a MEATER email and password in the source. The Arduino sketches contain Wi-Fi settings. `local_users.json` holds password hashes and is listed in `.gitignore`. Replace or omit those before you share a copy.
