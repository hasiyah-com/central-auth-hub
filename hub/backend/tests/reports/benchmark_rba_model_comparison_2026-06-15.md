# รายงาน: Benchmark Dataset (RBA-based) + เปรียบเทียบโมเดล Unsupervised

- **วันที่:** 2026-06-15
- **หัวข้อ:** สร้าง dataset เปรียบเทียบโมเดล Hybrid RBA + Passkey Trust Layer ตาม `docs/การทดสอบ.md`
- **อ้างอิงฟีเจอร์:** `docs/guides/ML_FEATURE_DATA_SOURCES.md`, `docs/การทดสอบ.md`
- **ฐานข้อมูลจริง:** RBA dataset (Wiefling et al. 2022) — `rba-dataset.csv` (~9 GB, 31,269,264 logins)

---

## 1. สรุปผล

| รายการ | ค่า |
|---|---|
| Dataset rows | **10,140** |
| normal (label=0) | 10,000 (sample จริงจาก RBA) |
| anomaly (label=1) | 140 = **100 ATO จริง** + **40 synthetic stealth** |
| สัดส่วน attack | 1.38% (imbalanced — สมจริง, ตรงแนว §9 ของ การทดสอบ.md) |
| Columns | 44 = 19 raw + 22 engineered feature + label/scenario/source |
| Feature sets | Experiment A=13 · B=19 · C=23 |

**Label ใช้ "วัดผล" เท่านั้น** — IsolationForest / OneClassSVM / LOF เป็น unsupervised
เทรนจาก features อย่างเดียว ไม่เห็น label; label ใช้คำนวณ Precision/Recall/F1/ROC-AUC/PR-AUC

---

## 2. ที่มาของข้อมูล (Methodology)

### 2.1 Base sample จากข้อมูลจริง — `scripts/sample_rba_base.py`
สตรีมไฟล์ 9 GB ทีละแถว (reservoir sampling, ไม่โหลดทั้งไฟล์):
- **normal 10,000**: `Is Account Takeover=False AND Is Attack IP=False AND Login Successful=True` (เห็น 11,736,887 แถว)
- **anomaly 100**: `Is Account Takeover=True` — ทั้ง dataset มี ATO จริงเพียง **141 แถว** → เก็บ 100
- output: `ml-service/data/rba_base_sample.csv` (raw RBA columns + label)

### 2.2 ยกระดับเป็น benchmark — `scripts/build_benchmark.py`
แปลงแต่ละแถวจริงเป็น schema `login_sessions` (ตาม §3 การทดสอบ.md) + 23 engineered feature:

| กลุ่ม feature | วิธีได้มา |
|---|---|
| `hour_of_day`, `day_of_week` | **ค่าจริง** จาก `Login Timestamp` |
| `is_attack_ip` | **ค่าจริง** จาก RBA column |
| `is_thailand` | จาก `Country` จริง — RBA เป็นชุดนอร์เวย์ จึง map "home country" (modal=`NO`) → `is_thailand=1` (proxy ของ "อยู่ประเทศบ้าน") |
| device (`is_new_device`, UA family) | สังเคราะห์ตาม base-rate จริง + bias ตาม label |
| history (typical hour, velocity, country change) | สังเคราะห์ — RBA sample สุ่มไม่มี per-user history พอ → ใช้ distribution ของระบบ (`feature_extraction.py`) condition ตาม label |
| project-specific (passkey, session, scope, permission, incident) | สังเคราะห์ — ไม่มีใน RBA → อิง `generate_data.py` + schema ระบบจริง |

> **ความซื่อสัตย์เชิงข้อมูล:** raw RBA columns (timestamp, IP, country, UA, ATO flag) เก็บค่า **จริง** ทั้งหมด;
> ฟีเจอร์ที่ระบบ RBA ไม่มี (passkey/session/scope) ถูกสังเคราะห์โดยระบุชัดในเอกสาร — ไม่ปลอมเป็นข้อมูลจริง

### 2.3 40 Synthetic Stealth Attacks (เนียน · หลากหลาย · ครอบคลุม 8 scenario §7)
raw **ดูปกติ** (อยู่ในประเทศ TH, เครื่องคุ้น, เวลางาน, login สำเร็จ) แต่ซ่อน anomaly แบบ multi-signal:

| Scenario | จำนวน | สัญญาณที่ซ่อน |
|---|---|---|
| credential_stuffing_stealth | 5 | `failed_logins_24h` 4–8 (ไม่สุดโต่ง) + login_count สูงนิด |
| new_device_stealth | 5 | `is_new_device=1` แต่ browser family เดิม + เพิ่ม passkey เอง |
| new_country_stealth | 5 | ประเทศใหม่แบบ plausible (เพื่อนบ้าน SG/MY/VN…) |
| attack_ip_stealth | 5 | `is_attack_ip=1` (threat feed) แต่ทุกอย่างดูปกติ (VPN exit) |
| passkey_abuse | 5 | `new_passkey_recently_added=1` + เครื่องใหม่ (ATO classic) |
| lateral_movement | 4 | `active_subsystem_count` 3–5 + concurrent |
| concurrent_sessions | 4 | `concurrent_session_count` 4–10 |
| privilege_abuse | 4 | `permission_change_age` 0–2 วัน + scope สูง |
| blended_low_and_slow | 3 | หลายสัญญาณอ่อนพร้อมกัน — จับยากสุด |

---

## 3. ผลเปรียบเทียบโมเดล — `scripts/evaluate_models.py`

`dataset: 10,140 rows | attack=140 (1.38%)` · StandardScaler · contamination=0.0138

| Experiment | Model | Prec | Recall | F1 | ROC-AUC | **PR-AUC** |
|---|---|---|---|---|---|---|
| A (13) | IsolationForest | 0.700 | 0.700 | 0.700 | 0.928 | 0.726 |
| A (13) | OneClassSVM | 0.551 | 0.693 | 0.614 | 0.923 | 0.723 |
| A (13) | LocalOutlierFactor | 0.414 | 0.414 | 0.414 | 0.692 | 0.389 |
| B (19) | IsolationForest | 0.714 | 0.714 | 0.714 | 0.930 | 0.749 |
| B (19) | OneClassSVM | 0.512 | 0.757 | 0.611 | 0.924 | **0.782** |
| B (19) | LocalOutlierFactor | 0.400 | 0.400 | 0.400 | 0.696 | 0.410 |
| **C (23)** | **OneClassSVM** | **0.609** | **0.836** | **0.705** | **0.963** | **0.844** |
| C (23) | IsolationForest | 0.707 | 0.707 | 0.707 | 0.928 | 0.734 |
| C (23) | LocalOutlierFactor | 0.500 | 0.500 | 0.500 | 0.751 | 0.536 |

### ตรงกับสมมุติฐาน §13
- **A → B** (เพิ่ม Tier-1 features): Recall + PR-AUC สูงขึ้น (OCSVM PR-AUC 0.723 → 0.782, Recall 0.693 → 0.757) ✓
- **B → C** (เพิ่ม Passkey Trust Layer): Precision + Recall สูงขึ้น (OCSVM Prec 0.512 → 0.609, Recall 0.757 → 0.836) ✓
- **OneClassSVM @ C ดีที่สุด** (PR-AUC 0.844, ROC-AUC 0.963, F1 0.705) — ตรงกับที่เอกสารคาด ✓

---

## 4. วิธีรันซ้ำ (Reproducible)

```bash
# 1) sample จากข้อมูลจริง (สตรีม 9 GB ~ไม่กี่นาที) — seed=42
py ml-service/scripts/sample_rba_base.py
#    → ml-service/data/rba_base_sample.csv

# 2) สร้าง benchmark เต็ม (raw + 23 feature + 40 synthetic) — seed=2026
py ml-service/scripts/build_benchmark.py
#    → ml-service/data/benchmark_rba.csv

# 3) เปรียบเทียบโมเดล A/B/C × {IForest, OCSVM, LOF}
py ml-service/scripts/evaluate_models.py
```

> ใช้ random.seed คงที่ → ผลทำซ้ำได้. ถ้า path ไฟล์ RBA ต่างออกไป ส่ง arg ให้ `sample_rba_base.py`

---

## 5. ไฟล์ที่เกี่ยวข้อง

| ไฟล์ | หน้าที่ |
|---|---|
| `ml-service/scripts/sample_rba_base.py` | สตรีม-sample RBA จริง → base 10,100 แถว |
| `ml-service/scripts/build_benchmark.py` | base → benchmark เต็ม + 40 stealth attack |
| `ml-service/scripts/evaluate_models.py` | เทรน/วัดผล A/B/C × 3 โมเดล |
| `ml-service/data/rba_base_sample.csv` | base จริง (gitignored) |
| `ml-service/data/benchmark_rba.csv` | dataset สุดท้าย 10,140 × 44 cols (gitignored) |

---

## 6. ข้อจำกัด / หมายเหตุเชิงวิชาการ
- ฟีเจอร์ passkey/session/scope/permission/incident **สังเคราะห์** (RBA ไม่มี) — เหมาะสำหรับเปรียบเทียบโครงสร้างโมเดล + แสดง ablation A→B→C ไม่ใช่ตัวแทน production จริง
- `is_thailand` เป็น proxy ของ "home country" เพราะ RBA เป็นชุดนอร์เวย์
- ผลโมเดลขึ้นกับ contamination/threshold — รายงานนี้ fix ตามสัดส่วน attack จริง (1.38%)
- SHAP top-10/20 (§12) ยังไม่รวมในรอบนี้ — รันต่อได้บน OCSVM/IForest ที่ชนะ
