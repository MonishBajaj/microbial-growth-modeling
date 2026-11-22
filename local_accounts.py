"""Dashboard sign-in accounts, stored as password hashes in local_users.json.

This is the analyzer login, separate from a MEATER or ThermoWorks cloud login.
Creating a profile or resetting a password also requires the lab access code
(LAB_ACCESS_CODE, default uga-microbial-lab). Three seed accounts are merged in
on first load if they are missing from the file. Passwords are hashed with
Werkzeug; the plaintext password is not stored here. app.py does keep the
plaintext in the Flask session so a MEATER run can reuse it.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import threading
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

_LOCK = threading.Lock()
_USERS_PATH = os.environ.get(
    "LOCAL_USERS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_users.json"),
)

# Seeded lab accounts (same hashes as before). Merged into the file on first load.
_SEED_USERS = {
    "bajajmonish0@gmail.com": {
        "name": "Monish Bajaj",
        "password_hash": (
            "pbkdf2:sha256:1000000$vTT6AXrrEBm77xNA$"
            "3a3813f741acf88a88d45ff46197c465f1a7135ce0baa73c60fe4c558a5927d8"
        ),
    },
    "mishralabuga@gmail.com": {
        "name": "Mishra Lab",
        "password_hash": (
            "pbkdf2:sha256:1000000$lUqC5MZOObykkvWl$"
            "afca0eb191db2c176d32c88d40026a217dccd71f67b1fe0d247f792875e3d1e7"
        ),
    },
    "juan.gao@uga.edu": {
        "name": "Juan Gao",
        "password_hash": (
            "pbkdf2:sha256:1000000$h7Es0zpHGXnbXVeY$"
            "3618974f1e8459e959434c645b7aced4ea56cea7460aed5bc70c23688cd8ebac"
        ),
    },
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def lab_access_code() -> str:
    """Shared lab code required to create a profile or reset a password."""
    return (os.environ.get("LAB_ACCESS_CODE") or "uga-microbial-lab").strip()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _load_unlocked() -> dict:
    users = {}
    try:
        with open(_USERS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            for email, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                users[_normalize_email(email)] = {
                    "name": (entry.get("name") or "").strip() or _normalize_email(email),
                    "password_hash": entry.get("password_hash") or "",
                }
    except (OSError, json.JSONDecodeError, TypeError):
        pass

    changed = False
    for email, entry in _SEED_USERS.items():
        if email not in users:
            users[email] = dict(entry)
            changed = True
    if changed or not os.path.exists(_USERS_PATH):
        _save_unlocked(users)
    return users


def _save_unlocked(users: dict) -> None:
    directory = os.path.dirname(_USERS_PATH) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{_USERS_PATH}.{os.getpid()}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(users, handle, indent=2, sort_keys=True)
    os.replace(tmp_path, _USERS_PATH)


def get_user(email: str) -> Optional[dict]:
    key = _normalize_email(email)
    with _LOCK:
        users = _load_unlocked()
        entry = users.get(key)
        return dict(entry) if entry else None


def verify_login(email: str, password: str) -> bool:
    user = get_user(email)
    if not user or not user.get("password_hash"):
        return False
    return check_password_hash(user["password_hash"], password or "")


def create_profile(name: str, email: str, password: str, access_code: str) -> None:
    name = (name or "").strip()
    email_key = _normalize_email(email)
    password = password or ""
    access_code = (access_code or "").strip()

    if not name or len(name) < 2:
        raise ValueError("Enter your name (at least 2 characters).")
    if not email_key or not _EMAIL_RE.match(email_key):
        raise ValueError("Enter a valid email address.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    expected = lab_access_code()
    if not expected or not hmac_compare(access_code, expected):
        raise ValueError("Lab access code is incorrect.")

    with _LOCK:
        users = _load_unlocked()
        if email_key in users:
            raise ValueError("An account with that email already exists. Sign in or reset your password.")
        users[email_key] = {
            "name": name,
            "password_hash": generate_password_hash(password),
        }
        _save_unlocked(users)


def reset_password(email: str, new_password: str, access_code: str) -> None:
    email_key = _normalize_email(email)
    new_password = new_password or ""
    access_code = (access_code or "").strip()

    if not email_key or not _EMAIL_RE.match(email_key):
        raise ValueError("Enter a valid email address.")
    if len(new_password) < 8:
        raise ValueError("New password must be at least 8 characters.")
    expected = lab_access_code()
    if not expected or not hmac_compare(access_code, expected):
        raise ValueError("Lab access code is incorrect.")

    with _LOCK:
        users = _load_unlocked()
        if email_key not in users:
            # Same message whether missing or present (avoid account enumeration soft-fail).
            raise ValueError("Could not reset that account. Check the email and lab access code.")
        users[email_key]["password_hash"] = generate_password_hash(new_password)
        _save_unlocked(users)


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest((left or "").encode("utf-8"), (right or "").encode("utf-8"))
