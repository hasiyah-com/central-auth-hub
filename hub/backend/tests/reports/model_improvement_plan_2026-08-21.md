# แผนปรับปรุงโมเดลให้ทำงานได้ดีที่สุด — ฉบับละเอียด

**วันที่:** 21 ส.ค. 2026
**ฐาน:** ต่อยอดจาก V3 (rule + behavior + one-class) — ไม่ใช้ supervised
**อ้างอิงผลจริง:** [`rba_4layer_v2_2026-08-21.md`](rba_4layer_v2_2026-08-21.md), [`v2_to_v7_version_sweep_2026-08-21.md`](v2_to_v7_version_sweep_2026-08-21.md)

---

## เป้าหมายเป็นตัวเลข

วัดบนชุด V2 (12 โปรไฟล์จริง · campus NAT · ไม่มี geo):

| | Recall | Policy success | Challenge FPR | PR-AUC |
|---|---|---|---|---|
| **production ตอนนี้** | 25.0% | 33.3% | 0.00% | 0.882 |
| **เป้า Phase 1** (contract_v2_plus) | **90.0%** | **96.2%** | 2.11% | 0.980 |

**ไม่ใช่ตัวเลขในฝัน — วัดได้จริงแล้วด้วย `ml-service/scripts/contract_v2.py`** แค่ยังไม่พอร์ตเข้า production

---

# ทำไม production ตอนนี้ได้แค่ 25%

ไม่ใช่โมเดลไม่ดี — **15 จาก 23 ฟีเจอร์ไม่มีชั้นไหนให้คะแนนเลย**

`rule_engine.SCORE_RULES` ให้คะแนนแค่ 6 ตัว · `behavior_profiling` แค่ 3 ตัว
เมื่อไม่มี geo เหลือกฎที่ใช้ได้จริงแค่ 5 ตัว → attack 5 ชนิดได้ **recall 0%**:

| scenario | prod ตอนนี้ | สาเหตุ |
|---|---|---|
| `concurrent_sessions` | **0%** | `concurrent_session_count` ไม่มีกฎ |
| `login_velocity` | **0%** | `log_minutes_since_last` + `login_count_24h` ไม่มีกฎ |
| `new_passkey` | **0%** | `new_passkey_recently_added` ไม่มีกฎ |
| `permission_change` | **0%** | `permission_change_age` ไม่มีกฎ |
| `subsystem_lateral` | 8% | ไม่มีฟีเจอร์ "เข้า subsystem ที่ไม่เคยใช้" |

ablation ยืนยัน: **ML คือชั้นเดียวที่ "เห็น" 15 ฟีเจอร์นี้** (ML-only recall 25.4% > Rule-only 10%)
แต่ ML ให้คะแนนสูงสุด +0.40 → ไม่พอถึงเกณฑ์ challenge 0.70

---

# PHASE 1 — พอร์ต Contract V2 เข้า production (2-3 วัน)

**ไม่ retrain · ไม่แตะ 23-feature contract · แก้แค่ 2 ไฟล์**
`contract_v2.py` พิสูจน์แล้วว่าได้ 90% — งานคือย้ายตรรกะเข้า `rule_engine.py` + `risk_aggregator.py`

## 1.1 หลักการ Signal Ownership (หัวใจของ V2/V3)

ปัญหาเดิม: ฟีเจอร์บางตัวถูกให้คะแนนซ้ำ 2 ชั้น (double-count) บางตัวไม่มีใครให้เลย
แก้: **ทุกสัญญาณมี "เจ้าของกลุ่ม" เดียว + น้ำหนัก + ขั้นต่ำที่บังคับ (policy floor)**

```
กลุ่ม        สัญญาณที่ครอบคลุม
device       new_device, new_ua_family
bruteforce   failed_logins_24h
velocity     log_minutes_since_last + login_count_24h    <- เดิมไม่มีใครให้คะแนน
session      concurrent_session_count, active_subsystem   <- เดิมไม่มีใครให้คะแนน
credential   new_passkey_recently_added                   <- เดิมไม่มีใครให้คะแนน
privilege    permission_change_age                        <- เดิมไม่มีใครให้คะแนน
temporal     hours_from_typical (off_hours)
geo          is_new_country, impossible_travel (คงไว้ ไม่ยิงเมื่อไม่มี geo)
```

**กติกา 3 ข้อ:**
1. แต่ละกลุ่มรวมคะแนนได้ไม่เกิน `GROUP_CAP = 0.40` (กันสัญญาณเดียวดันเกินจริง)
2. ML รวมได้ไม่เกิน `ML_CAP = 0.25` (ML เป็นตัวช่วย ไม่ใช่ตัวตัดสิน)
3. สองกลุ่มยืนยันกัน + คะแนน ≥0.58 → ยกเป็น challenge (ไม่ใช่ลด threshold รวม)

## 1.2 Policy Floor — เหตุการณ์ความปลอดภัยที่ชัดเจนต้องมี action ขั้นต่ำ

ปัญหาเดิม: `new_passkey` ที่เพิ่งลงทะเบียนก่อน login 5 นาที ถ้าคะแนนรวมไม่ถึง 0.70 → ปล่อยผ่าน
แก้: สัญญาณ deterministic บังคับ minimum action ไม่ว่าคะแนนรวมเท่าไหร่

| สัญญาณ | minimum action |
|---|---|
| new_device, failed_spike, velocity, concurrent, new_passkey, perm_recent, new_country | **challenge** |
| off_hours, new_os, failed_mild | **warn** |
| confirmed_incident | **block** (hard) |

**ผล:** policy success 33.3% → 91.2% (วัดแล้ว)

## 1.3 แก้ 2 จุดที่ทำ FPR พุ่งบน NAT (สำคัญกับ deployment นี้)

| จุด | ปัญหา | แก้ |
|---|---|---|
| `multi_account_ip` | ทุกคนใช้ IP `192.168.10.1` → ยิงใส่ normal **26%** (+0.25 ฟรี) | ปิดกฎเมื่อ `SHARED_NAT=True` |
| `scope_sensitivity` | เป็นค่าคงที่ต่อ subsystem ไม่ใช่ความผิดปกติ → **43% ของ FP** | ตัดออกจากหลักฐาน เก็บเป็นบริบท |

## 1.4 ไฟล์ที่แก้จริง

**`hub/backend/app/security/rule_engine.py`** — ขยาย `SCORE_RULES` 6 → 18 สัญญาณ + group/floor
(โครงเต็มอยู่ใน `ml-service/scripts/contract_v2.py:SIGNALS` — พอร์ตตรง ๆ ได้)

```python
SHARED_NAT = True   # deployment หลัง campus NAT — ปิด multi_account_ip
GROUP_CAP = 0.40

# (ฟีเจอร์, op, threshold, weight, group, min_action)  — ย่อ
SCORE_RULES = [
    ("is_new_device",              "==", 1,   0.30, "device",     "challenge"),
    ("is_new_user_agent_family",   "==", 1,   0.20, "device",     "challenge"),
    ("failed_logins_24h",          ">=", 5,   0.30, "bruteforce", "challenge"),
    ("failed_logins_24h",          ">=", 3,   0.20, "bruteforce", "warn"),
    ("__velocity__",               None, None, 0.25, "velocity",  "challenge"),  # log_min<=2 AND count>=5
    ("login_count_24h",            ">=", 15,  0.20, "velocity",   "warn"),
    ("concurrent_session_count",   ">=", 3,   0.25, "session",    "challenge"),
    ("active_subsystem_count",     ">=", 2,   0.20, "session",    "challenge"),
    ("new_passkey_recently_added", "==", 1,   0.30, "credential", "challenge"),
    ("permission_change_age",      "<=", 1,   0.25, "privilege",  "challenge"),
    ("permission_change_age",      "<=", 7,   0.10, "privilege",  "warn"),
    ("hours_from_typical_login_time", ">=", 10, 0.30, "temporal", "warn"),
    ("hours_from_typical_login_time", ">=", 6,  0.20, "temporal", None),
    ("is_new_country",             "==", 1,   0.30, "geo",        "challenge"),
    ("impossible_travel_score",    ">=", 0.5, 0.30, "geo",        "challenge"),
]
```

รวมคะแนนแบบ group-cap:
```python
by_group, floor = {}, 0
for feat, op, thr, w, group, min_act in SCORE_RULES:
    if hit(features, feat, op, thr):
        by_group[group] = min(GROUP_CAP, by_group.get(group, 0.0) + w)
        if min_act: floor = max(floor, RANK[min_act])
# ML cap 0.25 · multi_account_ip เพิ่มเฉพาะเมื่อ not SHARED_NAT
```

**`hub/backend/app/security/risk_aggregator.py`** — รับ `floor` มาบังคับ:
```python
rank = decision_from_total(total)
if len(real_groups) >= 2 and total >= 0.58:
    rank = max(rank, RANK["challenge"])   # two-group confirm
rank = max(rank, floor)                    # policy floor
```

## 1.5 การทดสอบ Phase 1

```bash
py ml-service/scripts/run_4layer_v2.py       # mode=production ต้องขึ้นเป็น ~90%
py hub/backend/tests/test_4layer_v2.py       # 12/12 ต้องยังผ่าน
```
เพิ่ม test `test_production_matches_contract_v2` — ยืนยัน production = contract_v2_plus

**เกณฑ์ผ่าน Phase 1:** recall ≥85% · Challenge FPR ≤5% · Warn FPR ≤6% · ทุก scenario > 0%

---

# PHASE 2 — แก้ข้อมูลจำลองให้เชื่อถือได้ (1 สัปดาห์)

**ต้องทำก่อน Phase 3 — ไม่งั้นวัด sequence model แล้วเชื่อไม่ได้**

ปัญหาที่พิสูจน์แล้ว: "normal" ของ generator สม่ำเสมอเกินจริง → attack แยกออกง่ายเกินไป
(V6 ได้ ROC-AUC 0.996 บนข้อมูลตัวเอง แต่ 0.64 บนชุดจริง)

## 2.1 แก้ generator (5 ฟีเจอร์ที่หลุด support)

| ฟีเจอร์ | ตอนนี้ | แก้เป็น |
|---|---|---|
| `success_10m` | normal = 0 เสมอ | คำนวณจาก timeline (แพตช์ `v7_generator_success_10m.patch` มีแล้ว) |
| `session_duration` | `lognormal(log 18, 0.42)` σ แคบ | ข้อมูลจริง 0.1–1,302 นาที → เพิ่ม σ + หางยาว |
| `browser_version` | ไต่ขึ้นทีละ 1 ทางเดียว | จริงมีหลายเครื่องคนละเวอร์ชัน + กระโดดข้าม |
| `concurrent_sessions` | normal เกือบ 0 หมด | ให้มี overlap ที่ถูกต้องบ้าง (เปิดหลายแท็บ) |
| duration ramp (attack) | คงที่ `(1.2, 1.55, 2.05, 2.8)` | สุ่มทิศ/ขนาด — ไม่งั้น "มี ramp = attack" |

## 2.2 เพิ่ม test กัน generator artifact (AUC จับไม่ได้)

```python
def test_no_feature_perfectly_separates():
    """ไม่มีฟีเจอร์ไหนที่ normal ตอนเทรนเป็นค่าเดียวขณะ attack ต่าง (บทเรียน success_10m)."""
    for feat in FEATURES:
        assert len({row[feat] for row in normal_train}) > 1, f"{feat}: normal ค่าเดียว = shortcut"

def test_support_overlap_with_real_data():
    """normal ในชุดจริงต้องหลุดช่วง train ไม่เกิน 10% ทุกฟีเจอร์."""
    for feat in FEATURES:
        assert fraction_outside(real_normal[feat], train_range[feat]) <= 0.10
```

**เกณฑ์ผ่าน Phase 2:** ไม่มีฟีเจอร์ AUC เดี่ยว >0.95 · normal จริงหลุด support ทุกตัว ≤10%

---

# PHASE 3 — Sequence layer แบบ one-class (2-3 สัปดาห์)

**เป้าหมาย: เติมช่องที่ V3 มองไม่เห็น = แคมเปญหลายระยะ** (V3 event recall แค่ 0.35% กับ attack 4 phase)

## 3.1 ทำไม one-class ไม่ใช่ supervised

| | supervised (V6 — ทิ้ง) | one-class (V5 — ใช้) |
|---|---|---|
| ต้องมี label attack | ✅ ซึ่ง production ไม่มี | ❌ เทรนจาก normal อย่างเดียว |
| เรียนทางลัดจาก label | ✅ (เกิดขึ้นจริง) | ❌ โดยโครงสร้าง |
| ตรงกับข้อมูลจริง | ❌ (normal เยอะ/attack แทบไม่มี) | ✅ |

## 3.2 ออกแบบเป็น "ชั้นเสริม" ไม่ใช่ตัวแทน

```
Layer 1 Rule (V3)      → จับ single-event, FPR ต่ำ       ← Phase 1
Layer 2 Behavior       → เทียบ baseline รายคน            ← คงไว้
Layer 3a IForest event → anomaly ต่อ event               ← มีอยู่แล้ว
Layer 3b Sequence      → anomaly ต่อ "ลำดับ 4 event"     ← เพิ่มใหม่ (one-class)
Layer 4 Aggregate      → รวม + policy floor              ← Phase 1
```

Sequence layer ใช้ 13 sequence feature ของ V5 แต่:
- เทรน `IsolationForest` บน **normal-only** (ไม่ใช่ RandomForest บน label)
- calibrate threshold จาก normal เท่านั้น
- **cap contribution ต่ำ** (+0.20) — ตัวเสริม ไม่ override rule

## 3.3 วัดผลให้ซื่อสัตย์ (บทเรียนจาก V6/V7)

1. **เทรนบน generator A วัดบน generator B เสมอ** — ไม่ใช่ test split ตัวเอง
2. รายงาน ROC-AUC ทั้งสองชุด — ต่างกัน >0.1 = generalize ไม่ได้
3. `release_gate` ต้องคำนวณใหม่ทุกครั้ง ไม่ copy จากเวอร์ชันก่อน

**เกณฑ์ผ่าน Phase 3:** ROC-AUC บนชุดนอก ≥0.80 · sequence detection ≥60% · FPR ไม่เพิ่มจาก Phase 1 เกิน 1%

---

# PHASE 4 — Feature 24 + production hardening (ต่อเนื่อง)

## 4.1 เพิ่ม `is_new_subsystem` (แก้ lateral 0% → 100%)

`active_subsystem_count` นับแค่ session ที่เปิดพร้อมกัน — ไม่รู้ว่า "ไม่เคยใช้ระบบนี้"
ทดลองแล้ว: เพิ่มฟีเจอร์นี้ทำ subsystem_lateral 0%→100% และ recall รวม 85%→90%

**ต้อง sync 4 ไฟล์ (B49):** `features.py` · `generate_data.py` · `feature_extraction.py` · `rule_engine.py:FEAT`
→ กลายเป็น 24-feature contract + retrain IForest

## 4.2 เปิด geo เมื่อ deploy บน infra ที่ได้ IP

ตอนนี้ 5 ฟีเจอร์ geo เป็นค่าคงที่ (campus NAT) — ถ้าย้าย infra ที่ได้ client IP:
ตั้ง `MAXMIND_LICENSE_KEY` → backfill → retrain → ได้สัญญาณ ATO ต่างประเทศคืนมา

## 4.3 ปิดวงจร feedback loop

`export_labeled_data.py` เก็บ real normal อยู่แล้ว → เมื่อมี real attack label (admin กด MLFeedback)
→ retrain เป็นระยะ → IForest เห็น distribution จริงมากขึ้น → FPR ลด

---

# สรุปลำดับความสำคัญ

| Phase | งาน | ผลที่คาด | เวลา | เสี่ยง |
|---|---|---|---|---|
| **1** | พอร์ต Contract V2 เข้า production | recall 25%→90%, policy 33%→96% | 2-3 วัน | ต่ำ (พิสูจน์แล้ว) |
| **2** | แก้ข้อมูลจำลอง + support test | วัดผลเชื่อถือได้ | 1 สัปดาห์ | ต่ำ |
| **3** | Sequence layer one-class | จับแคมเปญหลายระยะ | 2-3 สัปดาห์ | กลาง (ต้องการ Phase 2) |
| **4** | feature 24 + geo + feedback | recall 90%→95%+ | ต่อเนื่อง | กลาง (retrain) |

**เริ่ม Phase 1 ได้เลย** — ผลมากสุด เสี่ยงน้อยสุด ไม่ต้อง retrain
มีโค้ดพิสูจน์แล้วใน `ml-service/scripts/contract_v2.py` แค่พอร์ตเข้า `rule_engine.py`

---

## สิ่งที่ **ไม่** ควรทำ (บทเรียนจาก V6/V7)

- ❌ กลับไป supervised/RandomForest — production ไม่มี label attack
- ❌ ไล่ตามตัวเลขบน test split ตัวเอง — ต้องวัดบนข้อมูลนอกเสมอ
- ❌ เพิ่มฟีเจอร์ geo/IP ใหม่ตอนที่ยังไม่มี IP — ไม่มี data source
- ❌ เปิด enforcement ก่อนผ่าน shadow mode บน log จริง
