"""Periodic dummy-message heartbeat keeping remote schedulers unblocked."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

import httpx

from src.common.clock_sync import ClockSync
from src.common.messages import DummyMessage

logger = logging.getLogger(__name__)


class DummyMessageGenerator:
    """Broadcast DummyMessage(ts=clock.peek()) to all peer schedulers every interval_ms.

    Reference: Ozsu & Valduriez 2020, Section 5.2.2.2, p. 202 (idle TM MUST emit dummy ops).
    """

    def __init__(
        self,
        tm_id: int,
        clock: ClockSync,
        peer_urls: Iterable[str],
        interval_ms: int = 50,
    ) -> None:
        self._tm_id = tm_id
        self._clock = clock
        self._peer_urls = list(peer_urls)
        self._interval_ms = interval_ms
        self._running = False

    async def run_forever(self) -> None:
        """Loop: sleep interval_ms, then POST /dummy to each peer."""
        self._running = True
        async with httpx.AsyncClient(timeout=5.0) as client:
            while self._running:
                await asyncio.sleep(self._interval_ms / 1000)
                msg = DummyMessage(ts=self._clock.peek(), tm_id=self._tm_id)
                payload = msg.model_dump_json()
                for url in self._peer_urls:
                    try:
                        await client.post(
                            f"{url}/dummy",
                            content=payload,
                            headers={"Content-Type": "application/json"},
                        )
                    except Exception as exc:
                        logger.debug(
                            "dummy POST to %s failed: %s",
                            url,
                            exc,
                            extra={
                                "site": self._tm_id,
                                "ts": None,
                                "op": "DUMMY_FAIL",
                                "tx_id": "",
                            },
                        )

    def stop(self) -> None:
        self._running = False
