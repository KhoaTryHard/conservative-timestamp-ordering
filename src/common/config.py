"""Per-site runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SiteConfig:
    """Single source of truth for per-site runtime settings."""

    site_id: int
    sched_mode: str
    dummy_interval_ms: int
    stall_warn_ms: int
    db_path: str
    peer_urls: list[str]

    @classmethod
    def from_env(cls) -> "SiteConfig":
        """Build SiteConfig from process env. Missing required vars raise KeyError."""
        site_id = int(os.environ["SITE_ID"])
        sched_mode = os.environ.get("SCHED_MODE", "cto")
        dummy_interval_ms = int(os.environ.get("DUMMY_INTERVAL_MS", "50"))
        stall_warn_ms = int(os.environ.get("STALL_WARN_MS", "5000"))
        db_path = os.environ["DB_PATH"]
        peer_urls_raw = os.environ["PEER_URLS"]
        peer_urls = [u.strip() for u in peer_urls_raw.split(",") if u.strip()]
        return cls(
            site_id=site_id,
            sched_mode=sched_mode,
            dummy_interval_ms=dummy_interval_ms,
            stall_warn_ms=stall_warn_ms,
            db_path=db_path,
            peer_urls=peer_urls,
        )
