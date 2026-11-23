# ThermoWorks App Check Helper v1.3.0

What the token is used for, and the lab-PC sidecar alternative, are in [docs/USER_GUIDE.md](../../docs/USER_GUIDE.md) under "ThermoWorks Signals".

Opening ThermoWorks does **not** fill Render by itself. This helper mints App Check and **POSTs** the token to your dashboard.

## Critical setup

1. **Ad blockers** (uBlock, AdGuard, Brave shields, etc.) must allow:
   - `cloud.thermoworks.com`
   - `*.googleapis.com` / Firebase  
   Your console showed `ERR_BLOCKED_BY_CLIENT` — that blocks reCAPTCHA, so minting fails.
2. Install from this folder only. If you see CSP errors about `thermoworks_content.js`, you still have an **old** install.

## Clean install

1. `chrome://extensions`
2. On the helper → **Remove**
3. Developer mode → **Load unpacked** → this folder
4. Confirm version **1.3.0** and **no Errors**
5. Open Render dashboard in **this Chrome** → Signals → **Refresh**

## What success looks like

Popup briefly hits ThermoWorks login → returns to Success → Device dropdown fills (use channel 4 if that probe is live).
