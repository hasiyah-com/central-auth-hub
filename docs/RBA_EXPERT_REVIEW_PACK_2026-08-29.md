# ชุดหลักฐานสำหรับผู้เชี่ยวชาญตรวจ — 4-Layer RBA

**วันที่:** 29 ส.ค. 2026 · **สถานะ:** ผลการทดลอง freeze แล้ว (tag `rba-freeze-2026-08-29`)
**ผู้จัดทำ:** เจ้าของโปรเจค (Senior Project)

เอกสารนี้เป็น **ทางเข้า** ของชุดหลักฐานทั้งหมด — ออกแบบให้ผู้ตรวจอ่านตามลำดับแล้ว
ตัดสินได้เองว่าข้อสรุปเชื่อถือได้แค่ไหน โดยไม่ต้องเชื่อคำอธิบายของผู้จัดทำ

---

## 1. อ่านอะไรก่อน (30 นาทีแรก)

| ลำดับ | เอกสาร | ตอบคำถาม |
|---|---|---|
| 1 | เอกสารนี้ §3–§5 | ข้อสรุปคืออะไร · เชื่อได้แค่ไหน · จุดอ่อนอยู่ตรงไหน |
| 2 | `hub/backend/tests/reports/exp_final_gate_2026-08-26.md` | ผลบนชุดที่โมเดลไม่เคยเห็น (ตัวเลขที่ควรอ้างอิง) |
| 3 | `hub/backend/tests/reports/l3_shadow_replay_2026-08-29.md` | สิ่งที่เกิดขึ้นจริงบน traffic จริง |
| 4 | `docs/RBA_EXPERIMENTS_SUMMARY_2026-08-26.md` | เส้นทางการทดลองทั้งหมด (ยาว) |
| 5 | `docs/RBA_EVIDENCE_MANIFEST_2026-08-29.md` | commit SHA · config · seeds · hash ของทุกไฟล์ |

---

## 2. ระบบที่ตรวจคืออะไร

**4-Layer Hybrid Risk-Based Authentication** สำหรับ Central Auth Hub (ระบบ identity
รวมศูนย์ของมหาวิทยาลัย · ไม่ใช่ SSO — แต่ละ subsystem มี session ของตัวเอง)

| ชั้น | ทำอะไร | สถานะ |
|---|---|---|
| L1 Rule Engine | กฎ deterministic (เครื่องใหม่ · ประเทศใหม่ · failed login ฯลฯ) + policy floor | ✅ ใช้งานจริง |
| L2 Behavior Profiling | สถิติรายคน (rarity ของชั่วโมง/subsystem/อุปกรณ์ · cadence z-score) | ✅ ใช้งานจริง |
| L3 IsolationForest (sequence) | per-user anomaly บน residual 6 มิติ × window 5 | ⚙️ **shadow เท่านั้น** |
| L4 Aggregation | รวมคะแนน + บังคับ policy floor → allow/warn/challenge/block | ✅ ใช้งานจริง |

**L3 ถูกจำกัดอำนาจโดยตั้งใจ:** ยก decision ได้สูงสุดแค่ `warn` — ห้ามแตะ `challenge`/`block`
(ตรวจครบ 288 กรณี + วัดบน 63,230 เหตุการณ์: เปลี่ยน access decision **0 ครั้ง**)

---

## 3. ข้อสรุปหลัก 5 ข้อ

### 3.1 ชั้นที่ทำงานจริงคือ L1+L2 (สถิติ) ไม่ใช่ ML

| ชั้น | recall เดี่ยวๆ (final gate, size 5000) |
|---|---|
| L1 Rule | 50.5% [48.7, 52.2] |
| L2 Behavior | 49.8% [48.0, 51.5] |
| L3 IForest (ยิงระดับ event) | 5.7% [5.0, 6.6] |
| **L4 รวม** | **61.9% [60.2, 63.6]** |

### 3.2 โมเดล supervised ที่ดูดีที่สุดเป็น artifact ทั้งหมด

เวอร์ชันที่ได้ recall 90.9% ถูกตรวจพบว่าเรียน shortcut จาก generator —
ดู `v7_generator_fix_2026-08-21.md`, `v2_to_v7_version_sweep_2026-08-21.md`

### 3.3 สถิติรายคนเอาชนะ neural network บนข้อมูลที่ anchor จากผู้ใช้จริง

| แนวทาง | recall | Challenge FPR |
|---|---|---|
| Phase 1 (rule port) | 85.0% | 2.11% |
| **+ per-user rarity (Tier 1)** | **95.8%** | **2.11%** |
| V8 Temporal MLP | 86.2% | **14.1%** ❌ |

(ตัวเลขชุดพัฒนา — ดู §4 เรื่อง optimism bias)

### 3.4 ชั้นที่ overfit คือ L1/L2 ไม่ใช่ L3

บน campaign family ที่ไม่เคยเห็น: L1/L2 ตก **38.8% → 20.7%** ขณะที่ L3 (Config F)
ขึ้น 3.6% → 5.1% — ทิศทางตรงข้ามกับที่คาด

### 3.5 🔑 L3 ไปไม่ถึงเกณฑ์ที่จะมีประโยชน์ใน deployment จริง

จาก traffic จริง: **อัตรา login มัธยฐาน 1.65 ครั้ง/วัน/คน**
→ ต้องใช้ **~1.7 ปี** จึงจะสะสม history ครบ 1,000 เหตุการณ์ (เกณฑ์ที่ L3 เริ่มเปลี่ยน decision ได้)
→ **ในทางปฏิบัติ L3 จะอยู่ในสถานะ abstain/diagnostic แทบตลอดอายุการใช้งาน**

ข้อนี้ไม่ได้แปลว่าโมเดลผิด แต่แปลว่า **สมมติฐานเรื่องปริมาณข้อมูลต่อคน
ไม่ตรงกับความจริงของ deployment นี้** — เป็นข้อค้นพบที่ต้องการความเห็นผู้เชี่ยวชาญมากที่สุด

---

## 4. สิ่งที่ทำเพื่อไม่ให้หลอกตัวเอง

| มาตรการ | รายละเอียด |
|---|---|
| **แยก dev / final attack** | attack ที่ใช้ปรับจูน แยกจาก attack ที่ใช้วัดผลสุดท้ายคนละชุด |
| **Final gate seeds ใหม่ทั้งหมด** | train 42–46 · eval **101–105** (normal + attack ใหม่ทั้งคู่) รันครั้งเดียว |
| **ตรวจ leakage** | เทียบ 11 ฟิลด์ต่อแถว → **0/63,230** ซ้ำ |
| **ตรวจ generator shortcut** | ไม่มี feature ที่ AUC > 0.99 หรือ support < 5% |
| **Leave-one-family-out** | สร้าง campaign family ที่ออกแบบมาเลี่ยงแกนของโมเดลโดยเฉพาะ 5 แบบ |
| **CI ที่คำนึงถึง clustering** | Wilson (สัดส่วน) · cluster bootstrap (เหตุการณ์สัมพันธ์กัน) · hierarchical bootstrap (user→seed→instance) |
| **Episode-based generation** | 50 เหตุการณ์/25 วัน · reset rolling state · window ไม่ข้าม episode |
| **ไม่ปรับโมเดลจาก final holdout** | ผล freeze แล้ว — การเปลี่ยนใดๆ ต้องเป็นการทดลองรอบใหม่ |
| **Freeze ตรวจสอบได้** | SHA-256 ของหลักฐาน 43 ไฟล์ + commit SHA + tag |

**ตรวจว่าหลักฐานไม่ถูกแก้ย้อนหลัง:**

```bash
git checkout rba-freeze-2026-08-29
python scripts/build_evidence_manifest.py --verify
```

---

## 5. จุดอ่อนที่ผู้จัดทำระบุเอง (ขอให้ตรวจหนักที่จุดเหล่านี้)

| # | ข้อจำกัด | ผลกระทบ |
|---|---|---|
| 1 | **ทุกตัวเลขบนข้อมูลจำลอง** (anchor จากผู้ใช้จริง 12 คน แต่ generate เอง) | ยังไม่มีตัวเลขจาก traffic จริง — replay เพิ่งเริ่ม |
| 2 | **campaign attack ออกแบบเอง** | L3 จับได้เพราะเป็น joint-drift ที่ผู้จัดทำใส่เข้าไปเอง — circular ในระดับหนึ่ง |
| 3 | **Geo layer ใช้ไม่ได้** (campus NAT) | 5/23 ฟีเจอร์เป็นค่าคงที่ · ระบบทำงานบน 18 ฟีเจอร์ |
| 4 | **ช่องว่างระหว่างชุดพัฒนากับ final gate ใหญ่มาก** | 95.8% → 61.9% — ขนาดของ optimism bias ที่วัดได้ |
| 5 | **ไม่เคยทดสอบ enforcement จริง** | ทุกอย่างวัดในโหมดประเมินผล ไม่มีผู้ใช้จริงถูกบล็อก |
| 6 | **latency/concurrency วัดบนเครื่องพัฒนา** | ไม่ใช่ SLA ของ production |
| 7 | **ผู้ทดลองคนเดียว** | ไม่มี blind review ระหว่างทาง |

---

## 6. คำถามที่อยากให้ผู้เชี่ยวชาญตอบ

1. **§3.5 (tier reachability)** — ควรเดินทางไหน?
   | ทางเลือก | ผลที่ตามมา |
   |---|---|
   | คง L3 เป็น diagnostic อย่างเดียว | ซื่อตรงที่สุด · L3 ไม่มีผลต่อ decision เลย |
   | ลดเกณฑ์ tier ลง | ต้องทดลองใหม่ทั้งชุด (ที่ history ต่ำเคยวัดได้ 4.7%) |
   | รวม history ข้ามผู้ใช้ (population model) | เปลี่ยนสถาปัตยกรรม ไม่ใช่ per-user อีกต่อไป |
   | ตัด L3 ออก ยอมรับว่า L1+L2 พอ | สอดคล้องกับ final gate (L3-only 0.7%) |

2. **campaign attack ที่ออกแบบเอง** (§5 ข้อ 2) — มีวิธีทำให้ไม่ circular ไหม ในเมื่อไม่มี
   ชุดข้อมูลโจมตีจริงให้ใช้?

3. **recall 61.9% เพียงพอสำหรับระบบ RBA ระดับมหาวิทยาลัยหรือไม่** เมื่อ challenge FPR = 1.5%
   และ L3 ไม่ enforce?

4. **การรายงานผล** — ควรรายงานตัวเลขชุดพัฒนา (95.8%) คู่กับ final gate (61.9%) อย่างไร
   ใน thesis ให้ไม่ทำให้ผู้อ่านเข้าใจผิด?

5. **วิธี freeze/ตรวจสอบหลักฐาน** ที่ใช้ (§4) เพียงพอตามมาตรฐานงานวิจัยหรือไม่?

---

## 7. สารบัญหลักฐานทั้งหมด

### 7.1 ผลการทดลอง (`hub/backend/tests/reports/`)

| กลุ่ม | ไฟล์ |
|---|---|
| ชุดข้อมูล + baseline | `profiles_v2_*` · `rba_4layer_v2_*` · `learning_curve_v2_*` |
| ตรวจ artifact / เลือกเวอร์ชัน | `v7_generator_fix_*` · `v2_to_v7_version_sweep_*` · `model_version_decision_*` |
| เปรียบเทียบ neural network | `v8_verification_*` · `ablation_v8_vs_rule_*` |
| ปรับปรุง L2 | `tier1_rarity_behavior_*` · `tier2_cadence_signature_*` |
| กู้ L3 | `l3_ownership_nocampaign_*` · `l3_campaign_*` · `l3_sequence_channel_*` · `l3_raw_vs_effective_*` |
| รวม 4 ชั้น + SHAP | `exp_4layer_full_*` · `exp_l3_config_g_*` |
| ตรวจ overfitting | `exp_lc_v3_*` · `exp_thr_and_l2_fix_*` · `exp_l3_window_*` · `exp_campaign_level_*` |
| สถิติ/CI | `exp_final_synthetic_*` |
| **ด่านสุดท้าย** | **`exp_final_gate_2026-08-26.md`** |
| นำเข้า production | `l3_service_split_2026-08-29.md` |
| ความทนทานปฏิบัติการ | `l3_stability_2026-08-29.md` |
| **traffic จริง** | **`l3_shadow_replay_2026-08-29.md`** |

### 7.2 โค้ดที่ผลิตตัวเลข

| ประเภท | ที่อยู่ |
|---|---|
| Generator + feature | `ml-service/scripts/gen_v3.py` · `build_profiles_v2.py` · `features_v2.py` |
| Harness การทดลอง | `ml-service/scripts/exp_*.py` · `lc_*.py` |
| โค้ด production ที่ถูกวัด | `hub/backend/app/security/{rule_engine,behavior_profiling,l3_sequence,risk_aggregator,risk_engine}.py` · `ml-service/app/sequence.py` |
| เครื่องมือ replay | `hub/backend/scripts/l3_shadow_replay.py` |
| เครื่องมือ freeze/ตรวจสอบ | `scripts/build_evidence_manifest.py` |

### 7.3 ชุดทดสอบ

```bash
# ชุดทดลอง RBA (74 tests)
docker compose exec hub-backend pytest \
  tests/test_rule_engine_v2_signals.py tests/test_behavior_*.py \
  tests/test_tier2_catches_evasive.py tests/test_l3_*.py -q

# ความทนทานปฏิบัติการ (23 tests, ใช้ Redis + ml-service จริง)
docker compose exec hub-backend pytest tests/test_l3_stability.py -v -s

# restart resilience (รันบน host)
py hub/backend/tests/manual_l3_restart_driver.py

# full system
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
```

ผลล่าสุด: **795 passed / 53 skipped / 0 failed**

### 7.4 ข้อมูลที่ไม่ได้ส่งไปด้วย (โดยตั้งใจ)

ข้อมูลที่ anchor จากผู้ใช้จริงและอนุพันธ์ทั้งหมด **ไม่อยู่ใน git** ตามข้อกำหนด PII
(รายละเอียดใน `RBA_EVIDENCE_MANIFEST_2026-08-29.md` §6) — ผู้ตรวจที่ต้องการทำซ้ำ
ต้องใช้ anchor ของตนเอง แล้วรัน harness โดยส่ง `--users` และ `--seeds`

---

## 8. สถานะ ณ วันส่งตรวจ

| คำถาม | คำตอบ |
|---|---|
| L1+L2+L4 พร้อมใช้งานจริงไหม | ✅ ใช้งานอยู่แล้ว |
| L3 พร้อม shadow ไหม | ✅ เปิดใช้แล้ว 29 ส.ค. 2026 · เก็บ contract ทุก login |
| L3 พร้อม enforcement ไหม | ❌ **ไม่** — ไม่ผ่านเกณฑ์ unique ≥3% และติดข้อจำกัด §3.5 |
| ผลการทดลอง freeze แล้วไหม | ✅ tag `rba-freeze-2026-08-29` · ตรวจซ้ำได้ด้วย `--verify` |
| ยังปรับโมเดลอยู่ไหม | ❌ **หยุดแล้ว** — การเปลี่ยนใดๆ ต้องเป็นการทดลองรอบใหม่ |
