"""Conservative Timestamp Ordering scheduler — extremely-conservative variant."""

from __future__ import annotations

import asyncio
import logging
import time

from src.common.clock_sync import ClockSync
from src.common.messages import DummyMessage, Operation, OpResult, OpType
from src.dp.data_processor import DataProcessor
from src.scheduler.queue_manager import QueueManager

logger = logging.getLogger(__name__)


class ConservativeScheduler:
    """Extremely-conservative TO scheduler per Section 5.2.2.2.

    Release rule: op is dispatched to DP only when ALL Q^t_s are non-empty
    AND op has the minimum ts across all queue heads — guaranteeing no smaller
    ts will ever arrive, thus making abort impossible.

    Reference: Ozsu & Valduriez 2020, Section 5.2.2.2, p. 201-203,
    extends Algorithm 5.5 BTO-SC (p. 200).
    """

    def __init__(
        self,
        site_id: int,
        queues: QueueManager,
        dp: DataProcessor,
        stall_warn_ms: int = 5000,
        clock: ClockSync | None = None,
    ) -> None:
        self._site_id = site_id
        self._queues = queues
        self._dp = dp
        self._stall_warn_ms = stall_warn_ms
        # Observing incoming op timestamps advances the local clock so that
        # future dummies carry a ts > any op seen, allowing external-TM ops
        # to eventually become the global minimum (§5.2.2.2 timestamp advance).
        self._clock = clock
        # Per-op futures: key = (tx_id, op_seq) -> Future[OpResult]
        self._pending: dict[tuple[str, int], asyncio.Future[OpResult]] = {}
        self._new_op_event: asyncio.Event | None = None

    def _event(self) -> asyncio.Event:
        # Lazy-init inside the running loop so it binds to the correct loop.
        if self._new_op_event is None:
            self._new_op_event = asyncio.Event()
        return self._new_op_event

    async def submit(self, op: Operation) -> OpResult:
        """Enqueue op into Q^op.tm_id_s; block until release_loop dispatches it."""
        if self._clock is not None:
            # Advance local clock so subsequent dummies carry ts > op.ts,
            # allowing this op to eventually win the global-min race.
            self._clock.observe(op.ts)
        loop = asyncio.get_event_loop()
        future: asyncio.Future[OpResult] = loop.create_future()
        key = (op.tx_id, op.op_seq)
        self._pending[key] = future
        self._queues.enqueue(op)
        self._event().set()
        return await future

    async def submit_dummy(self, msg: DummyMessage) -> None:
        """Enqueue dummy sentinel to advance min_future_ts for msg.tm_id's queue."""
        if self._clock is not None:
            # Observing peer dummy ts advances local clock so our own dummies
            # carry a ts > incoming peer ts, propagating the frontier.
            self._clock.observe(msg.ts)
        # Dummy ops use op_seq=-1 to avoid collision with real ops
        dummy_op = Operation(
            type=OpType.DUMMY,
            ts=msg.ts,
            tm_id=msg.tm_id,
            tx_id=f"__dummy__{msg.tm_id}",
            op_seq=-1,
        )
        self._queues.enqueue(dummy_op)
        self._event().set()

    async def release_loop(self) -> None:
        """Main loop: block until all_non_empty(); pop min-ts op; dispatch to DP.

        Runs forever as an asyncio Task. Logs a warning if stall exceeds
        STALL_WARN_MS without progress.
        """
        stall_start_ms: float | None = None

        while True:
            if self._queues.all_non_empty():
                stall_start_ms = None
                op = self._queues.pop_min()
                if op is None:
                    # Race: another coroutine emptied the queue between check and pop
                    await asyncio.sleep(0)
                    continue

                if op.type == OpType.DUMMY:
                    # Dummy just unblocks the queue; no DP dispatch, no future to resolve
                    continue

                result = await self._dispatch(op)
                key = (op.tx_id, op.op_seq)
                future = self._pending.pop(key, None)
                if future is not None and not future.done():
                    future.set_result(result)
            else:
                now_ms = time.monotonic() * 1000
                if stall_start_ms is None:
                    stall_start_ms = now_ms
                elif now_ms - stall_start_ms >= self._stall_warn_ms:
                    logger.warning(
                        "stall detected: not all queues non-empty for %.0fms",
                        now_ms - stall_start_ms,
                        extra={
                            "site": self._site_id,
                            "ts": None,
                            "op": "STALL",
                            "tx_id": "",
                        },
                    )
                    stall_start_ms = now_ms  # Reset to avoid log flood

                self._event().clear()
                try:
                    await asyncio.wait_for(self._event().wait(), timeout=0.05)
                except asyncio.TimeoutError:
                    pass

    async def _dispatch(self, op: Operation) -> OpResult:
        """Forward op to DataProcessor; propagate result back to TM."""
        if op.type == OpType.READ:
            assert op.item is not None
            return self._dp.apply_read(op.item, op.ts)
        if op.type == OpType.WRITE:
            assert op.item is not None
            return self._dp.apply_write(op.item, op.value or "", op.ts)
        if op.type == OpType.COMMIT:
            return OpResult(ok=True)
        return OpResult(ok=False, error="UNKNOWN_OP_TYPE")
