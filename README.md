# Conservative Timestamp Ordering for Fault-Tolerant Assembly-Line Scheduling

**Project #27 — Category 3: Distributed Concurrency Control**
Course: Distributed Database Systems

Hiện thực giao thức **Conservative Timestamp Ordering (CTO)** cho hệ thống sản xuất tự động (Automated Manufacturing), so sánh trực tiếp với **Basic TO (Project #24)** trên cùng workload. Lý thuyết theo Özsu & Valduriez 2020, §5.2.2.2 (tr. 201–203).

---

## Architecture

```
+----------+   HTTP/REST   +----------+   HTTP/REST   +----------+
| site_a   |<------------>| site_b   |<------------>| site_c   |
| TM + SC  |              | TM + SC  |              | TM + SC  |
| DP+SQLite|              | DP+SQLite|              | DP+SQLite|
+----------+              +----------+              +----------+
     |                         |                         |
     +------- cto_net (Docker bridge network) -----------+
```

- **3 sites** (`site_a` port 8001, `site_b` 8002, `site_c` 8003).
- **Fragmentation:** `stable_hash(machine_id) % 3` using `hashlib.blake2b` — each site owns ~33% of `Assembly_Line_Steps`.
- **Scheduler:** CTO (default) or Basic TO — toggled via `SCHED_MODE` env var.
- **Dummy heartbeat:** every `DUMMY_INTERVAL_MS=50` ms from idle TMs → keeps remote queues non-empty.

## Prerequisites

- Python 3.11+
- Docker + Docker Compose v2
- (optional) `pandoc` for docx conversion

## Installation

```bash
git clone <repo-url>
cd <repo>
python -m venv .venv
. .venv/Scripts/activate          # Windows
# . .venv/bin/activate            # macOS/Linux
pip install -e ".[dev]"
```

## Generate Dataset

```bash
python -m data.data_generator --rows 10000 --seed 42 --out data/
```

Tạo `data/site_a.db`, `data/site_b.db`, `data/site_c.db` — mỗi file chứa bảng `Assembly_Line_Steps` và `step_meta` (rts/wts).

## Run — Single Site (no Docker)

```bash
SITE_ID=0 SCHED_MODE=cto DUMMY_INTERVAL_MS=50 DB_PATH=data/site_a.db \
  PEER_URLS=http://localhost:8002,http://localhost:8003 \
  uvicorn src.api.main:create_app --factory --port 8001
```

Health check:

```bash
curl http://localhost:8001/healthz
```

## Run — Full Cluster (Docker Compose)

```bash
docker compose up --build
```

Wait for all 3 containers healthy, then:

```bash
curl http://localhost:8001/healthz   # site_a
curl http://localhost:8002/healthz   # site_b
curl http://localhost:8003/healthz   # site_c
```

Switch to Basic TO:

```bash
SCHED_MODE=basic_to docker compose up --build
```

## Reproduce Latency Experiment

Restart the cluster with the matching `SCHED_MODE`, then run each benchmark with the same seed and transaction count. The runner checks `/healthz` and fails fast if the running scheduler mode does not match `--mode`.

```bash
python -m experiments.experiment_runner \
  --mode cto --txs 1000 --seed 42 \
  --out experiments/results/cto.json

python -m experiments.experiment_runner \
  --mode basic_to --txs 1000 --seed 42 \
  --out experiments/results/basic_to.json
```

Sweep `T_dummy` (requires cluster with matching `DUMMY_INTERVAL_MS`):

```bash
for ms in 10 50 100 500; do
  DUMMY_INTERVAL_MS=$ms docker compose up -d --build
  python -m experiments.experiment_runner --mode cto --txs 1000 \
    --out experiments/results/cto_dummy${ms}ms.json
done
```

Results are JSON — `avg_ms`, `p95_ms`, `p99_ms`, `total_restarts` per run.

## Trigger Failure Scenario (D5)

```bash
# Terminal 1 — cluster already running
docker compose up --build

# Terminal 2 — run experiment; kill site_b mid-way
python -m experiments.experiment_runner --mode cto --txs 1000 \
  --out experiments/results/cto_failure.json &

sleep 30
docker kill cto-site-b          # site_a & site_c STALL — no abort, no data loss

# After ~10s, restart site_b
docker start cto-site-b         # cluster resumes from exact stall point
```

**Expected behaviour (CTO):** `site_a` and `site_c` stall while `Q^b_a` and `Q^b_c` drain — no operation is released, no transaction aborts. On `docker start cto-site-b`, catch-up dummy messages unblock the queues and the cluster resumes. This demonstrates the CTO trade-off: eliminates restarts at the cost of delay (Özsu & Valduriez 2020, §5.2.2.2, tr. 202–203).

## Run Tests

```bash
pytest -q
```

Key test files:

| File | Coverage |
|---|---|
| `tests/test_clock_sync.py` | Monotonicity, tiebreak, observe |
| `tests/test_hash_partition.py` | Cross-process determinism, balance, valid index |
| `tests/test_queue_manager.py` | `all_non_empty`, `pop_min` ordering, edge cases |

## Configuration Reference

| Env var | Default | Purpose |
|---|---|---|
| `SITE_ID` | required | Site index 0/1/2 |
| `SCHED_MODE` | `cto` | `cto` or `basic_to` |
| `DUMMY_INTERVAL_MS` | `50` | Heartbeat interval |
| `STALL_WARN_MS` | `5000` | Log warning when stalled |
| `DB_PATH` | required | SQLite file path |
| `PEER_URLS` | required | Comma-separated peer base URLs |
| `WORKLOAD_TXS` | `1000` | Default benchmark size |

## Repository Layout

```
.
├── CLAUDE.md                  # Claude Code behavioral contract (auto-loaded)
├── README.md
├── docker-compose.yml
├── pyproject.toml
├── Dockerfile
├── src/
│   ├── common/                # messages.py, clock_sync.py, dummy_msg.py, config.py
│   ├── tm/                    # transaction_manager.py
│   ├── scheduler/             # scheduler_cto.py, scheduler_basic_to.py, queue_manager.py
│   ├── dp/                    # data_processor.py
│   └── api/                   # main.py (factory), routers.py
├── data/
│   └── data_generator.py
├── experiments/
│   ├── experiment_runner.py
│   └── metrics.py
├── tests/
│   ├── test_clock_sync.py
│   ├── test_hash_partition.py
│   └── test_queue_manager.py
└── docs/
    ├── proposal.md            # Deliverable D1
    ├── design_2page.md        # Deliverable D2
    └── analysis_report.md     # Deliverable D4 (generated after experiments)
```

## Theoretical Reference

M. Tamer Özsu & Patrick Valduriez — *Principles of Distributed Database Systems*, 4th Ed., Springer 2020.

| Section | Pages | Role |
|---|---|---|
| §5.2.2 Timestamp Ordering | ~197 | Framework |
| §5.2.2.1 Basic TO + Algorithms 5.4–5.5 | 198–201 | Baseline (Project #24) |
| §5.2.2.2 Conservative TO | 201–203 | Core of this project |
