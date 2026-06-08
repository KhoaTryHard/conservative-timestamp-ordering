# Conservative Timestamp Ordering for Fault-Tolerant Assembly-Line Scheduling

**Project #27 - Category 3: Distributed Concurrency Control**  
Course: Distributed Database Systems

Hiện thực giao thức **Conservative Timestamp Ordering (CTO)** cho hệ thống sản xuất tự động (Automated Manufacturing), đồng thời so sánh trực tiếp với **Basic TO (Project #24)** trên cùng workload. Cơ sở lý thuyết theo Özsu & Valduriez 2020, Section 5.2.2.2, pages 201-203.

---

## Architecture

```text
+----------+   HTTP/REST   +----------+   HTTP/REST   +----------+
| site_a   |<------------>| site_b   |<------------>| site_c   |
| TM + SC  |              | TM + SC  |              | TM + SC  |
| DP+SQLite|              | DP+SQLite|              | DP+SQLite|
+----------+              +----------+              +----------+
     |                         |                         |
     +------- cto_net (Docker bridge network) -----------+
```

- **3 sites:** `site_a` port `8001`, `site_b` port `8002`, `site_c` port `8003`.
- **Fragmentation:** `stable_hash(machine_id) % 3` using `hashlib.blake2b`; each site owns about one third of `Assembly_Line_Steps`.
- **Scheduler:** CTO by default, or Basic TO via `SCHED_MODE=basic_to`.
- **Dummy heartbeat:** used by CTO mode only; idle TMs send dummy messages every `DUMMY_INTERVAL_MS=50` ms so remote queues do not stay empty. Basic TO executes immediately and does not use the dummy protocol.

## Prerequisites

- Python 3.11+
- Docker + Docker Compose v2

## Installation

PowerShell:

```powershell
git clone <repo-url>
cd <repo>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Bash/macOS/Linux:

```bash
git clone <repo-url>
cd <repo>
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Generate Dataset

The repository includes a generated dataset snapshot for submission:

- `data/site_a.db`
- `data/site_b.db`
- `data/site_c.db`

To recreate the same 10,000-row dataset from source, run:

```powershell
python -m data.data_generator --rows 10000 --seed 42 --out data/
```

Each fragment contains `Assembly_Line_Steps` and `step_meta` tables. Rows are partitioned with `stable_hash(machine_id) % 3`.

## Run - Single Site Without Docker

PowerShell:

```powershell
$env:SITE_ID = "0"
$env:SCHED_MODE = "cto"
$env:DUMMY_INTERVAL_MS = "50"
$env:DB_PATH = "data/site_a.db"
$env:PEER_URLS = "http://localhost:8002,http://localhost:8003"
uvicorn src.api.main:create_app --factory --port 8001
```

Bash/macOS/Linux:

```bash
SITE_ID=0 SCHED_MODE=cto DUMMY_INTERVAL_MS=50 DB_PATH=data/site_a.db \
  PEER_URLS=http://localhost:8002,http://localhost:8003 \
  uvicorn src.api.main:create_app --factory --port 8001
```

Health check:

```powershell
curl.exe http://localhost:8001/healthz
```

## Run - Full Cluster With Docker Compose

Generate the dataset first, then start all three sites:

```powershell
python -m data.data_generator --rows 10000 --seed 42 --out data/
docker compose down --remove-orphans
$env:SCHED_MODE = "cto"
docker compose up --build --force-recreate
```

After the services finish starting, verify each site through `/healthz`:

```powershell
curl.exe http://localhost:8001/healthz   # site_a
curl.exe http://localhost:8002/healthz   # site_b
curl.exe http://localhost:8003/healthz   # site_c
```

Switch to Basic TO.

PowerShell:

```powershell
docker compose down --remove-orphans
$env:SCHED_MODE = "basic_to"
docker compose up --build --force-recreate
```

Bash/macOS/Linux:

```bash
docker compose down --remove-orphans
SCHED_MODE=basic_to docker compose up --build --force-recreate
```

PowerShell environment variables such as `$env:SCHED_MODE` apply only to the current PowerShell session. Set the variable in the same terminal that runs `docker compose up`.

## Reproduce Latency Experiment

Regenerate the dataset before each benchmark mode for a fair CTO vs Basic TO comparison, then restart the cluster with the matching `SCHED_MODE`. The runner checks `/healthz` and fails fast if the running scheduler mode does not match `--mode`.

```powershell
python -m experiments.experiment_runner `
  --mode cto --txs 1000 --seed 42 `
  --out experiments/results/cto.json

python -m experiments.experiment_runner `
  --mode basic_to --txs 1000 --seed 42 `
  --out experiments/results/basic_to.json
```

Bash/macOS/Linux:

```bash
python -m experiments.experiment_runner \
  --mode cto --txs 1000 --seed 42 \
  --out experiments/results/cto.json

python -m experiments.experiment_runner \
  --mode basic_to --txs 1000 --seed 42 \
  --out experiments/results/basic_to.json
```

Compare two result files:

```powershell
python -m experiments.compare_results experiments/results/cto.json experiments/results/basic_to.json
```

Sweep `T_dummy`. The cluster must be recreated with the matching `DUMMY_INTERVAL_MS` before each run.

PowerShell:

```powershell
foreach ($ms in 10, 50, 100, 500) {
  docker compose down --remove-orphans
  $env:DUMMY_INTERVAL_MS = "$ms"
  $env:SCHED_MODE = "cto"
  docker compose up -d --build --force-recreate
  python -m experiments.experiment_runner --mode cto --txs 1000 `
    --out "experiments/results/cto_dummy${ms}ms.json"
}
```

Bash/macOS/Linux:

```bash
for ms in 10 50 100 500; do
  docker compose down --remove-orphans
  DUMMY_INTERVAL_MS=$ms SCHED_MODE=cto docker compose up -d --build --force-recreate
  python -m experiments.experiment_runner --mode cto --txs 1000 \
    --out experiments/results/cto_dummy${ms}ms.json
done
```

Result JSON files include metrics such as `completed`, `avg_ms`, `p95_ms`, `p99_ms`, `max_ms`, and `total_restarts`.

## Trigger Failure Scenario (D5)

Terminal 1 - start CTO cluster:

```powershell
docker compose down --remove-orphans
$env:SCHED_MODE = "cto"
docker compose up --build --force-recreate
```

Terminal 2 - deterministic failure demo:

```powershell
python -m experiments.demo_failure --mode cto --seed 42 --kill-site 1 `
  --kill-delay-sec 5 --restart-delay-sec 8 `
  --out experiments/results/cto_failure.json
```

Bash/macOS/Linux:

```bash
python -m experiments.demo_failure --mode cto --seed 42 --kill-site 1 \
  --kill-delay-sec 5 --restart-delay-sec 8 \
  --out experiments/results/cto_failure.json
```

The demo script validates `/healthz`, avoids sending client requests directly to the killed container, runs a live-site stall probe during the failure window, restarts `cto-site-b`, and writes JSON evidence. Use `--manual-failure` if you want to run `docker kill cto-site-b` and `docker start cto-site-b` manually during a screen recording.

Manual recording flow:

```powershell
# Terminal 2: run the deterministic demo in manual mode
python -m experiments.demo_failure --mode cto --seed 42 --kill-site 1 `
  --kill-delay-sec 5 --restart-delay-sec 8 --manual-failure `
  --out experiments/results/cto_failure.json

# Terminal 3: execute when demo_failure.py asks you
docker kill cto-site-b
docker start cto-site-b
```

Evidence to check in `experiments/results/cto_failure.json`:

- `total_restarts = 0`
- `stall_probe.completed = false`
- `unexpected_failures = []`

**Expected CTO behavior:** `site_a` and `site_c` stall while the queues that depend on `site_b` drain. CTO does not release operations prematurely and does not abort transactions. After `docker start cto-site-b`, catch-up dummy messages unblock the queues and the cluster resumes. This demonstrates the CTO trade-off: fewer restarts at the cost of waiting during failures (Özsu & Valduriez 2020, Section 5.2.2.2, pages 202-203).

## Run Tests

```powershell
pytest -q
```

Current test suite: **18 tests**.

| File | Coverage |
|---|---|
| `tests/test_clock_sync.py` | Timestamp monotonicity, tiebreaking, observation |
| `tests/test_hash_partition.py` | Cross-process deterministic partitioning |
| `tests/test_queue_manager.py` | Queue non-empty checks, min-pop ordering, edge cases |
| `tests/test_demo_failure.py` | Deterministic failure-demo helpers and result fields |
| `tests/test_compare_results.py` | JSON comparison table rendering |

## Configuration Reference

| Env var | Default | Purpose |
|---|---|---|
| `SITE_ID` | required | Site index: `0`, `1`, or `2` |
| `SCHED_MODE` | `cto` | Scheduler mode: `cto` or `basic_to` |
| `DUMMY_INTERVAL_MS` | `50` | CTO dummy heartbeat interval |
| `STALL_WARN_MS` | `5000` | Log warning when a scheduler is stalled |
| `DB_PATH` | required | SQLite fragment path |
| `PEER_URLS` | required | Comma-separated peer base URLs |

## Repository Layout

```text
.
|-- README.md
|-- docker-compose.yml
|-- Dockerfile
|-- pyproject.toml
|-- src/
|   |-- common/              # messages.py, clock_sync.py, dummy_msg.py, config.py
|   |-- tm/                  # transaction_manager.py
|   |-- scheduler/           # scheduler_cto.py, scheduler_basic_to.py, queue_manager.py
|   |-- dp/                  # data_processor.py
|   `-- api/                 # main.py, routers.py
|-- data/
|   |-- data_generator.py
|   |-- site_a.db
|   |-- site_b.db
|   `-- site_c.db
|-- experiments/
|   |-- experiment_runner.py
|   |-- demo_failure.py
|   |-- compare_results.py
|   `-- metrics.py
|-- tests/
|   |-- test_clock_sync.py
|   |-- test_hash_partition.py
|   |-- test_queue_manager.py
|   |-- test_demo_failure.py
|   `-- test_compare_results.py
```

Generated files are intentionally ignored by git:

- SQLite runtime sidecar files: `data/*.db-journal`, `data/*.db-shm`, `data/*.db-wal`
- `experiments/results/`
- Python/test caches
- `.venv/`

## Submission Checklist

Before packaging the project for submission:

```powershell
python -m data.data_generator --rows 10000 --seed 42 --out data/
pytest -q
docker compose down --remove-orphans
$env:SCHED_MODE = "cto"
docker compose up --build --force-recreate
```

Then verify:

```powershell
curl.exe http://localhost:8001/healthz
curl.exe http://localhost:8002/healthz
curl.exe http://localhost:8003/healthz
```

Recommended deliverables:

- Source code repository with this README.
- `README.md` as the main run/reproduction guide.
- A 3-5 minute screen recording that follows the failure scenario in this README and shows `docker kill cto-site-b`, recovery, and `total_restarts = 0`.
- Optional experiment JSON files from `experiments/results/` if the instructor asks for raw evidence.
- Slides or Word/PDF report files if they are submitted separately outside this repository package.

## Theoretical Reference

M. Tamer Özsu and Patrick Valduriez, *Principles of Distributed Database Systems*, 4th Edition, Springer, 2020.

| Section | Pages | Role |
|---|---|---|
| Section 5.2.2 Timestamp Ordering | about 197 | Timestamp ordering framework |
| Section 5.2.2.1 Basic TO and Algorithms 5.4-5.5 | 198-201 | Baseline scheduler |
| Section 5.2.2.2 Conservative TO | 201-203 | Core protocol for this project |
