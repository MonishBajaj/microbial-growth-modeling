# ThermoWorks on Render (browser App Check — preferred)

ThermoWorks requires a Firebase **App Check** token from reCAPTCHA Enterprise.
Their reCAPTCHA key only works on `cloud.thermoworks.com`, so a normal webpage on
Render **cannot** mint it silently. Use either:

1. **Chrome helper extension** (automatic after one install), or
2. Manual Console paste (fallback), or
3. Lab-PC sidecar (below)

```text
Browser (+ optional Chrome helper) → Render dashboard → ThermoWorks Cloud
```

## Fully automatic (recommended): Chrome helper

1. On your PC open Chrome → `chrome://extensions` → Developer mode → **Load unpacked**
2. Select `chrome_extension/thermoworks_appcheck` from this repo
3. Open your Render URL → ThermoWorks Signals → **Refresh**
4. Allow the popup; ThermoWorks opens and the helper sends App Check back by itself

See `chrome_extension/thermoworks_appcheck/README.md`.

## Manual fallback (no extension)

1. Open your Render URL and sign in.
2. ThermoWorks Signals → email/password → **Refresh**
3. In the popup, script is copied and ThermoWorks opens.
4. On that ThermoWorks tab: **F12 → Console → paste → Enter**
5. When success appears, the dashboard continues.

Tokens are cached ~1 hour, so you usually only do this once per session.

Routes used:

| Path | Purpose |
|---|---|
| `/thermoworks/appcheck` | Popup mint page |
| `/api/thermoworks/appcheck` | Accept browser token (also CORS for console fallback) |
| `/api/thermoworks/appcheck/status` | Poll until token is ready |
| `/api/thermoworks/appcheck/bridge` | One-time bridge id for popup ↔ dashboard |

No new Render env vars are required for this path.

---

# Optional: lab-PC sidecar (legacy)

Only needed if you prefer Chrome on a lab machine instead of the visitor browser.

```text
Browser → Render dashboard → lab PC sidecar (Chrome App Check) → ThermoWorks Cloud
```

## 1. On the lab PC (desktop session)

```bash
cd microbial_growth_modeling
./scripts/start_thermoworks_sidecar.sh
```

Copy the printed **Public URL** and **Secret**.

Leave the machine on (do not sleep). A Chrome window may open briefly when
someone loads Signals devices or starts a collect.

## 2. On Render

**Environment** variables:

| Name | Value |
|---|---|
| `THERMOWORKS_SIDECAR_URL` | `https://….trycloudflare.com` from the script |
| `THERMOWORKS_SIDECAR_SECRET` | same as lab PC (`thermoworks-sidecar-secret` by default) |

Redeploy / restart the Render service after saving.

## 3. Use the site

1. Open your Render URL and sign in.
2. **ThermoWorks Signals** → enter ThermoWorks Cloud email/password → **Refresh**.
3. Pick device/channel → run analysis.

## Notes

- Cloudflare **quick tunnels** change URL when restarted. After re-running the
  script, update `THERMOWORKS_SIDECAR_URL` on Render.
- For a fixed hostname, use a named Cloudflare tunnel or expose the lab PC
  another stable way, still pointing at port `5055`.
- Local dashboard without sidecar still works (Chrome on that same PC).
- Set `THERMOWORKS_FORCE_LOCAL=1` on the sidecar process (the start script does).
- Prefer browser App Check (top of this file) when you do not want any local bind.
