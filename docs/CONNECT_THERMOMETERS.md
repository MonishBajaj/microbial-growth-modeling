# Connect a thermometer

The dashboard has five temperature cards. Three are the Arduino DS18B20 paths, covered in [ARDUINO_SETUP.md](ARDUINO_SETUP.md). The other two are cloud accounts: MEATER Cloud, and ThermoWorks Signals. A household thermostat, a random Bluetooth probe, or a different brand does not appear in the list. It would need its own collector. This page is how to attach the devices the app already knows.

Sign in to the dashboard first (`http://127.0.0.1:5000` if you started it locally). Then pick the card that matches the hardware, then a run mode. Quick connection test checks the device for about 30 seconds and does not run the growth model. Short analysis is about 6 minutes. Full analysis is about 8 hours.

## MEATER

You need a MEATER probe (Plus, Block, or another probe that shows up in MEATER Cloud) and a MEATER Cloud account. The probe has to be paired in the MEATER app and currently reporting. The website does not talk to the probe over Bluetooth. It calls `https://public-api.cloud.meater.com/v1`.

### Match the dashboard login to the MEATER login

This app sends the email and password you used to sign in to the dashboard straight to MEATER. There is no separate MEATER email box on that card.

So the dashboard account and the MEATER Cloud account need the same email and the same password. Create the dashboard profile with the MEATER email, the MEATER password (at least 8 characters), and the lab access code. If those passwords differ, MEATER returns authentication failed even though the dashboard sign-in succeeded.

ThermoWorks does not work this way. It has its own email and password fields.

### What you do in the MEATER app

1. Charge the probe in its charger.
2. Open the MEATER app and sign in to the account you will use on the dashboard.
3. Confirm the probe is online there. A reading that MEATER Cloud has stopped updating will be rejected here. The server keeps a sample only when `updated_at` is present and younger than 90 seconds (`MEATER_PROBE_MAX_AGE_SEC`). Both internal and ambient must be between -40 C and 300 C.
4. Leave the probe reporting during the run. The app uses the first device on the account. There is no device dropdown for MEATER.

### What you do on the dashboard

1. Sign in with that same email and password.
2. Step 1: choose a Ready model. The growth model uses the MEATER ambient temperature, not the tip temperature.
3. Step 2: choose MEATER Cloud. No port, no extension, no extra password.
4. Step 3: Quick connection test.

The status log should show authentication, then a device id, then lines like `Internal …°C, Ambient …°C (live probe)`. `Skipping MEATER sample` with "stale telemetry" means the cloud value is older than 90 seconds. Wake the probe in the MEATER app and run the test again.

No Chrome extension is involved.

## ThermoWorks Signals

You need a ThermoWorks Cloud account at [https://cloud.thermoworks.com](https://cloud.thermoworks.com) and a device that already appears there (Signals, or another Cloud device the account owns). The dashboard asks that cloud for the channel you pick. It does not pair the thermometer by Bluetooth.

The email and password on the Signals card are the ThermoWorks Cloud password. They can be different from the dashboard password. After a successful refresh they are stored in the session as `tw_email` and `tw_password`.

### Why the Chrome extension is required on a hosted site

ThermoWorks will not accept the email and password unless the request also carries a Firebase App Check token. That token is minted by reCAPTCHA on `cloud.thermoworks.com` only. A page on Render cannot mint it. The extension opens ThermoWorks in the same Chrome window, mints the token, and POSTs it to your dashboard.

You need the extension when the website is on Render or any host where you click Signals, Refresh. On a lab computer that runs both Chrome and the Flask app, the server can also open Chrome itself. The extension is still the path the dashboard is built around. Install it if Refresh says App Check, Chrome, or browser.

You do not need the extension for MEATER or for any Arduino card.

### Install the extension

Use Chrome. The folder to load is `chrome_extension/thermoworks_appcheck` in this project. Version in `manifest.json` is 1.2.0.

1. Unzip or copy that folder somewhere stable. Chrome reads it from disk every time it starts. Deleting the folder breaks the extension.
2. Turn off the ad blocker for `cloud.thermoworks.com` and for `*.googleapis.com`, or pause it. If the browser console shows `ERR_BLOCKED_BY_CLIENT`, reCAPTCHA never loads and the mint fails.
3. Open `chrome://extensions`.
4. Turn on Developer mode.
5. If an older helper is listed, click Remove. An old copy causes errors about `thermoworks_content.js`.
6. Click Load unpacked and select the `thermoworks_appcheck` folder (the one that contains `manifest.json`, not the parent `chrome_extension` folder, and not the `.zip` unless you are installing a packed copy on purpose).
7. The card should read ThermoWorks App Check Helper, version 1.2.0, with no errors. The toolbar popup says the same version.

Host access in the manifest covers `cloud.thermoworks.com`, `*.onrender.com`, the Firebase App Check host, `localhost`, and `127.0.0.1`. If your dashboard is on another domain, the extension will not be allowed to post the token until that origin is added to `host_permissions` in `manifest.json` and the extension is reloaded.

### Use Signals after the extension is installed

1. Open the dashboard in that same Chrome. Sign in.
2. Choose ThermoWorks Signals.
3. Enter the ThermoWorks Cloud email and password.
4. Click Refresh.

Refresh opens the helper flow. The tab goes to `https://cloud.thermoworks.com/auth/login`, the extension mints App Check in that page, and it POSTs JSON `{"token", "ttl", "bridge_id"}` to `/api/thermoworks/appcheck` on your dashboard. The tab then comes back. Wait until the Device menu is a list of devices, not "Loading". If it stays on Loading, click Refresh again after the helper finishes. The token is reused for about an hour, so the next run in the same session often skips the popup.

5. Pick the device. If you leave it on the first row, the server prefers a device whose type looks like Signals, smoke, RFX, or node.
6. Pick the channel, 1 to 4. That channel is the temperature the growth model uses. A second channel, when it has a live reading, is stored only as the companion series.
7. Run Quick connection test.

The sample is kept only when the channel looks connected and the reading is younger than 90 seconds (`THERMOWORKS_PROBE_MAX_AGE_SEC`). A probe that Cloud still shows with an old number is skipped. The log says it is not a live probe.

### If you cannot install the extension

A lab PC with a screen can mint the token instead. On that PC:

```bash
./scripts/start_thermoworks_sidecar.sh
```

Leave the PC awake. The script prints a public URL and a secret. On the hosted site set `THERMOWORKS_SIDECAR_URL` to that URL and `THERMOWORKS_SIDECAR_SECRET` to that secret, then restart the site. The quick-tunnel hostname changes when you rerun the script, and the hosted URL has to be updated to match. Details are in `THERMOWORKS_SIDECAR.md`.

Being signed in at cloud.thermoworks.com in a normal tab does not fill the dashboard by itself. The token has to be posted to this app.

## Which card to choose

| You have | Card | Extra software |
|---|---|---|
| MEATER probe on a MEATER Cloud account | MEATER Cloud | MEATER app. Dashboard password must match that account. |
| ThermoWorks Signals (or another device already in ThermoWorks Cloud) | ThermoWorks Signals | Chrome extension on a hosted site. ThermoWorks email and password on the card. |
| DS18B20 on a UNO R4 plugged into this computer | Arduino USB | Arduino IDE and the USB/Wi-Fi sketch. |
| Same board on the same Wi-Fi as this computer | Arduino Wi-Fi | Same sketch. |
| Same sensor, website somewhere else | Arduino Push | The push sketch, plus a public URL. |

After the test shows live readings, Short analysis or Full analysis runs the Ready model on that temperature series.
