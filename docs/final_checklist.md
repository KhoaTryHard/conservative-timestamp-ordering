# Final Checklist — Đề tài #27 CTO

> Tích [ ] → [x] trước khi nộp. Mỗi mục có đường dẫn file kiểm chứng.

---

## 5 Deliverables

### D1 — Project Proposal ✅
- [x] File: `docs/proposal.md`
- [x] 7 mục đúng thứ tự template
- [x] Tiêu đề tiếng Anh: "Conservative Timestamp Ordering for Fault-Tolerant Assembly-Line Scheduling"
- [x] Dataset: `Assembly_Line_Steps(StepID, MachineID, Status)`, 10k rows, seed=42
- [x] Failure scenario: `docker kill cto-site-b`
- [x] Timeline: Week 5/8/12
- [ ] **Điền tên nhóm và thành viên** (hiện còn placeholder)

### D2 — 2-page Design Document ✅
- [x] File: `docs/design_2page.md`
- [x] ASCII component diagram (TM/SC/DP per site)
- [x] Data structures: Q^t_s, rts(x), wts(x), Timestamp(counter, site_id)
- [x] Sequence diagram cross-site T_handoff
- [x] Pseudocode ConservativeScheduler (extends Alg. 5.5)
- [x] Failure table: 4-phase docker kill → stall → restart → resume
- [x] Config knobs: SCHED_MODE, DUMMY_INTERVAL_MS, SITE_ID, STALL_WARN_MS
- [x] Citations: §5.2.2.2, tr. 201–203

### D3 — Code Repo + README ✅
- [x] `README.md` đầy đủ (architecture, prerequisites, install, run, test, config)
- [x] `src/common/`: `messages.py`, `clock_sync.py`, `dummy_msg.py`, `config.py`
- [x] `src/scheduler/`: `scheduler_cto.py`, `scheduler_basic_to.py`, `queue_manager.py`
- [x] `src/dp/data_processor.py`
- [x] `src/tm/transaction_manager.py`
- [x] `src/api/main.py`, `src/api/routers.py`
- [x] `data/data_generator.py`
- [x] `experiments/experiment_runner.py`, `experiments/metrics.py`
- [x] `docker-compose.yml`, `Dockerfile`, `pyproject.toml`
- [x] `tests/`: 11/11 tests pass (`pytest -q`)
- [x] `.gitignore` loại trừ `data/site_*.db`, `experiments/results/*.json`, `.venv`

### D4 — Analysis Report ✅
- [x] File: `docs/analysis_report.md`
- [x] 9 mục: Giới thiệu, Lý thuyết, Thiết kế, Biện minh, Thí nghiệm, Kết quả, Trade-off, So sánh, Kết luận
- [x] Citation §5.2.2.1 (tr. 198–201), §5.2.2.2 (tr. 201–203), Alg. 5.4–5.5
- [x] Bảng kết quả có placeholder rõ ràng (không bịa số)
- [ ] **Điền số liệu thực nghiệm** vào bảng Section 6 sau khi chạy cluster

### D5 — Screen-recording ✅ (script)
- [x] Script: `docs/screenrecord_script.md`
- [x] Timeline 3:30–4:30 phút
- [x] Phân đoạn "Kill site_b" rõ ràng (02:10–03:20)
- [x] Checklist pre-recording và post-recording
- [ ] **Quay video thực tế** (cần cluster chạy)
- [ ] Video nêu §5.2.2.2, tr. 201–203 trong narration
- [ ] `total_restarts = 0` visible trong JSON output
- [ ] `docker kill` + `docker start` cả hai đều visible

### Slides — Final Exam Presentation ✅ (outline)
- [x] Outline: `docs/slides_outline.md` (10 slides, 10–15 phút)
- [ ] **Tạo slide thực tế** từ outline (PowerPoint/Google Slides)
- [ ] Điền số thực vào Slide 7 (kết quả thí nghiệm)
- [ ] Điền tên nhóm vào Slide 1

---

## Citations Checklist (bắt buộc trong tất cả deliverables)

| Claim | Section | Trang | Có trong |
|---|---|---|---|
| TO Framework (rts/wts) | §5.2.2 | ~197 | D2, D4, slides |
| Basic TO reject rule | §5.2.2.1, Alg. 5.5 | 200 | D4, slides |
| BTO-TM algorithm | §5.2.2.1, Alg. 5.4 | 199 | D4 |
| CTO release condition | §5.2.2.2 | 201–202 | D2, D4, slides |
| Dummy message necessity | §5.2.2.2 | 202 | D2, D4, slides |
| CTO failure/stall behavior | §5.2.2.2 | 202–203 | D4, D5 script, slides |

---

## Trước ngày nộp — To-Do

- [ ] `git init && git add -A && git commit -m "feat: complete project implementation"`
- [ ] Chạy `python -m data.data_generator --rows 10000 --seed 42 --out data/`
- [ ] Chạy `docker compose up --build` và verify healthz 3 sites
- [ ] Chạy experiment_runner CTO + Basic TO → điền số vào `analysis_report.md` Section 6
- [ ] Quay screen-recording theo `docs/screenrecord_script.md`
- [ ] Tạo slide thực từ `docs/slides_outline.md`
- [ ] Điền tên nhóm vào: `proposal.md`, `design_2page.md`, `analysis_report.md`, `CLAUDE.md`, slides

---

## Self-Check cuối (CLAUDE.md §workflow)

- [x] Mọi claim lý thuyết có cite §section + trang Özsu & Valduriez?
- [x] Không bịa số benchmark nào?
- [x] Template 7-mục và 5-deliverable giữ nguyên?
- [x] Vietnamese prose / English code — đúng cả hai?
- [x] Không bỏ qua bước nào trong 7-task workflow?
- [x] `stable_hash(machine_id) % 3` nhất quán giữa TM, DataGenerator, tests?
- [x] `DUMMY_INTERVAL_MS` tunable qua env var, không hard-code trong scheduler?
