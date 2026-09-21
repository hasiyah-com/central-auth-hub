# ML Capacity Gate — ml-service (L3) ต่อจำนวน worker — 2026-09-21

**ผลรวม: ไม่ผ่าน** ไม่มีค่าจำนวน worker ใดที่ผ่านครบทั้ง 4 เกณฑ์ · Shadow Pilot ยังเปิดไม่ได้

| workers | P1 p95 steady | P2 fit storm | P3 ความสอดคล้อง | P4 หน่วยความจำ |
|---|---|---|---|---|
| 1 | **ไม่ผ่าน** (c10, c20) | ผ่าน | ผ่าน | ผ่าน |
| 2 | **ไม่ผ่าน** (c20) | ผ่าน | ผ่าน | ผ่าน |
| 4 | **ไม่ผ่าน** (c20) | **ไม่ผ่าน** | ผ่าน | **ไม่ผ่าน** |

ค่าที่ใช้อยู่ตอนนี้ (`docker-compose.yml`) คือ worker 1 ตัวพร้อม `--reload`

## 1. เกณฑ์ (กำหนดก่อนวัด อยู่ใน `scripts/ml_capacity_gate.py`)

- **P1** steady state (cache อุ่น): ทุก (worker, concurrency) p95 ≤ 250 ms และ error = 0 — ใช้ค่าที่แย่สุดจาก 3 รอบ
- **P2** fit storm: ทุก process fit แต่ละคน ≤ 1 ครั้งตลอดการวัด · จบแล้วทุก process fit ครบ 20 คนพอดี · เห็นครบทุก worker · warm-up ต้องนิ่งภายใน 40 รอบ · ช่วง steady ต้องไม่มี fit เพิ่ม
- **P3** input เดียวกัน → คะแนนของโมเดล (sequence score/raw/percentile/n_history/eligibility, point score) เท่ากันทุกครั้ง ทุก worker รวม cold กับ warm · ทุก probe ต้องมีคะแนน sequence จริง (ไม่ abstain)
- **P4** RSS ต่อ process หลัง steady รอบ 3 โตจากรอบ 1 ไม่เกิน 5% และต้องวัดได้ทุก process
- ข้อมูลประกอบ: cold burst 20 request พร้อมกัน (10 ตัวเป็นคนเดียวกัน อีก 10 ตัวเป็นคนละคน) และจำนวนที่เกิน 500 ms (เพดาน L3 ของ login)

`duplicate_ratio` และ `monitoring_decision` ไม่อยู่ใน P3 เพราะขึ้นกับสถานะ `l3dup:` ใน Redis ซึ่งเปลี่ยนตามการส่งซ้ำโดยออกแบบ

## 2. สภาพแวดล้อม

- โค้ด: worktree ที่ `3991213` + ตัวนับ (`/v1/l3-capacity-stats`, ปิดไว้เป็นค่าเริ่มต้น) · image ml `sha256:d7282b7d0112` · image hub `sha256:d140bf98e81d`
- Docker Desktop 12 CPU / 8 GB · นาฬิกาผ่านตัวตรวจ (20 วินาที ไม่มีการกระโดด)
- ml-service ตัวใหม่ทุกค่าของ worker (`ml-cap`, ไม่มี `--reload`) → cache เย็นทุก process เท่ากับสภาพหลัง Docker restart
- ข้อมูลสังเคราะห์: 20 ผู้ใช้ × ประวัติ 2,000 แถว (MAX_HISTORY — ต้นทุน fit สูงสุด) ใน Redis DB 13 · ไม่แตะ DB 0/15 และ holdout
- โหลดเปิด connection ใหม่ทุก request เหมือน hub (`l3_sequence_client.py` สร้าง `AsyncClient` ใหม่ทุกครั้ง) · 400 request ต่อระดับ × 3 รอบ

## 3. ผล steady state — p50 / p95 / p99 (ms)

| workers | c=1 | c=5 | c=10 | c=20 |
|---|---|---|---|---|
| 1 | 14.9 / **24.5** / 27.1 | 96.7 / **152.5** / 177.0 | 189.0 / **314.1** / 367.3 | 401.2 / **555.9** / 599.7 |
| 2 | 15.5 / **24.9** / 28.6 | 44.1 / **101.1** / 134.1 | 70.6 / **139.6** / 177.2 | 147.3 / **402.0** / 431.1 |
| 4 | 16.6 / **30.7** / 37.6 | 43.3 / **104.7** / 148.8 | 52.0 / **135.7** / 250.5 | 85.2 / **271.6** / 310.8 |

(ค่า p95 = แย่สุดจาก 3 รอบ · p50/p99 จากรอบเดียวกัน) · error = 0 ทุกระดับ

- worker 1 ตัว: เวลาโตเป็นเส้นตรงกับ concurrency — endpoint เป็น sync ถือ GIL จึงประมวลผลทีละ request (ราว 19 ms ต่อ request รวม HTTP)
- worker 4 ตัวที่ c=20: p95 ต่อรอบ 265 / 272 / 239 — เกินเพดานสองในสามรอบ
- request ที่เกิน 500 ms ในช่วง steady: worker 1 ตัวที่ c=20 = 31 / 29 / 76 จาก 400 ต่อรอบ · worker 2 และ 4 = 0

## 4. Cold start (20 request พร้อมกันบน process เย็น)

| workers | p50 | p95 | เกิน 500 ms |
|---|---|---|---|
| 1 | 15.2 s | 15.3 s | 20/20 |
| 2 | 11.1 s | 11.2 s | 20/20 |
| 4 | 3.7 s | 3.8 s | 20/20 |

hub มีเพดาน L3 0.5 วินาที → login ทั้ง 20 ครั้งผ่านไปโดย L3 abstain (`l3_timeout`) ตามที่ออกแบบ แต่ ml-service ยังคำนวณต่อจนเสร็จและกิน CPU หลายวินาที ทำให้ request ถัดไปช้าตาม

**สาเหตุ (วัดแยกบน process ว่าง):**

| ส่วน | เวลา |
|---|---|
| request แรกของ process (ผู้ใช้ไม่มีประวัติ ไม่มี fit) | 1,115 ms |
| request ที่สอง | 20 ms |
| `predict_with_explanation` ครั้งแรก (import `shap` + สร้าง TreeExplainer) | 875 ms |
| fit ผู้ใช้ 2,000 แถว (ทีละตัว) | 156–197 ms (prep 32 · fit 132 · score_samples 12) |
| fit 11 คนพร้อมกันใน thread | 3,940 ms (มากกว่าผลรวมทีละตัว 2.2 เท่า — แย่ง GIL) |

1. **`model._load_explainer()` ไม่มีล็อก** — request ที่มาพร้อมกันตอนเย็น import `shap` และสร้าง TreeExplainer ซ้ำทุกตัว (ต้นทุนครั้งแรก ~0.9 วินาทีต่อตัว คูณจำนวน request)
2. fit หลายคนพร้อมกันแย่ง GIL — ล็อกต่อคน (B63) กัน fit ซ้ำคนเดียวกันได้ แต่ไม่ได้จำกัดจำนวน fit พร้อมกันข้ามคน
3. point view คำนวณ SHAP ทุก request แม้ `explain=False` (3.05 ms เทียบกับ 1.39 ms ถ้าไม่คำนวณ) — ไม่ใช่สาเหตุของ cold แต่กิน CPU ของ steady state ราวครึ่งหนึ่งของงานคำนวณ point view

## 5. ข้อค้นพบของ worker 4 ตัว — worker ถูกปล่อยเย็น

- warm-up 40 รอบ (3,200 request) ไม่นิ่ง: worker หนึ่งตัว (pid 9) แทบไม่ได้รับงาน · fit รวมหลัง warm-up = 60 จากที่ควรเป็น 80
- worker ตัวนั้นมา fit ครบ 20 คนในช่วง steady แทน → P2 ล้ม และวัด RSS รอบ 1 ของมันไม่ได้ → P4 ล้ม
- สาเหตุที่น่าจะเป็น: uvicorn หลาย worker ใช้ socket ร่วม kernel จึงแจก connection ให้แต่ละ worker ไม่เท่ากัน · ยังไม่ได้พิสูจน์ด้วยการนับต่อ pid ในช่วง warm-up
- ผลต่อระบบจริง: worker ที่ยังเย็นจะ fit ระหว่างช่วงใช้งาน (ราว 0.2–4 วินาทีต่อครั้งเมื่อมีงานพร้อมกัน) ในเวลาที่คาดเดาไม่ได้

## 6. ที่ผ่าน

- **ไม่มี fit storm ภายใน process** — ทุก process fit แต่ละคนครั้งเดียวในทุกค่าของ worker (ล็อกต่อคนของ B63 ทำงาน)
- **คะแนนสอดคล้องกัน 100%** — 20 probe × ~250 ครั้ง ข้าม worker ทุกตัว รวม cold กับ warm ไม่มีค่าต่างกันเลย
- **ไม่มี memory leak** — RSS เปลี่ยนไม่เกิน ±0.1% ระหว่างรอบ · RSS ต่อ process ~300–325 MB (worker 4 ตัวรวม 1.2 GB)
- log ของ ml-service ไม่มี error/traceback ทุกค่าของ worker

## 7. บั๊กของตัววัดที่เจอระหว่างทาง (ผลรอบนั้นทิ้งทั้งหมด)

รอบแรกของ worker 2 และ 4 ตัวเก็บสถิติเห็น pid เดียว เพราะ httpx ใช้ connection แบบ keep-alive ซ้ำ → ทุก request ไปลง worker เดิม · แก้ให้เปิด connection ใหม่ทุก request (เหมือน hub) แล้ววัดใหม่ทั้งสามค่า · มีเทสกันไว้ (`test_stats_open_a_new_connection_every_call`, `test_load_uses_a_new_connection_per_request_like_the_hub`)

หมายเหตุลำดับงาน: `evaluate()` ของตัววัดเขียนก่อนเทส (ผิดลำดับ TDD) — เทสจึงตรวจแบบกลับด้าน ทำให้แต่ละเกณฑ์เสียทีละข้อแล้วต้องเห็นว่าล้ม

## 8. ทางเลือกที่เสนอ (ยังไม่ได้ทำ — รอตัดสินใจ)

เรียงจากความเสี่ยงต่ำไปสูง:

1. **ล็อก + โหลด explainer ตอน startup** — ใส่ล็อกแบบ double-check ใน `_load_explainer()` และเรียกใน `startup()` → ตัดต้นทุนครั้งแรก ~1 วินาทีต่อ process และการสร้างซ้ำตอนเย็น · ไม่เปลี่ยนผลลัพธ์
2. **จำกัดจำนวน fit พร้อมกันต่อ process** (semaphore) — ลดการแย่ง GIL ตอนเย็น แต่ request ที่รอคิวจะช้าลงแทน ต้องวัดซ้ำ
3. **ปิด SHAP ของ point view เมื่อ `explain=False`** — ลดงานคำนวณ steady ราว 1.7 ms ต่อ request · เปลี่ยนเนื้อหา response (`point.explanation`, `model_attribution`) ต้องตรวจว่า hub ใช้อะไรบ้างก่อน
4. **แจกงานให้ worker เท่ากัน** — เช่น gunicorn + `--reuse-port` หรือ pre-fit ผู้ใช้ที่มีประวัติตอน startup · ต้องวัด P2 ซ้ำ
5. เปลี่ยน endpoint เป็น async + process pool — งานใหญ่ ไม่แนะนำก่อนลองข้อ 1–4

ข้อ 1 เป็นบั๊กชัดเจน (ขาดล็อกแบบเดียวกับที่ B63 แก้ให้ fit) ข้ออื่นเป็นการตัดสินใจด้านการออกแบบ

## 9. รันซ้ำ

```bash
bash scripts/test/ml_capacity_gate.sh            # 1 2 4
CAP_OUT=/path bash scripts/test/ml_capacity_gate.sh 4
```

ผลดิบ: `workers_{1,2,4}.json` + log ของ ml-service ต่อรอบ (เก็บใน `CAP_OUT` ไม่เข้า git)

เทส: `hub/backend/tests/test_ml_capacity_gate.py` (19) · `ml-service/tests/test_capacity_stats.py` (9)
