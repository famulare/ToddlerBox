"""Unsaved activity work kept by the launcher process when a save cannot finish.

Home must never wait on storage, yet memory is never durable. Parked work is
written in the background, retried, flushed at shutdown, and reported as
unsaved to save-current until a write of its newest bytes has succeeded.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from toddlerbox.runtime.persistence import write_bytes
from toddlerbox.runtime.workers import DaemonExecutor

RETRY_SECONDS = 2.0
DURABLE, PENDING, FAILED = "durable", "pending", "failed"


@dataclass
class ParkedWork:
    activity: str
    target: Path
    encode: Callable[[], bytes]  # Pure; runs on the retained writer thread.
    state: Any  # Exactly what the activity needs to resume this document.
    prior: Optional[Future] = None  # Earlier in-flight write of the same target.
    write_disabled: bool = False  # The target holds work that must never be overwritten.
    writer: Optional[Future] = field(default=None, repr=False)
    last_attempt: float = float("-inf")


_slots: Dict[str, ParkedWork] = {}
_lock = threading.RLock()
_executor: Optional[DaemonExecutor] = None


def _write(work: ParkedWork) -> None:
    # One writer per target: an older periodic write finishes before this one.
    if work.prior is not None:
        try:
            work.prior.result()
        except Exception:
            pass
    write_bytes(work.target, work.encode())


def _start(work: ParkedWork, now: float) -> None:
    global _executor
    if work.write_disabled:
        return
    if _executor is None:
        _executor = DaemonExecutor("retained-save")
    work.last_attempt = now
    work.writer = _executor.submit(_write, work)


def park(work: ParkedWork) -> None:
    with _lock:
        _slots[work.activity] = work
        _start(work, time.monotonic())


def adopt(activity: str) -> Optional[ParkedWork]:
    """The reopened activity takes back its document and any in-flight writer."""
    with _lock:
        return _slots.pop(activity, None)


def parked(activity: str) -> bool:
    with _lock:
        return activity in _slots


def _work_status(work: ParkedWork, now: float) -> str:
    if work.write_disabled:
        return FAILED
    writer = work.writer
    if writer is not None and not writer.done():
        return PENDING
    if writer is not None and writer.exception() is None:
        return DURABLE
    if now - work.last_attempt >= RETRY_SECONDS:
        _start(work, now)
    return PENDING


def status() -> str:
    """Non-blocking: durable only when every parked document has been written."""
    now = time.monotonic()
    result = DURABLE
    with _lock:
        for activity, work in list(_slots.items()):
            state = _work_status(work, now)
            if state == DURABLE:
                del _slots[activity]
            elif state == FAILED:
                result = FAILED
            elif result != FAILED:
                result = PENDING
    return result


def flush(timeout: float) -> str:
    """Bounded final attempt before the launcher process exits."""
    with _lock:
        for work in _slots.values():
            if work.writer is None or (work.writer.done() and work.writer.exception() is not None):
                _start(work, time.monotonic())
        writers = [work.writer for work in _slots.values() if work.writer is not None]
    if writers:
        wait(writers, timeout=timeout)
    return status()
