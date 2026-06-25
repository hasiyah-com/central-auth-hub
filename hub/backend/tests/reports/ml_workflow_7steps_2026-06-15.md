# กระบวนการทำงาน ML ตาม 7 ขั้นตอนมาตรฐาน
## Hybrid RBA Account-Takeover Detection — Central Auth Hub

วันที่ 2026-06-15 · จัดงานทั้งหมดที่ทำมาให้ตรงกับ ML lifecycle 7 ขั้น

---

## ขั้นที่ 1 — กำหนดเป้าหมายและปัญหา (Define Goal & Problem)

| หัวข้อ | รายละเอียด |
|---|---|
| **ปัญหา** | ตรวจจับ Account Takeover (ATO) / login ผิดปกติ ในระบบ Central Auth Hub แบบ Risk-Based Authentication |
| **ชนิดปัญหา** | **Unsupervised anomaly detection** — ตอนใช้จริงไม่มี label, attack หายากมาก (imbalanced) |
| **คำถามวิจัย** | (1) feature engineering เพิ่มการตรวจ ATO ได้ไหม (2) Passkey Trust Layer ลด False Positive ได้ไหม (3) โมเดลไหนเหมาะสุด (4) ใช้จริงใน Hub ได้ไหม |
| **ตัวชี้วัดหลัก** | **PR-AUC** (เหมาะ imbalanced) + ROC-AUC, Precision/Recall/F1 |
| **ข้อจำกัดออกแบบ** | ต้อง real-time + อธิบาย decision ได้ (audit) → explainability เป็น requirement |

---

## ขั้นที่ 2 — รวบรวมข้อมูล (Collect Data)

| แหล่ง | รายละเอียด |
|---|---|
| **RBA dataset จริง** | Wiefling 2022 — 31,269,264 logins (~9 GB), มี ground-truth (Is Account Takeover / Attack IP) |
| **Sampling** | normal 10,000 (reservoir) + ATO จริง 100–141 เคส |
| **Synthetic 40 แถว** | สร้างเอง 9 attack scenario เพราะ (ก) RBA ไม่มี feature ระบบ (passkey/session) (ข) ATO จริงน้อย+ไม่หลากหลาย |
| **2 ชุดข้อมูล** | semi-synthetic (10,140 แถว, 23 feat) + real-only (10,141 แถว, 12 feat จริงล้วน) |

> เครื่องมือ: `sample_rba_base.py`, `build_benchmark.py`, `build_real_only.py`

---

## ขั้นที่ 3 — เตรียมและทำความสะอาดข้อมูล (Prepare & Clean)

- **Filtering:** normal ต้องสะอาด (ไม่ปน attack-IP/ATO/login fail)
- **Type conversion:** `True/False` (string) → `1.0/0.0`
- **Parsing:** timestamp → datetime (2 รูปแบบ); user-agent → browser family + device type
- **จัดการ missing/รก:** `City="-"` ตัดทิ้ง, แถว field < 16 ข้าม, timestamp เสียข้าม
- **Memory hygiene (real-only):** ua → hash, cap 4,000 login/user (กัน OOM จาก attack account)
- **Cold start:** history < 5 session → personalized feature = neutral (0) ไม่ลงโทษ user ใหม่

---

## ขั้นที่ 4 — เลือกและสร้างฟีเจอร์ (Feature Selection & Engineering)

| ชุด | features | หมายเหตุ |
|---|---|---|
| Experiment A | 13 | baseline RBA (temporal/geo/device/velocity/brute/threat/session) |
| Experiment B | 19 | + Tier-1 (concurrent, active_subsystem, weekday_usage, scope, permission_change_age, confirmed_incident) |
| Experiment C | 23 | + Passkey (count, age, recently_added, last_used) |
| real-only | 12 | derive จาก RBA จริงล้วน (ตัด active_session_count ที่ RBA ไม่มี) |

- **Engineering:** is_thailand = home-country proxy, log-scale velocity, history features (online RBA)
- **Scaling:** StandardScaler (จำเป็นกับ OCSVM/LOF; IForest invariant)
- **Feature importance:** ใช้ SHAP ดูว่า feature ไหนสำคัญ + ทิศทาง (ขั้น 6)

> เครื่องมือ: `feature_extraction.py` (ระบบจริง), `build_*.py` (synthetic/real)

---

## ขั้นที่ 5 — เลือกอัลกอริทึมและฝึกสอนโมเดล (Algorithm & Training)

| โมเดล | ประเภท | setting |
|---|---|---|
| **IsolationForest** | tree-based | n_estimators=200, contamination=prevalence |
| **OneClassSVM** | kernel (RBF) | gamma=scale, nu≈prevalence |
| **LocalOutlierFactor** | density | n_neighbors=20 (novelty=True ตอน split) |

**2 โปรโตคอลฝึก:**
- **in-sample** — fit+score ชุดเดียวกัน (มาตรฐาน unsupervised)
- **proper (one-class, group-by-user)** — fit เฉพาะ normal ของ train users → test held-out + ATO; threshold จาก train; 10 splits (วัด generalization จริง)

> **Label ไม่ถูกใช้ตอน train** — ใช้เฉพาะวัดผล (ขั้น 6)
> เครื่องมือ: `evaluate_models.py`, `real_only_split_eval.py`, `proper_split_semisynth.py`

---

## ขั้นที่ 6 — ประเมินโมเดล (Evaluate)

| การประเมิน | ผลสรุป |
|---|---|
| Model comparison (semi-synth, C) | OCSVM ดีสุด PR-AUC 0.844 / ROC 0.963 |
| Ablation A→B→C | Tier-1 เพิ่ม Recall; Passkey เพิ่ม Precision |
| Robustness (20 seeds + Wilcoxon) | OCSVM > IForest บน synthetic (p<0.0001) |
| **Real-only (proper split)** | IForest ROC 0.890 / PR 0.427; **IForest ≈ OCSVM** บนข้อมูลจริง |
| Semi-synth vs Real (apples-to-apples) | synthetic ประเมินเกินจริง PR-AUC ~1.8 เท่า |
| SHAP (อธิบายผล) | passkey = trust signal (ลด FP); ตัวขับ anomaly = new_device/new_country/failed/concurrent |
| SHAP cost (IForest vs OCSVM) | Tree 3ms/row exact vs Kernel 203ms/row approx (~66×), overlap 4/10 |

> เครื่องมือ: `evaluate_models.py`, `shap_analysis.py`, `robustness_eval.py`, `real_only_eval.py`, `shap_ocsvm.py`, `generate_figures.py`

---

## ขั้นที่ 7 — นำไปใช้งานจริง (Deploy)

| ด้าน | การตัดสินใจ |
|---|---|
| **โมเดลที่เลือก** | **IsolationForest** — explainable (SHAP exact+เร็ว), เสมอ OCSVM บนข้อมูลจริง, เสถียร, scale เชิงเส้น |
| **OneClassSVM** | เก็บเป็น comparative upper-bound / secondary signal (ไม่ใช่ primary เพราะ SHAP ช้า+approx) |
| **Integration** | ML service `/v1/score` (FastAPI) → Hub 4-layer RBA (Rule + Behavior + IForest + Aggregation) |
| **Shadow Mode** | `ML_SHADOW_MODE=true` — score แต่ยังไม่ block (decision = would_mfa/would_block) จนกว่าจะมั่นใจ |
| **Retrain** | generate_data → train_model → restart hub-backend เมื่อ feature เปลี่ยน |
| **Monitoring/งานต่อไป** | validation บน traffic จริงของระบบ + เก็บ attack จริง (red-team) — ATO จริง 141 เคสยังน้อย |

---

## สรุปภาพรวม (mapping งานที่ทำ → 7 ขั้น)

```
1. เป้าหมาย    → ATO detection, unsupervised, PR-AUC, ต้อง explainable
2. รวบรวม      → RBA จริง 31M + synthetic 40 + 2 ชุด (semi/real)
3. ทำความสะอาด → filter/convert/parse/cold-start/memory-safe
4. ฟีเจอร์      → 23 (A/B/C) / 12 real, SHAP-guided
5. ฝึกโมเดล    → IForest/OCSVM/LOF × (in-sample + proper one-class)
6. ประเมิน     → metrics+ablation+robustness+real-vs-synth+SHAP
7. ใช้งานจริง  → IForest + Shadow Mode + 4-layer RBA + retrain workflow
```
