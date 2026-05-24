"""Monotonic logical clock per site producing Timestamp(counter, site_id)."""

from __future__ import annotations

import threading

from src.common.messages import Timestamp


class ClockSync:
    """Per-site monotonic counter.

    Reference: Ozsu & Valduriez 2020, Section 5.2.2.2, p. 203 (counter + site_id tiebreak,
    optionally synchronized via NTP — we use counter-only for determinism).
    """

    def __init__(self, site_id: int, persist_path: str | None = None) -> None:
        self._site_id = site_id
        self._counter = 0
        self._lock = threading.Lock()

    def next(self) -> Timestamp:
        """Atomically increment counter and return new Timestamp."""
        with self._lock:
            self._counter += 1
            return Timestamp(counter=self._counter, site_id=self._site_id)

    def peek(self) -> Timestamp:
        """Return minimum-future ts without advancing — used by DummyMessageGenerator."""
        with self._lock:
            return Timestamp(counter=self._counter + 1, site_id=self._site_id)

    def observe(self, ts: Timestamp) -> None:
        """Advance counter to max(local, incoming.counter) to preserve global order."""
        with self._lock:
            if ts.counter > self._counter:
                self._counter = ts.counter
