"""Transaction latency collector and JSON reporter."""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field


@dataclass
class TxRecord:
    tx_id: str
    begin_ns: int = 0
    commit_ns: int = 0
    restarts: int = 0

    @property
    def latency_ms(self) -> float:
        """Wall-clock latency from begin() to commit() in milliseconds."""
        return (self.commit_ns - self.begin_ns) / 1_000_000


class LatencyCollector:
    """Record per-transaction timing with time.perf_counter_ns.

    Measures from TM.begin() to TM.commit() — full round-trip including
    queue wait (CTO) or restart overhead (Basic TO).
    """

    def __init__(self) -> None:
        self._records: dict[str, TxRecord] = {}

    def begin(self, tx_id: str) -> None:
        """Record begin_ns = perf_counter_ns()."""
        self._records[tx_id] = TxRecord(tx_id=tx_id, begin_ns=time.perf_counter_ns())

    def commit(self, tx_id: str) -> None:
        """Record commit_ns = perf_counter_ns()."""
        rec = self._records.get(tx_id)
        if rec is not None:
            rec.commit_ns = time.perf_counter_ns()

    def record_restart(self, tx_id: str) -> None:
        rec = self._records.get(tx_id)
        if rec is not None:
            rec.restarts += 1

    def summary(self) -> dict:
        """Return dict with avg_ms, p50_ms, p95_ms, p99_ms, max_ms, total_restarts."""
        completed = [r for r in self._records.values() if r.commit_ns > 0]
        if not completed:
            return {
                "avg_ms": 0,
                "p50_ms": 0,
                "p95_ms": 0,
                "p99_ms": 0,
                "max_ms": 0,
                "total_restarts": 0,
                "completed": 0,
            }
        latencies = sorted(r.latency_ms for r in completed)
        n = len(latencies)
        total_restarts = sum(r.restarts for r in self._records.values())
        return {
            "avg_ms": round(sum(latencies) / n, 3),
            "p50_ms": round(statistics.median(latencies), 3),
            "p95_ms": round(latencies[min(int(n * 0.95), n - 1)], 3),
            "p99_ms": round(latencies[min(int(n * 0.99), n - 1)], 3),
            "max_ms": round(latencies[-1], 3),
            "total_restarts": total_restarts,
            "completed": n,
        }

    def dump(self, path: str) -> None:
        """Write summary + raw records to JSON file at path."""
        data = self.summary()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
