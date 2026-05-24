# STATUS — CSDLPT #27 CTO

> Snapshot ngày **2026-05-24**. Auto-loaded qua `CLAUDE.md`.
> Cập nhật mỗi khi hoàn thành deliverable hoặc thay đổi quyết định kiến trúc lớn.
> File này VẪN tuân theo rule "every line changes agent behavior" — không thêm narrative dư thừa.

## 1. Đã hoàn thành

### Code & Infrastructure
- [x] **D3 Code repo** chạy được end-to-end. 3 sites Docker Compose. Cả `SCHED_MODE=cto` và `basic_to` đều xanh.
- [x] `src/scheduler/scheduler_cto.py` — release rule cực-kỳ-bảo-thủ §5.2.2.2 (∀t Q^t_s ≠ ∅ + pop min ts).
- [x] `src/scheduler/scheduler_basic_to.py` — baseline so sánh (§5.2.2.1, Algorithm 5.5).
- [x] `src/scheduler/queue_manager.py` — `_core_tm_ids: frozenset` chặn external TM block release.
- [x] `src/common/dummy_msg.py` + `src/api/main.py` — dummy generator gửi tới CẢ self (`localhost:8000`) lẫn peer.
- [x] `src/common/clock_sync.py` propagation — `submit()` và `submit_dummy()` đều `clock.observe(ts)`.

### Experiments
- [x] `experiments/results/cto.json` — CTO 1000 tx: `avg=1507ms p95=113ms restarts=0` (warm-up dominated).
- [x] `experiments/results/basic_to.json` — Basic TO 1000 tx: `avg=52ms p95=95ms restarts=7`.
- [x] D5 failure scenario — full kill+restart cycle, evidence trong `experiments/results/d5/`:
  - `cto_during_kill.json` — 5000 tx `avg=62ms restarts=0`.
  - `cto_after_recovery.json` — 200 tx `avg=63ms restarts=0` (xác nhận hồi phục trùng baseline).
  - `logs_site_{a,b,c}_full.log` — full container logs có dòng `stall detected: not all queues non-empty for ~5000ms`.

### Docs
- [x] D1 `docs/proposal.md` — 7 sections theo Proposal Template.
- [x] D2 `docs/design_2page.md`.
- [x] D4 `docs/analysis_report.md` — DRAFT, chưa có số thật và D5 evidence.
- [x] D5 `docs/screenrecord_script.md` — đã thay placeholder bằng số thật và log wording thật.
- [x] `docs/slides_outline.md` — draft outline.
- [x] `docs/final_checklist.md`.

## 2. Trạng thái từng deliverable

| ID | Tên | Trạng thái | Việc còn lại |
|---|---|---|---|
| D1 | Proposal | ✅ Done | — |
| D2 | Design 2-page | ✅ Done | — |
| D3 | Code repo + README | ✅ Done | — |
| D4 | Analysis Report | ⚠️ Draft cần update | Inject số thật + D5 evidence |
| D5 | Screen recording | ⏳ Chưa quay | Quay theo `docs/screenrecord_script.md` |
| -- | Slides cuối kỳ | ⚠️ Draft outline | Inject số thật + 2 chart |

## 3. Bước tiếp theo (ưu tiên giảm dần)

1. **Update D4 `docs/analysis_report.md`** — inject:
   - Bảng so sánh CTO (cold 1507ms / warm ~62ms / restarts=0) vs Basic TO (52ms / restarts=7).
   - Phần warm-up: vì sao 1000 tx avg cao hơn 5000 tx (warm-up cost amortize).
   - Trade-off cho Automated Manufacturing: delay tốt hơn abort+restart máy.
   - Cite §5.2.2.1, §5.2.2.2, Algorithms 5.4–5.5 với page numbers chính xác.
2. **Quay D5 video** theo `docs/screenrecord_script.md`. 3:30–4:30 phút. BẮT BUỘC có rõ `docker kill cto-site-b` + log `stall detected` + `docker start` + `restarts=0`.
3. **Hoàn thiện `docs/slides_outline.md`** với 2 chart:
   - Latency p95: CTO warm vs Basic TO (gần như overlap).
   - Bar chart restarts: CTO=0 vs Basic TO=7.

## 4. Quyết định quan trọng & lý do

### Architecture (FROZEN — không đổi)
- **Hash partitioning `hash(machine_id) % 3`** — cả 2 scheduler dùng chung. Đổi formula phải update cả 2 + tests.
- **3 sites cố định** — đại diện 3 phân xưởng dây chuyền Automated Manufacturing.
- **SQLite per site** — cô lập failure domain, phù hợp scope assignment.

### Protocol
- **Release rule cực-kỳ-bảo-thủ** (§5.2.2.2 strongest form): cho phép chứng minh `restarts=0` mà không cần restart/abort logic.
- **DUMMY ops dùng `op_seq=-1`** — không đụng `op_seq` thật của real ops.
- **`_core_tm_ids` frozenset cố định lúc init** — runner (TM-99) gửi op nhưng KHÔNG nằm trong release condition.

### Ba bug-fixes quan trọng (đã apply — KHÔNG revert)
- **Bug 1** `queue_manager.py`: `_core_tm_ids: frozenset(known_tm_ids)`. Reason: TM-99 (runner) auto-register vào `_queues` qua `enqueue()` → `all_non_empty()` chờ chính nó → stall vĩnh viễn.
- **Bug 2** `api/main.py`: thêm `"http://localhost:8000"` vào `all_scheduler_urls`. Reason: site-X không tự gửi dummy cho chính mình → Q^X tại site-X rỗng vĩnh viễn.
- **Bug 3** `scheduler_cto.py`: `clock.observe(op.ts)` trong `submit()`, `clock.observe(msg.ts)` trong `submit_dummy()`. Reason: dummies dùng `peek()` không advance clock → Docker TM clocks frozen ở ts=(1, site_id) → op của runner ts=(n, 3) không bao giờ là global min → không bao giờ release.

### Documentation policy
- **Source duy nhất**: Özsu & Valduriez 2020 — không dùng nguồn khác.
- **Ngôn ngữ**: prose Việt, code English, comments tối thiểu (chỉ WHY non-obvious).
- **Số liệu**: chỉ paste số thật từ experiment files, không bịa.

---
Cập nhật cuối: 2026-05-24 — Khoa
