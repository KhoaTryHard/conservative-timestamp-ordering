"""FastAPI route definitions for the per-site CTO/Basic-TO HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from src.common.config import SiteConfig
from src.common.messages import DummyMessage, Operation, OpResult


def build_router(config: SiteConfig) -> APIRouter:
    """Return a configured APIRouter wired to Scheduler for this site."""
    router = APIRouter()

    @router.post("/op", response_model=OpResult)
    async def submit_op(op: Operation, request: Request) -> OpResult:
        """Receive R/W/COMMIT op from a remote TM; pass to local Scheduler."""
        scheduler = request.app.state.scheduler
        return await scheduler.submit(op)

    @router.post("/dummy", status_code=204)
    async def submit_dummy(msg: DummyMessage, request: Request) -> Response:
        """Receive dummy heartbeat; advance min_future_ts in CTO Scheduler queue."""
        if config.sched_mode == "cto":
            scheduler = request.app.state.scheduler
            await scheduler.submit_dummy(msg)
        return Response(status_code=204)

    @router.get("/healthz")
    async def healthz() -> dict:
        """Liveness probe — always returns 200 while process is alive."""
        return {"ok": True, "site_id": config.site_id, "mode": config.sched_mode}

    return router
