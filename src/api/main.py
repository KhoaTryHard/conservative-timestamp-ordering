"""FastAPI application factory — one instance per site container."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from src.api.routers import build_router
from src.common.clock_sync import ClockSync
from src.common.config import SiteConfig
from src.common.dummy_msg import DummyMessageGenerator
from src.dp.data_processor import DataProcessor
from src.scheduler.queue_manager import QueueManager
from src.scheduler.scheduler_basic_to import BasicTOScheduler
from src.scheduler.scheduler_cto import ConservativeScheduler
from src.tm.transaction_manager import TransactionManager

logger = logging.getLogger(__name__)

_NUM_SITES = 3


def create_app() -> FastAPI:
    """Read env, wire TM/Scheduler/DP, mount router. Called by uvicorn --factory."""
    config = SiteConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        dp = DataProcessor(config.db_path)
        dp.init_schema()

        clock = ClockSync(site_id=config.site_id)

        # Build site_id -> URL map
        all_sites = list(range(_NUM_SITES))
        peer_sites = sorted(s for s in all_sites if s != config.site_id)
        scheduler_urls: dict[int, str] = {config.site_id: "http://localhost:8000"}
        for i, peer_site in enumerate(peer_sites):
            if i < len(config.peer_urls):
                scheduler_urls[peer_site] = config.peer_urls[i]

        # Build scheduler
        release_task: asyncio.Task | None = None
        if config.sched_mode == "cto":
            queues = QueueManager(known_tm_ids=all_sites)
            scheduler: ConservativeScheduler | BasicTOScheduler = ConservativeScheduler(
                site_id=config.site_id,
                queues=queues,
                dp=dp,
                stall_warn_ms=config.stall_warn_ms,
                clock=clock,
            )
            release_task = asyncio.create_task(scheduler.release_loop())
        else:
            scheduler = BasicTOScheduler(site_id=config.site_id, dp=dp)

        app.state.scheduler = scheduler
        app.state.config = config

        # Build TM (used by experiment runner calling into the local site)
        tm = TransactionManager(
            tm_id=config.site_id,
            clock=clock,
            scheduler_urls=scheduler_urls,
        )
        app.state.tm = tm

        # CTO needs dummy heartbeats to keep every scheduler queue non-empty.
        # Basic TO executes immediately and does not use the dummy protocol.
        dummy_gen: DummyMessageGenerator | None = None
        dummy_task: asyncio.Task | None = None
        if config.sched_mode == "cto":
            all_scheduler_urls = ["http://localhost:8000"] + list(config.peer_urls)
            dummy_gen = DummyMessageGenerator(
                tm_id=config.site_id,
                clock=clock,
                peer_urls=all_scheduler_urls,
                interval_ms=config.dummy_interval_ms,
            )
            dummy_task = asyncio.create_task(dummy_gen.run_forever())

        logger.info(
            "site %d started sched_mode=%s",
            config.site_id,
            config.sched_mode,
            extra={"site": config.site_id, "ts": None, "op": "STARTUP", "tx_id": ""},
        )

        try:
            yield
        finally:
            if dummy_gen is not None:
                dummy_gen.stop()
            if dummy_task is not None:
                dummy_task.cancel()
            if release_task is not None:
                release_task.cancel()
            await tm.close()
            dp.close()

    app = FastAPI(
        title=f"cto-site-{config.site_id}",
        description="Conservative Timestamp Ordering — Automated Manufacturing",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(build_router(config))
    return app
