# Báo cáo Phân tích: Conservative Timestamp Ordering cho Hệ thống Sản xuất Tự động

**Môn học:** Distributed Database Systems  
**Đề tài #27 — Category 3: Distributed Concurrency Control**  
**Sinh viên thực hiện:** Nguyễn Đăng Khoa (N23DCCN030)  
**Ngày:** 2026-05-16

---

## 1. Giới thiệu

Báo cáo này phân tích và đánh giá giao thức **Conservative Timestamp Ordering (CTO)** được triển khai cho hệ thống sản xuất tự động (*Automated Manufacturing*). Trong bối cảnh dây chuyền sản xuất, nhiều Transaction Manager (TM) chạy song song cập nhật trạng thái các bước lắp ráp (`Assembly_Line_Steps`); đảm bảo nhất quán phân tán mà không cần khóa là bài toán cốt lõi.

Mục tiêu nghiên cứu:

1. Hiện thực CTO theo §5.2.2.2 *(Özsu & Valduriez 2020, tr. 201–203)* và Basic TO theo §5.2.2.1 *(tr. 198–201)* trong cùng một cơ sở hạ tầng.
2. Đo **Average Transaction Latency** (p50, p95, p99) của cả hai giao thức trên cùng workload.
3. Phân tích trade-off: CTO loại bỏ restart ở cái giá tăng độ trễ; Basic TO giảm trễ nhưng phải restart khi vi phạm thứ tự timestamp.
4. Minh chứng tính chịu lỗi của CTO qua kịch bản `docker kill cto-site-b`.

---

## 2. Nền tảng lý thuyết

### 2.1 Timestamp Ordering — khung chung

Timestamp Ordering (TO) gán mỗi giao dịch một timestamp duy nhất tại thời điểm bắt đầu *(Özsu & Valduriez 2020, §5.2.2, tr. 197)*. Scheduler duy trì `rts(x)` (read timestamp lớn nhất đã thực hiện) và `wts(x)` (write timestamp lớn nhất đã thực hiện) cho mỗi data item `x`. Một thao tác chỉ được thực hiện nếu nó không vi phạm thứ tự serialization dựa trên timestamp.

### 2.2 Basic TO — Algorithm 5.4 & 5.5

Basic TO xử lý mỗi operation ngay khi nhận được *(Özsu & Valduriez 2020, §5.2.2.1, tr. 198–201)*:

- **READ(x) bởi T_i** (Algorithm 5.5 — BTO-SC):
  - Nếu `ts(T_i) < wts(x)` → **reject** (restart T_i với timestamp mới).
  - Ngược lại: thực hiện READ, cập nhật `rts(x) = max(rts(x), ts(T_i))`.
- **WRITE(x) bởi T_i** (Algorithm 5.5 — BTO-SC):
  - Nếu `ts(T_i) < rts(x)` hoặc `ts(T_i) < wts(x)` → **reject** (restart T_i).
  - Ngược lại: thực hiện WRITE, cập nhật `wts(x) = ts(T_i)`.
- **TM** (Algorithm 5.4 — BTO-TM): gán timestamp từ đồng hồ cục bộ, gửi op đến site chứa data item.

Nhược điểm: restart giao dịch gây lãng phí tài nguyên và tăng tải hệ thống khi tỷ lệ xung đột cao.

### 2.3 Conservative TO — §5.2.2.2

CTO loại bỏ restart bằng cách **trì hoãn** thay vì **từ chối** *(Özsu & Valduriez 2020, §5.2.2.2, tr. 201–203)*. Mỗi Scheduler `s` duy trì một hàng đợi riêng biệt `Q^t_s` cho mỗi TM `t` gửi operation đến. Điều kiện giải phóng (dạng extremely-conservative):

> **Release condition:** `∀ t ∈ TM_set : Q^t_s ≠ ∅`  
> Khi đủ điều kiện, Scheduler chọn operation có `min { head(Q^t_s).ts }` trên tất cả hàng đợi và dispatch nó.

Để tránh stall vô hạn khi TM không có operation thực sự gửi đến, mỗi TM phát **dummy message** với `min_future_ts` sau mỗi khoảng `T_dummy` *(Özsu & Valduriez 2020, §5.2.2.2, tr. 202)*. Dummy message không mang thao tác dữ liệu; chỉ đóng vai trò heartbeat để Scheduler biết rằng TM đó tạm thời không có operation timestamp nhỏ hơn `min_future_ts`.

**Tính chịu lỗi:** Nếu một site bị crash, `Q^t_s` của site đó (tại các Scheduler khác) không bao giờ được bổ sung → điều kiện `all_non_empty()` không thỏa mãn → hệ thống **stall** (không abort, không mất dữ liệu). Khi site khởi động lại, dummy messages sẽ unblock các hàng đợi và hệ thống tiếp tục từ chính xác điểm stall. Đây là sự đánh đổi đặc trưng của CTO so với Basic TO (vốn restart ngay khi phát hiện vi phạm).

---

## 3. Mô tả thiết kế triển khai

### 3.1 Kiến trúc hệ thống

```
+----------+   HTTP/REST   +----------+   HTTP/REST   +----------+
| site_a   |<------------>| site_b   |<------------>| site_c   |
| TM + SC  |              | TM + SC  |              | TM + SC  |
| DP+SQLite|              | DP+SQLite|              | DP+SQLite|
+----------+              +----------+              +----------+
     |                         |                         |
     +------- cto_net (Docker bridge network) -----------+
```

Ba sites tương đương nhau; mỗi site có:
- **TransactionManager** — gán timestamp `(counter, site_id)`, điều phối cross-site ops, phát dummy messages.
- **ConservativeScheduler / BasicTOScheduler** — chọn theo `SCHED_MODE` env var.
- **DataProcessor** — áp dụng R/W lên SQLite, duy trì `rts(x)` / `wts(x)` trong bảng `step_meta`.
- **QueueManager** — priority queue thread-safe theo `(ts.counter, ts.site_id, tm_id)`.

### 3.2 Phân mảnh dữ liệu

Horizontal stable hash partitioning: `site_index = stable_hash(machine_id) % 3` bằng `hashlib.blake2b`. Bảng `Assembly_Line_Steps(StepID INT PK, MachineID TEXT, Status TEXT)` phân tán đồng đều ~33% mỗi site. Kiểm chứng phân phối: test `test_distribution_is_balanced` xác nhận 850–1150 bản ghi/site trên 3000 machines.

### 3.3 Timestamp

`Timestamp(counter: int, site_id: int)` — monotonic counter tăng mỗi lần `next()` được gọi; tiebreak theo `site_id`. Không phụ thuộc NTP; `observe(ts)` cập nhật counter cục bộ khi nhận operation từ peer để đảm bảo tính nhất quán nhân quả.

### 3.4 Dummy message

`DummyMessageGenerator` phát `DummyMessage(ts=clock.peek(), tm_id)` mỗi `DUMMY_INTERVAL_MS` ms (mặc định 50 ms) khi TM không có operation thực sự. Scheduler nhận dummy và `enqueue` vào `Q^t_s` tương ứng; dummy không gây thao tác dữ liệu.

### 3.5 Workload

Ba loại transaction mô phỏng dây chuyền sản xuất:
- **T_advance (60%):** TM đọc trạng thái bước hiện tại → ghi `Status='IN_PROGRESS'` (local, 1 site).
- **T_complete (30%):** TM ghi `Status='COMPLETED'` cho bước đó (local, 1 site).
- **T_handoff (10%):** TM đọc step tại site A, ghi kết quả vào step tại site B (cross-site, 2 sites).

---

## 4. Biện minh quyết định thiết kế

| Quyết định | Lựa chọn | Lý do |
|---|---|---|
| Dạng CTO | Extremely-conservative (all queues non-empty) | Đơn giản nhất để chứng minh đúng; không cần phân lớp operation *(§5.2.2.2, tr. 201)* |
| Timestamp | `(counter, site_id)` — không dùng NTP | Tránh phụ thuộc clock đồng bộ; tiebreak deterministc |
| Phân mảnh | `stable_hash(machine_id) % 3` | Phân phối đồng đều; deterministic routing không cần metadata lookup |
| T_dummy mặc định | 50 ms | Điểm khởi đầu cân bằng giữa overhead và block time; tunable qua env var |
| Storage | SQLite per site | Đơn giản, không cần external DB; phù hợp quy mô thí nghiệm |
| Transport | FastAPI + httpx async | Non-blocking I/O; tương thích asyncio scheduler loop |
| Baseline | Basic TO (cùng infra) | So sánh fair: cùng dataset, cùng workload, toggle qua `SCHED_MODE` |

---

## 5. Thiết kế thí nghiệm

### 5.1 Môi trường

- **Platform:** Docker Compose, 3 containers trên cùng bridge network `cto_net`, chạy trên localhost.
- **Dataset:** 10,000 rows, `seed=42`, phân phối `stable_hash(machine_id) % 3`.
- **Workload:** 1,000 transactions mỗi run; mix 60% T_advance / 30% T_complete / 10% T_handoff.
- **Lặp lại:** Mỗi cấu hình chạy ít nhất 3 lần; lấy median để giảm nhiễu cold-start.

### 5.2 Kịch bản đo lường

**Kịch bản 1 — Baseline so sánh CTO vs Basic TO:**

```bash
python -m experiments.experiment_runner --mode cto      --txs 1000 --seed 42 \
  --out experiments/results/cto.json

python -m experiments.experiment_runner --mode basic_to --txs 1000 --seed 42 \
  --out experiments/results/basic_to.json
```

Metric: `avg_ms`, `p50_ms`, `p95_ms`, `p99_ms`, `total_restarts` (Basic TO), `max_stall_ms` (CTO).

**Kịch bản 2 — Sweep T_dummy:**

Giá trị thử nghiệm: 10, 50, 100, 500 ms. Mục tiêu: tìm giá trị T_dummy tối ưu giảm thiểu latency CTO mà không gây overhead dummy message quá lớn.

```bash
for ms in 10 50 100 500; do
  DUMMY_INTERVAL_MS=$ms docker compose up -d --build
  python -m experiments.experiment_runner --mode cto --txs 1000 \
    --out experiments/results/cto_dummy${ms}ms.json
done
```

**Kịch bản 3 — Failure & Recovery (D5):**

```bash
docker compose up --build &
python -m experiments.experiment_runner --mode cto --txs 1000 \
  --out experiments/results/cto_failure.json &
sleep 30
docker kill cto-site-b
# Quan sát: site_a, site_c stall (không abort)
sleep 10
docker start cto-site-b
# Quan sát: hệ thống tiếp tục từ điểm stall
```

Metric: thời gian stall (giây), số transaction bị delay, số transaction abort = 0 (CTO invariant).

### 5.3 Công thức đo latency

```
latency(T_i) = t_commit(T_i) - t_begin(T_i)   [đơn vị: ms]
```

`t_begin` và `t_commit` đo bằng `time.perf_counter_ns()` tại TM; chuyển sang ms trước khi lưu. Aggregation: p50 = median, p95 = percentile 95, p99 = percentile 99 trên toàn bộ 1000 transactions.

---

## 6. Kết quả thí nghiệm

> **Lưu ý:** Bảng dưới đây là **placeholder** — chưa điền số thực nghiệm. Điền vào sau khi chạy `experiment_runner` và đọc file JSON output.

### 6.1 Bảng so sánh CTO vs Basic TO (T_dummy = 50 ms, 1000 txs, seed=42)

| Metric | CTO | Basic TO |
|---|---|---|
| avg_ms | `[chạy thực nghiệm]` | `[chạy thực nghiệm]` |
| p50_ms | `[chạy thực nghiệm]` | `[chạy thực nghiệm]` |
| p95_ms | `[chạy thực nghiệm]` | `[chạy thực nghiệm]` |
| p99_ms | `[chạy thực nghiệm]` | `[chạy thực nghiệm]` |
| total_restarts | 0 (invariant) | `[chạy thực nghiệm]` |
| max_stall_ms | `[chạy thực nghiệm]` | N/A |

### 6.2 Bảng sweep T_dummy (CTO, 1000 txs, seed=42)

| T_dummy (ms) | avg_ms | p95_ms | p99_ms | overhead_dummy_msgs |
|---|---|---|---|---|
| 10 | `[chạy]` | `[chạy]` | `[chạy]` | `[chạy]` |
| 50 | `[chạy]` | `[chạy]` | `[chạy]` | `[chạy]` |
| 100 | `[chạy]` | `[chạy]` | `[chạy]` | `[chạy]` |
| 500 | `[chạy]` | `[chạy]` | `[chạy]` | `[chạy]` |

**Giả thuyết trước thực nghiệm (chưa kiểm chứng):** T_dummy nhỏ giảm stall time nhưng tăng số dummy message; T_dummy lớn giảm overhead nhưng tăng latency trung bình khi CTO chờ heartbeat.

### 6.3 Kịch bản Failure (CTO, docker kill cto-site-b)

| Phase | Quan sát | Số abort |
|---|---|---|
| Trước kill | Hệ thống chạy bình thường | 0 |
| Sau `docker kill cto-site-b` | site_a, site_c stall (`Q^b_a`, `Q^b_c` không được bổ sung) | 0 |
| Thời gian stall | `[chạy thực nghiệm]` giây | 0 |
| Sau `docker start cto-site-b` | site_b gửi dummy messages → hàng đợi unblock | 0 |
| Sau recovery | Hệ thống tiếp tục, không mất transaction | 0 |

---

## 7. Phân tích trade-off: CTO vs Basic TO

### 7.1 Restart vs Delay

| Tiêu chí | CTO | Basic TO |
|---|---|---|
| Cơ chế xử lý conflict | **Delay** (trì hoãn release) | **Restart** (abort + timestamp mới) |
| Số restart | 0 (đảm bảo bởi thiết kế) | Phụ thuộc tỷ lệ conflict |
| Latency trung bình (low conflict) | Cao hơn ≥ T_dummy/2 | Thấp hơn |
| Latency trung bình (high conflict) | Ổn định (delay tăng tuyến tính) | Tăng phi tuyến (restart cascade) |
| Throughput | Ổn định, có thể dự đoán | Giảm mạnh khi conflict rate cao |
| Fault tolerance | **Stall** — không mất dữ liệu | Restart khi detect, có thể lost in-flight op |

**Luận điểm lý thuyết** *(Özsu & Valduriez 2020, §5.2.2.2, tr. 202–203)*: CTO phù hợp với workload có conflict rate cao hoặc yêu cầu tính chịu lỗi nghiêm ngặt (không chấp nhận abort). Basic TO phù hợp hơn khi conflict rate thấp và latency là ưu tiên.

### 7.2 Tác động của T_dummy

Độ trễ thêm do CTO ≈ `T_dummy / 2` trong trường hợp trung bình *(Özsu & Valduriez 2020, §5.2.2.2, tr. 202)*. Giảm `T_dummy` giảm latency CTO về gần Basic TO, nhưng tăng số message dummy và CPU overhead. Thực nghiệm sweep tìm điểm tối ưu cho workload cụ thể.

### 7.3 Tính chính xác (Correctness)

Cả hai giao thức đều đảm bảo **serializability** theo timestamp ordering *(Özsu & Valduriez 2020, §5.2.2, tr. 197)*:
- Basic TO: serializable vì reject bất kỳ op vi phạm thứ tự.
- CTO: serializable vì chỉ dispatch op theo thứ tự timestamp tăng dần (min-ts dispatch từ non-empty queues).

---

## 8. So sánh CTO ↔ Basic TO — Bảng tổng hợp

| Thuộc tính | CTO (§5.2.2.2) | Basic TO (§5.2.2.1) |
|---|---|---|
| Lý thuyết nền | §5.2.2.2, tr. 201–203 | §5.2.2.1, Alg. 5.4–5.5, tr. 198–201 |
| Queue structure | `Q^t_s` per TM per site | Không có (xử lý immediate) |
| Release condition | `∀t: Q^t_s ≠ ∅` + min-ts | Ngay khi nhận op (kiểm tra ts vs rts/wts) |
| Dummy message | Bắt buộc (prevent stall) | Không cần |
| Conflict handling | Delay (trì hoãn) | Reject + Restart |
| Abort count | 0 | > 0 khi có conflict |
| Stall on node failure | Có (đợi queue refill) | Không (restart ngay) |
| Latency (no failure) | avg ≥ T_dummy/2 overhead | Thấp hơn khi conflict thấp |
| Complexity | Cao hơn (queue mgmt + dummy) | Thấp hơn |
| Module chính | `scheduler_cto.py`, `queue_manager.py`, `dummy_msg.py` | `scheduler_basic_to.py` |

---

## 9. Kết luận

Thí nghiệm này trực tiếp minh chứng trade-off cơ bản của hai giao thức timestamp ordering trong hệ cơ sở dữ liệu phân tán *(Özsu & Valduriez 2020, §5.2.2, tr. 197)*:

1. **CTO** (§5.2.2.2, tr. 201–203) — phù hợp cho môi trường sản xuất cần **tính chịu lỗi cao**: không abort, không mất transaction, stall khi node lỗi và tự phục hồi sau khi node trở lại. Chi phí là latency tăng thêm ~T_dummy/2 mỗi transaction.

2. **Basic TO** (§5.2.2.1, tr. 198–201) — phù hợp cho môi trường **ưu tiên latency thấp** với tỷ lệ conflict thấp: xử lý ngay, không delay, nhưng phải trả giá bằng restart khi vi phạm thứ tự timestamp.

Trong bối cảnh **Automated Manufacturing** với dây chuyền lắp ráp liên tục, CTO là lựa chọn phù hợp hơn: một bước lắp ráp bị delay tốt hơn là bị abort và phải bắt đầu lại từ đầu. Kết quả thực nghiệm (sau khi điền số liệu thực) sẽ định lượng hóa trade-off này trên workload cụ thể.

---

## Tài liệu tham khảo

- M. Tamer Özsu & Patrick Valduriez. *Principles of Distributed Database Systems*, 4th Ed. Springer, 2020.
  - §5.2.2 Timestamp Ordering, tr. ~197
  - §5.2.2.1 Basic TO Algorithm (Algorithms 5.4–5.5), tr. 198–201
  - §5.2.2.2 Conservative TO Algorithm, tr. 201–203
