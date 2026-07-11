# รายงาน: Simulated Dataset (Anchor ผู้ใช้จริง) — Eval + SHAP

- **วันที่:** 2026-06-15
- **แนวคิด:** ดึง "ผู้ใช้จริง + สิทธิ์จริง" จาก DB → จำลองพฤติกรรม login 1 เดือน → ฉีด anomaly แบบคุมระดับ
- **Scripts:** `simulate_month.py`, `simulate_features.py`, `simulated_eval.py`

---

## 1. Dataset
- **9,673 แถว** · attack **300 (3.1%)** · 23 features (Experiment C)
- **users: จริง 5 + clone persona 145** (ผู้ใช้จริงเป็นต้นแบบของแต่ละกลุ่ม)
- login เข้าได้เฉพาะ subsystem ที่มีสิทธิ์จริง · geo/scope อิงระบบจริง
- แบ่งระดับความผิดปกติ: 🟡 level 1 = 35 · 🟠 level 2 = 47 · 🔴 level 3 = 253

> feature history-based (is_new_country, login_count_24h ฯลฯ) คำนวณจากลำดับ login จริงต่อ user;
> scope_sensitivity อิง subsystems.scope จริง; passkey/permission สังเคราะห์คงที่ต่อคน

---

## 2. ผล in-sample (flag @ 3.1%)
| Model | Prec | Recall | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|
| **IsolationForest** | 0.830 | 0.830 | 0.830 | 0.984 | **0.881** |
| OneClassSVM | 0.494 | 0.510 | 0.502 | 0.958 | 0.486 |
| LOF | 0.073 | 0.073 | 0.073 | 0.431 | 0.032 |

## 3. 🎯 การจับตามระดับความเนียน (IForest) — จุดเด่นของ dataset นี้
| ระดับ | ลักษณะ | จับได้ |
|---|---|---|
| 🟡 1 (IP เปลี่ยนเดี่ยว, label=0) | ปกติที่ดูแปลก | **0/35** → false positive ต่ำ ✓ |
| 🟠 2 (country/device เดี่ยว, label=1) | **เนียน** | **1/47** → จับยากมาก (single-column) ✓ |
| 🔴 3 (ATO เต็มรูป) | ชัดเจน | **248/253** → จับเกือบหมด ✓ |

→ พิสูจน์ว่าโมเดลจับ ATO ชัดได้ แต่ **attack เนียน (เปลี่ยนคอลัมน์เดียว) ยังจับแทบไม่ได้** — ความท้าทายจริง

## 4. ผล proper split (one-class, group-by-user, 10 splits)
| Model | ROC-AUC | PR-AUC | Recall@1% |
|---|---|---|---|
| **OneClassSVM** | 0.984 ± 0.000 | **0.703 ± 0.011** | 1.000 |
| IsolationForest | 0.880 ± 0.013 | 0.328 ± 0.037 | 0.311 |
| LOF | 0.952 ± 0.002 | 0.299 ± 0.016 | 0.999 |

**ข้อสังเกต:** ต่างจาก real-only RBA (ที่ IForest ≈ OCSVM) — บน dataset นี้ **OCSVM/LOF เด่นกว่า**
เพราะ attack ที่ฉีดเป็น "signal-rich" (มี `is_attack_ip=1`, ต่างประเทศ, เครื่อง attacker) → เมื่อเทรน
one-class บน normal สะอาด (TH ล้วน) attack จึงอยู่ "นอกขอบเขต" ชัด → kernel/density จับง่าย
ส่วน level-2 ที่เนียน (เปลี่ยนคอลัมน์เดียว) ยังยากสำหรับทุกโมเดล

## 5. SHAP (IForest) — top features
`permission_change_age, scope_sensitivity_score, passkey_age_days, confirmed_incident_count, passkey_count`

⚠️ **caveat:** feature ที่สังเคราะห์ (permission/scope/passkey) มี variance ต่อ user สูง → ครอง importance;
feature ที่ขับ attack จริง (is_attack_ip, is_new_country) อยู่รองลงมา — ตีความระวัง

---

## 6. สรุป / ข้อจำกัด
- **ข้อดี:** anchor identity + สิทธิ์ + scope จริง; ground-truth คุมระดับได้ (level 1/2/3 + columns_changed)
- **ข้อจำกัด:** พฤติกรรม+attack ยัง "ออกแบบเอง" → attack signal-rich อาจง่ายเกินจริง (เหมือน semi-synthetic);
  level-2 เนียนคือส่วนที่สมจริงและท้าทายสุด
- เทียบ 3 ชุด: semi-synthetic (RBA) · real-only (RBA จริง) · **simulated (anchor ระบบเราเอง)** — ครบทุกมุม

## 7. รูป (figures/SIM/)
confusion_matrices · roc_curves · pr_curves · shap_feature_importance · shap_summary_beeswarm

## 8. รันซ้ำ
```bash
py ml-service/scripts/simulate_month.py     # ATTACK_TARGET=300
py ml-service/scripts/simulate_features.py  # -> 23 features
py ml-service/scripts/simulated_eval.py     # metrics + by-level + proper split + SHAP
```
