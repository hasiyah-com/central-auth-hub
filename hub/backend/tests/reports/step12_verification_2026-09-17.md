# ขั้นที่ 12 — ทดสอบระบบแยกหลังแก้ scoring (Hybrid Shadow + calibration)

วันที่ 17 ก.ย. 2569 · รันบน `hub_test` + Redis DB 15 + `ml-service-test`

## สถานะ

| เกณฑ์ของแผนขั้นที่ 12 | ผล |
|---|---|
| 1–3 unit / evidence contract / shadow invariant | ผ่าน — อยู่ในชุดเต็ม |
| 4 cross-service Redis | ผ่าน — `test_l3_remote_e2e` อยู่ในชุดเต็ม |
| 5 เทสที่เคย flaky | `test_concurrent_requests_agree` ผ่านทุกรอบหลังแยกเกต |
| 6 ชุดเต็มลำดับปกติ | **1275 passed · 0 failed** |
| 7 ลำดับย้อนกลับ | **1275 passed · 0 failed** |
| 8 random seed 17 / 42 / 91 | **1275 passed · 0 failed ทั้งสาม** |
| 9 ชุดเต็ม 3 รอบ state ใหม่ทุกรอบ | **1275 passed · 0 failed ทั้งสาม** |
| 10 performance แยกจาก functional | แยกแล้ว · **Performance Gate ผ่าน 12/14 รอบ** (§4) |
| state รั่ว | **ไม่พบ** ทั้ง 8 รอบเต็ม + 98 ไฟล์ |
| p50/p95/p99 · ML availability | §4 |
| อัตรา abstain | **วัดไม่ได้ในสภาพแวดล้อมนี้** — ได้เฉพาะกติกาต่อขนาดประวัติ (§5) |

**สรุป: Functional Gate ผ่านครบตามเกณฑ์ขั้นที่ 12** · Performance ยังมีข้อค้นพบที่ต้องแก้ก่อนขั้นที่ 13

---

## 1. สภาพแวดล้อมที่ใช้เป็นหลักฐาน

| รายการ | ค่า |
|---|---|
| commit | `9dd22787188a0c86362d83dc69078e05e4f71ce2` |
| โค้ดที่ยังไม่ commit (diff ของ hub/backend, scripts, ml-service/scripts, docker-compose.test.yml) | sha256 `175bc9a20f15e2df` |
| ไฟล์ใหม่ที่ยังไม่ commit ในพื้นที่เดียวกัน | sha256 `47b90293fac33a49` |
| image `hub-backend` | `sha256:d140bf98e81d…` |
| image `ml-service` และ `ml-service-test` | `sha256:d7282b7d0112…` (ตัวเดียวกัน) |
| manifest ของ seed | `f7c41f7af1b07b93` เท่ากันทั้ง 9 ครั้งที่ setup |
| เวลา | 2026-09-16T18:02:21Z – 18:56:01Z |
| เกต | Functional (ค่าเริ่มต้นของ `run_tests.sh` — ไม่รวม marker `performance`) |

โค้ดถูก mount เข้าคอนเทนเนอร์และยังไม่ได้ commit จึงบันทึก fingerprint ของส่วนที่แก้ไว้ด้วย
commit อย่างเดียวบอกไม่ได้ว่าทดสอบโค้ดชุดไหน · ไม่มีการแก้โค้ดระหว่างรัน

`scripts/diag_l3_concurrency.py` ถูกแก้**หลัง**ชุดนี้จบ (เพิ่มโหมดวัด) — ไม่ได้อยู่ในเส้นทางที่
ชุดเทสเรียก

---

## 2. ลำดับการรัน

| โหมด | ผล | เวลา | state รั่ว |
|---|---|---|---|
| forward | 1275 passed · 23 skipped · 3 deselected | 191.8 s | ไม่มี |
| reverse | 1275 passed · 23 skipped · 3 deselected | 200.6 s | ไม่มี |
| shuffle seed 17 | 1275 passed · 23 skipped · 3 deselected | 196.9 s | ไม่มี |
| shuffle seed 42 | 1275 passed · 23 skipped · 3 deselected | 197.3 s | ไม่มี |
| shuffle seed 91 | 1275 passed · 23 skipped · 3 deselected | 199.5 s | ไม่มี |
| repeat 1 | 1275 passed · 23 skipped · 3 deselected | 189.7 s | ไม่มี |
| repeat 2 | 1275 passed · 23 skipped · 3 deselected | 190.5 s | ไม่มี |
| repeat 3 | 1275 passed · 23 skipped · 3 deselected | 190.9 s | ไม่มี |

seed ของการสุ่มลำดับเปลี่ยนจาก 1/2/3 เป็น 17/42/91 ตามแผน (`SHUFFLE_SEEDS` เปลี่ยนได้)

3 deselected คือเทสของ Performance Gate (§4) · 23 skipped คือ 21 ตัวเดิม (เหตุผลในรายงาน
test isolation) + parity กับ `tailcal` + ตัวตรวจ `run_tests.sh` ซึ่งทั้งสองรันได้บน host
และผ่านบน host แล้ว

---

## 3. รันทีละไฟล์ — 98 ไฟล์

| รายการ | รวมรายไฟล์ | ทั้งชุด |
|---|---|---|
| passed | 1275 | 1275 |
| skipped | 23 | 23 |
| deselected | 3 | 3 |
| failed | 0 | 0 |

ตรงกันทุกตัวเลข = ไม่มีเทสที่พึ่งไฟล์อื่นรันก่อน · ไม่มีไฟล์ไหนทิ้ง state

`tests/test_l1_oidc_authlib.py` ยัง collect ได้ 0 ตัว (ปัญหาเดิม ยังไม่แก้)

---

## 4. Performance

วัดด้วย `scripts/diag_l3_concurrency.py` ผ่าน `evaluate_l3` จริง · ประวัติ 1,500 แถว
seed 42 ตรงกับ fixture · ผลดิบ `step12/latency.txt`

### เรียงทีละตัว (300 ครั้ง × 3 รอบ)

| รอบ | p50 | p95 | p99 | max | ML ตอบสำเร็จ |
|---|---|---|---|---|---|
| 1 | 24.7 ms | 44.8 ms | 59.2 ms | 77.4 ms | 300/300 |
| 2 | 23.3 ms | 35.2 ms | 45.0 ms | 53.0 ms | 300/300 |
| 3 | 24.6 ms | 47.1 ms | 57.1 ms | 72.0 ms | 300/300 |

p95 ต่ำกว่างบ 250 ms ของแผนขั้นที่ 13 มาก · ML availability 100% (900/900)

### ยิงพร้อมกัน (3 รอบ)

| พร้อมกัน | p50 | max | ผล |
|---|---|---|---|
| 1 | 19–21 ms | 19–21 ms | สำเร็จทั้งหมด |
| 5 | 99–162 ms | 121–192 ms | สำเร็จทั้งหมด |
| 10 | 193–324 ms | 247–352 ms | สำเร็จทั้งหมด |
| 20 | 400–507 ms | **458–626 ms** | สำเร็จทั้งหมดรอบนี้ · วันก่อนหน้า timeout 14/20 |

เวลาโตเกือบเป็นเส้นตรงกับจำนวนที่ยิงพร้อมกัน — `/v1/l3-evaluate` เป็น endpoint แบบ sync
งาน numpy/sklearn ถือ GIL และ `ml-service-test` รัน worker เดียว

### Performance Gate ของชุดเทส (`TEST_GATE=performance`) — 14 รอบ

| เทส | ผ่าน |
|---|---|
| `test_l3_explainability::test_latency_within_login_budget` | 14/14 |
| `test_l3_stability::test_latency_within_login_budget` | 14/14 |
| `test_l3_explainability::test_concurrent_burst_mostly_within_timeout` | **12/14** — ล้มครั้งหนึ่งที่ 13/20 |

**Performance Gate ยังไม่ผ่านอย่างมั่นคง** — latency แบบทีละตัวผ่านทุกรอบ แต่การยิงพร้อมกัน
20 ตัวล้มประมาณ 1 ใน 7 รอบ ต้องแก้ความจุของ ml-service ก่อนใช้เกตนี้ตัดสินขั้นที่ 13

### ข้อค้นพบ: timeout 0.5 วินาทีไม่ใช่เพดานรวม

รอบที่ 2 มี request ใช้เวลา **626 ms แล้วยังสำเร็จ** ทั้งที่ตั้ง `L3_TIMEOUT_SECONDS=0.5`

สาเหตุ: `httpx.AsyncClient(timeout=0.5)` ใน `l3_sequence_client.py` ตั้งเพดาน **แยกต่อช่วง**
(connect / read / write / pool) ไม่ใช่เวลารวมของ request · เอกสารในโค้ดเขียนว่า timeout
คือ "เพดานแข็ง" ของ login path (B63) ซึ่งไม่ตรงกับพฤติกรรมจริง — login อาจรอ L3 นานกว่า
0.5 วินาทีได้ และค่าที่รอได้สูงสุดจริงยังไม่ได้วัด

**ยังไม่แก้** — อยู่บนเส้นทาง login ต้องตัดสินก่อน (เช่นครอบด้วย `asyncio.wait_for`)

---

## 5. abstain ตามขนาดประวัติ

อัตรา abstain จริงขึ้นกับการกระจายของขนาดประวัติของผู้ใช้จริง **วัดในสภาพแวดล้อมเทสไม่ได้**
ต้องได้จาก pilot · ที่วัดได้คือกติกาที่ ml-service ใช้จริงต่อขนาดประวัติ

| ประวัติที่บันทึก | `n_history` ที่ได้ | eligibility |
|---|---|---|
| 0 | 0 | abstain |
| 49 | 49 | abstain |
| 99 | 99 | abstain |
| 499 | 499 | diagnostic |
| 999 | 999 | diagnostic |
| 1000 | **999** | **diagnostic** |
| 4999 | **2000** | challenge |
| 5000 | **2000** | challenge |

ข้อค้นพบ

1. **บันทึก 1000 แถวยังไม่ถึง warn** — `n_history` ได้ 999 (ไม่นับเหตุการณ์ปัจจุบัน) จึงต้องมี
   1001 แถวถึงจะผ่าน `TIER_WARN = 1000`
2. **`MAX_HISTORY = 2000` เท่ากับ `TIER_CHALLENGE = 2000`** — ประวัติถูกตัดไว้ที่ 2000
   `n_history` จึงไม่เกิน 2000 และ challenge ต้องรอให้ประวัติเต็มก่อน
3. ช่วงที่แผนขั้นที่ 6 ให้รายงาน `1,000–4,999` กับ `5,000+` **แยกกันไม่ได้** ด้วยค่า
   `n_history` เพราะถูกตัดที่ 2000 · ถ้าต้องการสองช่วงนี้ต้องนับจากแหล่งอื่น (เช่นจำนวน
   login_sessions ของผู้ใช้)

---

## 6. ที่ยังไม่ทำจากขั้นที่ 12

| งาน | สถานะ |
|---|---|
| อัตรา abstain บน traffic จริง | ต้องรอ pilot |
| timeout รวมของ L3 บน login path | ยังไม่แก้ — ต้องตัดสิน |
| ความจุของ ml-service เมื่อยิงพร้อมกัน | ยังไม่แก้ — เงื่อนไขของขั้นที่ 13 |
| `test_l1_oidc_authlib.py` collect 0 ตัว | ยังไม่แก้ |

---

## 7. วิธีทำซ้ำ

```bash
TEST_RESULT_DIR=<ที่เก็บผล> bash scripts/test/order_matrix.sh all
TEST_RESULT_DIR=<ที่เก็บผล> bash scripts/test/order_matrix.sh repeat 3
TEST_RESULT_DIR=<ที่เก็บผล> bash scripts/test/order_matrix.sh per-file
TEST_GATE=performance bash scripts/test/run_tests.sh

# latency / availability / tiers (Redis ต้องเป็น DB 15)
docker compose exec -T -e REDIS_URL=<redis>/15 -e ML_SERVICE_URL=http://ml-service-test:9000 \
    -e TEST_ENVIRONMENT=1 hub-backend python -m scripts.diag_l3_concurrency --sequential 300
docker compose exec -T ... hub-backend python -m scripts.diag_l3_concurrency
docker compose exec -T ... hub-backend python -m scripts.diag_l3_concurrency --tiers
```
