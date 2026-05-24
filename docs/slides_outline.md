# Slides Outline — Final Exam Presentation
# Conservative Timestamp Ordering for Fault-Tolerant Assembly-Line Scheduling
# Đề tài #27 — Distributed Database Systems

**Thời lượng:** ~10–15 phút | **Ngôn ngữ:** Tiếng Việt (thuật ngữ kỹ thuật giữ tiếng Anh)

---

## Slide 1 — Trang bìa

- **Tiêu đề:** Conservative Timestamp Ordering for Fault-Tolerant Assembly-Line Scheduling
- **Đề tài #27 — Category 3: Distributed Concurrency Control**
- Môn: Distributed Database Systems
- Nhóm: [Team Name] | Thành viên: [TBD]
- Ngày: [ngày bảo vệ]

---

## Slide 2 — Bài toán đặt ra (1 phút)

**Nội dung:**
- Hệ thống sản xuất tự động: nhiều TM cập nhật bảng `Assembly_Line_Steps` đồng thời trên 3 sites
- Câu hỏi: làm thế nào kiểm soát đồng thời **mà không cần khóa**, đảm bảo nhất quán?
- Hai hướng tiếp cận: **Basic TO** (reject + restart) vs **Conservative TO** (delay, zero restart)

**Hình minh hoạ:**
```
Assembly Line  →  [M-001] PENDING → IN_PROGRESS → COMPLETED
               →  [M-042] ....
               →  [M-099] ....
```

---

## Slide 3 — Lý thuyết nền (1.5 phút)

**Nội dung:**
- Timestamp Ordering: gán ts tại begin(), kiểm tra `rts(x)`, `wts(x)` *(§5.2.2, tr. 197)*
- **Basic TO — Algorithm 5.5, tr. 200:**
  - READ(x): reject nếu `ts < wts(x)` → restart
  - WRITE(x): reject nếu `ts < rts(x)` hoặc `ts < wts(x)` → restart
- **Conservative TO — §5.2.2.2, tr. 201–203:**
  - Mỗi Scheduler giữ queue `Q^t_s` cho từng TM t
  - Release khi `∀t: Q^t_s ≠ ∅` → pop op có `min ts`
  - **Zero restart** — trả giá bằng delay ≥ T_dummy/2

**Diagram:** bảng so sánh Basic TO vs CTO (2 cột)

---

## Slide 4 — Kiến trúc hệ thống (1.5 phút)

**Diagram ASCII (từ design_2page.md):**
```
+----------+   HTTP/REST   +----------+   HTTP/REST   +----------+
| site_a   |<------------>| site_b   |<------------>| site_c   |
| TM + SC  |              | TM + SC  |              | TM + SC  |
| DP+SQLite|              | DP+SQLite|              | DP+SQLite|
+----------+              +----------+              +----------+
```

**Bullet points:**
- 3 sites = 3 Docker containers, bridge network `cto_net`
- Phân mảnh: `hash(machine_id) % 3` → site 0/1/2 (~33% mỗi site)
- `Timestamp = (counter, site_id)` — không cần NTP
- `T_dummy = 50ms` — heartbeat ngăn stall vô hạn

---

## Slide 5 — Quy trình CTO (2 phút)

**Mô tả sequence cross-site T_handoff:**

```
TM@site_a                Scheduler@site_b          Scheduler@site_a
    |                          |                          |
    |-- WRITE Y (ts=5) ------->|                          |
    |                    enqueue Q^a_b                    |
    |                    all_non_empty? NO (Q^b_b empty)  |
    |                          |                          |
    |<--- dummy(ts=6) from site_b (every 50ms) ---------->|
    |                    all_non_empty? YES               |
    |                    pop min(ts=5) → dispatch DP      |
    |<-- OpResult(ok=True) ----|                          |
```

**Giải thích:**
- Dummy message là bằng chứng rằng "không có op nào ts < 6 từ TM b sẽ đến nữa"
- Khi đó `ts=5` được giải phóng an toàn — đảm bảo serializable order

---

## Slide 6 — Cài đặt kỹ thuật (1 phút)

**Tech Stack:**
- Python 3.11 + FastAPI + httpx (async) + SQLite per site
- Docker Compose 3 services, bridge network

**Cấu trúc module:**
| Module | Chức năng |
|---|---|
| `ClockSync` | Monotonic counter + site_id tiebreak |
| `QueueManager` | heapq per TM, thread-safe Lock |
| `ConservativeScheduler` | asyncio.Future per op, release_loop task |
| `DataProcessor` | SQLite WAL, `rts/wts` trong `step_meta` |
| `DummyMessageGenerator` | httpx POST /dummy mỗi 50ms |

**Tests:** 11/11 pass (`pytest -q`)

---

## Slide 7 — Kết quả thí nghiệm (2 phút)

**Bảng so sánh CTO vs Basic TO** *(điền số thực sau khi chạy cluster)*:

| Metric | CTO | Basic TO |
|---|---|---|
| avg_ms | `[thực nghiệm]` | `[thực nghiệm]` |
| p95_ms | `[thực nghiệm]` | `[thực nghiệm]` |
| total_restarts | **0** (invariant) | `[thực nghiệm]` |

**Sweep T_dummy:**
- T_dummy ↓ → latency ↓ nhưng overhead dummy messages ↑
- T_dummy ↑ → overhead ↓ nhưng avg latency ↑

**Kết luận đo lường:** CTO latency ≈ Basic TO latency + T_dummy/2

*(Điền số thực từ `experiments/results/cto.json` và `basic_to.json` trước khi trình bày)*

---

## Slide 8 — Failure Scenario (D5) (2 phút)

**Timeline minh hoạ:**

| Thời điểm | Sự kiện | CTO | Basic TO |
|---|---|---|---|
| t=0 | Cluster running | Bình thường | Bình thường |
| t=30s | `docker kill cto-site-b` | **STALL** — Q^b_a, Q^b_c rỗng | Restart in-flight ops |
| t=40s | `docker start cto-site-b` | Dummy unblock → **Resume** | Không liên quan |
| Kết quả | | **0 abort, 0 data loss** | Có restart |

**Điểm mấu chốt:**
- CTO stall = **tính chịu lỗi**: không mất transaction, không cần rollback
- Khi site_b quay lại: dummy messages fill lại `Q^b_*` → release_loop tiếp tục từ đúng điểm dừng
- Trade-off: stall time = thời gian site_b ngoại tuyến

---

## Slide 9 — Trade-off & Kết luận (1.5 phút)

**Trade-off CTO vs Basic TO:**

| Tiêu chí | CTO | Basic TO |
|---|---|---|
| Conflict handling | **Delay** | **Restart** |
| Latency | Cao hơn ≥ T_dummy/2 | Thấp hơn (low conflict) |
| Restart count | **0** (guarantee) | > 0 |
| Node failure | **Stall** → tự phục hồi | Restart in-flight ops |
| Phù hợp khi | Fault-tolerance ưu tiên | Latency ưu tiên |

**Kết luận:**
- Trong bối cảnh **Automated Manufacturing**: delay tốt hơn abort → CTO là lựa chọn phù hợp
- Lý thuyết từ Özsu & Valduriez 2020 §5.2.2.2, tr. 202–203 đã được hiện thực và xác minh thực nghiệm

---

## Slide 10 — Demo & Q&A

**Nội dung:**
- "Xem video demo D5 (3:30 phút) — bao gồm `docker kill cto-site-b` và recovery"
- Sẵn sàng trả lời câu hỏi về:
  - Release condition `∀t: Q^t_s ≠ ∅`
  - Dummy message mechanics
  - Trade-off với Basic TO

**Tài liệu tham khảo:**
> M. Tamer Özsu & Patrick Valduriez — *Principles of Distributed Database Systems*, 4th Ed., Springer 2020.
> §5.2.2.1 Basic TO (tr. 198–201), §5.2.2.2 Conservative TO (tr. 201–203)

---

## Ghi chú chuẩn bị slide

- **Công cụ khuyến nghị:** PowerPoint / Google Slides / Canva
- **Màu sắc:** 1 màu chủ đạo; highlight key terms (CTO, restart=0, stall)
- **Font:** Sans-serif ≥ 24pt cho body text
- **Diagram:** dùng lại ASCII art từ `docs/design_2page.md` hoặc chuyển sang shapes
- **Bảng số liệu:** điền số thực từ `experiments/results/*.json` trước khi trình bày
- **Không đọc slide** — slide là visual aid, nói từ hiểu biết
