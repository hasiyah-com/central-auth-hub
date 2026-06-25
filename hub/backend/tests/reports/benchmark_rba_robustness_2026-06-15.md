# รายงาน: Robustness Study + การตัดสินใจเลือกโมเดล (Benchmark RBA)

- **วันที่:** 2026-06-15
- **ต่อจาก:** [`benchmark_rba_model_comparison_2026-06-15.md`](benchmark_rba_model_comparison_2026-06-15.md), [`benchmark_rba_shap_2026-06-15.md`](benchmark_rba_shap_2026-06-15.md)
- **คำถามที่ตอบ:** ความต่างของโมเดลเป็นจริงหรือ noise? + ตามบริบทจริงควรเปลี่ยนโมเดลไหม?
- **Script:** `ml-service/scripts/robustness_eval.py` — 20 seeds × subsample 80% (stratified), Exp C (23 feat)

---

## 1. Multi-seed (mean ± std [95% CI])

| Model | PR-AUC | ROC-AUC |
|---|---|---|
| **OneClassSVM** | **0.809 ± 0.017 [0.782, 0.844]** | **0.965 [0.954, 0.970]** |
| IsolationForest | 0.747 ± 0.018 [0.709, 0.780] | 0.925 [0.908, 0.936] |
| LocalOutlierFactor | 0.575 ± 0.018 [0.551, 0.606] | 0.779 [0.762, 0.801] |

**95% CI ของ OCSVM กับ IForest ไม่ทับกัน** (0.782 > 0.780)

## 2. Wilcoxon signed-rank (PR-AUC, OCSVM vs IForest)
- mean diff = **+0.063**
- **W = 0.0, p < 0.0001** → OCSVM ชนะ **ทั้ง 20/20 seeds**
- สรุป: **ความต่างมีนัยสำคัญทางสถิติ จริง ไม่ใช่ noise** (หักล้างสมมุติฐาน "อาจอยู่ในขอบเขต noise")

## 3. Operating-point sweep (Precision / Recall / F1 @ flag-rate)

| flag-rate | IForest (P/R/F1) | OCSVM (P/R/F1) |
|---|---|---|
| 0.50% | 1.000 / 0.364 / **0.534** | 1.000 / 0.364 / **0.534** |
| 1.00% | 0.951 / 0.693 / 0.802 | 0.971 / 0.707 / 0.818 |
| 1.38% | 0.707 / 0.707 / 0.707 | 0.750 / 0.750 / 0.750 |
| 2.00% | 0.493 / 0.714 / 0.583 | 0.581 / 0.843 / 0.688 |
| 5.00% | 0.207 / 0.750 / 0.325 | 0.250 / 0.907 / 0.393 |

**ที่จุดทำงานแคบ (≤1%) สองตัวเกือบเท่ากัน** — OCSVM ทิ้งห่างตอน flag เยอะ (recall สูงกว่า)

---

## 4. การตัดสินใจ — ควรเปลี่ยนโมเดลไหม? (อ้างอิงบริบทจริง)

**คำตอบ: ไม่เปลี่ยน production scorer เป็น OCSVM แบบรื้อทั้งหมด — แต่ยอมรับตรงๆ ว่า OCSVM
มี detection quality เหนือกว่า และใช้กลยุทธ์ hybrid แทน**

เหตุผลที่ detection-edge จริง **ยังไม่พอ**ให้รื้อสถาปัตยกรรม:

| ปัจจัย | น้ำหนัก | ฝั่งที่ได้เปรียบ |
|---|---|---|
| Detection (PR-AUC/ROC-AUC ภาพรวม) | – | **OCSVM** (significant, +0.063) |
| Detection @ จุดทำงานจริง ≤1% | สูง (นี่คือ regime ที่ deploy) | **เกือบเท่ากัน** |
| Explainability (SHAP รายเคสใน admin/audit) | **สูงมาก** (auth ต้อง audit ได้) | **IForest** (TreeExplainer exact+เร็ว) |
| Latency / scale (score ทุก login, ข้อมูลโตเรื่อยๆ) | สูง | **IForest** (เชิงเส้น) — OCSVM O(n²–n³) |
| เสถียรต่อ drift / hyperparameter | กลาง | **IForest** (OCSVM ไวต่อ nu/gamma) |
| External validity ของผล | – | **เสมอ** — benchmark กึ่ง-synthetic, significance = "ต่างจริงบนชุดนี้" ≠ generalize สู่ traffic จริง |

### ข้อสรุปที่ตอบกรรมการได้ (ซื่อสัตย์)
> "OneClassSVM ให้ detection quality สูงสุดอย่างมีนัยสำคัญ (PR-AUC 0.809 vs 0.747, p<0.0001)
> พิสูจน์ว่า feature engineering + kernel method มีค่า; **แต่ที่จุดทำงานจริง (flag ≤1%) ทั้งสอง
> โมเดลเกือบเท่ากัน** และ IsolationForest ชนะด้าน explainability (SHAP), latency, และ scalability
> ซึ่งเป็น hard requirement ของ identity hub ที่ต้อง audit ได้และ score แบบ real-time
> → เลือก **IForest เป็น primary online scorer** + ใช้ **OCSVM เป็น secondary/shadow signal**
> (หรือ ensemble vote) เพื่อดึง recall ที่ OCSVM เก่งกว่ามาใช้ในเคสที่ต้องการความไว"

---

## 5. รอบหน้า: rigor ที่ "สำคัญกว่า" multi-seed (สำหรับเล่มจริง)

⚠️ **ข้อจำกัดเชิงระเบียบวิธีที่ใหญ่ที่สุดตอนนี้:** evaluate ปัจจุบันเป็น **in-sample** (fit + score
บนข้อมูลชุดเดียวกัน). multi-seed/contamination ช่วยเรื่องความเสถียร แต่**ไม่แก้** in-sample bias.

ลำดับความสำคัญที่ควรทำก่อนอ้างในเล่ม:
1. **Train/test split ที่ถูกต้อง** (สำคัญสุด): fit บน normal-only (train) → evaluate บน held-out
   ที่มี attack — วัด generalization จริง ไม่ใช่ memorization
2. **Validation บนข้อมูลจริง**: ทดสอบบน real login slice (RBA จริง / login_sessions ของระบบ)
   ไม่ใช่ feature ที่ synthesize — เพื่อ external validity
3. contamination/seed sweep (ทำแล้วในรายงานนี้) = รอง

---

## 6. วิธีรันซ้ำ
```bash
py ml-service/scripts/robustness_eval.py
#   1) multi-seed PR-AUC/ROC-AUC + CI   2) Wilcoxon   3) operating-point sweep
```
> ต้องมี numpy, scikit-learn, scipy. N_SEEDS=20, subsample 80% stratified.

## 7. ไฟล์ที่เกี่ยวข้อง
| ไฟล์ | หน้าที่ |
|---|---|
| `ml-service/scripts/robustness_eval.py` | multi-seed + Wilcoxon + operating-point sweep |
