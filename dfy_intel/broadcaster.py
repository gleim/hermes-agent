"""Thread-safe in-memory broadcaster for DFY ingest events.

Provides a simple fan-out mechanism: when ``publish()`` is called (from the
ingest thread), every connected SSE subscriber receives the event via its own
``queue.Queue``.  Subscribers register by calling ``subscribe()`` which returns
a context manager that yields the queue and auto-deregisters on exit.

Design goals:
- Non-blocking publish: ``put_nowait`` drops the event if a subscriber's queue
  is full rather than stalling the ingest path.
- Thread-safe: a single ``threading.Lock`` guards the subscriber list.
- No external dependencies: stdlib only.
"""

from __future__ import annotations

import json
import queue
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

_lock = threading.Lock()
_subscribers: List[queue.Queue] = []

# Maximum events buffered per subscriber before oldest are dropped.
_QUEUE_MAXSIZE = 64

# Sentinel placed in a queue to signal the subscriber should stop.
_STOP = object()


def publish(kind: str, bot: Optional[str], data: Any) -> None:
    """Fan out one DFY event to all connected SSE subscribers.

    Called from ``dfy_intel.ingest.apply_event`` after a successful fold.
    Never raises; drops events for slow/full subscribers rather than blocking.
    """
    ts = datetime.now(timezone.utc).isoformat()
    payload = json.dumps({"kind": kind, "bot": bot or "unknown", "ts": ts, "data": data or {}})
    with _lock:
        targets = list(_subscribers)
    for q in targets:
        try:
            q.put_nowait(payload)
        except queue.Full:
            # Subscriber is too slow — drop the event rather than blocking ingest.
            pass


@contextmanager
def subscribe() -> Generator[queue.Queue, None, None]:
    """Context manager that registers a new subscriber queue.

    Usage::

        with broadcaster.subscribe() as q:
            while True:
                item = q.get()
                if item is broadcaster.STOP:
                    break
                yield item  # SSE line

    The queue is automatically removed from the fan-out list on exit.
    """
    q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
    with _lock:
        _subscribers.append(q)
    try:
        yield q
    finally:
        with _lock:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass
        # Unblock any thread blocked on q.get() so it can exit cleanly.
        try:
            q.put_nowait(_STOP)
        except queue.Full:
            pass


# Expose the sentinel so callers can check ``item is broadcaster.STOP``.
STOP = _STOP


def subscriber_count() -> int:
    """Return the number of currently connected SSE subscribers."""
    with _lock:
        return len(_subscribers)
