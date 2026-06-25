# รายงาน: Proper Train/Test (apples-to-apples) — Semi-Synthetic vs Real

- **วันที่:** 2026-06-15
- **ต่อจาก:** [`real_only_vs_synthetic_2026-06-15.md`](real_only_vs_synthetic_2026-06-15.md)
- **คำถาม:** ใช้โปรโตคอลเดียวกัน (one-class, group-by-user, 10 splits) แยกผลของ "feature set" ออกจาก "ความสมจริงของ attack"
- **Script:** `ml-service/scripts/proper_split_semisynth.py`

---

## 1. ผล (proper protocol เดียวกันทั้งหมด)

| Dataset / Feature | Model | ROC-AUC | PR-AUC | F1@1% | Recall |
|---|---|---|---|---|---|
| **semi-synth @ 12** | IsolationForest | 0.894 ± 0.002 | 0.751 ± 0.007 | 0.707 | 0.676 |
| | OneClassSVM | 0.912 ± 0.001 | 0.797 ± 0.002 | 0.749 | 0.762 |
| | LOF | 0.894 ± 0.003 | 0.801 ± 0.005 | 0.754 | 0.775 |
| **semi-synth @ 23** | IsolationForest | 0.890 ± 0.004 | 0.745 ± 0.006 | 0.729 | 0.693 |
| | OneClassSVM | 0.936 ± 0.002 | 0.844 ± 0.001 | 0.764 | 0.816 |
| | LOF | 0.927 ± 0.005 | 0.847 ± 0.004 | 0.758 | 0.814 |
| **real-only @ 12** | IsolationForest | 0.890 ± 0.041 | 0.427 ± 0.166 | 0.325 | 0.265 |
| | OneClassSVM | 0.839 ± 0.028 | 0.414 ± 0.164 | 0.486 | 0.500 |

---

## 2. การแยกตัวแปร (variable isolation)

### (ก) ผลของ "ความสมจริงของ attack" — semi@12 vs real@12 (feature เดียวกัน, โปรโตคอลเดียวกัน)
| | semi@12 (synthetic) | real@12 (ATO จริง) |
|---|---|---|
| IForest ROC-AUC | 0.894 ± 0.002 | 0.890 ± 0.041 |
| IForest PR-AUC | 0.751 ± 0.007 | 0.427 ± 0.166 |

- **ROC-AUC แทบเท่ากัน (0.894 vs 0.890)** — ความสามารถ "จัดอันดับ" attack เหนือ normal ใกล้เคียงกัน
- **PR-AUC ต่างชัด (0.751 vs 0.427) + variance ต่างมหาศาล (±0.007 vs ±0.166)** —
  synthetic attack **แยกง่ายกว่าและสม่ำเสมอกว่ามาก**; ATO จริง noisy + ผันผวนสูง
- **สรุป:** การประเมินเกินจริงของ synthetic ไม่ได้อยู่ที่ "ranking" (ROC) แต่อยู่ที่ "precision ที่จุดบนสุด"
  (PR-AUC) และ "ความนิ่งของผล" — ตัวเลข synthetic ดูดีและนิ่งหลอกตา

### (ข) ผลของ "feature set" — semi@12 vs semi@23 (attack เดียวกัน)
| Model | PR-AUC @12 | PR-AUC @23 | Δ |
|---|---|---|---|
| IsolationForest | 0.751 | 0.745 | ≈ 0 (แทบไม่ขยับ) |
| OneClassSVM | 0.797 | 0.844 | **+0.047** |
| LOF | 0.801 | 0.847 | **+0.046** |

- การเพิ่ม 11 feature (Tier-1 + Passkey) **ช่วย OCSVM/LOF (kernel/distance) แต่ IForest แทบไม่ขยับ**
- ตีความ: tree-based อิ่มตัวกับสัญญาณ behavioral แล้ว; kernel/distance ใช้มิติเพิ่มได้มากกว่า

---

## 3. ข้อสรุปสำหรับเล่ม
1. **ROC-AUC ทนต่อชนิด attack (IForest ~0.89 ทุกกรณี, variance ต่ำ)** → IForest = ตัวเลือก production
   ที่เสถียรสุด (ยืนยันการตัดสินใจในบท 8)
2. **synthetic ประเมิน PR-AUC เกินจริง ~1.8 เท่า แม้ใช้โปรโตคอลถูกต้องและ feature เดียวกัน** —
   ห้าม quote ตัวเลข synthetic เป็นค่า production
3. **feature expansion ให้ผลต่างกันตามชนิดโมเดล** — OCSVM/LOF ได้ประโยชน์, IForest อิ่มตัว
4. ทุกข้ออยู่บนโปรโตคอลเดียวกัน → เป็นการเปรียบเทียบที่ยุติธรรม (apples-to-apples)

---

## 4. รันซ้ำ
```bash
py ml-service/scripts/proper_split_semisynth.py
```
> one-class, group-by-user, 10 splits, threshold จาก train (flag 1%)
