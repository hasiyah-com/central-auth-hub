# Runbook: เอา Log จริง → ผลลัพธ์ทีละขั้นตอน (Log → Feature → 4-Layer → Decision)

เอกสารนี้บอก **"log เข้าไฟล์ไหน → ได้อะไรออกมา"** ทีละขั้น ตั้งแต่มี log ดิบ จนได้คำตัดสิน/โมเดลใหม่
ทุก path/ไฟล์เป็นของจริงในระบบ

---

## 0. Log ดิบอยู่ที่ไหน

| Log | ตาราง (DB) | ใช้ทำอะไร |
|---|---|---|
| ทุก HTTP request | `request_logs` | เส้นทางการล็อกอิน (audit) — ไม่ได้ป้อนเข้า ML |
| ทุก login สำเร็จ | **`login_sessions`** | **ต้นทางของ pipeline ทั้งหมด** |

คอลัมน์สำคัญใน `login_sessions`:
`user_id, ip, user_agent, geo_country, geo_city, os_name, browser, device_type, created_at,
decision, risk_score, risk_breakdown, risk_reasons, is_attack_ip, is_account_takeover, subsystem_id`

---

## มี 2 เส้นทาง — เลือกตามเป้าหมาย

- **เส้นทาง A (Online):** login เกิด → ประเมิน real-time 4 ชั้น → บันทึกผล (เกิดเองตอน user login)
- **เส้นทาง B (Offline):** เอา log ที่มีอยู่ → export → เทรน/ประเมินใหม่ (คุณสั่งรันเอง)

---

# เส้นทาง A — Online (เกิดตอน login จริง)

ลำดับไฟล์ที่ log ไหลผ่าน (real-time):

| ขั้น | ไฟล์ที่ประมวลผล | Input | Output |
|---|---|---|---|
| A1 | `app/deps.py:get_client_ip()` | HTTP headers (X-Real-IP/XFF) | IP จริงของ client |
| A2 | `app/services/geoip.py:lookup_country()` | IP | `geo_country` (เช่น "TH") |
| A3 | `app/services/feature_extraction.py:extract_session_features()` | user_id, ip, ua, geo + **ประวัติใน DB** | **list 23 ตัวเลข** |
| A4 | `app/security/rule_engine.py:evaluate_rules()` | 23 features + DB | `RuleResult(blocked, score, reasons)` |
| A5 | `app/security/behavior_profiling.py:evaluate_behavior()` | 23 features + profile 30 วัน | `BehaviorResult(score, reasons)` |
| A6 | `app/services/ml_client.py` → `ml-service:9000` → `iforest_scorer.py:map_score()` | 23 features | `IForestResult(raw, risk_score, SHAP)` |
| A7 | `app/security/risk_aggregator.py:aggregate()` | 3 ชั้นรวม | `RiskDecision(total, decision, breakdown)` |
| A8 | `app/routers/oauth.py:607` | decision | **บันทึกลง `login_sessions`** |

**Orchestrator:** `app/security/risk_engine.py:evaluate_login_risk()` เรียก A4→A7 ให้ (ถ้า A4 hard block → ข้าม A5,A6)

---

# เส้นทาง B — Offline (เอา log มาทำเอง)

## ขั้น B1 — Export: `login_sessions` → CSV ฟีเจอร์

**ไฟล์:** `hub/backend/scripts/export_labeled_data.py`
```bash
docker exec <backend> python -m scripts.export_labeled_data
```
| Input | ประมวลผล | Output |
|---|---|---|
| `login_sessions` (ทุกแถวที่มี label) | เรียก `extract_session_features()` ต่อแถว | **`/app/tests/reports/real_labeled.csv`** |

**หน้าตา output** (`real_labeled.csv`) — 23 ฟีเจอร์ + label:
```
hour_of_day,day_of_week,hours_from_typical_login_time,is_thailand,is_new_country,...,label
15.0,0.0,4.5,1.0,0.0,...,0
3.0,6.0,0.0,0.0,1.0,...,1
```
> label: `1`=attack (จาก MLFeedback / is_account_takeover / is_attack_ip), `0`=normal

---

## ขั้น B2 — ย้ายไฟล์ไป ml-service

```bash
docker cp <backend>:/app/tests/reports/real_labeled.csv /tmp/
docker cp /tmp/real_labeled.csv <ml-service>:/app/data/
```
| Input | Output |
|---|---|
| `real_labeled.csv` (จาก backend) | `ml-service:/app/data/real_labeled.csv` |

---

## ขั้น B3 — เทรนโมเดลใหม่

**ไฟล์:** `ml-service/scripts/train_model.py`
```bash
docker exec <ml-service> python -m scripts.train_model
```
| Input | ประมวลผล | Output |
|---|---|---|
| `/app/data/sessions.csv` (synthetic) **+** `/app/data/real_labeled.csv` (จริง, ถ้ามี) | merge → เทรน IsolationForest | **`/app/models/iforest_v1.pkl`** |

**หน้าตา output บนจอ:**
```
🔁 feedback loop: merge real labeled 219 แถว (normal=210, attack=9)
   train ...  ROC-AUC 0.9xx  ...
✅ saved → /app/models/iforest_v1.pkl
```
> ml-service โหลด `.pkl` นี้เข้า memory → ใช้ตอบ `/v1/score` (คือ Layer 3 ในเส้นทาง A)

---

## ขั้น B4 — ประเมินบน log จริง

**ไฟล์:** `hub/backend/scripts/evaluate_on_real.py`
```bash
docker exec <backend> python -m scripts.evaluate_on_real
```
| Input | Output |
|---|---|
| `login_sessions` (จริง) + โมเดลใหม่ | รายงาน Precision/Recall/**FPR** |

**ดูอะไร:** FPR (false positive rate) — ถ้าสูงเกินรับได้ → ปรับ threshold ใน `risk_aggregator.py`
(`block 0.85 / challenge 0.7 / warn 0.5`) ก่อนเปิดใช้

---

## สรุปการไหลของไฟล์ (เส้นทาง B)

```
login_sessions (DB)
   │  export_labeled_data.py
   ▼
real_labeled.csv (23 features + label)      ← ขั้น B1
   │  docker cp
   ▼
ml-service:/app/data/real_labeled.csv       ← ขั้น B2
   │  train_model.py  (+ sessions.csv synthetic)
   ▼
iforest_v1.pkl (โมเดล)                       ← ขั้น B3
   │  evaluate_on_real.py
   ▼
รายงาน Precision/Recall/FPR                  ← ขั้น B4
```

---

# ตัวช่วยที่ควรรันก่อน (เตรียม log ให้พร้อม)

| ปัญหา | ไฟล์แก้ | คำสั่ง |
|---|---|---|
| log เก่า `geo_country` = NULL | `scripts/backfill_geo.py` | `docker exec <backend> python -m scripts.backfill_geo` |
| เช็กว่าต้อง retrain ไหม (train/serve skew) | `scripts/check_feature_drift.py` | `docker exec <backend> python -m scripts.check_feature_drift` |

---

# ตัวอย่างจริง — 1 log ผ่านครบทุกขั้น (จาก DB จริง)

**Log ดิบ** (`login_sessions` แถวจริง):
```
created_at=2026-07-20 15:25:40  user=<U08>  ip=172.18.0.1
browser=Chrome 150  device=desktop  subsystem=ระบบหอพัก
```

**หลัง extract_session_features()** → 23 ตัวเลข (บางส่วน):
```
hour_of_day=15  hours_from_typical=4.5  log_minutes_since_last_login=7.4819
scope_sensitivity_score=1.0  weekday_usage_score=0.88
```

**หลัง 4 ชั้น** (ค่าจริงจาก `risk_breakdown` ใน DB):
```
Layer1 (rule)     = 0.0
Layer2 (behavior) = 0.1   (weekend_mismatch)
Layer3 (iforest)  = 0.1   (raw 0.4486)
─────────────────────────
Layer4 total      = 0.2   →  decision = allow
```

> อยากได้ตัวอย่างละเอียดครบ 23 ฟีเจอร์ + เคส "ผิดปกติ" ดูที่
> [`feature_trace_real_examples_2026-07-20.md`](feature_trace_real_examples_2026-07-20.md)

---

# หมายเหตุสำคัญ
- **เส้นทาง B ไม่กระทบ production** จนกว่าจะเทรนเสร็จ + ml-service โหลดโมเดลใหม่
- ต้องมี `sessions.csv` (synthetic) เสมอ — ถ้า volume ว่าง รัน `python -m scripts.generate_data` ก่อน
- feature ต้องครบ 23 ตัว (B49) — `train_model.py` เช็กให้: ถ้าไม่ตรงจะข้าม real data แทนที่จะพัง
- ยังไม่มี attack label จริง → export จะได้แต่ normal (ก็ช่วยลด FPR ได้) จนกว่า admin จะกด MLFeedback
