# ThermoWorks App Check Helper (Chrome)

After a one-time install, dashboard **Refresh** reuses the **same popup**, switches it to ThermoWorks, mints App Check, and **POSTs the token to your Render server over HTTPS**. No Console paste. No second browser window.

## Install (once)

1. Use **Google Chrome** (the helper only runs there).
2. Open `chrome://extensions`
3. Enable **Developer mode**
4. **Load unpacked** → select this folder:
   `chrome_extension/thermoworks_appcheck`
5. Leave it enabled

## Use

1. Open the Render dashboard **in that same Chrome**
2. ThermoWorks Signals → **Refresh**
3. Allow the popup
4. The popup itself goes to ThermoWorks, then returns — the dashboard continues

## Notes

- The token is sent with a normal `POST /api/thermoworks/appcheck` to Render.
- Tokens are cached about an hour.
- If ThermoWorks opens in another browser, you opened the dashboard there without the helper — switch to the Chrome that has the extension.
