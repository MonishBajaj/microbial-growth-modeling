"""Mint a Firebase App Check token for ThermoWorks Cloud.

ThermoWorks enforces App Check on email/password sign-in. The token is produced
by the same reCAPTCHA Enterprise widget the Cloud website uses, then exchanged
inside that page. Headless Chrome is rejected, so this opens a short real
Chrome window on the local display and caches the token until it nears expiry.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from typing import Optional, Tuple

import aiohttp

_PROFILE = "/tmp/microbial-thermoworks-chrome"
_LOGIN_URL = "https://cloud.thermoworks.com/auth/login"
_API_KEY = "AIzaSyCf079iccUFc1k7VHdGXng22zXDy8Y3KEY"
_APP_ID = "1:78998049458:web:b41e9d405d8c7de95eefab"
_PROJECT = "thermoworks-cloud-production"

_cache_lock = threading.Lock()
_mint_lock = threading.Lock()
_token: Optional[str] = None
_expires_at = 0.0
# bridge_id -> {created, token?, expires_at?}
_bridges: dict = {}
_BRIDGE_TTL_SEC = 900.0
# Shared across gunicorn workers (in-memory alone loses the handoff on Render).
_STATE_PATH = os.environ.get(
    "THERMOWORKS_APPCHECK_STATE",
    "/tmp/microbial-thermoworks-appcheck-state.json",
)

_EXCHANGE_JS = r"""
(async () => {
  const start = Date.now();
  let g = null;
  while (Date.now() - start < 20000) {
    g = window.grecaptcha && window.grecaptcha.enterprise;
    const ids = Object.keys((window.___grecaptcha_cfg || {}).clients || {});
    if (g && ids.length) break;
    await new Promise(r => setTimeout(r, 250));
  }
  if (!g) return {ok: false, error: "reCAPTCHA did not load on cloud.thermoworks.com"};
  const ids = Object.keys((window.___grecaptcha_cfg || {}).clients || {});
  const widgetId = ids.length ? Number(ids[0]) : 0;
  const recaptcha = await Promise.race([
    new Promise((resolve, reject) => {
      g.ready(() => {
        g.execute(widgetId, {action: "fire_app_check"}).then(resolve).catch(reject);
      });
    }),
    new Promise((_, reject) => setTimeout(() => reject(new Error("reCAPTCHA timed out")), 15000))
  ]);
  const url = "https://content-firebaseappcheck.googleapis.com/v1/projects/"
    + "%s/apps/%s:exchangeRecaptchaEnterpriseToken?key=%s";
  const resp = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({recaptcha_enterprise_token: recaptcha})
  });
  const body = await resp.text();
  let parsed = {};
  try { parsed = JSON.parse(body); } catch (e) {}
  if (!resp.ok) {
    const message = (parsed.error && parsed.error.message) || body.slice(0, 300);
    return {ok: false, status: resp.status, error: message};
  }
  return {ok: true, token: parsed.token, ttl: parsed.ttl || "3600s"};
})()
""" % (_PROJECT, _APP_ID, _API_KEY)


def _load_state() -> dict:
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {"token": None, "expires_at": 0.0, "bridges": {}}


def _save_state(token: Optional[str], expires_at: float, bridges: dict) -> None:
    payload = {
        "token": token,
        "expires_at": expires_at,
        "bridges": bridges,
    }
    directory = os.path.dirname(_STATE_PATH) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{_STATE_PATH}.{os.getpid()}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp_path, _STATE_PATH)


def _sync_from_disk() -> None:
    """Refresh in-process cache from the shared state file."""
    global _token, _expires_at, _bridges
    data = _load_state()
    disk_token = data.get("token")
    disk_expires = float(data.get("expires_at") or 0)
    disk_bridges = data.get("bridges") if isinstance(data.get("bridges"), dict) else {}
    now = time.time()
    # Prefer whichever token lasts longer.
    if disk_token and disk_expires > _expires_at:
        _token = disk_token
        _expires_at = disk_expires
    # Merge bridges; keep the newer / completed entry.
    for bridge_id, entry in disk_bridges.items():
        if not isinstance(entry, dict):
            continue
        if now - float(entry.get("created") or 0) > _BRIDGE_TTL_SEC:
            continue
        local = _bridges.get(bridge_id)
        if local is None or (entry.get("token") and not local.get("token")):
            _bridges[bridge_id] = {
                "created": float(entry.get("created") or now),
                "token": entry.get("token"),
                "expires_at": float(entry.get("expires_at") or 0),
            }
        elif entry.get("expires_at", 0) > local.get("expires_at", 0):
            _bridges[bridge_id] = {
                "created": float(entry.get("created") or local.get("created") or now),
                "token": entry.get("token") or local.get("token"),
                "expires_at": float(entry.get("expires_at") or 0),
            }


def _persist_locked() -> None:
    now = time.time()
    alive = {
        key: value
        for key, value in _bridges.items()
        if now - float(value.get("created") or 0) <= _BRIDGE_TTL_SEC
    }
    _bridges.clear()
    _bridges.update(alive)
    _save_state(_token, _expires_at, _bridges)


def _cached() -> Optional[str]:
    with _cache_lock:
        _sync_from_disk()
        if _token and time.time() < _expires_at - 120:
            return _token
    return None


def _store(token: str, ttl_seconds: float) -> None:
    global _token, _expires_at
    with _cache_lock:
        _sync_from_disk()
        _token = token
        _expires_at = time.time() + ttl_seconds
        _persist_locked()


def store_browser_token(token: str, ttl: str | float = "3600s") -> float:
    """Accept an App Check JWT minted in the user's browser."""
    token = (token or "").strip()
    if not token or len(token) < 20:
        raise ValueError("App Check token is missing or too short.")
    if isinstance(ttl, (int, float)):
        ttl_seconds = max(float(ttl), 60.0)
    else:
        ttl_seconds = _ttl_seconds(str(ttl))
    _store(token, ttl_seconds)
    return ttl_seconds


def create_bridge() -> str:
    """Create a one-time bridge id for browser App Check without a lab PC."""
    import secrets

    bridge_id = secrets.token_urlsafe(16)
    now = time.time()
    with _cache_lock:
        _sync_from_disk()
        dead = [
            key for key, value in _bridges.items()
            if now - float(value.get("created") or 0) > _BRIDGE_TTL_SEC
        ]
        for key in dead:
            _bridges.pop(key, None)
        _bridges[bridge_id] = {"created": now, "token": None, "expires_at": 0.0}
        _persist_locked()
    return bridge_id


def complete_bridge(bridge_id: str, token: str, ttl: str | float = "3600s") -> float:
    """Store token for a bridge id and in the global App Check cache."""
    global _token, _expires_at

    bridge_id = (bridge_id or "").strip()
    if not bridge_id:
        raise ValueError("bridge_id is required.")
    token = (token or "").strip()
    if not token or len(token) < 20:
        raise ValueError("App Check token is missing or too short.")
    if isinstance(ttl, (int, float)):
        ttl_seconds = max(float(ttl), 60.0)
    else:
        ttl_seconds = _ttl_seconds(str(ttl))

    now = time.time()
    with _cache_lock:
        _sync_from_disk()
        entry = _bridges.get(bridge_id)
        # Accept even if this worker never saw create_bridge (other gunicorn worker).
        if entry is None:
            entry = {"created": now, "token": None, "expires_at": 0.0}
            _bridges[bridge_id] = entry
        elif now - float(entry.get("created") or 0) > _BRIDGE_TTL_SEC:
            _bridges.pop(bridge_id, None)
            raise ValueError("App Check bridge expired. Re-open App Check from the dashboard.")
        _token = token
        _expires_at = now + ttl_seconds
        entry["token"] = token
        entry["expires_at"] = _expires_at
        _persist_locked()
    return ttl_seconds


def bridge_status(bridge_id: str) -> dict:
    bridge_id = (bridge_id or "").strip()
    with _cache_lock:
        _sync_from_disk()
        entry = _bridges.get(bridge_id)
        cached = _token if _token and time.time() < _expires_at - 120 else None
        if entry and entry.get("token"):
            return {
                "ready": True,
                "bridge_ready": True,
                "expires_in": max(int(float(entry.get("expires_at") or 0) - time.time()), 0),
            }
        if cached:
            return {
                "ready": True,
                "bridge_ready": False,
                "expires_in": max(int(_expires_at - time.time()), 0),
            }
        return {"ready": False, "bridge_ready": False, "expires_in": 0}


def appcheck_status() -> dict:
    with _cache_lock:
        _sync_from_disk()
        cached = bool(_token and time.time() < _expires_at - 120)
        expires_in = max(int(_expires_at - time.time()), 0) if cached else 0
    return {"ready": cached, "expires_in": expires_in}


def _ttl_seconds(ttl: str) -> float:
    text = (ttl or "").strip().lower()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return max(float(text), 60.0)
    except ValueError:
        return 3600.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.wait(timeout=5)


async def _cdp_call(ws, pending, seq_box, method, params=None, timeout=30):
    seq_box[0] += 1
    seq = seq_box[0]
    fut = asyncio.get_running_loop().create_future()
    pending[seq] = fut
    await ws.send_json({"id": seq, "method": method, "params": params or {}})
    data = await asyncio.wait_for(fut, timeout)
    if "error" in data:
        raise RuntimeError(data["error"].get("message") or str(data["error"]))
    return data.get("result", {})


def _env_token() -> Optional[Tuple[str, float]]:
    """Optional App Check JWT from env (useful only until it expires)."""
    token = (os.environ.get("THERMOWORKS_APPCHECK_TOKEN") or "").strip()
    if not token:
        return None
    try:
        ttl = float(os.environ.get("THERMOWORKS_APPCHECK_TTL_SECONDS") or "3000")
    except ValueError:
        ttl = 3000.0
    return token, max(ttl, 60.0)


async def _mint() -> Tuple[str, float]:
    env = _env_token()
    if env:
        return env

    cached = _cached()
    if cached:
        with _cache_lock:
            return cached, max(_expires_at - time.time(), 60.0)

    if not os.environ.get("DISPLAY"):
        raise RuntimeError(
            "ThermoWorks App Check token missing. Click Refresh again and complete "
            "the browser App Check popup (or paste the capture script on cloud.thermoworks.com)."
        )
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if not chrome:
        raise RuntimeError(
            "Google Chrome is required for ThermoWorks App Check on this machine."
        )

    os.makedirs(_PROFILE, exist_ok=True)
    port = _free_port()
    proc = subprocess.Popen(
        [
            chrome,
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--window-size=480,360",
            "--window-position=80,80",
            f"--user-data-dir={_PROFILE}",
            f"--remote-debugging-port={port}",
            _LOGIN_URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        async with aiohttp.ClientSession() as http:
            page = None
            deadline = time.time() + 20
            while time.time() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("Chrome closed before ThermoWorks App Check could run.")
                try:
                    async with http.get(f"http://127.0.0.1:{port}/json/list", timeout=1) as resp:
                        pages = await resp.json(content_type=None)
                    page = next(
                        (
                            item for item in pages
                            if item.get("type") == "page" and "thermoworks.com" in item.get("url", "")
                        ),
                        None,
                    )
                    if page and page.get("webSocketDebuggerUrl"):
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError):
                    page = None
                await asyncio.sleep(0.25)
            if not page:
                raise RuntimeError("Chrome did not open ThermoWorks Cloud.")

            await asyncio.sleep(1.5)
            async with http.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=8_000_000) as ws:
                pending = {}

                async def reader():
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            break
                        data = json.loads(msg.data)
                        fut = pending.get(data.get("id"))
                        if fut and not fut.done():
                            fut.set_result(data)

                task = asyncio.create_task(reader())
                try:
                    result = None
                    last_error = None
                    for _ in range(3):
                        try:
                            result = await _cdp_call(
                                ws, pending, [0],
                                "Runtime.evaluate",
                                {
                                    "expression": _EXCHANGE_JS,
                                    "awaitPromise": True,
                                    "returnByValue": True,
                                },
                                timeout=40,
                            )
                            last_error = None
                            break
                        except RuntimeError as exc:
                            last_error = exc
                            if "context was destroyed" not in str(exc).lower():
                                raise
                            await asyncio.sleep(1)
                    if last_error:
                        raise last_error
                finally:
                    task.cancel()

            value = (result.get("result") or {}).get("value")
            details = result.get("exceptionDetails")
            if details:
                text = (details.get("exception") or {}).get("description") or details.get("text")
                raise RuntimeError(f"ThermoWorks App Check failed: {text}")
            if not isinstance(value, dict) or not value.get("ok"):
                error = (value or {}).get("error") if isinstance(value, dict) else None
                raise RuntimeError(error or "ThermoWorks App Check was rejected.")
            token = value.get("token")
            if not token:
                raise RuntimeError("ThermoWorks App Check did not return a token.")
            return token, _ttl_seconds(value.get("ttl") or "")
    finally:
        _stop(proc)


def _mint_if_needed() -> str:
    with _mint_lock:
        cached = _cached()
        if cached:
            return cached
        token, ttl = asyncio.run(_mint())
        _store(token, ttl)
        return token


async def get_app_check_token() -> str:
    """Return a cached App Check token, minting one in Chrome when needed."""
    cached = _cached()
    if cached:
        return cached
    return await asyncio.to_thread(_mint_if_needed)
