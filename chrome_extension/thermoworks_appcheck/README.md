# ThermoWorks App Check Helper (Chrome) v1.1

Opening ThermoWorks alone does **not** fill the Render dashboard. This helper must:

1. Mint App Check on `cloud.thermoworks.com`
2. **POST** the token to your Render app (`/api/thermoworks/appcheck`)
3. Return the popup so Device can load

## Install / update

1. Chrome → `chrome://extensions`
2. Developer mode on
3. If already installed: click **Reload** on this extension (must show **1.1.0**)
4. Or **Load unpacked** → this folder

## Use

1. Open the **Render** dashboard in **this same Chrome**
2. ThermoWorks Signals → **Refresh**
3. Allow the popup — it should stay on ThermoWorks **login** briefly
4. Popup returns to “Success” and Device fills in

If you only see the ThermoWorks “My Account Dashboard” and Device stays **Loading…**, the token never reached Render — Reload the extension to 1.1.0 and try again. Do not stay only on `/home`; the helper needs the login page’s reCAPTCHA.
