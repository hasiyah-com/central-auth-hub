# รายงาน: แก้ปัญหา Single-Column Anomaly (level-2) จับไม่ได้

- **วันที่:** 2026-06-15
- **ปัญหา:** บน simulated dataset, IForest จับ attack เนียน (เปลี่ยนคอลัมน์เดียว) ได้แค่ 1/47
- **คำถาม:** ต้องเพิ่ม feature หรือเปลี่ยนเป็น SVM?
- **Scripts:** `targeted_features_eval.py` (ขั้น 1), `rule_hybrid_eval.py` (ขั้น 2)

---

## บริบท: แยก "จับไม่ได้" 2 แบบ
- 🟡 **level 1** (IP เปลี่ยนเดี่ยว, **label=0**) จับไม่ได้ = **ถูกต้อง** (เป็นปกติ — กัน false positive)
- 🟠 **level 2** (country/device เดี่ยว, **label=1**) จับได้ 1/47 = **ปัญหาจริง**

สาเหตุ: single-column change = ปกติ 22 มิติ + ผิด 1 มิติ → สัญญาณถูกกลบ (signal dilution / curse of dimensionality)

---

## ขั้นที่ 1 — เพิ่ม Targeted Features
เพิ่ม 2 feature ที่ทำให้การเปลี่ยนประเทศ "ดังขึ้น": `geo_distance_from_home_km`, `impossible_travel_kmh`

| | level-2 | country_change | new_device_night | PR-AUC | F1 |
|---|---|---|---|---|---|
| 23-feat (เดิม) | 1/47 | 0/19 | 1/28 | 0.881 | 0.830 |
| **25-feat (+geo)** | **7/47** | **7/19** | 0/28 | **0.907** | **0.860** |

**สรุป:** feature ตรงเป้าช่วยจริง (country 0→7, PR-AUC ขึ้น) **แต่ไม่ครบ** — ML ลำพังที่ threshold ต่ำยัง
dilute สัญญาณเดียว; และ geo ช่วย country ไม่ช่วย device → feature เดียวแก้ทุกแบบไม่ได้

---

## ขั้นที่ 2 — Rule Engine Layer + Hybrid
กฎ deterministic 6 ข้อ: ประเทศใหม่ / attack IP / impossible travel (>1000 km/h) / brute force (≥5 fail) /
เครื่องใหม่ตอนดึก / ประเทศไกล (>2000 km)

| วิธี | level-2 | level-3 | level-1 | Precision | Recall | F1 | FP/9373 |
|---|---|---|---|---|---|---|---|
| ML-only (IForest 25) | 7/47 | 251/253 | 0/35 | 0.860 | 0.860 | 0.860 | 42 |
| **RULE-only (6 กฎ)** | **44/47** | **253/253** | 0/35 | 0.839 | **0.990** | **0.908** | 57 |
| HYBRID (Rule OR ML) | 44/47 | 253/253 | 0/35 | 0.773 | 0.990 | 0.868 | 87 |

**สรุป:**
- Rule layer จับ single-column (level-2) ได้ **44/47** vs ML 7/47 — เพราะ single-signal เขียนเป็นกฎตรงได้
- FP ต่ำ (0.6%) + level-1 (IP เดี่ยว) ยัง 0/35 = ไม่ flag ของปกติ
- Hybrid recall 0.99 (จับเกือบครบ) แต่ precision ลดเพราะ ML เพิ่ม FP → ของจริงควรใช้ **Aggregation layer**
  ถ่วงน้ำหนัก ไม่ใช่ OR ตรงๆ

---

## คำตอบสุดท้าย
> **ไม่ใช่ "เพิ่ม feature" หรือ "เปลี่ยน SVM" อย่างใดอย่างหนึ่ง** — single-signal anomaly เป็นหน้าที่ของ
> **Rule Engine layer** (deterministic) ส่วน ML (IForest) จับ multi-signal subtle ที่กฎเขียนตายตัวไม่ได้
> → ยืนยันว่าสถาปัตยกรรม **4-Layer RBA** (Rule + Behavior + IForest + Aggregation) ของระบบถูกต้องตั้งแต่แรก;
> targeted features ช่วยเสริมชั้น ML; SVM ดีกว่า IForest เฉพาะ signal-rich แต่แลก explainability/scale

## งานต่อ (ถ้าต้องการ)
- เพิ่ม targeted feature สำหรับ device-trust/time (แก้ new_device_night)
- ใช้ Aggregation layer (weighted) แทน OR เพื่อคุม precision
- รวมผลนี้เข้า .docx
