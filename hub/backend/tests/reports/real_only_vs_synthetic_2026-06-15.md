# รายงาน: Real-Only Benchmark (RBA จริง 100%) เทียบกับ Semi-Synthetic

- **วันที่:** 2026-06-15
- **ต่อจาก:** [`benchmark_rba_model_comparison_2026-06-15.md`](benchmark_rba_model_comparison_2026-06-15.md)
- **คำถาม:** ถ้าใช้ feature ที่ derive จาก RBA จริงล้วน + ATO จริง โมเดลทำได้แค่ไหน?
- **Scripts:** `ml-service/scripts/build_real_only.py`, `real_only_eval.py`

---

## 1. Dataset (real-only)

| รายการ | ค่า |
|---|---|
| total rows | 10,141 |
| normal (label 0) | 10,000 — sample จาก 97,466 login จริง (history จริงต่อ user) |
| attack (label 1) | **141 — ATO จริง "ทั้งหมด" ในชุด RBA** |
| features | **12** (Experiment A 13 ตัว − active_session_count ที่ RBA ไม่มี) |
| home country | NO (Norway, modal) |

**วิธี:** 2-pass — หา ATO users ทั้งหมด (138 คน) + สุ่ม 3,997 normal users → ดึง login history
จริง → คำนวณ feature แต่ละ login จากประวัติก่อนหน้า (online RBA, O(n) two-pointer)
**ทุก feature เป็นค่าจริง ไม่มี synthetic** · `failed_logins_24h` = Login Successful=False จริง

---

## 2. ผล (in-sample, flag @ 1.39%)

| Model | Prec | Recall | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|
| IsolationForest | 0.057 | 0.057 | 0.057 | **0.872** | 0.079 |
| OneClassSVM | 0.156 | 0.156 | 0.156 | 0.764 | **0.093** |
| LocalOutlierFactor | 0.071 | 0.071 | 0.071 | 0.451 | 0.021 |

Confusion @ 1.39%: IForest จับได้ **8/141**, OCSVM **22/141**, LOF **10/141**

---

## 3. เทียบ Semi-Synthetic vs Real-Only (จุดสำคัญที่สุด)

| Metric | Exp A semi-synth (attack สังเคราะห์) | **Real-only (ATO จริง)** | ต่างกัน |
|---|---|---|---|
| IForest ROC-AUC | 0.928 | 0.872 | ใกล้เคียง |
| IForest PR-AUC | 0.726 | **0.079** | **~9× ต่ำลง** |
| OCSVM PR-AUC | 0.723 | **0.093** | **~8× ต่ำลง** |
| TP @ flag 1.39% (IForest) | ~99/140 | **8/141** | ตกฮวบ |

### ตีความ (ซื่อสัตย์ — ใส่ในเล่ม)
1. **Semi-synthetic ประเมินสูงเกินจริง** — attack ที่สังเคราะห์ "แยกง่ายเกินไป" PR-AUC พุ่ง ~9 เท่า
   เทียบกับ ATO จริง → ตัวเลขสวยในชุด synthetic **ไม่ใช่** ตัวแทน production
2. **ROC-AUC ยังพอใช้ (0.87) แต่ PR-AUC พังที่ 0.079** — บน prevalence 1.39% การ rank พอมีสัญญาณ
   แต่ precision ที่จุดทำงานจริงต่ำมาก → **PR-AUC คือ metric ที่ซื่อสัตย์** (ยืนยัน §11 ที่เลือก PR-AUC เป็นหลัก)
3. **ATO จริงตรวจยากด้วย 12 behavioral feature ลำพัง** — ATO จริงใน RBA มักมาจาก session ที่
   "ดูสมเหตุผล"; normal จำนวนมากก็เป็น cold-start/เครื่องใหม่ → สัญญาณกลบกัน
   (สอดคล้องผล Wiefling 2022 ที่ว่า RBA ตรวจ ATO ยากและมี FP สูง)
4. **เหตุผลที่ต้องเพิ่ม feature (passkey/session)** ได้รับการสนับสนุน — 12 feature ไม่พอ;
   แต่ feature ใหม่ทดสอบบนข้อมูลจริงไม่ได้ (ยังไม่มี) → **คือ frontier ของงานต่อไป**

---

## 4. สรุปสำหรับเล่ม
> "เมื่อประเมินบนข้อมูลจริงล้วน (RBA, ATO จริง 141 เคส) ด้วย 12 behavioral feature โมเดล
> unsupervised ทำ ROC-AUC ได้ ~0.87 (IForest) แต่ PR-AUC เพียง ~0.08 — ต่ำกว่าผลบน
> semi-synthetic ~9 เท่า สะท้อนว่า (ก) benchmark สังเคราะห์ประเมินสูงเกินจริง (ข) การตรวจ
> ATO จริงยากและต้องการ feature ที่รวยกว่า behavioral ลำพัง ซึ่งเป็นแรงจูงใจของ 4-layer RBA +
> passkey/session layer และ (ค) PR-AUC เป็นตัวชี้วัดที่เหมาะกับงาน imbalanced จริง"

**ข้อควรระวัง:** อย่ารายงานเฉพาะตัวเลขสวยจาก semi-synthetic — ต้องคู่กับ real-only เสมอ

---

## 4.5 Proper train/test protocol (one-class, group-by-user) — `real_only_split_eval.py`

โปรโตคอลที่ถูกต้องสำหรับ generalization: เทรน **normal-only** ของ train users (70%),
ทดสอบบน normal ของ test users + **ATO จริงทั้งหมด**; threshold ตั้งจาก train; ทำซ้ำ 10 splits

| Model | ROC-AUC | PR-AUC | F1@1% | Precision | Recall |
|---|---|---|---|---|---|
| IsolationForest | 0.890 ± 0.041 | 0.427 ± 0.166 | 0.325 | 0.740 | 0.265 |
| OneClassSVM | 0.839 ± 0.028 | 0.414 ± 0.164 | 0.486 | 0.541 | 0.500 |
| LocalOutlierFactor | 0.489 ± 0.085 | 0.103 ± 0.067 | 0.074 | 0.226 | 0.050 |

### ข้อค้นพบสำคัญ
1. **in-sample ให้ผลแย่เกินจริงสำหรับ one-class** — fit บนข้อมูลที่ปน attack 1.4% ทำให้แบบจำลอง
   normal เพี้ยน → PR-AUC ต่ำผิด (0.079). โปรโตคอลถูกต้อง (เทรน normal-only สะอาด) ให้ **0.427**
   → **in-sample ไม่ได้ optimistic เสมอ**; สำหรับ one-class การ contaminate training ทำให้แย่ลง
2. **ROC-AUC เทียบได้ (prevalence-invariant): 0.872 → 0.890** — ใกล้เคียง ยืนยันสัญญาณ ranking เสถียร
   (PR-AUC สูงขึ้นส่วนหนึ่งเพราะ test prevalence ~4.5% > 1.39% → **อย่าเทียบ PR-AUC ข้าม prevalence**)
3. **บนข้อมูลจริง + โปรโตคอลถูกต้อง: IForest ≈ OCSVM** (0.427 vs 0.414, std ทับกัน) — ต่างจาก
   semi-synthetic ที่ OCSVM ชนะขาด → **สนับสนุนการเลือก IsolationForest** (เสมอด้าน detection
   แต่ชนะด้าน explainability/scale)
4. **variance สูง (±0.166)** — เพราะ ATO จริงมีแค่ 141 เคส → ข้อมูล attack จริงไม่พอสำหรับข้อสรุปเด็ดขาด
5. recall @ flag 1%: IForest 27% / OCSVM 50% — ยังต่ำ → ATO จริงตรวจยาก ต้องการ feature รวยกว่า behavioral

> **สำหรับเล่ม:** ใช้ proper protocol นี้เป็นตัวเลขหลักของ "ผลบนข้อมูลจริง" (ไม่ใช่ in-sample)
> และรายงาน ROC-AUC คู่ PR-AUC พร้อม std เสมอ

## 5. รูป (figures/REAL/)
confusion_matrices · roc_curves · pr_curves · shap_feature_importance · shap_summary_beeswarm

## 6. รันซ้ำ
```bash
py ml-service/scripts/build_real_only.py   # 2-pass, ได้ real_only_rba.csv
py ml-service/scripts/real_only_eval.py    # metrics + figures/REAL/
```
