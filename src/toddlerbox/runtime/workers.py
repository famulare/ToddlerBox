"""Background writers that can never hold the launcher process open."""
from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable


class DaemonExecutor:
    """One daemon worker thread with the submit/shutdown subset of an Executor.

    ThreadPoolExecutor workers are joined at interpreter exit, so one write
    stalled on a failing disk would keep a stopping launcher alive past the
    controller's grace. An interrupted daemon write is like a power cut: the
    previous file survives and the orphaned temporary is classified next start.
    """

    def __init__(self, name: str) -> None:
        self._queue: "queue.SimpleQueue[Any]" = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._work, name=name, daemon=True)
        self._thread.start()

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, function, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(function(*args, **kwargs))
            except BaseException as error:
                future.set_exception(error)

    def submit(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        future: Future = Future()
        self._queue.put((future, function, args, kwargs))
        return future

    def shutdown(self, wait: bool = False, cancel_futures: bool = False) -> None:
        if cancel_futures:
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is not None:
                    item[0].cancel()
        self._queue.put(None)
        if wait:
            self._thread.join()
