"""Persistent background analysis jobs (survive leaving the status page / multi-worker)."""

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


class JobLogs(list):
    """List that persists the parent job whenever a log line is appended."""

    def __init__(self, job: "JobRecord", items=None):
        super().__init__(items or [])
        self._job = job

    def append(self, message):  # noqa: A003
        super().append(str(message))
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
            "mode_label": mode_label or "",
            "label": label or "",
            "source": source or "",
        },
    )
    job.persist()
    return job


def get_job(task_id: str, *, prefer_cache: bool = False) -> Optional[JobRecord]:
    """Load a job. Default reloads from disk so other gunicorn workers see updates."""
    with _LOCK:
        cached = _CACHE.get(task_id)
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
            for key in ("status", "mode_label", "label", "source", "started_at", "duration_seconds", "owner"):
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
        "running": status not in ("done", "error"),
        "ok": status == "done" and not (isinstance(job.get("result"), dict) and job["result"].get("error")),
    }
