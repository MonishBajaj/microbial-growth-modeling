"""Disk-backed record of each analysis run.

app.py starts collection on a background thread and writes status here so the
user can leave /status/<id> and open the run later from the dashboard. Each job
is one JSON file under job_store/ (or JOB_STORE_DIR). The in-memory JobRecord
keeps the plot image; persist() also writes a JSON-safe copy, including
image_data, so another gunicorn worker can render the results page.

Jobs are filtered by the signed-in email (the owner field).
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

_LOCK = threading.RLock()
_DIR = os.environ.get(
    "JOB_STORE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_store"),
)
# In-process cache (thread that owns the run updates this; other workers load from disk).
_CACHE: dict = {}


def _path(task_id: str) -> str:
    safe = "".join(ch for ch in task_id if ch.isalnum() or ch in "-_")
    return os.path.join(_DIR, f"{safe}.json")


def _stop_path(task_id: str) -> str:
    return _path(task_id)[:-5] + ".stop"


def request_stop(task_id: str) -> None:
    """Ask a running job to stop collecting and analyze what it has.

    This is a marker file, not a field on the job JSON: the runner thread
    rewrites the JSON on every log line from its own memory, so a flag written
    there by another gunicorn worker could be overwritten before it is seen.
    """
    with _LOCK:
        os.makedirs(_DIR, exist_ok=True)
        with open(_stop_path(task_id), "w", encoding="utf-8") as handle:
            handle.write(str(time.time()))


def stop_requested(task_id: str) -> bool:
    return os.path.exists(_stop_path(task_id))


def clear_stop(task_id: str) -> None:
    try:
        os.remove(_stop_path(task_id))
    except OSError:
        pass


def _serialize_result(result):
    if result is None:
        return None
    if not isinstance(result, dict):
        return {"error": str(result)}
    out = {}
    for key, value in result.items():
        if key == "logs":
            # Logs already stored on the job; avoid huge duplication when possible.
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = {
                k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v))
                for k, v in value.items()
            }
        elif isinstance(value, list):
            out[key] = [
                item if isinstance(item, (str, int, float, bool)) or item is None else str(item)
                for item in value
            ]
        else:
            out[key] = str(value)
    return out


def is_new_reading_line(message: str) -> bool:
    """True for a log line that reports a freshly received temperature.

    Every collector (MEATER, ThermoWorks, Arduino USB/Wi-Fi/Push) logs each new
    sample as "🌡️ Reading #N…" (Arduino Push also logs a "🌡️ Seed reading").
    Push "(held, …)" lines repeat the last value when nothing new arrived, so
    they do not count as data.
    """
    return message.startswith("🌡️") and "(held," not in message


class JobLogs(list):
    """List that persists the parent job whenever a log line is appended.

    It also stamps ``last_reading_at`` on the job for each new reading line, so
    the dashboard can tell when a source has stopped sending data.
    """

    def __init__(self, job: "JobRecord", items=None):
        super().__init__(items or [])
        self._job = job

    def append(self, message):  # noqa: A003
        message = str(message)
        if is_new_reading_line(message):
            dict.__setitem__(self._job, "last_reading_at", time.time())
        super().append(message)
        self._job.persist()


class JobRecord(dict):
    """Dict-like job that writes through to disk on mutation."""

    def __init__(self, task_id: str, data: dict):
        payload = dict(data)
        payload["task_id"] = task_id
        logs = payload.pop("logs", []) or []
        super().__init__(payload)
        super().__setitem__("logs", JobLogs(self, list(logs)))

    def __setitem__(self, key, value):
        if key == "logs" and not isinstance(value, JobLogs):
            value = JobLogs(self, list(value or []))
        if key == "result":
            # Keep full in-memory result (includes image); disk gets a JSON-safe copy.
            super().__setitem__(key, value)
            self.persist()
            return
        super().__setitem__(key, value)
        self.persist()

    def persist(self) -> None:
        with _LOCK:
            os.makedirs(_DIR, exist_ok=True)
            payload = {
                "task_id": self.get("task_id"),
                "owner": self.get("owner"),
                "status": self.get("status"),
                "label": self.get("label"),
                "mode_label": self.get("mode_label"),
                "source": self.get("source"),
                "started_at": self.get("started_at"),
                "duration_seconds": self.get("duration_seconds"),
                "interval_seconds": self.get("interval_seconds"),
                "last_reading_at": self.get("last_reading_at"),
                "updated_at": time.time(),
                "logs": list(self.get("logs") or []),
                "result": _serialize_result(self.get("result")),
            }
            # Prefer keeping image_data in the on-disk result when present in memory.
            mem_result = self.get("result")
            if isinstance(mem_result, dict) and mem_result.get("image_data"):
                if payload["result"] is None:
                    payload["result"] = {}
                payload["result"]["image_data"] = mem_result.get("image_data")
                if "stats" in mem_result and isinstance(mem_result["stats"], dict):
                    payload["result"]["stats"] = mem_result["stats"]
                for key in ("mode_name", "connection_result", "readings_count", "avg_temps", "error"):
                    if key in mem_result:
                        payload["result"][key] = mem_result[key]
            path = _path(self["task_id"])
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, path)
            _CACHE[self["task_id"]] = self


def create_job(
    task_id: str,
    *,
    owner: str,
    mode_label: str,
    duration_seconds: int,
    label: str = "",
    source: str = "",
    interval_seconds: float = 0,
) -> JobRecord:
    job = JobRecord(
        task_id,
        {
            "owner": (owner or "").lower(),
            "status": "starting",
            "result": None,
            "logs": [],
            "started_at": time.time(),
            "duration_seconds": int(duration_seconds or 0),
            # Sampling interval; sets how long a silent source counts as stalled.
            "interval_seconds": float(interval_seconds or 0),
            "last_reading_at": None,
            "mode_label": mode_label or "",
            "label": label or "",
            "source": source or "",
        },
    )
    # In-memory only (persist() writes a fixed key list): this process runs the
    # job, so its object is the source of truth and get_job must not overwrite it.
    dict.__setitem__(job, "_owned", True)
    job.persist()
    return job


def get_job(task_id: str, *, prefer_cache: bool = False) -> Optional[JobRecord]:
    """Load a job. Default reloads from disk so other gunicorn workers see updates."""
    with _LOCK:
        cached = _CACHE.get(task_id)
        if cached is not None and cached.get("_owned"):
            # This process runs the job and is the only writer of its file.
            # Copying the disk version back would race with the runner: a poll
            # could read the file just before a status change and then write the
            # old status onto the runner's object (e.g. 'collecting' -> 'starting').
            return cached
        path = _path(task_id)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None

        if prefer_cache and cached is not None and mtime is not None:
            if float(cached.get("_disk_mtime") or 0) >= mtime:
                return cached

        if mtime is None:
            return cached

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            return cached
        if not isinstance(data, dict):
            return cached

        # Keep the live in-memory object if this process owns the runner and
        # the disk copy is not newer in a meaningful way for result payloads.
        if cached is not None and cached.get("status") not in ("done", "error"):
            # Refresh fields from disk into the same object so runners keep working.
            for key in (
                "status", "mode_label", "label", "source", "started_at", "duration_seconds",
                "owner", "interval_seconds", "last_reading_at",
            ):
                if key in data:
                    dict.__setitem__(cached, key, data.get(key))
            logs = data.get("logs") or []
            current_logs = cached.get("logs")
            if isinstance(current_logs, JobLogs):
                if len(logs) > len(current_logs):
                    current_logs[:] = list(logs)
            else:
                dict.__setitem__(cached, "logs", JobLogs(cached, list(logs)))
            if data.get("result") is not None and cached.get("result") is None:
                dict.__setitem__(cached, "result", data.get("result"))
            dict.__setitem__(cached, "_disk_mtime", mtime)
            return cached

        job = JobRecord(task_id, data)
        dict.__setitem__(job, "_disk_mtime", mtime)
        _CACHE[task_id] = job
        return job


def list_jobs(owner: str, limit: int = 30) -> list:
    owner_key = (owner or "").lower()
    jobs = []
    with _LOCK:
        os.makedirs(_DIR, exist_ok=True)
        for name in os.listdir(_DIR):
            if not name.endswith(".json"):
                continue
            task_id = name[:-5]
            job = get_job(task_id)
            if not job:
                continue
            if owner_key and (job.get("owner") or "").lower() != owner_key:
                continue
            jobs.append(job)
    jobs.sort(key=lambda item: float(item.get("started_at") or 0), reverse=True)
    return jobs[:limit]


def job_summary(job: JobRecord) -> dict:
    started = float(job.get("started_at") or 0)
    duration = int(job.get("duration_seconds") or 0)
    elapsed = max(0.0, time.time() - started) if started else 0.0
    status = job.get("status") or "unknown"
    if not duration and status not in ("done", "error", "simulating"):
        remaining = None  # continuous monitoring has no end time
    else:
        remaining = max(0, int(duration - elapsed)) if duration and status not in ("done", "error", "simulating") else 0
    return {
        "task_id": job.get("task_id"),
        "status": status,
        "mode_label": job.get("mode_label") or "",
        "label": job.get("label") or "",
        "source": job.get("source") or "",
        "started_at": started,
        "duration_seconds": duration,
        "elapsed_seconds": int(elapsed),
        "remaining_seconds": remaining,
        "interval_seconds": float(job.get("interval_seconds") or 0),
        "last_reading_at": job.get("last_reading_at"),
        "running": status not in ("done", "error"),
        # duration 0 marks continuous monitoring: no end time, runs until stopped.
        "continuous": duration == 0,
        "ok": status == "done" and not (isinstance(job.get("result"), dict) and job["result"].get("error")),
    }
