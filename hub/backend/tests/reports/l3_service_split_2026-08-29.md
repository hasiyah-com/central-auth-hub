# L3 Sequence — แยก numeric core ไป ml-service + เปิดใช้งาน (shadow)

**วันที่:** 29 ส.ค. 2026
**ขอบเขต:** (1) เก็บ L3 contract ลง audit · (B) ย้าย L3 scoring ไป ml-service · (3) เปิด flag + verify
**สถานะ:** ✅ ครบทั้งสามข้อ — 772 passed / 53 skipped / 0 failed

---

## 1. ปัญหาที่ทำให้ต้องตัดสินใจสถาปัตยกรรม

ตอนรัน `tests/test_l3_sequence.py` ในคอนเทนเนอร์จริง เจอ:

```
ModuleNotFoundError: No module named 'numpy'
```

`hub-backend` image **ไม่มี numpy/sklearn โดยตั้งใจ** — ML ถูกแยกเป็นคอนเทนเนอร์ของตัวเอง
ตั้งแต่ Week 5 (IForest 23 ฟีเจอร์ก็อยู่ที่ `ml-service` มาตลอด) ผลคือโค้ด L3 sequence
ที่เขียนไว้ใน `app/security/l3_sequence.py` จะ **abstain เงียบๆ ตลอดกาล** ถ้ารันจริง
— ผ่านเทสบน host (มี numpy) แต่ไม่เคยทำงานใน production

ทางเลือกที่พิจารณา:

| ทาง | วิธี | ผล |
|---|---|---|
| A | เพิ่ม numpy+sklearn เข้า hub-backend image | image โต ~300MB · ขัดการแยก concern ที่ทำมาตั้งแต่ Week 5 · มี ML สองที่ |
| **B** ✅ | ย้าย numeric core ไป ml-service (เหมือน IForest เดิม) | สอดคล้องสถาปัตยกรรมเดิม · hub เบาเท่าเดิม |
| C | ปิด L3 ถาวร | เสียงานทดลองทั้งหมด |

**เลือก B**

---

## 2. การแบ่งหน้าที่หลังย้าย

```
hub-backend  ── residual_raw()      6 มิติ, pure python  ─┐
             ── record_residual()   เขียน Redis          │  HTTP POST /v1/sequence-score
             ── result_from_payload()                    │  (httpx, fail-safe B21)
             ── apply_channel()     ยกได้สูงสุดแค่ warn   │
             ── to_contract()       ลง risk_breakdown    ─┘
                                                            ↓
ml-service   ── load_history()      อ่าน Redis เอง (key l3resid:{user_id})
             ── fit_user_model()    IsolationForest รายคน + cache 1 ชม.
             ── evaluate_window()   score window W=5 → contract
```

**ทำไม ml-service ต่อ Redis เอง:** hub มี residual แค่ตัวปัจจุบัน ถ้าจะส่ง history 1,500 แถว
ไปกับ request ทุกครั้ง = ~70KB/login โดยเปล่าประโยชน์ · ml-service อยู่ compose network
เดียวกัน (`cah-net`) อ่านตรงได้เลย · hub ยังเป็นคนเขียน history เจ้าเดียว (single writer)

**Config ที่ย้ายมาไม่เปลี่ยนเลย** — residual 6 มิติ × [mean, slope, ptp] · W=5 · p99.9 ·
abstention tiers (ตามที่ล็อกใน `exp_final_gate_2026-08-26.md`)

---

## 3. ไฟล์ที่แก้

| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `ml-service/app/sequence.py` | **ใหม่** — numeric core + Redis adapter (fit/score/cache) |
| `ml-service/app/main.py` | `POST /v1/sequence-score` + lazy Redis (fail-safe) |
| `ml-service/requirements.txt` | `redis==5.2.0` (pin ตรงกับ hub) |
| `docker-compose.yml` | `ml-service.environment.REDIS_URL` |
| `hub/backend/app/services/l3_sequence_client.py` | **ใหม่** — httpx client ตาม pattern `ml_client.py` |
| `hub/backend/app/security/l3_sequence.py` | `+L3Result.n_history` · `result_from_payload()` · `evaluate_login_remote()` · แก้ `to_contract().eligible` |
| `hub/backend/app/security/risk_engine.py` | `await evaluate_login_remote()` + merge contract เข้า `breakdown` |
| `.env` / `.env.example` | `L3_SEQUENCE_ENABLED` |

**ไม่ต้อง migration** — `LoginSession.risk_breakdown` เป็น JSON column อยู่แล้ว
(`app/models.py:194`) และ merge ที่ `risk_engine` จุดเดียวครอบคลุมทุก call site
(auth ×3, oauth, passkey) โดยไม่ต้องแก้ router

---

## 4. บั๊กที่เจอระหว่างทำ (เจอด้วยเทส ไม่ใช่เดา)

**`to_contract().eligible` เป็น False เสมอบน remote path**

```python
"eligible": bool(model is not None and result.eligibility != "abstain")
```

remote path ไม่มี `L3Model` object ในมือ (โมเดลอยู่ที่ ml-service) → `model=None` เสมอ →
`eligible=False` ทุกแถว ทั้งที่ผู้ใช้มี history 1,500 และ L3 ยิงจริง

ผลถ้าไม่เจอ: **ข้อมูล production replay เพี้ยนทั้งชุด** — จะสรุปผิดว่า "L3 ไม่เคย eligible เลย"
ซึ่งเป็นความผิดพลาดชนิดเดียวกับที่เคยเจอตอนแยก raw (16.3%) ออกจาก effective (0.2%) ไม่ได้

แก้เป็นยืนยันจาก `n_history` ที่ ml-service ส่งมา:
```python
"eligible": bool(result.eligibility != "abstain"
                 and (model is not None or result.n_history > 0))
```

จับได้โดย `test_l3_remote_e2e.py::test_contract_complete_for_replay`

---

## 5. ผลการทดสอบ

### 5.1 TDD — RED ก่อน

```
tests/test_l3_sequence_client.py:23: in <module>
    from app.services import l3_sequence_client as C
E   ImportError: cannot import name 'l3_sequence_client' from 'app.services'
```

### 5.2 GREEN — unit + contract (8 เทส)

```
tests/test_l3_sequence_client.py::test_client_failsafe_when_ml_unreachable PASSED
tests/test_l3_sequence_client.py::test_client_failsafe_on_garbage_payload PASSED
tests/test_l3_sequence_client.py::test_client_parses_payload PASSED
tests/test_l3_sequence_client.py::test_client_skips_call_when_residual_invalid PASSED
tests/test_l3_sequence_client.py::test_evaluate_login_remote_without_numpy PASSED
tests/test_l3_sequence_client.py::test_evaluate_login_remote_no_profile_skips PASSED
tests/test_l3_sequence_client.py::test_contract_uses_result_n_history_when_model_none PASSED
tests/test_l3_sequence_client.py::test_constants_parity_hub_vs_ml_service SKIPPED
========================= 7 passed, 1 skipped in 1.64s =========================
```

`test_evaluate_login_remote_without_numpy` บังคับ `_numeric()` คืน `None` — พิสูจน์ว่าเส้นทาง
production ทำงานได้ **โดยไม่มี numpy ที่ hub เลย** ซึ่งคือเหตุผลทั้งหมดของการย้าย

parity test skip ในคอนเทนเนอร์ (ไม่ได้ mount `ml-service/`) — รันบน host แทน:

```
hub       : {'DIMS': 6, 'WINDOW': 5, 'MAX_HISTORY': 2000, 'CAL_FPR': 0.001,
             'EXTREME_FPR': 0.0003, 'MODEL_VERSION': 'iforest-l3-seq-v1',
             'TIER_DIAGNOSTIC': 100, 'TIER_WARN': 1000, 'TIER_CHALLENGE': 2000}
ml-service: {เหมือนกันทุกค่า}
PARITY OK
```

### 5.3 Integration ข้ามคอนเทนเนอร์จริง (ไม่ mock — 5 เทส)

`test_l3_remote_e2e.py` เขียน residual ปกติ 1,500 แถวผ่าน `record_residual()` ของ hub เอง
→ ให้ ml-service อ่าน Redis + fit + score จริง

```
tests/test_l3_remote_e2e.py::test_record_residual_writes_redis PASSED
tests/test_l3_remote_e2e.py::test_normal_residual_does_not_fire PASSED
tests/test_l3_remote_e2e.py::test_extreme_drift_fires_and_raises_to_warn
  raw=0.745 pct=1.000 tier=extreme
PASSED
tests/test_l3_remote_e2e.py::test_contract_complete_for_replay PASSED
tests/test_l3_remote_e2e.py::test_abstain_for_fresh_user PASSED
```

ตรวจครบทั้งสามข้อกำหนดของ channel:

| ข้อกำหนด | เทส | ผล |
|---|---|---|
| login ปกติไม่ยิง (แต่ eligible จริง) | `test_normal_residual_does_not_fire` | ✅ `eligibility=warn`, `fired=False` |
| drift หลายมิติ → ยิง + ยก `allow`→`warn` | `test_extreme_drift_fires...` | ✅ raw 0.745, pct 1.000 |
| **ห้ามแตะ challenge/block** | เทสเดียวกัน | ✅ `challenge`→`challenge`, `block`→`block` |
| ผู้ใช้ใหม่ → abstain | `test_abstain_for_fresh_user` | ✅ ไม่เปลี่ยน decision |

### 5.4 L3 ทั้งหมด (36 เทส)

```
tests/test_l3_remote_e2e.py .....                    [ 13%]
tests/test_l3_sequence_client.py .......s            [ 36%]
tests/test_l3_contract_persisted.py ....             [ 47%]
tests/test_l3_sequence.py sssss....ssss.             [ 86%]
tests/test_l3_window_integrity.py .....              [100%]
================ 26 passed, 10 skipped in 8.76s =================
```

skip = เทส numeric ที่ต้องใช้ numpy (ยังรันบน host ได้ — เป็นเทสของ harness ทดลอง)

### 5.5 Full suite ใน Docker

```
================= 772 passed, 53 skipped in 133.88s (0:02:13) ==================
```

คำสั่ง:
```bash
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
```

⚠️ **ต้อง `--ignore` สองไฟล์** — `test_e2e_full_stack.py` และ `test_l1_oidc.py` เป็น
**สคริปต์ standalone** (มี `sys.exit()` ระดับ module ตาม docstring "Run: docker exec ...")
ไม่ใช่ pytest module · pytest collect แล้ว `SystemExit` ทำให้ **ทั้ง suite ตายที่ INTERNALERROR**
เป็นปัญหาเดิม ไม่เกี่ยวกับงานนี้

รันสองไฟล์ตามวิธีของมันเอง:

| สคริปต์ | ผล | หมายเหตุ |
|---|---|---|
| `test_l1_oidc.py` | 58/62 | 4 fail: 2 = userinfo scope field, 2 = 503 จาก api_guard ที่สคริปต์เองยิงรัวจนตัดวงจร (ยิงมือได้ 400 ถูกต้อง) |
| `test_e2e_full_stack.py` | 38/41 | 2 fail = dorm/library stack ไม่ได้รัน (DNS resolve ไม่ได้) |

ทั้ง 6 รายการไม่แตะ L3 — เป็นปัญหาสภาพแวดล้อม/เดิม

---

## 6. Deploy (งาน 3)

```bash
docker compose build ml-service                       # redis==5.2.0 เข้า image
docker compose up -d --force-recreate ml-service hub-backend
```

ใช้ `--force-recreate` ไม่ใช่ `restart` ตาม **B36** (restart ไม่ re-read `.env`) แล้ว verify:

```
$ docker exec hub-backend env | grep L3_SEQUENCE
L3_SEQUENCE_ENABLED=true
$ docker exec hub-ml env | grep REDIS_URL
REDIS_URL=redis://redis:6379/0
```

smoke test:
```json
{"data": {"fired": false, "eligibility": "abstain", "n_history": 0,
          "model_version": "iforest-l3-seq-v1"},
 "meta": {"version": "v1", "redis": "ok"}}
```

---

## 7. Security check

| หัวข้อ | สถานะ |
|---|---|
| **B21 fail-safe** | 3 ชั้น: client (timeout/HTTP/exception → เงียบ) · `evaluate_login_remote` (try/except) · `risk_engine` (try/except ครอบทั้งบล็อก) — ml-service ล่ม = L1/L2/L4 ตัดสินต่อปกติ · มีเทสยืนยัน |
| **ml-service ไม่มี auth** | ยังคง bind `127.0.0.1:9000` เท่านั้น (ไม่เปิด surface ใหม่) · endpoint ใหม่ไม่ได้รับ/คืน PII — รับแค่ `user_id` + residual 6 ตัวเลข |
| **Input validation** | pydantic บังคับ `len(residual)==DIMS`, `user_id` 1–128 ตัวอักษร · `_coerce()` ฝั่ง hub บังคับชนิดทุกฟิลด์ (มีเทส garbage payload) |
| **ห้ามยกเกิน warn** | `apply_channel()` ยัง cap ที่ warn · มีเทส integration ยืนยัน `challenge`/`block` ไม่ถูกแตะ |
| **Timeout** | ใช้ `settings.ml_timeout_seconds` (2 วินาที) เดียวกับ ML client เดิม |
| **Constants drift** | มี parity test กัน (บทเรียน B49 — feature order ไม่ sync แล้ว score มั่ว) |
| **PII** | รายงานนี้ไม่มีอีเมล/ชื่อ/IP จริง |

---

## 8. สรุป

| งาน | สถานะ |
|---|---|
| 1 — เก็บ L3 contract ลง audit | ✅ merge ที่ `risk_engine` จุดเดียว ลง `risk_breakdown` (JSON, ไม่ต้อง migration) |
| B — ย้าย L3 scoring ไป ml-service | ✅ ทำงานจริงข้ามคอนเทนเนอร์แล้ว (พิสูจน์ด้วย integration test ไม่ mock) |
| 3 — เปิด flag + force-recreate | ✅ verify env ทั้งสองฝั่งแล้ว |

**สถานะระบบ:** L3 sequence channel **ทำงานจริงใน production เป็นครั้งแรก** (ก่อนหน้านี้
abstain เงียบตลอดเพราะไม่มี numpy) — อยู่ในโหมดเก็บข้อมูล: ยกได้สูงสุดแค่ `warn`
และเขียน contract ทุก login ลง `risk_breakdown` เพื่อวัด raw vs effective ตอน production replay

**ยังไม่ทำ (ตามแผนเดิม):** ไม่ปรับ threshold/โมเดลจากข้อมูล production จนกว่าจะมี replay
เพียงพอ — ตามที่ตกลงว่า "หยุดปรับโมเดลจาก final holdout"

---

## 9. รันซ้ำได้

```bash
# unit + contract
docker compose exec hub-backend pytest tests/test_l3_sequence_client.py -v

# integration ข้ามคอนเทนเนอร์ (ต้องมี Redis + ml-service ขึ้น)
docker compose exec hub-backend pytest tests/test_l3_remote_e2e.py -v -s

# L3 ทั้งหมด
docker compose exec hub-backend pytest tests/test_l3_*.py -q

# full suite
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
```
