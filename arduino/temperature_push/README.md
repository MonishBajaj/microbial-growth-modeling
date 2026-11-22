# Arduino Push (stable public ingest)

How this POST fits the rest of the app is in [docs/USER_GUIDE.md](../../docs/USER_GUIDE.md) under "Arduino push".

The board POSTs Celsius JSON to Flask:

`POST /api/arduino/ingest`  
Header: `Authorization: Bearer microbial-lab-token`  
Body: `{"celsius": 23.5, "device_id": "uno-r4-1"}`

## Run the dashboard + public URL

```bash
cd microbial_growth_modeling
./scripts/start_push_tunnel.sh
```

That starts Flask on port 5000 and a Cloudflare quick tunnel, then writes
`public_base_url.txt`. Open the printed **Ingest URL** in the dashboard
**Arduino Push** panel (Copy).

> Quick tunnels create a new `*.trycloudflare.com` hostname each time the
> tunnel process restarts. For a permanent hostname, deploy Flask (Render,
> Railway, etc.) and set `PUBLIC_BASE_URL` or `public_base_url.txt` to that
> origin — then update `SERVER_HOST` in the sketch once.

## Sketch setup

1. Install libraries: **OneWire**, **DallasTemperature**, **ArduinoHttpClient**.
2. Edit `temperature_push.ino`:
   - `WIFI_SSID` / `WIFI_PASSWORD`
   - `SERVER_HOST` = host from the ingest URL (no `https://`)
   - `PUSH_TOKEN` = `microbial-lab-token` (or your `ARDUINO_PUSH_TOKEN`)
3. Upload to **UNO R4 WiFi**.
4. Serial Monitor 9600: look for `WIFI_OK`, `TEMP …`, `POST_OK`.

## Dashboard

Sign in → **Arduino Push** → confirm last reading → Quick test / Short / Full.
