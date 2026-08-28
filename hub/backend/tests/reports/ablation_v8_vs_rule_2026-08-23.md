# Option 1 — Ablation: Rule/Behavior เดี่ยว vs + V8 MLP (โปรไฟล์ V2 คนจริง)

**วันที่:** 23 ส.ค. 2026
**คำถาม:** ML (V8 Temporal MLP) เพิ่ม recall เหนือ Rule/Behavior จริงไหม — คุ้ม complexity ไหม
**วิธี:** import โค้ด production จริง (`evaluate_rules`+`evaluate_behavior`+`aggregate`) + V8 จริง
(`neural_features`+`fit_profile_baselines`+runtime) · combine แบบ "OR" (`max(base, v8)`)
**ข้อมูล:** V2 size-5000 (12 โปรไฟล์ anchor คนจริง, ทุกคน ≥1000 event → V8 eligible)
**สคริปต์:** `ml-service/scripts/eval_ablation_v8.py`

---

## คำตอบ

> **บนโปรไฟล์ V2 (คนจริง, campus NAT) — V8 ไม่เพิ่มค่าเลย**
> - threshold เดิม: recall +3.3% แต่ FPR พุ่ง 1.7%→14.1% (8 เท่า)
> - **recalibrate บน V2 แล้ว: recall +0.0% · FPR 2.2%** ← ชี้ขาด
> → **Rule/Behavior อย่างเดียวเป็นตัวเลือกที่ดีกว่า** — V8 as-is แยก normal/attack บน V2 ไม่ออก

---

## 0. บทพิสูจน์ชี้ขาด — recalibrate แล้วยังไม่ช่วย

recalibrate V8 threshold จาก **normal-train ของ V2** (calibration set แยกจาก test, 47,940 windows)
ให้ V8 flag normal ได้ไม่เกิน 0.5%:

| | threshold เดิม (generator V8) | recalibrate บน V2 |
|---|---|---|
| challenge threshold | 0.9962 | **1.0000** |
| **V8 เพิ่ม recall** | +3.3% (แต่ FPR +12.4) | **+0.0%** |
| Challenge FPR (combined) | 14.1% | **2.2%** (ในงบ) |
| scenario ที่ V8 ช่วย | 3 ตัว (off_hours/lateral/velocity) | **0 ตัว** |

**threshold recalibrate = 1.0000** หมายความว่า เพื่อคุม FPR บน V2 ต้องตั้งสูงจน V8
**แทบไม่ยิงอะไรเลยทั้ง normal และ attack** → ปัญหาคือ **ranking (แยก normal/attack ไม่ออกบน V2)
ไม่ใช่แค่ตำแหน่ง threshold** → recalibrate กู้ไม่ได้

> +3.3% recall ที่ threshold เดิม **มาจากการ over-flag ล้วนๆ** (แลกกับ 14% FPR) —
> ไม่มี threshold ไหนที่ V8 เพิ่ม recall ได้โดย FPR อยู่ในงบ

---

## 1. ผลรวม (normal test 12,000 · attack 240)

| ตัวชี้วัด | Rule+Behavior | + V8 MLP | ต่าง |
|---|---|---|---|
| **Recall** | 82.9% | 86.2% | **+3.3** |
| **Policy success** | 82.9% | 86.7% | +3.7 |
| **Challenge FPR** | **1.7%** | **14.1%** | **+12.4** ⚠️ |
| Warn FPR | 1.7% | 21.6% | +19.9 |
| **Precision** | 49.9% | **10.9%** | **−39.0** ⚠️ |

**V8 แลก recall +3.3% ด้วย FPR +12.4% และ precision ตก 39 จุด** — ไม่คุ้มเลย
ที่ FPR 14.1% แปลว่า **1 ใน 7 ของ login ปกติจะโดน challenge** — ผู้ใช้จริงจะโดนกวนตลอด

---

## 2. V8 ช่วยตรงไหน (per-scenario)

| scenario | Rule+Beh | +V8 | V8 ช่วย |
|---|---|---|---|
| 8 scenario (device/passkey/velocity/perm/concurrent/failed/ato) | 100% | 100% | 0 |
| `login_velocity` | 79% | 83% | +4 |
| `off_hours` | 0% | 17% | +17 |
| `subsystem_lateral` | 0% | 25% | +25 |

V8 ช่วยเฉพาะ 3 scenario ที่ rule จับไม่ได้อยู่แล้ว (off_hours, lateral, velocity บางส่วน)
**แต่ช่วยได้แค่ 17–25%** ขณะที่ต้องแลกกับ FPR ทั้งระบบพุ่ง 8 เท่า

---

## 3. ทำไม FPR พุ่ง — distribution mismatch

V8 calibrate threshold (0.996) บน normal **ของ generator ตัวเอง** (0.2% เกิน)
พอเจอ normal ของ V2 (คนจริง) → **14% เกิน threshold** = V8 มอง normal V2 เป็น anomaly

→ V8's normal-model ผูกกับ distribution ของ generator ตัวเอง **ไม่ generalize ไปหา distribution อื่น**
(สอดคล้องกับที่พบก่อนหน้า: V8-on-V2 standalone ได้ FPR 12.66%)

**นี่คือปัญหา generalization ที่ไม่ขึ้นกับชนิด attack** — normal ผิดที่ก็ over-flag แล้ว

---

## 4. ⚠️ ข้อจำกัดของการทดสอบ (fairness)

V2 attack เป็น **single-event** แต่ V8 ออกแบบจับ **multi-phase campaign** (window สะสม phase ของ campaign เอง) → recall +3.3% ที่วัดได้เป็นการทดสอบ V8 บน attack ที่มันไม่ได้ optimize มา
→ recall ที่แท้จริงของ V8 อาจสูงกว่านี้ถ้าเป็น campaign

**แต่ปัญหา FPR 14% ไม่เกี่ยวกับชนิด attack** — มันมาจาก normal distribution ที่ต่างกัน
→ ต่อให้ attack เป็น campaign, V8 ก็ยัง over-flag normal V2 อยู่ดี **จนกว่าจะ recalibrate บน distribution จริง**

---

## 5. ข้อสรุป & ทางเลือก

**สำหรับ deployment นี้ (campus NAT, ผู้ใช้จริง): เก็บ Rule/Behavior พอ**
- ได้ recall 82.9% ที่ FPR แค่ 1.7% — operational จริง
- V8 as-is ทำให้แย่ลง (FPR 8 เท่า) โดยเพิ่ม recall นิดเดียว

**ถ้าจะใช้ V8 จริง ต้องทำก่อน:**

| # | งาน | เหตุผล |
|---|---|---|
| 1 | **recalibrate V8 threshold บน normal ของ deployment จริง** (production replay) | ตอนนี้ calibrate บน generator ตัวเอง → FPR พุ่งบน distribution อื่น |
| 2 | ทดสอบด้วย attack แบบ **multi-phase** (ไม่ใช่ single-event) | ให้ fair กับ design ของ V8 |
| 3 | ถ้าหลัง 1–2 แล้ว V8 ยังเพิ่ม recall โดย FPR อยู่ในงบ → ค่อยเอาเข้า | ตัดสินด้วยตัวเลขจริง |

ตรงกับที่ V8 เขียนเอง: **"ห้ามอ้าง synthetic gate เป็น production readiness · ต้อง production replay ก่อน enforce"**

---

## 6. นัยต่อสถาปัตยกรรม

- **Layer 1 Rule (Phase 1 ที่ port แล้ว) = ตัวหลักที่ใช้งานได้จริงตอนนี้** (recall 82.9% / FPR 1.7%)
- **Layer 3 ML (V8) = ยังไม่พร้อม** สำหรับ distribution นี้ — ต้อง recalibrate ก่อน
- คำตอบ "ใช้ ML จริงไหม/คุ้มไหม" = **ตอนนี้ยังไม่คุ้ม** แต่ **ไม่ได้แปลว่า ML ไร้ค่าถาวร** —
  ถ้า recalibrate บนข้อมูลจริง + ทดสอบ campaign แล้วดี ก็เอากลับมาได้

> ค่าที่ได้จาก ablation นี้: **หลักฐานเชิงตัวเลขว่าอย่าเพิ่งเอา V8 เข้า production** — ประหยัด
> การ deploy โมเดลที่จะทำ FPR พุ่ง 8 เท่าโดยไม่รู้ตัว

---

## 7. รันซ้ำ

```bash
py ml-service/scripts/build_profiles_v2.py --rows 5000 --seed 42
py ml-service/scripts/features_v2.py
cd hub/backend
SHARED_NAT=true PYTHONPATH=. python ../../ml-service/scripts/eval_ablation_v8.py \
    --v8 <path>/experiments/rba_user_learning_curve
```
