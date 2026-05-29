# Design Document — Conservative Timestamp Ordering for Fault-Tolerant Assembly-Line Scheduling

**Project #27 — Category 3 — Distributed Concurrency Control** · Team `[TBD]`

Hệ thống hiện thực giao thức **Conservative Timestamp Ordering (CTO)** trên 3 site (`site_a/b/c`) tương ứng 3 phân xưởng. Mỗi site host đầy đủ 3 module — `TransactionManager` (TM), `ConservativeScheduler` (SC), `DataProcessor` (DP) — giao tiếp qua HTTP/REST (FastAPI + httpx async). Dữ liệu `Assembly_Line_Steps` phân mảnh ngang: `site_index = stable_hash(machine_id) % 3` bằng `hashlib.blake2b`.

## 1. Component diagram

```
+-------- site_a ---------+   +-------- site_b ---------+   +-------- site_c ---------+
| TM_a -> dummy heartbeat |   | TM_b -> dummy heartbeat |   | TM_c -> dummy heartbeat |
|   |                     |   |   |                     |   |   |                     |
|   v                     |   |   v                     |   |   v                     |
| SC_a : Q^a_a Q^b_a Q^c_a|<->| SC_b : Q^a_b Q^b_b Q^c_b|<->| SC_c : Q^a_c Q^b_c Q^c_c|
|   |  release-rule       |   |   |                     |   |   |                     |
|   v                     |   |   v                     |   |   v                     |
| DP_a : rts/wts + SQLite |   | DP_b : rts/wts + SQLite |   | DP_c : rts/wts + SQLite |
+-------------------------+   +-------------------------+   +-------------------------+
        \______________ ClockSync (counter_local, site_id) + httpx bridge ___________/
```

`ClockSync` cung cấp `Timestamp = (counter_local: int64, site_id: 0|1|2)` với tiebreak `site_id`. `DummyMessageGenerator` phát heartbeat mỗi `T_dummy = 50 ms` (env `DUMMY_INTERVAL_MS`). `QueueManager` quản lý các priority queue `Q^t_s` nội tại `SC_s`.

## 2. Data structures

| Symbol | Type | Owner | Purpose |
|---|---|---|---|
| `Q^t_s` | `heapq[(ts, tx_id, op_seq, op)]` | `SC` tại site `s` | buffered ops từ TM tại site `t` |
| `rts(x)` | int64 | `DP` của site sở hữu `x` | timestamp đọc lớn nhất từng thấy *(§5.2.2, tr. 198)* |
| `wts(x)` | int64 | như trên | timestamp ghi lớn nhất từng thấy |
| `min_future_ts[t]` | int64 | `SC` | cận dưới ts tương lai từ TM `t` (cập nhật bởi dummy) |
| `Operation` | `(type, item, value?, ts, tm_id, tx_id, op_seq)` | gói tin REST | `type ∈ {READ, WRITE, DUMMY, COMMIT}` |

## 3. Sequence — cross-site `T_handoff` (Step X ở `site_a` → Step Y ở `site_b`)

```
TM_a            SC_a          DP_a         SC_b          DP_b
 | begin ts=t1   |              |             |             |
 |--WRITE(X,t1)->| enqueue Q^a_a              |             |
 |               | all_queues_non_empty? YES (dummy from b,c held)
 |               | pop min ts → send DP_a    |             |
 |               |------------->| wts(X):=t1 |             |
 |--WRITE(Y,t1)-------------------------------->| enqueue Q^a_b
 |               |              |             | all_queues_non_empty? YES
 |               |              |             | pop min ts → send DP_b
 |               |              |             |------------>| wts(Y):=t1
 |<----------------- COMMIT ack (t1) --------------------------|
```

Dummy messages từ `TM_b`, `TM_c` (không vẽ) duy trì `Q^b_a`, `Q^c_a`, `Q^b_b`, ... non-empty. Không có abort, không restart — đảm bảo bởi release-rule.

## 4. Pseudocode — `ConservativeScheduler` (extremely-conservative, §5.2.2.2 tr. 201–203)

Bám Algorithm 5.5 BTO-SC *(tr. 200)* nhưng thay điều kiện "compare ts với rts/wts → reject" bằng "block until safe":

```pseudo
loop forever:
    wait until all_queues_non_empty()                       # §5.2.2.2 tr. 202
    op := pop_head_with_min_ts(Q^t_s for all t)             # min ts xuyên mọi queue
    if op.type = DUMMY:
        min_future_ts[op.tm_id] := op.ts                    # advance lower-bound
        continue
    send op to DataProcessor                                 # GUARANTEED safe
    on ack:
        if op.type = READ:  rts(op.item) := max(rts, op.ts); return value
        if op.type = WRITE: wts(op.item) := op.ts; persist value
        ack TM(op.tm_id)

fn all_queues_non_empty(): return ∀ t ∈ KnownTMs : Q^t_s ≠ ∅
```

`TransactionManager` bám Algorithm 5.4 BTO-TM *(tr. 199)*:

```pseudo
on begin(tx):  tx.ts := ClockSync.next()                    # (counter++, site_id)
on op(tx, o):  scheduler_at(site_of(o.item)).send((o, tx.ts, tx.id, seq++))
on idle T_dummy ms:
    broadcast DummyMessage(ts = ClockSync.peek()) to ALL schedulers
on commit(tx): broadcast COMMIT(tx.ts, tx.id) to ALL schedulers touched
```

## 5. Failure handling — `docker kill cto-site-b`

| Phase | Diễn biến | Trạng thái cluster |
|---|---|---|
| t=0 | bình thường, dummy 50 ms từ B duy trì `Q^b_a`, `Q^b_c` | tiến độ ổn định |
| t=30s | `docker kill cto-site-b` | TM_b chết, không phát dummy |
| t≈30.05s | `Q^b_a` & `Q^b_c` cạn → `all_queues_non_empty()` = false | SC_a, SC_c **stall** — KHÔNG abort, KHÔNG mất data |
| t=k+T | `docker start cto-site-b` → TM_b nạp `counter_local` từ persistent + phát dummy catch-up | SC_a, SC_c resume từ đúng vị trí |

Cảnh báo: env `STALL_WARN_MS=5000` chỉ log; KHÔNG tự abort (giữ semantic CTO thuần). Đối chiếu Basic TO: cross-site tx phụ thuộc B sẽ restart khi B quay lại — không phù hợp manufacturing vì thao tác vật lý đã thực hiện không thể rollback.

## 6. Configuration knobs

| Env var | Default | Purpose |
|---|---|---|
| `SCHED_MODE` | `cto` | switch `cto` ↔ `basic_to` (bench) |
| `DUMMY_INTERVAL_MS` | `50` | `T_dummy` heartbeat — sweep `{10,50,100,500}` |
| `SITE_ID` | `0/1/2` | per-container; dùng trong ts tiebreak |
| `STALL_WARN_MS` | `5000` | warn-only, no auto-abort |
| `WORKLOAD_TXS` | `1000` | bench size |

*Reference: Özsu & Valduriez 2020 — §5.2.2 (tr. 198), §5.2.2.1 Alg. 5.4–5.5 (tr. 199–200), §5.2.2.2 (tr. 201–203). Layout: A4, 11pt, lề 1 inch — render fits 2 pages.*
