"""Synthetic dataset generator for Assembly_Line_Steps.

Usage:
    python -m data.data_generator --rows 10000 --seed 42 --out data/
"""

from __future__ import annotations

import argparse
import os
import random
import sqlite3

from src.tm.transaction_manager import site_for_machine

_SITE_FILES = ["site_a.db", "site_b.db", "site_c.db"]


def generate(rows: int, seed: int, out_dir: str) -> None:
    """Generate site_a.db, site_b.db, site_c.db with hash-partitioned rows.

    Each row: (StepID, MachineID, Status='PENDING').
    Partition: site_for_machine(machine_id) -> site index 0/1/2.
    Tables created: Assembly_Line_Steps + step_meta (rts=0, wts=0).
    """
    rng = random.Random(seed)
    num_machines = max(rows // 10, 1)

    # Bucket rows by site
    site_rows: dict[int, list[tuple[int, str, str]]] = {0: [], 1: [], 2: []}
    for step_id in range(1, rows + 1):
        machine_id = f"M-{rng.randint(1, num_machines)}"
        site = site_for_machine(machine_id)
        site_rows[site].append((step_id, machine_id, "PENDING"))

    os.makedirs(out_dir, exist_ok=True)

    for site_idx, rows_list in site_rows.items():
        db_path = os.path.join(out_dir, _SITE_FILES[site_idx])
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Assembly_Line_Steps (
                step_id    INTEGER PRIMARY KEY,
                machine_id TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'PENDING'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS step_meta (
                step_id     INTEGER PRIMARY KEY,
                rts_counter INTEGER NOT NULL DEFAULT 0,
                rts_site    INTEGER NOT NULL DEFAULT 0,
                wts_counter INTEGER NOT NULL DEFAULT 0,
                wts_site    INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.executemany(
            "INSERT OR REPLACE INTO Assembly_Line_Steps"
            " (step_id, machine_id, status) VALUES (?,?,?)",
            rows_list,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO step_meta (step_id) VALUES (?)",
            [(r[0],) for r in rows_list],
        )
        conn.commit()
        conn.close()
        label = chr(ord("a") + site_idx)
        print(f"[site_{label}] {len(rows_list)} rows -> {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Assembly_Line_Steps dataset")
    parser.add_argument("--rows", type=int, default=10_000, help="Total rows across all sites")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    parser.add_argument("--out", type=str, default="data/", help="Output directory for .db files")
    args = parser.parse_args()
    generate(rows=args.rows, seed=args.seed, out_dir=args.out)


if __name__ == "__main__":
    main()
