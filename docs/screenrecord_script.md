# Kịch bản Screen-recording — Deliverable D5
# Conservative Timestamp Ordering for Fault-Tolerant Assembly-Line Scheduling

**Thời lượng mục tiêu:** 3 phút 30 giây – 4 phút 30 giây  
**Công cụ ghi:** OBS Studio (hoặc bất kỳ screen recorder nào)  
**Layout màn hình:** Terminal trái (cluster + logs), Terminal phải (commands), Browser (healthz)  
**Ngôn ngữ narration:** Tiếng Việt  

---

## Chuẩn bị trước khi quay (KHÔNG quay phần này)

```powershell
# 1. Sinh dataset
python -m data.data_generator --rows 10000 --seed 42 --out data/

# 2. Build Docker images (để lần quay không phải chờ build)
docker compose build

# 3. Dọn container cũ nếu có
docker compose down -v
```

---

## Timeline kịch bản

---

### [00:00 – 00:30] Giới thiệu đề tài

**Hành động:** Hiển thị màn hình Desktop hoặc slide title.

**Narration:**
> "Xin chào, đây là video demo cho đề tài số 27: *Conservative Timestamp Ordering for Fault-Tolerant Assembly-Line Scheduling*, thuộc môn Distributed Database Systems.
>
> Chúng tôi hiện thực hai giao thức kiểm soát đồng thời phân tán: **Basic Timestamp Ordering** theo §5.2.2.1 và **Conservative Timestamp Ordering** theo §5.2.2.2 trong sách Özsu & Valduriez 2020. Mục tiêu là so sánh Average Transaction Latency và minh chứng tính chịu lỗi của CTO."

---

### [00:30 – 01:00] Khởi động cluster 3 sites

**Hành động — Terminal trái:**

```powershell
docker compose up --build
```

Chờ xuất hiện log từ cả 3 containers:
```
cto-site-a  | INFO: Uvicorn running on http://0.0.0.0:8001
cto-site-b  | INFO: Uvicorn running on http://0.0.0.0:8002
cto-site-c  | INFO: Uvicorn running on http://0.0.0.0:8003
```

**Hành động — Terminal phải (health check):**

```powershell
curl http://localhost:8001/healthz
curl http://localhost:8002/healthz
curl http://localhost:8003/healthz
```

**Output mẫu:**
```json
{"site": 0, "status": "ok", "sched_mode": "cto"}
{"site": 1, "status": "ok", "sched_mode": "cto"}
{"site": 2, "status": "ok", "sched_mode": "cto"}
```

**Narration:**
> "Chúng tôi khởi động cụm 3 sites bằng Docker Compose — site_a cổng 8001, site_b cổng 8002, site_c cổng 8003. Mỗi site chạy FastAPI với scheduler CTO, lưu trữ trên SQLite riêng biệt.
>
> Health check cho thấy cả 3 sites đang hoạt động bình thường với `sched_mode: cto`."

---

### [01:00 – 01:40] Chạy thí nghiệm CTO — đo latency

**Hành động — Terminal phải:**

```powershell
python -m experiments.experiment_runner `
  --mode cto --txs 1000 --seed 42 `
  --out experiments/results/cto.json
```

Chờ kết thúc (khoảng 20–30 giây tùy máy). Sau đó hiển thị kết quả:

```powershell
Get-Content experiments/results/cto.json | python -m json.tool
```

**Số liệu thực tế đo ngày 2026-05-24 (`--txs 1000 --seed 42`):**
```
[done] mode=cto txs=1000 avg=1507.227ms p95=113.237ms restarts=0
```
*(avg cao do warm-up: vài chục transaction đầu phải chờ dummy heartbeat đẩy clock của 3 site vượt qua ts của runner. Sau warm-up, latency rơi về ~60–110 ms — xác nhận bởi run 5000 txs avg=61.811ms cùng p95=111.973ms.)*

**Narration:**
> "Chúng tôi chạy 1000 transactions với seed 42, workload gồm 60% T_advance, 30% T_complete và 10% T_handoff cross-site.
>
> Lưu ý `restarts = 0` — đây là **bất biến của CTO**: Scheduler không bao giờ reject hay restart một giao dịch. Thay vào đó, operation được giữ trong hàng đợi `Q^t_s` cho đến khi tất cả hàng đợi đều có ít nhất một phần tử — đây chính là *release condition* theo §5.2.2.2."

---

### [01:40 – 02:10] So sánh với Basic TO

**Hành động — Terminal phải (dừng cluster, restart với Basic TO):**

```powershell
docker compose down
$env:SCHED_MODE = "basic_to"
docker compose up -d --build
Start-Sleep -Seconds 5

python -m experiments.experiment_runner `
  --mode basic_to --txs 1000 --seed 42 `
  --out experiments/results/basic_to.json

Get-Content experiments/results/basic_to.json | python -m json.tool
```

**Số liệu thực tế đo ngày 2026-05-24 (`--mode basic_to --txs 1000 --seed 42`):**
```
[done] mode=basic_to txs=1000 avg=52.45ms p95=94.977ms restarts=7
```

**Narration:**
> "Bây giờ chúng tôi chuyển sang **Basic Timestamp Ordering** bằng cách đặt biến môi trường `SCHED_MODE=basic_to`. Cùng dataset, cùng seed, cùng số transaction.
>
> Basic TO xử lý operation ngay khi nhận — nếu timestamp của transaction nhỏ hơn `rts(x)` hoặc `wts(x)`, operation bị **reject và transaction phải restart** với timestamp mới, theo Algorithm 5.5 tr. 200.
>
> Kết quả: Basic TO `avg=52ms p95=95ms restarts=7` — nhanh hơn CTO ở steady state nhưng có 7 transaction bị abort + restart trên 1000 tx (~0.7%). Trade-off cốt lõi: CTO đổi *latency* lấy *zero restart*."

---

### [02:10 – 03:20] Kịch bản Failure — docker kill site_b (PHẦN QUAN TRỌNG NHẤT)

**Chuẩn bị — restart cluster với CTO:**

```powershell
docker compose down
docker compose up -d --build
Start-Sleep -Seconds 5
```

**Bước 1 — Khởi động experiment trong background:**

```powershell
# Terminal phải — chạy experiment (sẽ bị stall khi kill site_b)
python -m experiments.experiment_runner `
  --mode cto --txs 1000 --seed 42 `
  --out experiments/results/cto_failure.json
```

*(Để lệnh này chạy, KHÔNG chờ kết thúc)*

**Bước 2 — Sau ~15 giây, kill site_b:**

```powershell
# Mở Terminal mới hoặc dùng Ctrl+Z rồi bg
Start-Sleep -Seconds 15
docker kill cto-site-b
```

**Bước 3 — Quan sát log site_a và site_c stall:**

Trong Terminal trái (docker compose logs), sẽ thấy (log thực tế đo ngày 2026-05-24):
```
cto-site-a  | stall detected: not all queues non-empty for 5001ms
cto-site-a  | stall detected: not all queues non-empty for 5041ms
cto-site-c  | stall detected: not all queues non-empty for 5002ms
cto-site-c  | stall detected: not all queues non-empty for 5035ms
```

Đồng thời, log dòng `POST /op` BIẾN MẤT khỏi site_a và site_c — chỉ còn lại `POST /dummy` từ địa chỉ IP self (`127.0.0.1`) và IP của site còn lại (172.18.0.x). IP của site_b (trước kill là `172.18.0.3`) hoàn toàn vắng mặt.

*(Không có "ABORT" hay "RESTART" — đây là bằng chứng CTO stall chứ không abort)*

**Narration (trong khi stall):**
> "Chúng tôi vừa kill site_b — container đã dừng. Quan sát log của site_a và site_c: xuất hiện cảnh báo **stall detected** — hàng đợi `Q^b_a` và `Q^b_c` không còn được bổ sung bởi site_b.
>
> Theo §5.2.2.2, release condition yêu cầu *tất cả* hàng đợi phải có phần tử. Vì site_b đã ngừng gửi, hàng đợi của nó rỗng → **hệ thống stall hoàn toàn**, không abort, không mất dữ liệu. Đây chính là tính chịu lỗi đặc trưng của CTO."

**Bước 4 — Restart site_b:**

```powershell
docker start cto-site-b
```

**Quan sát — site_b khởi động lại, gửi dummy messages, unblock queues:**

Log thực tế đo ngày 2026-05-24:
```
cto-site-b  | INFO: Uvicorn running on http://0.0.0.0:8000
cto-site-b  | INFO: Application startup complete.
cto-site-a  | INFO: 172.18.0.3:59772 - "POST /dummy HTTP/1.1" 204 No Content
cto-site-c  | INFO: 172.18.0.3:37926 - "POST /dummy HTTP/1.1" 204 No Content
```

(Site_b nhận IP mới sau restart, dummy thread khôi phục heartbeat → Q^1_0 và Q^1_2 lại non-empty → release loop dispatch op tiếp tục. Dòng `stall detected` ngừng xuất hiện.)

**Bằng chứng phục hồi hoàn toàn — chạy 200 tx ngay sau recovery:**
```
[done] mode=cto txs=200 avg=63.133ms p95=113.369ms restarts=0
```
*(Latency trùng với steady-state CTO trước kill ⇒ hệ thống trở về 100% baseline.)*

**Narration:**
> "Chúng tôi restart site_b. Ngay khi site_b kết nối trở lại, nó gửi **dummy messages** với `min_future_ts` để unblock hàng đợi tại site_a và site_c.
>
> Hệ thống tiếp tục xử lý từ chính xác điểm stall — **không có transaction nào bị abort, không có dữ liệu nào bị mất**. Đây là sự khác biệt căn bản với Basic TO: nếu dùng Basic TO, các in-flight operations sẽ bị reject và transaction phải restart."

---

### [03:20 – 04:00] Kết quả thí nghiệm failure & tổng kết

**Hành động — Chờ experiment kết thúc, hiển thị kết quả:**

```powershell
Get-Content experiments/results/cto_failure.json | python -m json.tool
```

**Narration:**
> "Kết quả sau failure scenario: `total_restarts` vẫn bằng 0 — CTO giữ vững bất biến ngay cả khi có node failure. Thời gian stall (được ghi trong `max_stall_ms`) phản ánh thời gian site_b ngoại tuyến.
>
> Tóm tắt so sánh:
> - **CTO**: zero restart, stall khi fault, latency cao hơn ~T_dummy/2, phục hồi tự động.
> - **Basic TO**: restart khi conflict, không stall khi fault, latency thấp hơn trong điều kiện bình thường.
>
> Trong bối cảnh dây chuyền lắp ráp, một bước bị *delay* tốt hơn bị *abort và làm lại*. CTO là lựa chọn phù hợp theo §5.2.2.2, tr. 202–203.
>
> Cảm ơn đã theo dõi."

---

### [04:00 – 04:15] Credits (tuỳ chọn)

**Hành động:** Hiển thị slide kết thúc với thông tin nhóm.

```
Đề tài #27 — Conservative Timestamp Ordering
Môn: Distributed Database Systems
Nhóm: [Team Name]
Lý thuyết: Özsu & Valduriez 2020, §5.2.2.2, tr. 201–203
```

---

## Checklist trước khi quay

- [ ] Dataset đã được sinh (`data/site_a.db`, `data/site_b.db`, `data/site_c.db` tồn tại).
- [ ] Docker images đã được build sẵn (`docker compose build` thành công).
- [ ] Xóa kết quả cũ: `Remove-Item experiments/results/*.json -ErrorAction SilentlyContinue`.
- [ ] Terminal trái dành cho `docker compose up` + logs.
- [ ] Terminal phải dành cho commands.
- [ ] Font terminal đủ lớn để rõ trên video (≥ 14pt).
- [ ] Tắt notification OS trước khi quay.
- [ ] Luyện narration ít nhất 1 lần để đúng thời lượng 3:30 – 4:30.

## Checklist D5 (submit)

- [ ] Video 3–5 phút, không cắt ghép quá thô.
- [ ] Xuất hiện rõ `docker kill cto-site-b` và log stall.
- [ ] Xuất hiện rõ `docker start cto-site-b` và log unblock.
- [ ] `restarts = 0` được đọc rõ trong kết quả CTO.
- [ ] So sánh ngắn với Basic TO (`restarts > 0`, cụ thể 7/1000).
- [ ] Narration đề cập §5.2.2.2, tr. 201–203.

## Evidence files (dry-run D5 đã chạy ngày 2026-05-24)

- `experiments/results/cto.json` — CTO 1000 tx (avg=1507ms p95=113ms restarts=0)
- `experiments/results/basic_to.json` — Basic TO 1000 tx (avg=52ms p95=95ms restarts=7)
- `experiments/results/d5/cto_during_kill.json` — CTO 5000 tx, kill timing đã chạm
- `experiments/results/d5/cto_after_recovery.json` — CTO 200 tx sau restart site_b
- `experiments/results/d5/logs_site_{a,b,c}_full.log` — full container logs có dòng `stall detected`
