"""Benchmark runner: send N transactions against the cluster, dump latency JSON.

Usage:
    python -m experiments.experiment_runner --mode cto --txs 1000 --out experiments/results/cto.json
    python -m experiments.experiment_runner --mode basic_to --txs 1000 --out experiments/results/basic_to.json
"""

from __future__ import annotations

import argparse
import asyncio
import random
import uuid

import httpx

from experiments.metrics import LatencyCollector
from src.common.clock_sync import ClockSync
from src.common.messages import Operation, OpResult, OpType
from src.tm.transaction_manager import site_for_machine

SITE_URLS = {
    0: "http://localhost:8001",
    1: "http://localhost:8002",
    2: "http://localhost:8003",
}

# Experiment runner acts as a dedicated TM with tm_id=99 and site_id=3
_RUNNER_TM_ID = 99
_RUNNER_SITE_ID = 3


async def _post_op(client: httpx.AsyncClient, site: int, op: Operation) -> OpResult:
    url = SITE_URLS[site]
    resp = await client.post(
        f"{url}/op",
        content=op.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return OpResult.model_validate(resp.json())


async def run_experiment(
    mode: str,
    num_txs: int,
    seed: int,
    collector: LatencyCollector,
) -> None:
    """Submit num_txs transactions against a running cluster; collect timings.

    Workload mix (representative of Automated Manufacturing):
        60% T_advance  (single-site WRITE Status=IN_PROGRESS)
        30% T_complete (single-site WRITE Status=DONE)
        10% T_handoff  (cross-site WRITE at two sites)
    """
    rng = random.Random(seed)
    clock = ClockSync(site_id=_RUNNER_SITE_ID)

    # Machine population: 100 distinct machines
    machine_ids = [f"M-{i}" for i in range(1, 101)]

    async with httpx.AsyncClient(timeout=120.0) as client:
        for _ in range(num_txs):
            tx_id = str(uuid.uuid4())
            ts = clock.next()
            collector.begin(tx_id)

            roll = rng.random()

            if roll < 0.60:
                # T_advance: single-site WRITE IN_PROGRESS
                machine_id = rng.choice(machine_ids)
                step_id = rng.randint(1, 10_000)
                site = site_for_machine(machine_id)
                op = Operation(
                    type=OpType.WRITE,
                    item=step_id,
                    value="IN_PROGRESS",
                    ts=ts,
                    tm_id=_RUNNER_TM_ID,
                    tx_id=tx_id,
                    op_seq=1,
                )
                try:
                    result = await _post_op(client, site, op)
                    if not result.ok and result.error == "RESTART":
                        collector.record_restart(tx_id)
                        ts = clock.next()
                        op = op.model_copy(update={"ts": ts})
                        await _post_op(client, site, op)
                except Exception:
                    pass

            elif roll < 0.90:
                # T_complete: single-site WRITE COMPLETED
                machine_id = rng.choice(machine_ids)
                step_id = rng.randint(1, 10_000)
                site = site_for_machine(machine_id)
                op = Operation(
                    type=OpType.WRITE,
                    item=step_id,
                    value="COMPLETED",
                    ts=ts,
                    tm_id=_RUNNER_TM_ID,
                    tx_id=tx_id,
                    op_seq=1,
                )
                try:
                    result = await _post_op(client, site, op)
                    if not result.ok and result.error == "RESTART":
                        collector.record_restart(tx_id)
                        ts = clock.next()
                        op = op.model_copy(update={"ts": ts})
                        await _post_op(client, site, op)
                except Exception:
                    pass

            else:
                # T_handoff: cross-site WRITE at two different sites
                m1 = rng.choice(machine_ids)
                m2 = rng.choice(machine_ids)
                step1 = rng.randint(1, 10_000)
                step2 = rng.randint(1, 10_000)
                for machine_id, step_id, val, seq in [
                    (m1, step1, "IN_PROGRESS", 1),
                    (m2, step2, "HANDOFF", 2),
                ]:
                    site = site_for_machine(machine_id)
                    op = Operation(
                        type=OpType.WRITE,
                        item=step_id,
                        value=val,
                        ts=ts,
                        tm_id=_RUNNER_TM_ID,
                        tx_id=tx_id,
                        op_seq=seq,
                    )
                    try:
                        await _post_op(client, site, op)
                    except Exception:
                        pass

            collector.commit(tx_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="CTO/Basic-TO latency benchmark")
    parser.add_argument("--mode", choices=["cto", "basic_to"], required=True)
    parser.add_argument("--txs", type=int, default=1000, help="Number of transactions")
    parser.add_argument("--seed", type=int, default=42, help="Workload RNG seed")
    parser.add_argument("--out", type=str, required=True, help="Output JSON path")
    parser.add_argument(
        "--dummy-interval-ms",
        type=int,
        default=50,
        dest="dummy_interval_ms",
        help="Override DUMMY_INTERVAL_MS for this run (sweep experiment)",
    )
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
