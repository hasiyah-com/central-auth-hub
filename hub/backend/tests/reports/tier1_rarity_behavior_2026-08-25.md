# Tier 1 — เก็บ behavior-rarity ของ V8 มาใส่ Rule/Behavior (hour_rarity + subsystem novelty)

**วันที่:** 25 ส.ค. 2026
**ที่มา:** หลัง ablation สรุปว่า V8 (neural) ไม่ generalize บนข้อมูลจริง → เก็บเฉพาะ
**แนวคิด rarity per-profile (สถิติล้วน ไม่ใช่ ML)** ของ V8 มาเสริม production layer แทน
**เป้า:** แก้ 2 scenario ที่ Phase 1 ได้ 0% — `off_hours`, `subsystem_lateral`
**วิธี:** TDD (RED→GREEN→REFACTOR) + A/B บนชุด V2 เดียวกัน (import โค้ด production จริง)

---

## ผลลัพธ์ (A/B ชุด V2 เดียวกัน · normal test 190 · attack 240)

| ตัวชี้วัด | baseline (Phase 1) | +Tier 1 | ต่าง |
|---|---|---|---|
| **Recall** | 85.0% | **95.8%** | **+10.8** |
| **Policy success** | 85.0% | **99.6%** | **+14.6** |
| **Challenge FPR** | 2.1% | **2.1%** | **+0.0** ✅ |
| Warn FPR | 2.1% | 5.8% | +3.7 |
| Precision | 98.1% | 98.3% | +0.2 |

> **ได้การตรวจจับที่ V8 ควรจะให้ (+10.8 recall) แต่ Challenge FPR ไม่ขยับเลย (2.1%→2.1%)**
> — ต่างจาก V8 ที่ดัน FPR เป็น 14% เพื่อ recall แค่ +3.3%

### per-scenario (สองตัวที่เคย 0%)

| scenario | baseline (r / policy) | +Tier 1 (r / policy) |
|---|---|---|
| `subsystem_lateral` | 0% / 0% | **100% / 100%** ✅ |
| `off_hours` | 0% / 0% | **58% / 96%** ✅ |
| อีก 9 scenario | 100% / 100% | 100% / 100% (ไม่ถดถอย) |

- `subsystem_lateral` — เข้าระบบที่ไม่เคยใช้ = deterministic → **policy floor challenge** → 100%
- `off_hours` — EXPECTED = **warn** → policy 96% (ถึง warn เกือบทุก case) คือตัวเลขที่ถูกต้อง
  (recall 58% นับเฉพาะ challenge+ ซึ่ง off_hours ไม่จำเป็นต้องถึง)

---

## สิ่งที่เพิ่ม (สถิติล้วน — อธิบายได้ ไม่มีโมเดล)

`rarity = 1 − (count+1)/(total + buckets)` (Laplace smoothing) ต่อโปรไฟล์แต่ละคน

### 1. `hour_rarity` — แก้ off_hours (จับ multi-peak รายคน)
- `get_user_profile` เก็บ `hour_counts` (histogram ชั่วโมง login 30 วัน)
- ชั่วโมงที่ผู้ใช้คนนี้แทบไม่เคยเข้า (`rarity ≥ 0.95`) → +0.30
- **ต่างจาก `hours_from_typical` เดิม** ที่ใช้ median เดียว → ผู้ใช้หลาย peak (เช้า/บ่าย/ค่ำ)
  ไม่ถูก flag ผิด แต่ชั่วโมงที่ไม่เคยเข้าเลย = rarity สูง จับได้

### 2. subsystem novelty — แก้ subsystem_lateral
- `get_user_profile` เก็บ `subsystem_counts` + `seen_subsystems`
- **ไม่เคยใช้ระบบนี้เลย** → +0.30 **และ `min_action="challenge"` (policy floor)** — เพราะเป็น
  ข้อเท็จจริงแน่นอน (เคย/ไม่เคย) ไม่ใช่แค่คะแนนที่อาจไม่ถึง threshold
- เคยใช้แต่นานๆ ที (`rarity ≥ 0.95`) → +0.15 soft (warn) ไม่บังคับ challenge — legit rare use ไม่โดนกวน

### 3. `BehaviorResult.min_action` + aggregate honor
- เพิ่ม field `min_action` ให้ behavior ตั้ง policy floor ได้ (mirror `RuleResult.min_action` ของ B60)
- `risk_aggregator.aggregate` honor ทั้ง `rule.min_action` และ `behavior.min_action`

**Guard กัน false alarm:** rarity ทำงานเมื่อ `total ≥ MIN_HISTORY_FOR_RARITY = 20` เท่านั้น
(history น้อยเกินยังไม่เชื่อคำว่า "ไม่เคย") · cold-start (profile None) พฤติกรรมเดิมทุกอย่าง

---

## ทำไมไม่ดัน Challenge FPR (จุดสำคัญ)

- **hour_rarity** ยิงเฉพาะชั่วโมงที่ rarity ≥ 0.95 (แทบไม่เคยเข้า) → +0.30 = **warn เท่านั้น**
  ไม่ถึง challenge (0.7) เอง → normal ที่บังเอิญ login ชั่วโมงแปลกได้แค่ warn (soft, ไม่กวน user)
- **subsystem floor** ยิงเฉพาะระบบที่ **ไม่อยู่ใน seen_subsystems** — normal test เข้าระบบที่เคยใช้
  ทั้งหมด → ไม่ยิงเลย → challenge FPR ไม่ขยับ
- Warn FPR +3.7 มาจาก hour_rarity ยิง normal บางส่วน (ชั่วโมงนานๆ เข้าที) แต่ warn = monitoring
  ไม่ challenge ผู้ใช้ → operational cost ต่ำ

---

## เทียบกับ V8 (ทำไมทางนี้ดีกว่า)

| | V8 (neural) | Tier 1 (rarity สถิติ) |
|---|---|---|
| off_hours + lateral | +17% / +25% (บางส่วน) | **+96% / +100% (policy)** |
| Challenge FPR | **1.7% → 14.1%** ⚠️ | **2.1% → 2.1%** ✅ |
| อธิบายได้ | ทึบ (64-dim MLP) | โปร่งใส (`hour_rarity=0.98`, `new_subsystem`) |
| generalize | ผูก generator ตัวเอง (ranking พังบน V2) | คำนวณจาก history ผู้ใช้จริงแต่ละคน |
| cold-start | abstain (< 1000 event) | smoothing + guard 20 event |

**สรุป:** ของดีของ V8 คือ "แนวคิด rarity รายคน" ไม่ใช่ neural net — พอเอาแนวคิดมาทำเป็น
สถิติในชั้น behavior ได้ผลตรวจจับดีกว่า + FPR ต่ำกว่า + อธิบายได้ + generalize

---

## ไฟล์ที่แก้ (production)

| ไฟล์ | เปลี่ยน |
|---|---|
| `app/security/behavior_profiling.py` | `get_user_profile` เก็บ hour/subsystem histogram · `evaluate_behavior(..., subsystem_id)` เพิ่ม hour_rarity + subsystem novelty · `BehaviorResult.min_action` |
| `app/security/risk_aggregator.py` | `aggregate` honor `behavior.min_action` (policy floor จาก behavior) |
| `app/security/risk_engine.py` | ส่ง `subsystem_id` เข้า `evaluate_behavior` (มี var อยู่แล้ว) |

## ไฟล์ test / eval

| ไฟล์ | บทบาท |
|---|---|
| `tests/test_behavior_rarity.py` | 9 unit tests (TDD) — rarity ยิง/ไม่ยิง, policy floor, backward compat, cold start |
| `tests/test_rule_engine_v2_signals.py` | 12 tests เดิม — ยัน ไม่ regress |
| `ml-service/scripts/eval_tier1_ab.py` | A/B baseline vs +Tier1 บนชุดเดียวกัน |
| `ml-service/scripts/eval_production_v2.py` | อัปเดตให้ profile ใหม่ + ส่ง subsystem_id |

---

## TDD log

```
RED    tests/test_behavior_rarity.py  →  1/9 (8 fail: evaluate_behavior ยังไม่รับ subsystem_id)
GREEN  implement 3 จุด                →  9/9 pass
REFACTOR  py_compile OK · rarity 9/9 · rule signals 12/12 (ไม่ regress)
```

## รันซ้ำ

```bash
py ml-service/scripts/build_profiles_v2.py
py ml-service/scripts/features_v2.py
cd hub/backend
SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/eval_tier1_ab.py
PYTHONPATH=. python tests/test_behavior_rarity.py
```

---

## สถานะ & ต่อไป

- ✅ Tier 1 เสร็จ — recall 85%→95.8%, 2 scenario 0% แก้แล้ว, Challenge FPR ไม่ขยับ
- ⏳ ต้องรัน full pytest (`test_risk_scenarios.py` ที่มี db fixture) ใน docker ก่อน commit —
  เครื่อง local รันแค่ offline test ได้
- ยังไม่ commit (รอ OK ตามกฎ propose-before-editing)
- **Tier 2 (ถ้าจะทำต่อ):** `cadence_tail` (velocity รายคน) + `signature_rarity` (device graded) +
  `_robust_center_scale` (normalize รายคนทน outlier)
