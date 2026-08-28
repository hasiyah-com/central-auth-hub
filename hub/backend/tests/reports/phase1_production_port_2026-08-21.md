# Phase 1 — Port Contract V2+ เข้า Production (เสร็จ)

**วันที่:** 21 ส.ค. 2026 · **แนวทาง:** TDD (RED→GREEN) · **ยังไม่ commit**
**ผล:** production recall **25% → 85%** · policy 33% → 85% · FPR 2.11%

---

## สรุป

พิสูจน์ผ่าน [`learning_curve_v2_2026-08-21.md`](learning_curve_v2_2026-08-21.md) แล้วว่า Contract V2+
ทำงานดีทุก data size → ขั้นนี้ย้าย logic เข้า **production จริง** (`rule_engine.py` +
`risk_aggregator.py` + `config.py`) แล้ววัดด้วยการ **import โค้ด production ตรงๆ** บนชุด V2

**ยืนยัน 3 ชั้น:**
1. Unit — `tests/test_rule_engine_v2_signals.py` 12/12 (เรียก `evaluate_rules`/`aggregate` จริง)
2. End-to-end — `ml-service/scripts/eval_production_v2.py` (import production) → recall 85%
3. Regression — pipeline tests 12/12 + 14/14 ยังผ่าน · `risk_engine` import ได้ (hard-block path ไม่พัง)

---

## สิ่งที่แก้ (3 ไฟล์ · +79 −12)

### 1. `config.py` — เพิ่ม `shared_nat: bool = False`
เปิดผ่าน env `SHARED_NAT=true` สำหรับ deployment หลัง campus/office NAT ร่วม

### 2. `rule_engine.py`
| แก้ | เดิม | ใหม่ |
|---|---|---|
| `SCORE_RULES` เป็น 5-tuple + op `<=` | `(feat, op, threshold, weight)` 6 กฎ | `(feat, op, threshold, weight, min_action)` 15 กฎ |
| เพิ่มกฎให้ฟีเจอร์ไร้เจ้าของ | — | concurrent, active_subsystem, new_passkey, permission_age, login burst, failed graded |
| velocity compound (2 ฟีเจอร์) | — | `log_minutes<=2 AND login_count>=15` |
| `RuleResult.min_action` | — | policy floor ต่อกฎ |
| `multi_account_ip` | ยิงเสมอถ้ามี ip | `if ip and not settings.shared_nat` |

### 3. `risk_aggregator.py` — policy floor
`aggregate()` บังคับ `raw_decision = max(raw_decision, rule.min_action)` →
deterministic security event ได้ min action เสมอ แม้คะแนนรวมไม่ถึง threshold

---

## ผลบนชุด V2 (import production จริง, SHARED_NAT=true)

```
Recall 85.0% | Precision 98.1% | F1 0.911
Challenge FPR 2.11% (4/190) | Warn FPR 2.11% | Policy success 85.0%
```

| scenario | recall | policy |
|---|---|---|
| combined_ato / concurrent_sessions / failed_spike | 100% | 100% |
| login_velocity / new_device / new_os | 100% | 100% |
| new_passkey / new_ua_family / permission_change | 100% | 100% |
| **off_hours** | 0% | **0%** ⚠️ |
| **subsystem_lateral** | 0% | **0%** ⚠️ |

**9/11 scenario ได้ 100%** · 2 ตัวที่เหลือคือข้อจำกัดที่รู้อยู่แล้ว:
- `subsystem_lateral` — ต้องเพิ่มฟีเจอร์ที่ 24 `is_new_subsystem` (แตะ B49 contract + retrain)
- `off_hours` — ต้องจูน behavior temporal (z-score รายคนแทนเกณฑ์ตายตัว 6/10 ชม.)

ตรงกับที่วิเคราะห์: contract_v2 (23 feat) = 85% / lateral 0% · +1 feat = 90% / lateral 100%
→ **production ตอนนี้ = contract_v2 = 85%** (ยังไม่รวมฟีเจอร์ที่ 24)

---

## เทียบก่อน–หลัง (ชุดเดียวกัน)

| | Recall | Policy | Challenge FPR |
|---|---|---|---|
| production เดิม | 25.0% | 33.3% | 0.00% |
| **production หลัง port** | **85.0%** | **85.0%** | 2.11% |

FPR ขึ้นจาก 0%→2.11% (แลกกับ recall +60 จุด) — ยังอยู่ในงบ (<5%)

---

## TDD trail

```
RED  : 9/12 fail (กฎใหม่ยังไม่มี) · 3 pass (normal-safe ยังถูก)
GREEN: 12/12 pass หลังแก้ 3 ไฟล์
```

Unit tests ครอบคลุม: แต่ละกฎใหม่ยิงถูก · normal vector = 0 · permission เก่าไม่ยิง ·
policy floor บังคับ challenge (new_passkey/permission/concurrent) · normal ยัง allow

---

## ข้อควรระวัง / ยังไม่ทำ

1. **ยังไม่ commit** — ตาม policy ของโปรเจกต์ (รอ review)
2. **full pytest (`test_risk_scenarios.py`) ต้องรันใน docker** — deps (psycopg2/redis) ผมติดตั้ง local ชั่วคราวเพื่อรัน unit + e2e เท่านั้น ควรรัน suite เต็มใน container ก่อน merge:
   ```bash
   docker compose exec hub-backend pytest tests/test_rule_engine_v2_signals.py tests/test_risk_scenarios.py -v
   ```
3. **เปิด `SHARED_NAT=true` ใน .env ของ production หลัง campus NAT** — ไม่งั้น multi_account_ip ยังยิง
4. **shadow mode ก่อน enforce** — ยังไม่ควรตั้ง `ML_SHADOW_MODE=false` จนกว่าจะดู FPR บน log จริง
5. FPR 2.11% วัดบน synthetic — ต้องยืนยันบน production replay ก่อน enforce

---

## ไฟล์

| ไฟล์ | สถานะ |
|---|---|
| `hub/backend/app/config.py` | แก้ (+shared_nat) |
| `hub/backend/app/security/rule_engine.py` | แก้ (SCORE_RULES + min_action + NAT) |
| `hub/backend/app/security/risk_aggregator.py` | แก้ (policy floor) |
| `hub/backend/tests/test_rule_engine_v2_signals.py` | ใหม่ (unit, 12 tests) |
| `ml-service/scripts/eval_production_v2.py` | ใหม่ (e2e harness) |
| `docs/bugs-encountered.md` | เพิ่ม B60 |

## ถัดไป (Phase 1 ที่เหลือ + Phase 2)
- เพิ่มฟีเจอร์ที่ 24 `is_new_subsystem` (sync 4 ไฟล์ B49 + retrain) → lateral 0%→100%
- จูน behavior temporal เป็น z-score รายคน → off_hours
- รัน suite เต็มใน docker → shadow mode → วัด FPR จริง → ค่อย enforce
