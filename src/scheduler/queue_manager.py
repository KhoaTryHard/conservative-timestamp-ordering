"""Per-TM priority queues Q^t_s for the Conservative Scheduler."""

from __future__ import annotations

import heapq
import threading

from src.common.messages import Operation


class QueueManager:
    """Manages one heap per remote TM — Q^t_s in textbook notation.

    Reference: Ozsu & Valduriez 2020, Section 5.2.2.2, p. 201 — each scheduler
    at site s maintains one queue per TM t; ops ordered by increasing timestamp.
    """

    def __init__(self, known_tm_ids: list[int]) -> None:
        self._lock = threading.Lock()
        # Core TMs that participate in the dummy-heartbeat protocol.
        # all_non_empty() checks only these — external clients (e.g. tm_id=99)
        # must not block the release condition.
        self._core_tm_ids: frozenset[int] = frozenset(known_tm_ids)
        # Each entry: list of (sort_key_tuple, Operation)
        self._queues: dict[int, list[tuple]] = {tm_id: [] for tm_id in known_tm_ids}

    def enqueue(self, op: Operation) -> None:
        """Insert op into Q^op.tm_id_s, keyed by (ts.counter, ts.site_id, op_seq)."""
        sort_key = (op.ts.counter, op.ts.site_id, op.op_seq)
        with self._lock:
            if op.tm_id not in self._queues:
                self._queues[op.tm_id] = []
            heapq.heappush(self._queues[op.tm_id], (sort_key, op.tx_id, op))

    def register_tm(self, tm_id: int) -> None:
        """Add a new TM queue at runtime (e.g., when a peer announces itself)."""
        with self._lock:
            if tm_id not in self._queues:
                self._queues[tm_id] = []

    def all_non_empty(self) -> bool:
        """True iff every Q^t_s has at least one entry.

        This is the extremely-conservative release condition:
        Reference: Ozsu & Valduriez 2020, Section 5.2.2.2, p. 202.
        """
        with self._lock:
            return bool(self._core_tm_ids) and all(
                len(self._queues.get(tm_id, [])) > 0 for tm_id in self._core_tm_ids
            )

    def pop_min(self) -> Operation | None:
        """Pop the op with min ts across all queue heads.

        Returns None if any queue is empty (condition not met yet).
        """
        with self._lock:
            if not all(len(self._queues.get(t, [])) > 0 for t in self._core_tm_ids):
                return None
            min_key: tuple | None = None
            min_tm: int | None = None
            for tm_id, q in self._queues.items():
                if not q:
                    continue
                head_key = q[0][0]
                if min_key is None or head_key < min_key:
                    min_key = head_key
                    min_tm = tm_id
            if min_tm is None:
                return None
            _, _tx_id, op = heapq.heappop(self._queues[min_tm])
            return op

    def peek_min_ts(self) -> tuple[int, int] | None:
        """Return (counter, site_id) of the globally-minimum head ts, or None."""
        with self._lock:
            result: tuple[int, int] | None = None
            for q in self._queues.values():
                if not q:
                    return None
                key = q[0][0]  # (counter, site_id, op_seq)
                ts_pair = (key[0], key[1])
                if result is None or ts_pair < result:
                    result = ts_pair
            return result
