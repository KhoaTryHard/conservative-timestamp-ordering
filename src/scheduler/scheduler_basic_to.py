"""Basic Timestamp Ordering scheduler — baseline for Project #24 comparison."""

from __future__ import annotations

import asyncio
import logging

from src.common.messages import Operation, OpResult, OpType
from src.dp.data_processor import DataProcessor

logger = logging.getLogger(__name__)


class BasicTOScheduler:
    """Basic TO scheduler: accept op if ts passes rts/wts check; abort otherwise.

    Unlike CTO, this scheduler does NOT buffer ops — each op is evaluated
    immediately on arrival. Violated ts causes rejection (TM must restart
    with a new, larger ts).

    Reference: Ozsu & Valduriez 2020, Section 5.2.2.1, p. 198-201,
    Algorithm 5.5 BTO-SC (p. 200).
    """

    def __init__(self, site_id: int, dp: DataProcessor) -> None:
        self._site_id = site_id
        self._dp = dp
        self._lock = asyncio.Lock()

    async def submit(self, op: Operation) -> OpResult:
        """Compare op.ts with rts(item)/wts(item); reject if violated.

        READ:  reject if op.ts < wts(item).
        WRITE: reject if op.ts < rts(item) or op.ts < wts(item).
        On reject, return OpResult(ok=False, error="RESTART") so TM retries.

        Reference: Ozsu & Valduriez 2020, Algorithm 5.5 BTO-SC, p. 200.
        """
        async with self._lock:
            if op.type == OpType.READ:
                wts = self._dp.get_wts(op.item)
                if wts is not None and op.ts < wts:
                    logger.info(
                        "basic_to reject READ ts=%s wts=%s tx_id=%s",
                        op.ts.as_tuple(),
                        wts.as_tuple(),
                        op.tx_id,
                        extra={"site": self._site_id, "ts": op.ts.as_tuple(),
                               "op": "READ_REJECT", "tx_id": op.tx_id},
                    )
                    return OpResult(ok=False, error="RESTART")
                return self._dp.apply_read(op.item, op.ts)

            if op.type == OpType.WRITE:
                rts = self._dp.get_rts(op.item)
                wts = self._dp.get_wts(op.item)
                if (rts is not None and op.ts < rts) or (wts is not None and op.ts < wts):
                    logger.info(
                        "basic_to reject WRITE ts=%s tx_id=%s",
                        op.ts.as_tuple(),
                        op.tx_id,
                        extra={"site": self._site_id, "ts": op.ts.as_tuple(),
                               "op": "WRITE_REJECT", "tx_id": op.tx_id},
                    )
                    return OpResult(ok=False, error="RESTART")
                return self._dp.apply_write(op.item, op.value or "", op.ts)

            if op.type == OpType.COMMIT:
                return OpResult(ok=True)

            return OpResult(ok=False, error="UNKNOWN_OP_TYPE")
