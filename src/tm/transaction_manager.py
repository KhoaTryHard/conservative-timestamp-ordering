"""Transaction Manager: assigns timestamps and dispatches ops to remote schedulers."""

from __future__ import annotations

import hashlib
import uuid

import httpx

from src.common.clock_sync import ClockSync
from src.common.messages import Operation, OpResult, OpType


class TransactionManager:
    """Issues transactions and routes ops to the owning site's scheduler via HTTP.

    Timestamp is a (counter, site_id) pair from ClockSync, providing global
    total order without NTP. When idle beyond DUMMY_INTERVAL_MS, TM delegates
    to DummyMessageGenerator to broadcast heartbeats.

    Reference: Ozsu & Valduriez 2020, Section 5.2.2.1, p. 199,
    Algorithm 5.4 BTO-TM (p. 199).
    """

    def __init__(
        self,
        tm_id: int,
        clock: ClockSync,
        scheduler_urls: dict[int, str],
    ) -> None:
        self._tm_id = tm_id
        self._clock = clock
        # site_id -> base URL (e.g. http://cto-site-b:8000)
        self._scheduler_urls = scheduler_urls
        # Active transactions: tx_id -> {ts, touched_sites, op_seq}
        self._txs: dict[str, dict] = {}
        self._client = httpx.AsyncClient(timeout=60.0)

    async def begin(self) -> str:
        """Allocate tx_id, snapshot ts from clock. Return tx_id."""
        tx_id = str(uuid.uuid4())
        ts = self._clock.next()
        self._txs[tx_id] = {"ts": ts, "touched_sites": set(), "op_seq": 0}
        return tx_id

    async def read(self, tx_id: str, step_id: int, machine_id: str) -> str:
        """Route READ(step_id) to site_for_machine(machine_id). Return Status value."""
        tx = self._txs[tx_id]
        site = site_for_machine(machine_id)
        tx["op_seq"] += 1
        op = Operation(
            type=OpType.READ,
            item=step_id,
            ts=tx["ts"],
            tm_id=self._tm_id,
            tx_id=tx_id,
            op_seq=tx["op_seq"],
        )
        tx["touched_sites"].add(site)
        result = await self._post_op(site, op)
        return result.value or ""

    async def write(self, tx_id: str, step_id: int, machine_id: str, status: str) -> None:
        """Route WRITE(step_id, status) to site_for_machine(machine_id)."""
        tx = self._txs[tx_id]
        site = site_for_machine(machine_id)
        tx["op_seq"] += 1
        op = Operation(
            type=OpType.WRITE,
            item=step_id,
            value=status,
            ts=tx["ts"],
            tm_id=self._tm_id,
            tx_id=tx_id,
            op_seq=tx["op_seq"],
        )
        tx["touched_sites"].add(site)
        await self._post_op(site, op)

    async def commit(self, tx_id: str) -> None:
        """Broadcast COMMIT to all touched sites; record commit_ns for metrics."""
        tx = self._txs.pop(tx_id)
        for site in tx["touched_sites"]:
            tx["op_seq"] += 1
            op = Operation(
                type=OpType.COMMIT,
                ts=tx["ts"],
                tm_id=self._tm_id,
                tx_id=tx_id,
                op_seq=tx["op_seq"],
            )
            await self._post_op(site, op)

    async def _post_op(self, site: int, op: Operation) -> OpResult:
        url = self._scheduler_urls[site]
        resp = await self._client.post(
            f"{url}/op",
            content=op.model_dump_json(),
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return OpResult.model_validate(resp.json())

    async def close(self) -> None:
        await self._client.aclose()


def site_for_machine(machine_id: str, num_sites: int = 3) -> int:
    """Stable hash partition: site_index = stable_hash(machine_id) % num_sites.

    Single source of truth for data placement. Used by TM and data_generator.
    NEVER change the hash function without also updating tests and re-partitioning data.
    """
    digest = hashlib.blake2b(machine_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % num_sites
