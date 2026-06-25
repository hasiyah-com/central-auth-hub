# เอกสารกระบวนการทดลองทั้งหมด (Full Methodology)
## Hybrid RBA + Passkey Trust Layer — การสร้าง Dataset และเปรียบเทียบโมเดล

- **วันที่:** 2026-06-15 · **โปรเจค:** Central Auth Hub (Senior Project)
- **ขอบเขต:** ตั้งแต่การเลือกข้อมูล → สร้างข้อมูล → ทำความสะอาด → แปลง → เทรน → วัดผล → สรุป
- เอกสารนี้เขียน **"กระบวนการ" ก่อน "ผล"** ของแต่ละขั้นตอน

---

# ส่วนที่ 1 — การเลือกข้อมูล (Data Selection)

## 1.1 ทำไมเลือก RBA dataset (Wiefling et al. 2022)
- เป็น **public dataset ของ login จริง** ที่ใหญ่ที่สุดในงาน Risk-Based Authentication (31,269,264 logins)
- มี **ground-truth label จริง**: `Is Account Takeover`, `Is Attack IP`
- มีคอลัมน์ตรงกับระบบเรา: timestamp, IP, country, user-agent, device, login success
- ใช้อ้างอิงทางวิชาการได้ (ตอบกรรมการได้ว่าใช้ข้อมูลจริงระดับ benchmark สากล)

## 1.2 ทำไมไม่ใช้ "synthetic ล้วน 500,000 แถว" (แผนเดิม)
- แผนแรกคือ gen ข้อมูล balanced 500k จาก feature ของระบบเอง — **ปัญหา:** ไม่มีฐานความจริง,
  ตัวเลขจะสะท้อนแค่ "กฎที่เราเขียน gen เอง" ไม่ใช่พฤติกรรมจริง → อ่อนเชิงวิชาการ
- จึงเปลี่ยนมายึด **RBA จริง** เป็นฐาน แล้วเสริม synthetic เฉพาะส่วนที่จำเป็น

## 1.3 ทำไมต้องมี 2 ชุด (semi-synthetic + real-only)
| ชุด | จุดประสงค์ |
|---|---|
| **รอบ 1: semi-synthetic** | ทดสอบ pipeline + ablation feature ครบ 23 ตัว (รวม passkey/session ที่ระบบใหม่ยังไม่มีข้อมูลจริง) |
| **รอบ 2: real-only** | วัดผลบนข้อมูลจริงล้วน (ATO จริง) เพื่อความซื่อสัตย์ — กันการอ้างตัวเลขเกินจริง |

---

# ส่วนที่ 2 — ข้อมูลที่สร้างเอง (Synthetic) และเหตุผล

## 2.1 ทำไมต้องสร้างเอง (synthesize)
1. **RBA ไม่มีคอลัมน์ของระบบเรา** — passkey, session concurrency, subsystem, scope, permission
   → feature 11 ตัวนี้ **ไม่มีทางได้จาก RBA** ต้องสังเคราะห์
2. **ATO จริงใน RBA มีแค่ 141 เคส และไม่หลากหลาย** — ไม่ครอบคลุม attack pattern ที่ระบบต้องรับมือ
   (lateral movement, passkey abuse, privilege abuse ฯลฯ)
3. ต้องการ attack ที่ **"เนียน" (stealth)** — raw ดูปกติแต่ซ่อน anomaly — เพื่อทดสอบขีดจำกัดโมเดล

## 2.2 ข้อมูล synthetic ที่สร้าง = 40 แถว (9 scenario)
สร้างให้ raw ดูปกติ (อยู่ในประเทศ TH, เวลางาน, login สำเร็จ) แต่ฝัง anomaly แบบ multi-signal

### ตารางครบทั้ง 40 แถว (key columns)
> เต็มทุกคอลัมน์อยู่ใน `ml-service/data/synthetic_attacks_40.csv`
> ตัวย่อ: hr=hour, newC=is_new_country, newD=is_new_device, fail=failed_logins_24h,
> lc24=login_count_24h, conc=concurrent_session_count, asub=active_subsystem_count,
> npk=new_passkey_recently_added, perm=permission_change_age(วัน), scope=scope_sensitivity, aip=is_attack_ip

| # | scenario | hr | ctry | newC | newD | fail | lc24 | conc | asub | npk | perm | scope | aip |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | credential_stuffing_stealth | 13 | TH | 0 | 0 | 5 | 10 | 0 | 1 | 0 | 180 | 0.8 | 0 |
| 2 | credential_stuffing_stealth | 15 | TH | 0 | 0 | 6 | 8 | 0 | 1 | 0 | 9999 | 0.8 | 0 |
| 3 | credential_stuffing_stealth | 14 | TH | 0 | 0 | 4 | 6 | 0 | 1 | 0 | 90 | 0.8 | 0 |
| 4 | credential_stuffing_stealth | 11 | TH | 0 | 0 | 5 | 6 | 0 | 1 | 0 | 9999 | 0.8 | 0 |
| 5 | credential_stuffing_stealth | 14 | TH | 0 | 0 | 6 | 10 | 0 | 1 | 0 | 9999 | 0.8 | 0 |
| 6 | new_device_stealth | 16 | TH | 0 | 1 | 0 | 3 | 0 | 1 | 1 | 180 | 0.8 | 0 |
| 7 | new_device_stealth | 9 | TH | 0 | 1 | 0 | 1 | 0 | 1 | 1 | 90 | 0.5 | 0 |
| 8 | new_device_stealth | 10 | TH | 0 | 1 | 0 | 3 | 0 | 1 | 1 | 90 | 0.5 | 0 |
| 9 | new_device_stealth | 9 | TH | 0 | 1 | 0 | 1 | 0 | 1 | 1 | 365 | 0.8 | 0 |
| 10 | new_device_stealth | 13 | TH | 0 | 1 | 0 | 1 | 0 | 1 | 1 | 180 | 0.5 | 0 |
| 11 | new_country_stealth | 16 | LA | 1 | 0 | 0 | 1 | 0 | 1 | 0 | 365 | 0.5 | 0 |
| 12 | new_country_stealth | 15 | LA | 1 | 0 | 0 | 2 | 0 | 1 | 0 | 90 | 0.5 | 0 |
| 13 | new_country_stealth | 16 | LA | 1 | 0 | 0 | 2 | 0 | 1 | 0 | 90 | 0.8 | 0 |
| 14 | new_country_stealth | 15 | SG | 1 | 0 | 0 | 3 | 0 | 1 | 0 | 365 | 0.5 | 0 |
| 15 | new_country_stealth | 14 | JP | 1 | 0 | 0 | 2 | 0 | 1 | 0 | 9999 | 0 | 0 |
| 16 | attack_ip_stealth | 9 | TH | 0 | 0 | 0 | 2 | 0 | 1 | 0 | 9999 | 0 | 1 |
| 17 | attack_ip_stealth | 13 | TH | 0 | 0 | 0 | 4 | 0 | 1 | 0 | 180 | 0.8 | 1 |
| 18 | attack_ip_stealth | 10 | TH | 0 | 0 | 0 | 3 | 0 | 1 | 0 | 90 | 0.8 | 1 |
| 19 | attack_ip_stealth | 11 | TH | 0 | 0 | 0 | 4 | 0 | 1 | 0 | 9999 | 0.8 | 1 |
| 20 | attack_ip_stealth | 9 | TH | 0 | 0 | 0 | 2 | 0 | 1 | 0 | 180 | 0.5 | 1 |
| 21 | passkey_abuse | 11 | TH | 0 | 1 | 0 | 2 | 0 | 1 | 1 | 9999 | 0.5 | 0 |
| 22 | passkey_abuse | 16 | TH | 0 | 1 | 0 | 2 | 0 | 1 | 1 | 365 | 0 | 0 |
| 23 | passkey_abuse | 15 | TH | 0 | 1 | 0 | 2 | 0 | 1 | 1 | 180 | 0.5 | 0 |
| 24 | passkey_abuse | 10 | TH | 0 | 1 | 0 | 4 | 0 | 1 | 1 | 9999 | 0.8 | 0 |
| 25 | passkey_abuse | 9 | TH | 0 | 1 | 0 | 4 | 0 | 1 | 1 | 365 | 0 | 0 |
| 26 | lateral_movement | 15 | TH | 0 | 0 | 0 | 3 | 2 | 4 | 0 | 180 | 0.8 | 0 |
| 27 | lateral_movement | 10 | TH | 0 | 0 | 0 | 3 | 2 | 4 | 0 | 180 | 0.8 | 0 |
| 28 | lateral_movement | 15 | TH | 0 | 0 | 0 | 4 | 2 | 5 | 0 | 180 | 0.8 | 0 |
| 29 | lateral_movement | 13 | TH | 0 | 0 | 0 | 2 | 2 | 3 | 0 | 9999 | 0.8 | 0 |
| 30 | concurrent_sessions | 9 | TH | 0 | 0 | 0 | 1 | 8 | 1 | 0 | 180 | 0.5 | 0 |
| 31 | concurrent_sessions | 10 | TH | 0 | 0 | 0 | 4 | 8 | 1 | 0 | 9999 | 0.8 | 0 |
| 32 | concurrent_sessions | 13 | TH | 0 | 0 | 0 | 1 | 8 | 1 | 0 | 9999 | 0 | 0 |
| 33 | concurrent_sessions | 11 | TH | 0 | 0 | 0 | 1 | 8 | 1 | 0 | 9999 | 0.8 | 0 |
| 34 | privilege_abuse | 9 | TH | 0 | 0 | 0 | 4 | 0 | 1 | 0 | 0 | 0.881 | 0 |
| 35 | privilege_abuse | 10 | TH | 0 | 0 | 0 | 2 | 0 | 1 | 0 | 2 | 0.87 | 0 |
| 36 | privilege_abuse | 14 | TH | 0 | 0 | 0 | 2 | 0 | 1 | 0 | 1 | 0.897 | 0 |
| 37 | privilege_abuse | 16 | TH | 0 | 0 | 0 | 1 | 0 | 1 | 0 | 1 | 0.866 | 0 |
| 38 | blended_low_and_slow | 14 | TH | 0 | 1 | 0 | 2 | 1 | 1 | 1 | 180 | 0.5 | 0 |
| 39 | blended_low_and_slow | 16 | TH | 0 | 1 | 0 | 4 | 1 | 1 | 0 | 365 | 0 | 0 |
| 40 | blended_low_and_slow | 15 | TH | 0 | 1 | 0 | 2 | 1 | 1 | 0 | 90 | 0.8 | 0 |

### อธิบายแต่ละ scenario (เพราะอะไร)
| scenario | n | สัญญาณหลัก | ทำไมเนียน |
|---|---|---|---|
| credential_stuffing_stealth | 5 | fail 4–6 + lc24 6–10 | fail ไม่สุดโต่ง กลืนกับคนพิมพ์รหัสผิด |
| new_device_stealth | 5 | newD=1 + npk=1 | เครื่องใหม่แต่ browser family เดิม + เพิ่ม passkey เอง |
| new_country_stealth | 5 | newC=1 (LA/SG/JP) | ประเทศเพื่อนบ้าน plausible ไม่ใช่ที่แปลกสุดขั้ว |
| attack_ip_stealth | 5 | aip=1 | IP ติด threat feed แต่ทุกอย่างดูปกติ (VPN exit) |
| passkey_abuse | 5 | npk=1 + newD=1 | ATO classic — เพิ่ม passkey ก่อน login เงียบๆ |
| lateral_movement | 4 | asub 3–5 + conc 2 | เข้าหลาย subsystem พร้อมกัน |
| concurrent_sessions | 4 | conc 8 | หลาย session พร้อมกัน |
| privilege_abuse | 4 | perm 0–2 วัน + scope 0.87+ | สิทธิ์เพิ่งเปลี่ยน + ขอ scope สูง |
| blended_low_and_slow | 3 | newD + conc + หลายสัญญาณอ่อน | หลายสัญญาณอ่อนพร้อมกัน — จับยากสุด |

---

# ส่วนที่ 3 — กระบวนการ (Pipeline) — เขียน "วิธี" ก่อน "ผล"

## 3.1 Data Selection / Sampling
**รอบ 1 (semi-synthetic):** `sample_rba_base.py`
- สตรีมไฟล์ 9 GB ทีละแถว (ไม่โหลดทั้งไฟล์) — **reservoir sampling**
- normal pool = `ATO=False AND AttackIP=False AND LoginOK=True` → สุ่ม 10,000
- anomaly = `ATO=True` → เก็บ 100 (จากทั้งหมด 141)

**รอบ 2 (real-only):** `build_real_only.py` — **2-pass**
- Pass 1: หา ATO users ทั้งหมด (138) + สุ่ม normal users (3,997)
- Pass 2: ดึง login history ของ target users (compact: ua→hash, cap 4,000/user กัน OOM)

## 3.2 Data Cleaning
- **Filtering:** normal ต้องสะอาด (ไม่ปน attack-IP/ATO/login fail)
- **Type conversion:** `True/False` (string) → `1.0/0.0`
- **Parsing:** `Login Timestamp` → datetime (รองรับ 2 รูปแบบ มี/ไม่มี microsecond);
  `User Agent` → browser family (Edge/Chrome/Firefox/Safari/Opera) + device type
- **Missing/รก:** `City="-"` → ตัดทิ้ง; แถวที่ field < 16 → ข้าม; timestamp parse ไม่ได้ → ข้าม
- **Memory hygiene (รอบ 2):** เก็บ ua เป็น hash (ไม่เก็บ string ยาว), cap login/user

## 3.3 Data Transformation / Feature Engineering
**รอบ 1 (23 features):** mix ของจริง + สังเคราะห์
- จริงจาก raw: `hour_of_day`, `day_of_week`, `is_attack_ip`
- `is_thailand` = home-country proxy (RBA modal country)
- history-dependent (is_new_country, login_count_24h ฯลฯ): **สังเคราะห์ตาม label** (sample ไม่มี history พอ)
- passkey/session/scope/permission: **สังเคราะห์ทั้งหมด** (RBA ไม่มี)

**รอบ 2 (12 features จริงล้วน):** คำนวณจาก **ประวัติ login จริงต่อ user** (online RBA, O(n) two-pointer)
- เรียง login ตามเวลา/คน → คำนวณ feature จาก "ประวัติก่อนหน้า" เท่านั้น
- `failed_logins_24h` = `Login Successful=False` จริง
- **ตัด `active_session_count`** เพราะ RBA ไม่มี logout/session-duration → derive ไม่ได้
- Cold start: history < 5 → personalized feature = neutral (0)

**Scaling:** `StandardScaler` (จำเป็นสำหรับ OCSVM/LOF ที่เป็น distance-based; IForest invariant)

## 3.4 Model Training
3 โมเดล unsupervised:
| โมเดล | setting | หมายเหตุ |
|---|---|---|
| IsolationForest | n_estimators=200, contamination=prevalence | tree-based |
| OneClassSVM | kernel=RBF, gamma=scale, nu≈prevalence | distance/kernel |
| LocalOutlierFactor | n_neighbors=20 (novelty=True ตอน split) | density |

**2 โปรโตคอลการเทรน:**
- **in-sample**: fit + score บนข้อมูลชุดเดียวกัน (มาตรฐาน unsupervised benchmark)
- **proper (one-class, group-by-user)**: fit เฉพาะ normal ของ train-users → test บน held-out
  + ATO; threshold จาก train; ทำซ้ำ 10 splits → mean±std (วัด generalization จริง)

**Label ไม่ถูกใช้ตอน train** — ใช้เฉพาะ "วัดผล"

## 3.5 Evaluation
- Metrics: Precision, Recall, F1, ROC-AUC, **PR-AUC (ตัวหลัก เพราะ imbalanced)**
- Ablation A(13)→B(19)→C(23) — ดูผลของการเพิ่ม feature
- Robustness: multi-seed + Wilcoxon signed-rank + operating-point sweep
- Explainability: SHAP (TreeExplainer สำหรับ IForest, KernelExplainer สำหรับ OCSVM)

---

# ส่วนที่ 4 — ผลรอบ 1 (Semi-Synthetic)

## 4.1 Model comparison (in-sample, 23 feat)
| Model | Prec | Recall | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|
| IsolationForest | 0.707 | 0.707 | 0.707 | 0.928 | 0.734 |
| **OneClassSVM** | 0.609 | 0.836 | 0.705 | **0.963** | **0.844** |
| LOF | 0.500 | 0.500 | 0.500 | 0.751 | 0.536 |

## 4.2 Ablation A→B→C
- A→B (เพิ่ม Tier-1): OCSVM PR-AUC 0.723 → 0.782 (Recall เพิ่ม)
- B→C (เพิ่ม Passkey): OCSVM Precision 0.512 → 0.609, F1 0.611 → 0.705

## 4.3 SHAP (IForest)
- ตัวขับ anomaly: country_change, is_new_device, is_new_country, failed_logins, concurrent_session
- **Passkey เป็น trust signal ทิศบวก** (ดึงเข้าหา normal) → ลด False Positive

## 4.4 Robustness (20 seeds)
- OCSVM PR-AUC 0.809±0.017 > IForest 0.747±0.018; Wilcoxon p<0.0001 (OCSVM ชนะ 20/20)
- แต่ที่ flag ≤1% สองตัวเกือบเท่ากัน

---

# ส่วนที่ 5 — ผลรอบ 2 (Real-Only)

## 5.1 in-sample (12 feat จริง, ATO จริง 141)
| Model | ROC-AUC | PR-AUC | จับ ATO @1.39% |
|---|---|---|---|
| IsolationForest | 0.872 | 0.079 | 8/141 |
| OneClassSVM | 0.764 | 0.093 | 22/141 |

## 5.2 proper train/test (one-class, group-by-user, 10 splits)
| Model | ROC-AUC | PR-AUC | F1@1% | Recall |
|---|---|---|---|---|
| **IsolationForest** | 0.890 ± 0.041 | 0.427 ± 0.166 | 0.325 | 0.265 |
| OneClassSVM | 0.839 ± 0.028 | 0.414 ± 0.164 | 0.486 | 0.500 |
| LOF | 0.489 | 0.103 | 0.074 | 0.050 |

> in-sample ให้ผลแย่เกินจริงสำหรับ one-class (attack ปน train); proper protocol = ตัวเลขที่ถูกต้อง

---

# ส่วนที่ 6 — เปรียบเทียบ รอบ 1 vs รอบ 2 (apples-to-apples)

โปรโตคอลเดียวกัน (one-class, group-by-user, 10 splits):

| Dataset / Feat | IForest ROC / PR-AUC | OCSVM ROC / PR-AUC |
|---|---|---|
| semi-synth @ 12 | 0.894 / 0.751 ±0.007 | 0.912 / 0.797 |
| semi-synth @ 23 | 0.890 / 0.745 | 0.936 / 0.844 |
| **real @ 12** | 0.890 / **0.427 ±0.166** | 0.839 / 0.414 |

**แยกตัวแปร:**
- (ก) **ความสมจริงของ attack** (semi@12 vs real@12): ROC ใกล้กัน (0.894/0.890) แต่ PR-AUC ต่าง
  (0.751 vs 0.427) + variance ต่างมหาศาล (±0.007 vs ±0.166) → synthetic แยกง่าย+นิ่งหลอกตา
- (ข) **feature set** (semi@12 vs semi@23): IForest แทบไม่ขยับ (อิ่มตัว), OCSVM/LOF +0.05

---

# ส่วนที่ 7 — SHAP บน OneClassSVM: ทำไม IsolationForest ไปต่อ

## 7.1 ต้นทุนการอธิบาย (วัดจริง)
| Explainer | ขอบเขต | เวลา | ต่อแถว | ชนิด |
|---|---|---|---|---|
| TreeExplainer (IForest) | **ทั้งชุด 10,140 แถว** | 31 s | **3.07 ms** | **exact** |
| KernelExplainer (OCSVM) | แค่ 300 แถว (bg=30) | 61 s | **203 ms** | **approximate** |

→ OCSVM อธิบาย **ช้ากว่า ~66 เท่า** และเป็นค่า **ประมาณ** — explain ทุก login แบบ real-time ไม่ไหว

## 7.2 ความสอดคล้องของ importance
- **Top-10 overlap (IForest ∩ OCSVM) = แค่ 4/10** — OCSVM ให้ feature สำคัญต่างจาก IForest มาก
  และไม่นิ่ง (มาจาก subset + approximation) → อธิบายต่อ auditor ได้ไม่สม่ำเสมอ
- (รูป: `figures/shap_ocsvm_vs_iforest.png`)

## 7.3 สรุปเหตุผลที่เลือก IsolationForest ไป production
1. **Explainability** — SHAP exact + เร็ว (3 ms/แถว) อธิบายทุก login ใน admin/audit UI ได้จริง
   (OCSVM 66× ช้า + approx → ทำไม่ได้)
2. **Generalization บนข้อมูลจริง** — proper protocol: IForest ≈ OCSVM (0.427 vs 0.414, std ทับกัน)
   → detection เสมอกันบนของจริง
3. **เสถียร** — ROC-AUC ~0.89 ทุกเงื่อนไข, variance ต่ำ; scale เชิงเส้น (OCSVM O(n²–n³))
4. OCSVM ชนะเฉพาะบน semi-synthetic (attack สังเคราะห์) ซึ่งประเมินเกินจริง

> **ข้อสรุป:** OneClassSVM = comparative upper-bound ที่พิสูจน์คุณค่า feature engineering;
> **IsolationForest = production choice** เพราะ explainable + เร็ว + สเกลได้ + เสมอกันบนข้อมูลจริง

---

# ส่วนที่ 8 — ข้อจำกัด
- feature passkey/session/scope/permission สังเคราะห์ (RBA ไม่มี) — เหมาะ ablation ไม่ใช่ตัวแทน production
- ATO จริงมีแค่ 141 เคส → variance สูง, ข้อสรุปบนข้อมูลจริงยังไม่เด็ดขาด
- งานต่อไป: validation บน traffic จริงของระบบ + เก็บ attack จริงเพิ่ม (red-team)

---

# ภาคผนวก — ไฟล์ที่เกี่ยวข้อง
| ไฟล์ | หน้าที่ |
|---|---|
| `ml-service/scripts/sample_rba_base.py` | sample RBA จริง (รอบ 1 base) |
| `ml-service/scripts/build_benchmark.py` | สร้าง semi-synthetic + 40 attack |
| `ml-service/scripts/build_real_only.py` | สร้าง real-only (2-pass, feature จริงล้วน) |
| `ml-service/scripts/evaluate_models.py` | model comparison A/B/C |
| `ml-service/scripts/shap_analysis.py` | SHAP IForest A/B/C |
| `ml-service/scripts/robustness_eval.py` | multi-seed + Wilcoxon + operating-point |
| `ml-service/scripts/real_only_eval.py` | eval real-only (in-sample) |
| `ml-service/scripts/real_only_split_eval.py` | proper split real-only |
| `ml-service/scripts/proper_split_semisynth.py` | proper split semi-synth (apples-to-apples) |
| `ml-service/scripts/shap_ocsvm.py` | SHAP OCSVM vs IForest |
| `ml-service/scripts/generate_figures.py` | รูปกราฟทั้งหมด |
| `ml-service/data/synthetic_attacks_40.csv` | 40 แถว synthetic เต็ม |
