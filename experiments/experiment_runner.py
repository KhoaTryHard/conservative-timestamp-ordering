"""Benchmark runner: send N transactions against the cluster, dump latency JSON.

Usage:
    python -m experiments.experiment_runner --mode cto --txs 1000 --out experiments/results/cto.json
    python -m experiments.experiment_runner --mode basic_to --txs 1000 --out experiments/results/basic_to.json
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from experiments.metrics import LatencyCollector
from src.common.clock_sync import ClockSync
from src.common.messages import Operation, OpResult, OpType, Timestamp
from src.tm.transaction_manager import site_for_machine

SITE_URLS = {
    0: "http://localhost:8001",
    1: "http://localhost:8002",
    2: "http://localhost:8003",
}
SITE_DB_FILES = {
    0: "site_a.db",
    1: "site_b.db",
    2: "site_c.db",
}

# Experiment runner acts as a dedicated TM with tm_id=99 and site_id=3
_RUNNER_TM_ID = 99
_RUNNER_SITE_ID = 3
_MAX_RETRIES = 3

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkloadOp:
    machine_id: str
    step_id: int
    value: str


class RestartRequired(Exception):
    """Raised when Basic TO rejects an op and the full transaction must restart."""


async def _post_op(client: httpx.AsyncClient, site: int, op: Operation) -> OpResult:
    url = SITE_URLS[site]
    resp = await client.post(
        f"{url}/op",
        content=op.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return OpResult.model_validate(resp.json())


async def _verify_cluster_mode(client: httpx.AsyncClient, expected_mode: str) -> None:
    """Fail fast if the running Docker cluster does not match --mode."""
    for site, url in SITE_URLS.items():
        try:
            resp = await client.get(f"{url}/healthz")
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"Cannot verify scheduler mode for site {site} at {url}. "
                f"Start the cluster with: SCHED_MODE={expected_mode} docker compose up --build"
            ) from exc

        actual_mode = payload.get("mode")
        if actual_mode != expected_mode:
            raise RuntimeError(
                f"Scheduler mode mismatch for site {site} at {url}: "
                f"expected {expected_mode!r}, got {actual_mode!r}. "
                f"Restart the cluster with: SCHED_MODE={expected_mode} docker compose up --build"
            )


def _build_workload(rng: random.Random, dataset_items: list[tuple[str, int]]) -> list[WorkloadOp]:
    """Build one deterministic transaction workload from the experiment RNG."""
    roll = rng.random()

    if roll < 0.60:
        machine_id, step_id = rng.choice(dataset_items)
        return [
            WorkloadOp(
                machine_id=machine_id,
                step_id=step_id,
                value="IN_PROGRESS",
            )
        ]

    if roll < 0.90:
        machine_id, step_id = rng.choice(dataset_items)
        return [
            WorkloadOp(
                machine_id=machine_id,
                step_id=step_id,
                value="COMPLETED",
            )
        ]

    m1, step1 = rng.choice(dataset_items)
    m2, step2 = rng.choice(dataset_items)
    return [
        WorkloadOp(
            machine_id=m1,
            step_id=step1,
            value="IN_PROGRESS",
        ),
        WorkloadOp(
            machine_id=m2,
            step_id=step2,
            value="HANDOFF",
        ),
    ]


def _load_dataset_items(data_dir: str = "data") -> list[tuple[str, int]]:
    """Load valid (MachineID, StepID) pairs from generated SQLite fragments."""
    items: list[tuple[str, int]] = []
    for site, filename in SITE_DB_FILES.items():
        db_path = Path(data_dir) / filename
        if not db_path.exists():
            raise RuntimeError(
                f"Missing dataset fragment {db_path}. "
                "Run: python -m data.data_generator --rows 10000 --seed 42 --out data/"
            )
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT step_id, machine_id FROM Assembly_Line_Steps").fetchall()
        finally:
            conn.close()

        for step_id, machine_id in rows:
            expected_site = site_for_machine(machine_id)
            if expected_site != site:
                raise RuntimeError(
                    f"Dataset partition mismatch for {machine_id}: "
                    f"{db_path} is site {site}, stable hash routes to {expected_site}. "
                    "Regenerate dataset with: "
                    "python -m data.data_generator --rows 10000 --seed 42 --out data/"
                )
            items.append((machine_id, step_id))

    if not items:
        raise RuntimeError("Dataset is empty; regenerate it before running experiments.")
    return items


async def _submit_workload(
    client: httpx.AsyncClient,
    tx_id: str,
    ts: Timestamp,
    workload: list[WorkloadOp],
    mode: str,
) -> None:
    """Submit every op in a transaction; Basic TO restart rejects the whole tx."""
    for seq, workload_op in enumerate(workload, start=1):
        site = site_for_machine(workload_op.machine_id)
        op = Operation(
            type=OpType.WRITE,
            item=workload_op.step_id,
            value=workload_op.value,
            ts=ts,
            tm_id=_RUNNER_TM_ID,
            tx_id=tx_id,
            op_seq=seq,
        )
        result = await _post_op(client, site, op)
        if result.ok:
            continue
        if mode == "basic_to" and result.error == "RESTART":
            raise RestartRequired
        raise RuntimeError(
            f"{mode} op failed tx_id={tx_id} seq={seq} site={site} error={result.error!r}"
        )


async def run_experiment(
    mode: str,
    num_txs: int,
    seed: int,
    collector: LatencyCollector,
) -> None:
    """Submit num_txs transactions against a running cluster; collect timings.

    Workload mix (representative of Automated Manufacturing):
        60% T_advance  (single-site WRITE Status=IN_PROGRESS)
        30% T_complete (single-site WRITE Status=COMPLETED)
        10% T_handoff  (cross-site WRITE at two sites)
    """
    rng = random.Random(seed)
    clock = ClockSync(site_id=_RUNNER_SITE_ID)

    dataset_items = _load_dataset_items()

    async with httpx.AsyncClient(timeout=120.0) as client:
        await _verify_cluster_mode(client, mode)

        for _ in range(num_txs):
            tx_id = str(uuid.uuid4())
            workload = _build_workload(rng, dataset_items)
            collector.begin(tx_id)
            retries = 0

            while True:
                ts = clock.next()
                try:
                    await _submit_workload(client, tx_id, ts, workload, mode)
                    collector.commit(tx_id)
                    break
                except RestartRequired:
                    collector.record_restart(tx_id)
                    retries += 1
                    if retries > _MAX_RETRIES:
                        raise RuntimeError(
                            f"Basic TO exceeded max retries tx_id={tx_id} "
                            f"max_retries={_MAX_RETRIES}"
                        )
                except Exception:
                    logger.exception("transaction failed tx_id=%s mode=%s", tx_id, mode)
                    raise


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="CTO/Basic-TO latency benchmark")
    parser.add_argument("--mode", choices=["cto", "basic_to"], required=True)
    parser.add_argument("--txs", type=int, default=1000, help="Number of transactions")
    parser.add_argument("--seed", type=int, default=42, help="Workload RNG seed")
    parser.add_argument("--out", type=str, required=True, help="Output JSON path")
    args = parser.parse_args()

    collector = LatencyCollector()
    asyncio.run(run_experiment(args.mode, args.txs, args.seed, collector))
    collector.dump(args.out)
    summary = collector.summary()
    print(
        f"[done] mode={args.mode} txs={summary['completed']}"
        f" avg={summary['avg_ms']}ms p95={summary['p95_ms']}ms"
        f" restarts={summary['total_restarts']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
