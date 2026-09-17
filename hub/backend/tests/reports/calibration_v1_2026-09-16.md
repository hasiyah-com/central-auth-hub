# Calibration v1 (synthetic) — ขั้นที่ 7 ของแผน Hybrid Shadow

วันที่ 15–16 ก.ย. 2569 · commit ฐาน `9dd2278` (งานนี้ยังไม่ commit ขณะเขียนรายงาน)

## สถานะ

| รายการ | ผล |
|---|---|
| ตัวสร้าง + เทส (RED ก่อน) | **เสร็จ** — 30 เทส + 1 parity บน host |
| ชุดเทสเต็ม | ก่อนงานส่วน §9: 1251 passed · 0 failed · หลัง §9: 1272 passed · 1 failed (freeze ก่อน re-freeze) · รอบยืนยันหลัง re-freeze: 1 failed (`test_concurrent_requests_agree` — ไม่เกี่ยวกับงานนี้ ดู §11) · หลังแยกเกต: **Functional Gate 1275 passed · 23 skipped · 3 deselected · 0 failed** · ไม่มี state รั่ว |
| artifact บนประชากร P48-T2 | **สร้างแล้ว ผ่าน validate** — ยังอยู่ใน scratchpad |
| อัตรายิงบนชุดตรวจที่ไม่ได้ใช้สร้าง | **อยู่ในงบทั้งสามระดับ** |
| นำไฟล์เข้า repo | **เสร็จ** — `app/security/artifacts/calibration_v1.json` + `.meta.json` (§12) · ไม่โหลดเอง |
| sha256 + fail-closed ใน `calibration.py` | **เสร็จ** — re-freeze แล้ว (§9) |
| holdout P48-T2 (16 โปรไฟล์) | **ไม่ถูกแตะ** |

ตาราง v1 นี้สร้างจาก **ประชากรจำลอง** ใช้เพื่อให้คะแนนสามชั้นเทียบกันได้ระหว่างเก็บข้อมูล
shadow เท่านั้น **ห้ามอ้างเป็น FPR ของผู้ใช้จริง**

---

## 1. โครงสร้าง

| ไฟล์ | หน้าที่ | รันที่ |
|---|---|---|
| `hub/backend/scripts/calibration_core.py` | กริด, เกณฑ์ตามงบ, reachability, exceedance, PIT, validate, ledger | คอนเทนเนอร์ hub-backend (ไม่มี ML dep) |
| `ml-service/scripts/build_calibration.py` | ต่อท่อข้อมูล — เรียก `fit_ecdf` และ `configs.evaluate` ตัวเดียวกับการทดลอง | host (ต้องใช้ numpy/sklearn) |
| `hub/backend/tests/test_calibration_build.py` | 31 เทส | ชุดเทสปกติ + host |

ไม่เขียนสูตรคะแนนซ้ำ (B66) — ตัวสร้างเรียก `exp_hybrid_gate.fit_ecdf` ซึ่งการทดลองใช้อยู่แล้ว
และ `_anomaly_alone_capped` เรียก `resolve_action` ของ production ตรง ๆ

เพิ่ม `ECDF.raw_samples()` ใน `hybrid_experiment/dataset.py` เพราะ `to_artifact()` เดิม
ย่อเหลือ 512 จุดซึ่งหยาบเกินไปสำหรับตารางที่ใช้ตัดสินจริง

---

## 2. RED ก่อน GREEN

| รอบ | ผล |
|---|---|
| ไม่มีโมดูล (`importorskip`) | 1 skipped — อ่อนเกินจะเรียกว่า RED |
| โครงเปล่า `NotImplementedError` | **25 failed** · 1 skipped |
| implement | 26 passed · 1 skipped |
| เทสเกณฑ์ตามงบ กับพฤติกรรมเดิม (nearest-rank) | **3 failed** · 1 passed |
| หลังแก้ | 31 passed (host) · 30 passed + 1 skipped (คอนเทนเนอร์) |

ตัวที่ผ่านตั้งแต่ RED ในรอบเกณฑ์ตามงบใช้ข้อมูลต่อเนื่องไม่มีค่าซ้ำ nearest-rank จึงไม่พลาด —
มันยืนยันแค่ว่ามีฟิลด์ `fire_rate_fit`

---

## 3. ข้อสมมติของผมที่เทสจับได้

1. **เพดาน evidence คือ 1.0 ไม่ใช่ `(n−1)/n`** — `bisect_left` คืน `len(q)` เมื่อคะแนนชนะทุกค่า
   ในตาราง เกณฑ์สูงจึงไม่ได้ "ไปไม่ถึง" แต่อาจกลายเป็น "ต้องชนะทุกตัวอย่าง" แทนความหมาย
   ของเปอร์เซ็นไทล์
2. **corroboration พาไปถึงเกณฑ์ละเอียดได้** — กริด 1,000 จุด m = s = 0.999 γ = 1.0 ได้
   0.999999 ซึ่งเกิน 0.9999 เทสแรกยืนยันตรงข้าม จึงแก้เทสให้ตรงกับความจริง และแยกวัด
   `single_layer_needs_exceeding_table` กับ `min_pair`

---

## 4. รอบแรกรันผิดประชากร

`DS.build()` เรียก `G3.build_seed(users, seed)` **โดยไม่ส่ง spec** จึงได้ประชากร 12 โปรไฟล์เดิม
แทน P48-T2 หลักฐาน: 6,000 เหตุการณ์/seed ÷ 12 = 500 ต่อคน (P48-T2 ต้องได้ราว 16,000)

แก้โดยเพิ่ม `--population` โหลดตามรูปแบบของ `exp_p48_validation.py` และส่ง `raw` ต่อให้
`DS.build` (ของเดิมสร้างประชากรสองครั้ง — โมเดล fit จากชุดหนึ่ง split มาจากอีกชุด)
พร้อม assert หยุดทันทีถ้าเผลอสร้าง alias ของ holdout

ยืนยันแล้วว่า holdout ที่โหลดได้ตรงกับรายการที่ freeze ไว้ในรายงาน P48-T2 ทั้ง 16 ตัว

```
T01 T04 T05 T09 T10 T11 T13 T17 T18 T19 T22 T23 T30 T33 T42 T43
```

ตัวเลขของรอบนั้น (seed 501-503) ใช้ไม่ได้ทั้งหมด — บันทึกหมายเหตุแก้ไขลง ledger แล้ว
โดยไม่ลบของเดิม

---

## 5. เกณฑ์ยิงเกินงบ — บั๊กที่เจอจากตัวเลขจริง

production เทียบด้วย `>=` (`risk_fusion._action_for`) แต่ nearest-rank เลือกค่าที่ตกกลาง
กลุ่มค่าซ้ำ `>=` จึงกวาดทั้งกลุ่ม · ตัวตรวจ `tailcal.benign_exceedance` เทียบด้วย `>`
จึงมองไม่เห็น — สองนิยามต่างกันเงียบ ๆ แบบเดียวกับ B66

| ระดับ | งบ | ยิงจริง (nearest-rank) | ยิงจริง (ตามงบ) |
|---|---|---|---|
| warn | 2% | **2.85%** | 1.92% |
| challenge | 0.5% | **0.625%** | 0.31% |
| block | 0.01% | **0.015%** | 0.0063% |

แก้ด้วย `_budget_threshold` — เลือกค่าไม่ซ้ำตัวแรกที่ `P(score >= t)` อยู่ในงบ ถ้าแม้ค่าสูงสุด
ก็เกินงบ เกณฑ์จะอยู่เหนือทุกค่าที่เคยเห็น · artifact รายงาน `fire_rate_fit` และ
`fire_rate_check` ด้วยนิยาม `>=` คู่กับ exceedance เดิม

---

## 6. ผลของ artifact ที่ใช้ได้

**P48-T2 · 32 โปรไฟล์ validation · fit seed 511-518 · ตรวจ seed 519-520 · size 5000 · γ 1.0**

```
sha256   e093b3ac25a46094e31b1304fe02e13c1e4f8c4cf12e9bfcffc20d9bbc944fbc   (LF · เก็บใน repo)
         1e9038c3edfe5bed3311f46c97d67ebbe011bbfeeab8c9a710e917dfa1c5a4f0   (ไฟล์ตามที่สร้างบน Windows มี CRLF)
ขนาด     ราว 1.9 MB
ตัวอย่าง 128,000 เหตุการณ์ต่อชั้น -> กริด 20,000 จุด
```

### เกณฑ์ที่ได้

| ระดับ | เปอร์เซ็นไทล์ที่ประกาศ | เกณฑ์ | ยิงบนชุด fit | ยิงบนชุดตรวจ |
|---|---|---|---|---|
| warn | 0.98 | 0.9864 | 1.917% | 1.888% |
| challenge | 0.995 | 0.996407 | 0.308% | 0.272% |
| block | 0.9999 | 0.999914 | 0.0063% | 0.0063% |

**ข้อสังเกตที่ต้องรายงานตรง ๆ:** challenge ยิงแค่ 0.31% ไม่ใช่ 0.5% ตามงบ เพราะคะแนน
L1+L2 เป็นขั้นบันได ค่าไม่ซ้ำที่อยู่ในงบตัวแรกกระโดดลงมาไกล — จุดทำงานจริงคือ 0.31%
ไม่ใช่ตัวเลขที่ประกาศ · block บนชุดตรวจ 0.0063% = **2 เหตุการณ์จาก 32,000** เป็นตัวเลข
ที่ความไม่แน่นอนสูงมาก

### reachability

| ระดับ | ไปถึงได้ | คู่ต่ำสุด | ชั้นเดียวต้องชนะทุกตัวอย่าง |
|---|---|---|---|
| warn | ใช่ | m 0.9864 · s 0 | ไม่ |
| challenge | ใช่ | m 0.9401 · s 0.9401 | ไม่ |
| block | ใช่ | m 0.99075 · s 0.99075 | ไม่ · **L3 เดี่ยวถูกกด** |

### ตรวจความถูกต้องอื่น

| รายการ | ค่า |
|---|---|
| parity กับ ECDF ของการทดลอง | rule 4.1e-05 · behavior 4.2e-05 · point 0 · sequence 3.9e-05 (จากการย่อกริด) |
| หางของ block | 12.8 ตัวอย่าง (เกณฑ์ ≥ 10) |
| `tail_shift_detected` | false |
| `final_pit_ks` | 0.724 — **ห้ามอ่านว่าประชากรต่างกัน** ดูด้านล่าง |

PIT ใช้กับคะแนนที่มีมวลกระจุก 72.4% ที่ค่าเดียวไม่ได้ ค่า KS สูงเกิดจากโครงสร้างค่าซ้ำ
ตัวที่อ่านได้จริงคืออัตรายิงบนชุดตรวจ ซึ่งอยู่ในงบทั้งสามระดับ

---

## 7. ข้อค้นพบเชิงโครงสร้าง (ยังไม่สรุป)

| Config | ค่าไม่ซ้ำ | มวลสูงสุดที่ค่าเดียว |
|---|---|---|
| B — L1+L2 | 27 | 0.724 (ที่ 0.0) |
| E — L1+L2+L3 | 18,495 | < 0.001 |

`tie_mass_at_zero`: rule 0.986 · behavior 0.736 · anomaly_point 0 · anomaly_sequence 0

L3 เป็นชั้นเดียวที่ให้คะแนนต่อเนื่อง ผลที่ตามมาคือเกณฑ์ของ Config B ทำได้แค่จุดทำงานบน
บันได 27 ขั้น (เห็นได้จาก challenge ที่ได้ 0.31% แทน 0.5%) — Isolation Forest อาจมีคุณค่า
ด้าน **ความละเอียดของจุดทำงาน** นอกเหนือจาก recall

ยังไม่สรุปเป็นข้อค้นพบ: เห็นบนสองประชากร (12 โปรไฟล์ และ P48-T2) แต่ขนาดประวัติเดียว (5000)

---

## 8. ที่ยังไม่ทำ

| งาน | สถานะ |
|---|---|
| วาง artifact ที่ `app/security/calibration_v1.json` | รอตัดสิน — ขนาด 1.9 MB และเป็นข้อมูลจำลองจึง commit ได้ตามนโยบาย |
| ความไวต่อขนาดประวัติ (50 / 500 / 1000) | ยังไม่วัด |
| ตั้ง `L4_THRESHOLD_*` + `L4_GAMMA` + `CALIBRATION_*` บนสภาพแวดล้อมแยก | ยังไม่ทำ |
| v2 จากข้อมูลจริงของ shadow epoch | ยังไม่เริ่ม |

---

## 9. sha256 + fail-closed ใน `calibration.py`

### ความเสี่ยงที่พบก่อนวางไฟล์

เดิม `calibration.py` โหลด `calibration_v1.json` อัตโนมัติถ้ามีไฟล์วางอยู่ข้าง ๆ ถ้าวางไฟล์
ตอนนั้น หลักฐานทุกชั้นจะกลายเป็นเปอร์เซ็นไทล์ทันที (กฎเดียวที่ยิงได้ราว 0.99) ขณะที่เกณฑ์
ยังเป็น 0.50/0.70/0.85 — การตัดสินจริงเกือบทุกครั้งจะกลายเป็น block โดยไม่มีอะไรฟ้อง

### การเปิดใช้ตารางต้องประกาศชัด

| สถานะ | เงื่อนไข | ผล |
|---|---|---|
| `not_configured` | ไม่ได้ตั้ง `CALIBRATION_PATH` | พฤติกรรมเดิม (ค่าปัจจุบันของคอนเทนเนอร์) |
| `missing` / `sha_mismatch` / `error` | ไฟล์หาย / hash ไม่ตรง / อ่านไม่ได้ | ไม่ใช้ตาราง |
| `unverified` | เทสหรือการทดลองชี้ `CALIBRATION_FILE` เองโดยไม่มี hash | ใช้ตาราง — เทสเดิมและ parity gate ทำงานเหมือนเดิม |
| `ok` | hash ตรง | ใช้ตาราง |

### `validate_startup()` — เรียกใน `main.py` lifespan

ปฏิเสธการ start เมื่อ

* `L3_MODE=shadow_hybrid` แต่ไม่ได้ตั้งตาราง
* ตั้ง path แล้ว (ทุกโหมด) แต่ไม่มีไฟล์ / ไม่ได้ตั้ง sha256 / sha256 ไม่ตรง / version ไม่ตรง
* ตารางไม่มี `derived_thresholds` หรือไม่ได้บันทึก gamma
* **เกณฑ์สามระดับหรือ gamma ใน env ไม่ตรงกับที่ตารางผลิตมา**

ตัวสร้างบันทึก `fusion: {gamma, config}` ลงไฟล์แล้ว เพื่อให้ตรวจข้อสุดท้ายได้

### ผล

```
RED    tests/test_calibration_integrity.py  22 failed
GREEN  107 passed · 1 skipped  (integrity 22 + ตัวสร้าง 30 + evidence contract 55)
แอปจริง restart -> health 200 · status = not_configured
```

ไฟล์รอบ 3 (sha256 `1e9038c3edfe…`) ผ่าน `validate_startup` เมื่อตั้งค่าตรงกับตาราง และถูก
ปฏิเสธเมื่อใส่ gamma ชุดเก่า 0.35 · เกณฑ์และอัตรายิงเท่ารอบ 2 ทุกตัว (สร้างซ้ำได้ผลเดิม)

### re-freeze (อนุมัติแล้ว 16 ก.ย. 2569)

`calibration.py` อยู่ในรายการ freeze · hash เปลี่ยนไฟล์เดียว อีก 8 ไฟล์ไม่เปลี่ยน
(`risk_engine.py` ปรากฏใน diff เพราะ re-freeze ของ 15 ก.ย. ยังไม่ได้ commit)

พบว่าสคริปต์ `update_scoring_freeze.py` **เขียนทับเหตุผลของการ freeze ครั้งก่อน** ซึ่งยังไม่
เคยถูก commit — ถ้าปล่อยไว้เหตุผลของ `risk_engine.py` จะหายไปจากทุกที่ จึง

* กู้คืนเป็น `history` 3 รายการ (7 / 15 / 16 ก.ย.) พร้อมไฟล์ที่เปลี่ยนต่อครั้ง
* แก้สคริปต์ให้ต่อท้ายประวัติเสมอ และคำนวณ `files_changed` จาก hash — ทดสอบกับสำเนา
  ได้ 4 รายการโดยของเดิมไม่หาย

---

## 10. วิธีทำซ้ำ

```bash
cd hub/backend
PYTHONPATH=. python ../../ml-service/scripts/build_calibration.py \
    --population p48t2 --seeds 511 512 513 514 515 516 517 518 \
    --check-seeds 519 520 --size 5000 --allow-spent-seeds \
    --out <ปลายทาง>/calibration_v1.json

# เทสของตัวสร้าง (คอนเทนเนอร์)
bash scripts/test/run_tests.sh tests/test_calibration_build.py

# parity กับ tailcal (host)
cd hub/backend
PYTHONPATH=".;../../ml-service/scripts" python -m pytest tests/test_calibration_build.py --noconftest -q
```

ต้องใช้ `--allow-spent-seeds` เพราะ seed ชุดนี้ถูกบันทึกลง ledger แล้ว (open_count 2)
การรันซ้ำจะเพิ่ม open_count ไม่ลบประวัติ

---

## 11. test_concurrent_requests_agree ล้มหลัง Docker restart — ไม่เกี่ยวกับงานนี้

รอบยืนยันหลัง re-freeze ได้ `1 failed` ที่เทสนี้ (สำเร็จ 9/20 ต้อง >= 18) และรันไฟล์ซ้ำ
ล้ม 2 ใน 3 รอบ (7/20, ผ่าน, 5/20) · เทสนี้ผ่านมาทุกรอบก่อนหน้า (8 รอบเต็ม + ทีละไฟล์)

**ไม่ได้มาจากงานนี้** — เทสเรียก `evaluate_l3` ตรง ไม่ผ่าน `risk_engine` หรือ `calibration`
และโค้ดของ ml-service ไม่ได้แก้

**สาเหตุ** — `/v1/l3-evaluate` เป็น endpoint แบบ sync ที่งาน numpy/sklearn ถือ GIL และ
`ml-service-test` รัน uvicorn worker เดียว request จึงถูกประมวลผลต่อคิว วัดด้วย
`scripts/diag_l3_concurrency.py` (ประวัติ 1,500 แถว seed 42 ตรงกับ fixture) สองรอบ

| พร้อมกัน | ผล | latency p50 | max |
|---|---|---|---|
| 1 | ผ่านทั้งหมด | 24–31 ms | 24–31 ms |
| 5 | ผ่านทั้งหมด | 107–137 ms | 139–163 ms |
| 10 | ผ่านทั้งหมด | 277–365 ms | 337–386 ms |
| 20 | **timeout 14/20** / ผ่านทั้งหมด | 535–631 ms | 642–720 ms |

timeout ฝั่ง hub คือ 0.5 วินาที · ที่ 20 request พร้อมกัน p50 อยู่เหนือเส้นนั้นแล้ว
รอบก่อน ๆ ผ่านเพราะอยู่ใต้เส้นแบบเฉียดฉิว

**เทสนี้ผูกกับ latency โดยไม่ได้ตั้งใจ** — เจตนาคือพิสูจน์ว่าไม่มี race (ผลต้องตรงกัน)
แต่เงื่อนไข "สำเร็จ >= 18/20" ขึ้นกับความเร็วของเครื่อง ซึ่งเป็นเรื่องของ Performance Gate

**ข้อค้นพบด้านความจุ** — ถ้ามี login พร้อมกันราว 15–20 ครั้ง L3 จะ timeout แล้ว abstain
แบบ fail-safe โดยไม่มีอะไรฟ้อง (ตระกูล B61) ต้องนับเป็นเงื่อนไขของขั้นที่ 13 (latency gate)

### แยก Functional Gate กับ Performance Gate ในโค้ด (17 ก.ย. 2569)

การแยกสองเกตตกลงกันไว้ก่อนหน้า แต่ยังไม่มีในโค้ด จึงทำให้เป็นจริง

| เปลี่ยน | รายละเอียด |
|---|---|
| marker `performance` | ลงทะเบียนใน `pytest.ini` · ติดที่ `test_latency_within_login_budget` สองไฟล์ |
| `test_concurrent_requests_agree` | ขยาย timeout เป็น 10 วินาทีเฉพาะในเทส · ต้องสำเร็จ **20/20** และผลตรงกัน · แสดง error จริงถ้าไม่สำเร็จ |
| `test_concurrent_burst_mostly_within_timeout` (ใหม่) | Performance Gate · เงื่อนไขเดิม >= 18/20 ภายใน timeout จริงของ login |
| `run_tests.sh` | `TEST_GATE=functional` (ค่าเริ่มต้น · release gate) / `performance` / `all` |
| `tests/test_gate_markers.py` (ใหม่) | อ่านซอร์สยืนยันว่าเทสแต่ละตัวอยู่ถูกเกต |

```
RED    test_gate_markers.py           4 failed
GREEN  host 5 passed · คอนเทนเนอร์ 44 passed + 1 skipped (ตัวตรวจ run_tests.sh รันได้บน host)
test_concurrent_requests_agree        ผ่าน 5/5
Performance Gate (เครื่องอุ่น)         ผ่าน 5/5
Functional Gate ชุดเต็ม               1275 passed · 23 skipped · 3 deselected · 0 failed
```

**Performance Gate ยังไม่ควรใช้ตัดสินเปิด pilot** — ผ่าน 5/5 ตอนเครื่องอุ่น แต่หลัง Docker
restart ล้ม 2 ใน 3 เพราะความจุของ ml-service อยู่ใกล้เส้น timeout ต้องแก้ความจุก่อน
(เพิ่ม worker หรือเปลี่ยนรูปแบบการประมวลผล — ยังไม่ได้วัด)

---

## 12. เก็บตารางเข้า repo (17 ก.ย. 2569)

| ไฟล์ | หน้าที่ |
|---|---|
| `hub/backend/app/security/artifacts/calibration_v1.json` | ตารางที่ใช้จริง (1.9 MB) |
| `hub/backend/app/security/artifacts/calibration_v1.meta.json` | version, sha256, gamma, เกณฑ์, ประชากร, seed, commit ของตัวสร้าง, `synthetic_only` |
| `hub/backend/tests/test_calibration_artifact.py` | ไฟล์กับ metadata ตรงกัน · ผ่าน `validate_startup` และ `validate_artifact` · ไม่มีข้อมูลระบุตัว · ไม่มี CR |

ระบบยังไม่โหลดไฟล์นี้เอง — ต้องตั้ง `CALIBRATION_PATH`, `CALIBRATION_SHA256` และเกณฑ์/gamma ให้ตรง

### บั๊กที่เจอ: hash ขึ้นกับระบบที่สร้าง

`write_artifact` ใช้ `write_text` ซึ่งบน Windows แปลง `
` เป็น `
` ไฟล์รอบ 3 จึงมี CRLF ทั้งไฟล์
และ sha256 `1e9038c3…` ที่บันทึกไว้เป็นของเวอร์ชันนั้น · สร้างซ้ำบน Linux จะได้ hash คนละค่า

* แก้ `write_artifact` ให้เขียน bytes ที่ใช้ LF เสมอ (เทส `test_written_artifact_uses_lf_on_every_platform` ล้มบน Windows ก่อนแก้)
* แปลงไฟล์ที่มีอยู่เป็น LF โดย **ไม่สร้างใหม่** (ไม่เปิด seed เป็นครั้งที่ 4) — ตรวจแล้วว่า JSON เท่าเดิมทุกค่า
* sha256 ใหม่ `e093b3ac25a46094e31b1304fe02e13c1e4f8c4cf12e9bfcffc20d9bbc944fbc` · บันทึกทั้งสองค่าไว้ใน metadata และ ledger
* `.gitattributes` ตั้ง `hub/backend/app/security/artifacts/** -text` กัน `core.autocrlf=true` แปลงกลับตอน checkout
* pre-commit ยกเว้นโฟลเดอร์นี้จาก `check-added-large-files` (500 KB) และ `detect-secrets` (sha256 ใน metadata)
