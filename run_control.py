"""Stop checks shared by the temperature collectors.

A collector receives ``should_stop``, a no-argument callable that returns True
once the user has pressed Stop. Collectors check it between readings and wait
with sleep_unless_stopped() so a stop takes effect within about a second
instead of after a full sampling interval. Passing ``None`` means "never stop
early", which keeps the old fixed-duration behaviour.

Continuous monitoring passes duration_hours=CONTINUOUS (infinity), so the run
lasts until should_stop() returns True.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Callable, Optional

StopFn = Optional[Callable[[], bool]]

CONTINUOUS = math.inf


def is_continuous(duration_hours) -> bool:
    try:
        return math.isinf(float(duration_hours))
    except (TypeError, ValueError):
        return False


def stop_requested(should_stop: StopFn) -> bool:
    if should_stop is None:
        return False
    try:
        return bool(should_stop())
    except Exception:
        return False


def sleep_unless_stopped(seconds: float, should_stop: StopFn, step: float = 1.0) -> bool:
    """Sleep up to ``seconds``; return True early if a stop was requested."""
    if should_stop is None:
        time.sleep(max(0.0, seconds))
        return False
    end = time.time() + max(0.0, seconds)
    while True:
        if stop_requested(should_stop):
            return True
        left = end - time.time()
        if left <= 0:
            return False
        time.sleep(min(step, left))


async def async_sleep_unless_stopped(seconds: float, should_stop: StopFn, step: float = 1.0) -> bool:
    """Async version of sleep_unless_stopped for the ThermoWorks collector."""
    if should_stop is None:
        await asyncio.sleep(max(0.0, seconds))
        return False
    end = time.time() + max(0.0, seconds)
    while True:
        if stop_requested(should_stop):
            return True
        left = end - time.time()
        if left <= 0:
            return False
        await asyncio.sleep(min(step, left))
