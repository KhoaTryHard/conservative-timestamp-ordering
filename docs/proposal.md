# Distributed Database Project Proposal

**Due Date:** Week 3
**Project ID & Category:** #27 — Conservative Timestamp Ordering — Category 3 (Distributed Concurrency Control)

---

## 1. Project Identity

- **Team Name:** Nguyễn Đăng Khoa
- **Team Members:** Nguyễn Đăng Khoa — MSSV: N23DCCN030
- **Project Title:** *Conservative Timestamp Ordering for Fault-Tolerant Assembly-Line Scheduling*

## 2. Objective & Problem Statement

- **The "Why":** Trong nhà máy tự động, nhiều phân xưởng song song cập nhật trạng thái các bước lắp ráp trên cùng một sản phẩm vật lý. Basic Timestamp Ordering (Project #24) xử lý xung đột bằng cách **restart** giao tác có timestamp đến muộn — một hành vi **không thể chấp nhận** trong bối cảnh sản xuất vật lý (một máy không thể "huỷ" thao tác đã hàn). Dự án này hiện thực **Conservative TO** để **loại trừ hoàn toàn restart**, sau đó định lượng cái giá phải trả — *delay* — thông qua **Average Transaction Latency** trên cùng workload với Basic TO.
- **Core Logic:** Hiện thực Conservative TO theo §5.2.2.2 *(Özsu & Valduriez 2020, tr. 201–203)*. Mỗi scheduler tại site `s` duy trì một queue `Q^t_s` cho mỗi Transaction Manager `t`. Operations được nhét vào queue theo timestamp tăng dần. Scheduler chỉ release một op tới Data Processor khi (a) **mọi** `Q^t_s ≠ ∅` và (b) op đó có `ts` nhỏ nhất xuyên qua tất cả queue (*extremely conservative form*). TM khi idle gửi **dummy message** mỗi `T_dummy = 50 ms` để báo cận dưới timestamp tương lai, bảo đảm tiến độ. Timestamp = `(counter_local, site_id)` với tiebreak theo `site_id`.

## 3. Dataset Specification

- **Source:** Synthetic — sinh bằng script `data/data_generator.py` trong repo. Dataset `Assembly_Line_Steps` **không tồn tại** dưới dạng public dataset; do đó dùng generator có seed cố định để tái lập (`--seed 42`). Không bịa link.
- **Size:** Mặc định **10,000 rows** (~0.4 MB SQLite); scalable tới 100,000 qua flag `--rows`. Workload thí nghiệm: **1,000 transactions** mỗi run.
- **Schema:**

  | Column | Type | Note |
  |---|---|---|
  | `StepID` | INTEGER PRIMARY KEY | Đóng vai `x` trong `R(x)/W(x)` của giao thức |
  | `MachineID` | TEXT | Dùng làm khoá phân mảnh |
  | `Status` | TEXT (enum: `PENDING / IN_PROGRESS / DONE / FAILED`) | Trường biến động chính, chịu W |

  Bảng phụ `step_meta(step_id, rts, wts)` lưu cặp timestamp đọc/ghi theo §5.2.2 *(tr. 198)*.

- **Fragmentation Strategy:** Horizontal **hash partitioning** — `site_index = hash(machine_id) % 3`. Mỗi site sở hữu ~33% tuple. Theo nguyên tắc fragmentation, hash phù hợp khi predicate truy cập dựa trên *equality* của attribute phân mảnh (đúng với workload `WHERE machine_id = ?`). Phép `hash` dùng `hashlib.blake2b(...).digest()[:8]` để deterministic xuyên process.

## 4. System Architecture

- **Nodes:** **3 sites** (`site_a`, `site_b`, `site_c`) — bám khuyến nghị template (Min 2, Recommended 3). Ánh xạ nghiệp vụ: 3 phân xưởng song song trong nhà máy, mỗi phân xưởng phụ trách một tập máy theo hash.
- **Communication Layer:** **HTTP/REST** qua FastAPI; mỗi op (`READ`, `WRITE`, `DUMMY`, `COMMIT`) là một HTTP request từ TM tới scheduler của site sở hữu data. Client async dùng `httpx.AsyncClient`. Chọn HTTP/REST thay vì gRPC vì: dễ inspect bằng `curl` khi demo screen-recording, đủ throughput cho 1k tx, không cần code generation.
- **Storage:** **SQLite per site**, file `data/site_a.db`, `data/site_b.db`, `data/site_c.db`. Hai bảng: `Assembly_Line_Steps` (dữ liệu) và `step_meta` (rts/wts theo §5.2.2 tr. 198). SQLite chọn thay vì CSV vì: hỗ trợ transaction WAL ngay, query SQL chuẩn, file độc lập per site khớp mô hình phân mảnh.

## 5. Tech Stack & Implementation Plan

- **Programming Language:** Python 3.11+ (type hints, asyncio, structural pattern matching).
- **Deployment:** **Docker Compose** — 3 services (`cto-site-a/b/c`) trên bridge network `cto_net`; mỗi service expose 1 cổng FastAPI. Lệnh demo failure: `docker kill cto-site-b`.
- **Libraries/Frameworks:**
  - `fastapi` + `uvicorn` — HTTP server per site.
  - `httpx` — async client cho cross-site ops.
  - `pydantic` v2 — schema cho `Operation`, `DummyMessage`, `Timestamp`.
  - `pytest` + `pytest-asyncio` — unit + integration tests.
  - `ruff` + `black` — lint/format.
  - `matplotlib` — vẽ chart latency cho Analysis Report.

## 6. Success Metrics & Analysis

- **Quantitative Metric:** **Average Transaction Latency (ms)** = mean của `(commit_time − begin_time)` đo tại phía Transaction Manager bằng `time.perf_counter_ns`, qua `N = 1000` giao tác. Phụ metric: p95/p99 latency, throughput (TPS), `dummy_msg_rate` (msg/s), `restart_count` (kỳ vọng = 0 cho CTO, > 0 cho Basic TO). So sánh **CTO ↔ Basic TO** trên cùng generator, cùng seed, cùng hardware — kết quả lưu JSON dưới `experiments/results/`.
  - Phụ thí nghiệm tuning `T_dummy ∈ {10, 50, 100, 500} ms` để tìm điểm trade-off tối ưu giữa latency và network overhead — số liệu trình bày trong Analysis Report; chưa có kết quả tại thời điểm proposal.

- **The "Failure" Scenario:** *"What happens when I kill Node B mid-transaction?"*
  - **Thiết lập:** cluster đang chạy 1000 cross-site transactions; tại giây 30 ta thực thi `docker kill cto-site-b`.
  - **Hành vi CTO mong đợi (theo §5.2.2.2, tr. 201–203):** scheduler tại `site_a` và `site_c` **stall** vì `Q^B_A` và `Q^B_C` ngừng được bồi op/dummy → điều kiện "mọi queue non-empty" vĩnh viễn không thoả → KHÔNG giao tác nào commit được, nhưng cũng KHÔNG abort, KHÔNG mất tính nhất quán. Khi `docker start cto-site-b` → `site_b` gửi catch-up dummy + buffered ops → cluster tiếp tục từ đúng vị trí dừng. Đây là biểu hiện trực tiếp của trade-off "eliminates restarts but introduces delay and possibility of deadlock" *(tr. 202–203)*.
  - **Đối chiếu Basic TO:** `site_a` và `site_c` vẫn xử lý op cục bộ, nhưng các giao tác cross-site phụ thuộc `site_b` sẽ abort khi gặp `ts` xung đột → restart. Trong bối cảnh nhà máy, restart đồng nghĩa thao tác vật lý có thể đã thực hiện một phần — minh hoạ tại sao CTO phù hợp hơn cho workload này.

## 7. Project Milestones

- **Milestone 1 (Week 5) — Environment setup & data fragmentation complete:**
  - `data/data_generator.py` sinh 10k rows `Assembly_Line_Steps` với seed cố định.
  - `docker-compose.yml` boot 3 sites, mỗi site có FastAPI + SQLite riêng.
  - Hàm `get_site_for_machine(machine_id) -> int` (hash mod 3) verified bằng unit test phân bổ đều.
- **Milestone 2 (Week 8) — Core algorithm operational:**
  - `TransactionManager`: cấp `ts = (counter_local, site_id)`, dispatch ops tới các scheduler liên quan.
  - `ConservativeScheduler`: hiện thực queue `Q^t_s` (priority queue theo ts), release-rule "all queues non-empty + min ts".
  - `DummyMessageGenerator`: heartbeat `T_dummy = 50 ms` mặc định, override qua `DUMMY_INTERVAL_MS`.
  - `DataProcessor`: maintains `rts(x)`, `wts(x)` trong bảng `step_meta`.
  - `scheduler_basic_to.py` chạy song song (mode flag `SCHED_MODE`) — để bench so sánh.
- **Milestone 3 (Week 12) — Failure handling & benchmarking complete:**
  - Kịch bản `docker kill cto-site-b` verified — system stall đúng quy luật CTO, khôi phục khi restart.
  - Benchmark 1,000 tx mỗi mode; sweep `T_dummy ∈ {10, 50, 100, 500}` ms.
  - Analysis Report draft — bảng so sánh CTO vs Basic TO, biện minh từng quyết định theo §5.2.2.1 và §5.2.2.2.
  - Screen-recording 3–5 phút final cut + slides present.

---

*Tham chiếu lý thuyết duy nhất: M. Tamer Özsu & Patrick Valduriez — Principles of Distributed Database Systems, 4th Ed., Springer 2020 — §5.2.2 (tr. ~197), §5.2.2.1 (tr. 198–201, Algorithms 5.4–5.5), §5.2.2.2 (tr. 201–203).*
