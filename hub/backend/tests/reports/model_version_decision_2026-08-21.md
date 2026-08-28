# ควรพัฒนาต่อจากเวอร์ชันไหน — ข้อเสนอพร้อมหลักฐาน

**วันที่:** 21 ส.ค. 2026
**คำถาม:** ไม่ควรใช้ Random Forest แล้วควรต่อยอดจากเวอร์ชันไหน

---

## คำตอบ: **ต่อยอดจาก V3**

และเก็บแนวคิด sequence ของ **V5** ไว้เป็นทิศทางวิจัย — แต่ยังวัดผลไม่ได้จนกว่าจะแก้ข้อมูลจำลอง

---

## 1. ทำไม "ไม่ใช้ Random Forest" ถึงถูก — แต่เหตุผลที่ถูกต้องคนละอย่าง

**เหตุผลที่มักเข้าใจกัน:** RF overfit / เรียนทางลัด
**เหตุผลที่แท้จริงและหนักกว่า:** **supervised ต้องมี label attack — ซึ่ง production ไม่มี**

ระบบจริงตอนนี้:
```
scripts/export_labeled_data.py:
  "⚠️ ยังไม่มี attack label จริง — loop จะเพิ่มแค่ real normal (ช่วยลด FPR)"
```

- `MLFeedback` มีไว้ให้ admin กด label แต่ยังแทบไม่มีข้อมูล
- attack จริงเกิดน้อยมากโดยธรรมชาติ และกว่าจะรู้ว่าเป็น attack ก็ผ่านไปแล้ว
- ถ้าเทรน supervised ต้องใช้ attack สังเคราะห์เป็น label → **โมเดลเรียน generator ไม่ได้เรียน attack**

**นี่คือสิ่งที่เกิดขึ้นจริง** — V6 ได้ ROC-AUC 0.996 บนข้อมูลตัวเอง แต่ 0.641 บนชุดข้อมูลจาก generator อื่น

> Random Forest ไม่ใช่อัลกอริทึมที่แย่ — แต่ **supervised เป็นรูปแบบปัญหาที่ผิด**สำหรับงานนี้
> production มีแต่ normal เยอะ ๆ กับ attack แทบไม่มี → เป็นโจทย์ anomaly detection ไม่ใช่ classification

---

## 2. หลักฐานว่า V3 คือตัวที่ควรต่อยอด

### 2.1 ผ่าน gate ครบ 9/9 — เวอร์ชันเดียวที่ทำได้

| ตัวชี้วัด (60 runs) | ค่า | เกณฑ์ | ผล |
|---|---|---|---|
| Challenge FPR | **0.13%** | ≤0.3% | ✅ |
| Warn FPR | 0.48% | ≤1% | ✅ |
| Known-attack policy success | **99.17%** | ≥90% | ✅ |
| **Evasive attack recall** | **96.62%** | ≥70% | ✅ |
| Cold-start policy success | 92.63% | ≥90% | ✅ |
| Lateral policy success | **100%** | ≥90% | ✅ |
| NAT recall gap | 0.17% | ≤2% | ✅ |
| trusted-history allowlist | — | — | ✅ |
| admin always MFA | — | — | ✅ |

`ready_for_production_shadow: True` — **เวอร์ชันเดียวที่ได้ธงนี้จากการวัดจริง**

### 2.2 ตัวเลขไม่ขยับเลยหลังแก้ generator ← หลักฐานที่สำคัญที่สุด

| metric | generator เดิม | หลังแก้ | ต่าง |
|---|---|---|---|
| evasive_challenge_recall | 1.0000 | 1.0000 | **0** |
| known_policy_success | 1.0000 | 1.0000 | **0** |
| lateral_policy_success | 1.0000 | 1.0000 | **0** |
| challenge_fpr | 0.0015 | 0.0014 | −0.0001 |

**V3 ไม่ได้พึ่ง artifact เลย** — ต่างจาก V6 ที่ตก 5.2 จุดทันทีที่แก้ bug เดียว

### 2.3 ไม่มี supervised classifier

ตรวจโค้ดแล้ว `run_production_readiness_v3.py` **ไม่มี** `RandomForestClassifier` /
`LogisticRegression` เลย — ใช้ rule + behavior + one-class IForest ตามสถาปัตยกรรม 4 ชั้น

### 2.4 Feature contract สะอาด — overlap = 0

```json
rule_features    : 11 ตัว
behavior_features:  9 ตัว
ml_features      : 17 ตัว
overlap          :  0     <- ไม่มีฟีเจอร์ไหนถูกให้คะแนนซ้ำ
```

### 2.5 ตรงกับผลที่ผมวัดได้อิสระบนชุด V2

สถาปัตยกรรมเดียวกัน (rule + policy floor + signal ownership) บนชุดข้อมูล 12 โปรไฟล์จริง:

| | Recall | Challenge FPR | PR-AUC |
|---|---|---|---|
| contract_v2_plus (rule-based) | **90.0%** | **2.11%** | **0.980** |
| V7 sequence (supervised) | 0–58% | 0.5–38% | 0.666 |

**สองการทดลองที่แยกกันโดยสิ้นเชิง ชี้ไปทางเดียวกัน**

### 2.6 อธิบายได้ — สำคัญกับวิทยานิพนธ์และกับ admin

ทุกคะแนนย้อนกลับไปหาเหตุผลได้ (`is_new_device (+0.30)`, `failed_logins_24h >= 3 (+0.20)`)
ไม่ใช่ probability ลอย ๆ จากป่าไม้ 260 ต้น — ตรงกับที่ระบบมี SHAP + `risk_reasons` อยู่แล้ว

---

## 3. จุดอ่อนของ V3 ที่ต้องยอมรับ

**V3 มองไม่เห็นแคมเปญหลายระยะ** — จากผลที่ทีมรายงานเอง:

| | V3 (event-based) | V4 (sequence prototype) |
|---|---|---|
| Event recall (แคมเปญ 4 phase) | **0.35%** | 7.97% |
| ตรวจพบอย่างน้อย 1 phase | 1.20% | 19.78% |
| Challenge FPR | **0.127%** | 5.41% |

V3 เก่งกับ attack ที่เห็นได้ใน **event เดียว** · แต่แคมเปญที่ค่อย ๆ คืบทีละ phase มันจับไม่ได้

**นี่คือช่องว่างจริงที่ควรวิจัยต่อ — ไม่ใช่ข้ออ้างให้กลับไปใช้ supervised**

---

## 4. แผนที่เสนอ

### ระยะสั้น — เอา V3 เป็นฐาน production

| # | งาน | เหตุผล |
|---|---|---|
| 1 | นำแนวคิด V3 ไปใช้กับ `rule_engine.py` จริง | ตอนนี้ production มี 15/23 ฟีเจอร์ที่ไม่มีชั้นไหนให้คะแนน → recall แค่ 25% |
| 2 | เพิ่ม policy floor ใน `risk_aggregator.py` | ทำให้ policy success 33% → 91% (วัดแล้วบนชุด V2) |
| 3 | ปิดกฎ `multi_account_ip` เมื่ออยู่หลัง NAT | ยิงใส่ normal 26% โดยไม่มีข้อมูล |
| 4 | ตัด `scope_sensitivity` ออกจากหลักฐาน | เป็นค่าคงที่ต่อ subsystem ไม่ใช่ความผิดปกติ |

> ข้อ 1–4 **ไม่ต้อง retrain และไม่แตะ feature contract** — แก้เฉพาะกฎกับการรวมคะแนน

### ระยะกลาง — แก้ข้อมูลจำลองก่อน แล้วค่อยวัด sequence

| # | งาน |
|---|---|
| 5 | ใช้แพตช์ `success_10m` |
| 6 | ทำ "normal" ให้แปรผันเท่าข้อมูลจริง (duration σ, browser version, ล็อกอินถี่) |
| 7 | นิยาม attack ใหม่ — อย่าใช้ ramp คงที่ต่อ phase |
| 8 | เพิ่ม support check + test กัน generator artifact |

**ต้องทำ 5–8 ก่อน ไม่งั้นวัดอะไรก็เชื่อไม่ได้**

### ระยะยาว — sequence layer แบบ one-class (ทิศทาง V5)

| # | งาน | เหตุผล |
|---|---|---|
| 9 | กลับไปที่ **V5 one-class** ไม่ใช่ V6 supervised | one-class เทรนจาก normal อย่างเดียว → **เรียนทางลัดจาก label ไม่ได้โดยโครงสร้าง** |
| 10 | วัดผลบนชุดข้อมูลนอกเสมอ ไม่ใช่แค่ test split ตัวเอง | gate ปัจจุบันผ่านได้แม้ generalize ไม่ได้ |
| 11 | ใช้ sequence layer เป็น **ชั้นเสริม** ของ V3 ไม่ใช่ตัวแทน | V3 คุม FPR ได้ · sequence เติมช่องแคมเปญหลายระยะ |

**V5 ได้ recall แค่ 8.65% ซึ่งต่ำ — แต่เป็นตัวเลขที่ซื่อสัตย์** เทียบกับ V6 ที่ได้ 90.9% จากทางลัด
ตัวเลขต่ำที่เชื่อถือได้ ดีกว่าตัวเลขสูงที่วัดความง่ายของข้อมูลตัวเอง

---

## 5. สรุปเป็นตาราง

| เวอร์ชัน | ต่อยอดไหม | เหตุผล |
|---|---|---|
| V2 | ⬅ ฐานของ V3 | contract + diverse normal |
| **V3** | ✅ **ใช่ — เอาเป็นฐาน production** | ผ่าน gate 9/9 · FPR 0.13% · ไม่พึ่ง artifact · อธิบายได้ |
| V4 | 📋 เก็บไว้เป็น "ชุดทดสอบ" | แคมเปญ 4 phase มีประโยชน์ในฐานะ benchmark |
| **V5** | 🔬 **ใช่ — เป็นทิศทางวิจัย** | one-class เรียนทางลัดไม่ได้ · ต้องแก้ข้อมูลก่อนถึงจะวัดได้ |
| V6 | ❌ ไม่ | supervised ใช้ไม่ได้ใน production (ไม่มี label) + เรียน artifact |
| V7 | ❌ ไม่ (แต่เก็บโค้ด) | เป็นแค่ packaging ของ V6 · **portable bundle + runtime contract ดีมาก เอาไปใช้กับโมเดลอื่นได้** |

> V7 มีของดีที่ควรเก็บ: portable forest export (ไม่ผูก sklearn version), runtime ที่ปฏิเสธ
> enforcement-enabled bundle, manifest + sha256 — **ยกไปใช้กับโมเดลที่เลือกได้เลย**
