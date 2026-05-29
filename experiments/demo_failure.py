"""Deterministic failure demo for CTO stall/resume behavior.

Usage:
    python -m experiments.demo_failure --mode cto --seed 42 --kill-site 1 \
      --kill-delay-sec 5 --restart-delay-sec 8 --out experiments/results/cto_failure.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from experiments.experiment_runner import SITE_URLS, _load_dataset_items, _post_op
from experiments.experiment_runner import _verify_cluster_mode
from src.common.clock_sync import ClockSync
from src.common.messages import Operation, OpType
from src.tm.transaction_manager import site_for_machine

CONTAINER_NAMES = {
    0: "cto-site-a",
    1: "cto-site-b",
    2: "cto-site-c",
}
_RUNNER_TM_ID = 99
_RUNNER_SITE_ID = 3

logger = logging.getLogger(__name__)


@dataclass
class DemoStats:
    """Mutable counters and observations for the failure demo result JSON."""

    total_submitted: int = 0
    total_completed: int = 0
    total_restarts: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    expected_failures: list[dict] = field(default_factory=list)
    unexpected_failures: list[dict] = field(default_factory=list)
    stall_probe: dict | None = None

    @property
    def average_latency_ms(self) -> float | None:
        """Return mean completed-op latency, or None when no op completed."""
        if not self.latencies_ms:
            return None
        return round(sum(self.latencies_ms) / len(self.latencies_ms), 3)


def get_container_name(site: int) -> str:
    """Return Docker container name for a site id."""
    try:
        return CONTAINER_NAMES[site]
    except KeyError as exc:
        raise ValueError(
            f"Unknown site id {site}; expected one of {sorted(CONTAINER_NAMES)}"
        ) from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the failure demo."""
    parser = argparse.ArgumentParser(description="Deterministic CTO failure demo")
    parser.add_argument("--mode", choices=["cto", "basic_to"], required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--kill-site", type=int, default=1, choices=sorted(CONTAINER_NAMES))
    parser.add_argument("--kill-delay-sec", type=float, default=5.0)
    parser.add_argument("--restart-delay-sec", type=float, default=8.0)
    parser.add_argument("--out", type=str, required=True)
    parser.add_argument(
        "--manual-failure",
        action="store_true",
        help="Print docker kill/start commands instead of running them automatically",
    )
    parser.add_argument(
        "--probe-timeout-sec",
        type=float,
        default=3.0,
        help="HTTP timeout for live-site probes during the failure window",
    )
    parser.add_argument(
        "--resume-txs",
        type=int,
        default=5,
        help="Number of live-site transactions to submit after restart",
    )
    return parser.parse_args(argv)


def _items_for_sites(
    dataset_items: list[tuple[str, int]], sites: set[int]
) -> list[tuple[str, int]]:
    """Filter generated dataset items by owning site."""
    return [
        (machine_id, step_id)
        for machine_id, step_id in dataset_items
        if site_for_machine(machine_id) in sites
    ]


def _run_docker(command: str, container: str) -> None:
    """Run a docker lifecycle command and raise with useful output on failure."""
    try:
        subprocess.run(
            ["docker", command, container],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        stdout = exc.stdout.strip()
        details = stderr or stdout or str(exc)
        raise RuntimeError(f"docker {command} {container} failed: {details}") from exc


def _write_result(path: str, result: dict) -> None:
    """Write result JSON, creating the parent directory when needed."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)


async def _wait_for_site_health(
    client: httpx.AsyncClient,
    site: int,
    mode: str,
    timeout_sec: float = 30.0,
) -> None:
    """Wait until a restarted site serves /healthz with the expected mode."""
    url = SITE_URLS[site]
    deadline = time.monotonic() + timeout_sec
    last_error = ""
    while time.monotonic() < deadline:
        try:
            resp = await client.get(f"{url}/healthz")
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("mode") == mode:
                return
            last_error = f"mode={payload.get('mode')!r}"
        except Exception as exc:
            last_error = str(exc)
        await asyncio.sleep(0.5)
    raise RuntimeError(f"Site {site} at {url} did not recover in {timeout_sec}s: {last_error}")


async def _submit_one_op(
    client: httpx.AsyncClient,
    rng: random.Random,
    clock: ClockSync,
    items: list[tuple[str, int]],
    stats: DemoStats,
    phase: str,
    timeout_sec: float | None = None,
    timeout_expected: bool = False,
) -> bool:
    """Submit one deterministic WRITE to a selected live site."""
    machine_id, step_id = rng.choice(items)
    site = site_for_machine(machine_id)
    tx_id = str(uuid.uuid4())
    ts = clock.next()
    op = Operation(
        type=OpType.WRITE,
        item=step_id,
        value=f"DEMO_{phase.upper()}",
        ts=ts,
        tm_id=_RUNNER_TM_ID,
        tx_id=tx_id,
        op_seq=1,
    )

    started = time.perf_counter()
    stats.total_submitted += 1
    try:
        if timeout_sec is None:
            result = await _post_op(client, site, op)
        else:
            result = await asyncio.wait_for(_post_op(client, site, op), timeout=timeout_sec)
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        event = {
            "phase": phase,
            "site": site,
            "url": SITE_URLS[site],
            "tx_id": tx_id,
            "error": f"{type(exc).__name__}: {exc}",
        }
        logger.warning("request timed out phase=%s site=%s tx_id=%s", phase, site, tx_id)
        if timeout_expected:
            stats.expected_failures.append(event)
            return False
        stats.unexpected_failures.append(event)
        raise RuntimeError(
            f"Unexpected request timeout phase={phase} site={site} url={SITE_URLS[site]} "
            f"tx_id={tx_id}: {exc}"
        ) from exc
    except Exception as exc:
        event = {
            "phase": phase,
            "site": site,
            "url": SITE_URLS[site],
            "tx_id": tx_id,
            "error": f"{type(exc).__name__}: {exc}",
        }
        stats.unexpected_failures.append(event)
        logger.exception("request failed phase=%s site=%s tx_id=%s", phase, site, tx_id)
        raise RuntimeError(
            f"Unexpected request failure phase={phase} site={site} url={SITE_URLS[site]} "
            f"tx_id={tx_id}: {exc}"
        ) from exc

    latency_ms = (time.perf_counter() - started) * 1000
    if result.ok:
        stats.total_completed += 1
        stats.latencies_ms.append(latency_ms)
        return True
    if result.error == "RESTART":
        stats.total_restarts += 1
    raise RuntimeError(
        f"Scheduler rejected op phase={phase} site={site} tx_id={tx_id} error={result.error!r}"
    )


async def _run_warmup(
    client: httpx.AsyncClient,
    rng: random.Random,
    clock: ClockSync,
    items: list[tuple[str, int]],
    stats: DemoStats,
    delay_sec: float,
) -> None:
    """Run live-site writes until the kill delay elapses."""
    deadline = time.monotonic() + delay_sec
    while time.monotonic() < deadline:
        await _submit_one_op(client, rng, clock, items, stats, phase="warmup")
        await asyncio.sleep(0.1)


def _build_result(
    args: argparse.Namespace,
    container: str,
    stats: DemoStats,
    downtime_ms: float | None,
) -> dict:
    """Build the final JSON payload without inventing stall observations."""
    return {
        "mode": args.mode,
        "seed": args.seed,
        "killed_site": args.kill_site,
        "killed_container": container,
        "kill_delay_sec": args.kill_delay_sec,
        "restart_delay_sec": args.restart_delay_sec,
        "manual_failure": args.manual_failure,
        "total_submitted": stats.total_submitted,
        "total_completed": stats.total_completed,
        "total_restarts": stats.total_restarts,
        "stall_observed": None,
        "stall_probe": stats.stall_probe,
        "failure_window_ms": None if downtime_ms is None else round(downtime_ms, 3),
        "downtime_ms": None if downtime_ms is None else round(downtime_ms, 3),
        "average_latency_ms": stats.average_latency_ms,
        "expected_failures": stats.expected_failures,
        "unexpected_failures": stats.unexpected_failures,
        "notes": (
            "CTO failure demo sends live-site probes while the killed site is down. "
            "A timeout to site_a/site_c during that window is consistent with CTO stall, "
            "but stall_observed remains null because this script does not read Docker logs; "
            "check container logs for 'stall detected'."
        ),
    }


async def run_demo(args: argparse.Namespace) -> dict:
    """Run the deterministic failure demo and return the result payload."""
    container = get_container_name(args.kill_site)
    live_sites = set(SITE_URLS) - {args.kill_site}
    rng = random.Random(args.seed)
    clock = ClockSync(site_id=_RUNNER_SITE_ID)
    stats = DemoStats()

    print("[1/8] Start validation")
    dataset_items = _load_dataset_items()
    live_items = _items_for_sites(dataset_items, live_sites)
    if not live_items:
        raise RuntimeError(f"No dataset items found for live sites {sorted(live_sites)}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        await _verify_cluster_mode(client, args.mode)
        print(f"[2/8] Cluster mode verified: {args.mode}")

        print(f"[3/8] Running warm-up workload for {args.kill_delay_sec}s")
        await _run_warmup(client, rng, clock, live_items, stats, args.kill_delay_sec)

        print(f"[4/8] Killing site_{args.kill_site}: {container}")
        if args.manual_failure:
            print(f"      Manual mode: run in Terminal 3: docker kill {container}")
            input("      Press Enter after the container is killed...")
        else:
            _run_docker("kill", container)
        killed_at = time.perf_counter()

        print("[5/8] Waiting for CTO stall window")
        probe_timeout = min(args.probe_timeout_sec, max(args.restart_delay_sec, 0.1))
        probe_completed = await _submit_one_op(
            client,
            rng,
            clock,
            live_items,
            stats,
            phase="failure_window",
            timeout_sec=probe_timeout,
            timeout_expected=True,
        )
        stats.stall_probe = {
            "target": "live site only",
            "completed": probe_completed,
            "timeout_sec": probe_timeout,
            "interpretation": (
                "timeout_on_live_site_is_consistent_with_cto_stall"
                if not probe_completed
                else "probe_completed_before_or_without_observable_stall"
            ),
        }
        remaining = max(args.restart_delay_sec - probe_timeout, 0)
        if remaining > 0:
            await asyncio.sleep(remaining)

        print(f"[6/8] Restarting site_{args.kill_site}: {container}")
        if args.manual_failure:
            print(f"      Manual mode: run in Terminal 3: docker start {container}")
            input("      Press Enter after the container is started...")
        else:
            _run_docker("start", container)
        restarted_at = time.perf_counter()
        downtime_ms = (restarted_at - killed_at) * 1000

        await _wait_for_site_health(client, args.kill_site, args.mode)

        print("[7/8] Running resume workload")
        for _ in range(args.resume_txs):
            await _submit_one_op(client, rng, clock, live_items, stats, phase="resume")

    result = _build_result(args, container, stats, downtime_ms)
    print(f"[8/8] Writing result JSON: {args.out}")
    _write_result(args.out, result)
    return result


def main() -> None:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parse_args()
    result = asyncio.run(run_demo(args))
    print(
        "[done]"
        f" mode={result['mode']}"
        f" submitted={result['total_submitted']}"
        f" completed={result['total_completed']}"
        f" restarts={result['total_restarts']}"
        f" downtime_ms={result['downtime_ms']}"
        f" -> {args.out}"
    )


if __name__ == "__main__":
    main()
