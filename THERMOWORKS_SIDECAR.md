# ThermoWorks on Render (browser App Check — preferred)

ThermoWorks requires a Firebase **App Check** token from reCAPTCHA Enterprise.
Render has no desktop Chrome, so the dashboard mints the token in **your browser**
instead of needing a lab PC.

```text
Browser (App Check popup) → Render dashboard → ThermoWorks Cloud
```

## How to use (no lab PC)

1. Open your Render URL and sign in.
2. Choose **ThermoWorks Signals**, enter ThermoWorks Cloud email/password.
3. Click **Refresh** (or Run analysis). A popup opens for App Check.
4. Allow popups if the browser blocks them.
5. If automatic mint fails (common — reCAPTCHA is often locked to ThermoWorks’
   domain), use the popup fallback:
   - Open ThermoWorks Cloud
   - Copy the capture script → paste in that tab’s DevTools Console → Enter
6. When the popup shows success, device list / analysis continues on Render.

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
