# Hybrid RBA 4-Layer Risk Scoring System

## Context

ระบบปัจจุบันใช้ Isolation Forest ชั้นเดียว (12 features → anomaly_score → pass/mfa/block)
ต้องการอัปเกรดเป็น **4 ชั้น** ตามเอกสาร `RISK_SCORING_SYSTEM.md` + `hybrid_rba_architecture_rules_and_research_th.md`

ผลลัพธ์: ระบบตรวจจับแม่นยำขึ้น + อธิบายผลได้ (explainability) + ลด false positive

---

## Flow ใหม่

```
Login → Feature Extraction (12 features — มีอยู่แล้ว)
  │
  ├─ Layer 1: Rule Engine
  │   ├─ Hard block → reject ทันที (brute force, impossible travel, blacklisted IP)
  │   └─ risk_score_1 (0.0–1.0)
  │
  ├─ Layer 2: Behavior Profiling
  │   └─ เทียบประวัติ user 30 วัน → risk_score_2 (0.0–1.0)
  │
  ├─ Layer 3: Isolation Forest (มีอยู่แล้ว)
  │   └─ anomaly score → risk_score_3 (0.0–0.4)
  │
  └─ Layer 4: Risk Aggregation
      total = rule + behavior + iforest (cap 1.0)
      ├─ >= 0.8 → block
      ├─ >= 0.5 → challenge (MFA/re-auth)
      ├─ >= 0.3 → warn (allow + log)
      └─ < 0.3  → allow
```

---

## Layer 1 — Rule Engine

**หลักการ:** จับ known attacks ทันที ไม่ต้องรอ ML
**อ้างอิง:** NIST SP 800-63B-4 (2024), Freeman et al. (2016), Microsoft Entra ID Protection (2024)

### Hard Block (score = 1.0, หยุดทันที)

| กฎ | Threshold | อ้างอิง |
|----|-----------|---------|
| `failed_logins_24h >= 10` | brute-force / credential stuffing | NIST SP 800-63B-4 §5.2.2 |
| `login_count_24h >= 50` | velocity abuse / bot | Freeman 2016 |
| `country_change_count_30d >= 8` | impossible travel pattern | Wiefling 2022, Microsoft Entra |
| `is_blacklisted(ip)` | IP ใน blacklist | IP Blacklist (มีอยู่แล้ว) |
| **Impossible Travel** | เปลี่ยนประเทศใน < 1 ชม. (ที่ GeoIP resolve ได้ทั้งคู่) | Microsoft Entra 2024, Wiefling 2022 |

### Risk Score (สะสม, cap 1.0)

| กฎ | Score | อ้างอิง |
|----|-------|---------|
| `is_new_device == 1` | +0.30 | Freeman 2016, F-RBA 2024 |
| `is_new_country == 1` | +0.30 | Freeman 2016, Wiefling 2022 |
| `is_new_user_agent_family == 1` | +0.20 | Laperdrix 2020 |
| `failed_logins_24h >= 3` | +0.20 | NIST SP 800-63B-4 |
| `is_thailand == 0` | +0.10 | project-specific (มหาวิทยาลัยไทย) |
| **Multiple accounts from same IP > 5 ใน 1 ชม.** | +0.25 | OWASP API4:2023, credential stuffing pattern |

### Impossible Travel Detection

```python
# ดึง session ล่าสุดของ user (ก่อนหน้านี้)
# ถ้า country เปลี่ยน + เวลาห่าง < 1 ชม. → hard block
# (ตั้งใจใช้ country-level เพราะ GeoIP city ไม่แม่นพอสำหรับ Haversine)
last_session = get_last_session(db, user_id)
if (last_session
    and last_session.geo_country != current_country
    and both_countries_known
    and time_diff_hours < 1.0):
    → hard block (impossible travel)
```

### Multiple Accounts from Same IP

```python
# นับจำนวน user_id ที่ซ้ำกันจาก IP เดียวกันใน 1 ชม.
# ถ้า > 5 accounts → +0.25 (credential stuffing / shared bot)
distinct_users = count_distinct_users_from_ip(db, ip, window=1h)
if distinct_users > 5:
    score += 0.25
```

**ไฟล์:** `app/security/rule_engine.py` (~80 บรรทัด)

---

## Layer 2 — Behavior Profiling

**หลักการ:** เทียบพฤติกรรมปัจจุบันกับ baseline ของ user คนนั้น (30 วัน)
**อ้างอิง:** Wiefling et al. (2022) ACM TOPS, Freeman et al. (2016), F-RBA (2024)

### Risk Score

| กฎ | Score | อ้างอิง |
|----|-------|---------|
| `hours_from_typical_login_time >= 10` | +0.40 | Wiefling 2022 |
| `hours_from_typical_login_time >= 6` | +0.20 | Wiefling 2022 |
| `is_new_country == 1` | +0.30 | Freeman 2016 |
| `is_new_device == 1` | +0.20 | Freeman 2016 |
| `is_weekend != typical_weekend` | +0.10 | Wiefling 2022 |
| ไม่มีประวัติ (new user) | ค่าคงที่ 0.20 | cold start policy |

**หมายเหตุ:** Features เหล่านี้ถูก extract อยู่แล้วใน `feature_extraction.py`
Layer 2 ใช้ features เดียวกันแต่ score แยกจาก ML (double signal = ลด false negative)

**ไฟล์:** `app/security/behavior_profiling.py` (~60 บรรทัด)
ใช้ `feature_extraction.py` ที่มีอยู่ + query `login_sessions` 30 วัน

---

## Layer 3 — Isolation Forest (มีอยู่แล้ว)

**หลักการ:** ตรวจจับ unknown/novel attacks ที่ Rule + Behavior ไม่รู้จัก
**อ้างอิง:** Liu, Ting, Zhou (2008), Wiefling 2022

### Score Mapping (raw → risk)

| IForest anomaly_score | Risk Score | ความหมาย |
|----------------------|------------|----------|
| >= 0.7 | +0.40 | anomaly ชัดเจน |
| >= 0.5 | +0.20 | น่าสงสัย |
| >= 0.3 | +0.10 | เฝ้าระวัง |
| < 0.3 | +0.00 | ปกติ |

**ไฟล์:** `app/security/iforest_scorer.py` (~25 บรรทัด)
เรียก `ml_client.get_anomaly_score()` ที่มีอยู่แล้ว → map score

---

## Layer 4 — Risk Aggregation

**หลักการ:** รวม 3 ชั้นเป็นการตัดสินครั้งเดียว
**อ้างอิง:** Freeman et al. (2016), F-RBA (2024)

### Decision Table

| Total Score | Decision | Action |
|-------------|----------|--------|
| >= 0.8 | **block** | 403 + reject login |
| >= 0.5 | **challenge** | redirect ไป MFA / re-auth (รอ Week 9-10) |
| >= 0.3 | **warn** | allow + log warning |
| < 0.3 | **allow** | allow ปกติ |

### Shadow Mode

เมื่อ `ML_SHADOW_MODE=true`:
- decision = `would_block` / `would_challenge` / `would_warn` (ไม่บังคับจริง ปล่อยผ่าน)
- เก็บ risk_score + breakdown ใน login_sessions เพื่อวิเคราะห์

**ไฟล์:** `app/security/risk_aggregator.py` (~40 บรรทัด)

---

## Orchestrator

**ไฟล์:** `app/security/risk_engine.py` (~50 บรรทัด)

```python
async def evaluate_login_risk(features: dict, user_id: str, db: Session) -> dict:
    # Layer 1
    rule_result = evaluate_rules(features)
    if rule_result.blocked:
        return {"decision": "block", "score": 1.0, ...}

    # Layer 2
    profile = get_user_profile(db, user_id)
    behavior_result = evaluate_behavior(features, profile)

    # Layer 3 (fail-safe)
    ml_result = await get_anomaly_score(features)
    iforest_result = map_score(ml_result["anomaly_score"])

    # Layer 4
    return aggregate(rule_result, behavior_result, iforest_result)
```

---

## โครงสร้างไฟล์

```
hub/backend/app/
├── security/                          ← โฟลเดอร์ใหม่
│   ├── __init__.py
│   ├── rule_engine.py                 ← Layer 1: hard block + risk score
│   ├── behavior_profiling.py          ← Layer 2: user baseline comparison
│   ├── iforest_scorer.py              ← Layer 3: map ML score → risk
│   ├── risk_aggregator.py             ← Layer 4: combine + decide
│   └── risk_engine.py                 ← orchestrator
│
├── routers/
│   └── oauth.py                       ← แก้: เปลี่ยนจาก ML เดี่ยว → risk_engine
│
├── models.py                          ← แก้: เพิ่ม risk_score, risk_breakdown columns
│
└── services/
    ├── feature_extraction.py          ← ไม่แก้ (reuse ทั้งหมด)
    ├── ml_client.py                   ← ไม่แก้ (reuse)
    └── ip_blacklist.py                ← ไม่แก้ (reuse)
```

**ไฟล์ใหม่ 6 ไฟล์ / แก้ 2 ไฟล์**

---

## Database Changes

เพิ่ม columns ใน `login_sessions`:

| Column | Type | หมายเหตุ |
|--------|------|---------|
| `risk_score` | NUMERIC(4,3) | 0.000–1.000 (aggregated total) |
| `risk_breakdown` | JSON | `{"rule": 0.3, "behavior": 0.2, "iforest": 0.1}` |
| `risk_reasons` | JSON | `["is_new_device (+0.30)", "hours_diff=12 (+0.40)"]` |

**หมายเหตุ:** `anomaly_score` เดิมยังเก็บเหมือนเดิม (backward compatible)
`risk_score` เป็นค่ารวมจาก 4 ชั้น, `anomaly_score` เป็นค่าจาก ML อย่างเดียว

---

## Integration ใน oauth.py

**ก่อน (ชั้นเดียว):**
```python
features = extract_session_features(...)
ml_result = await get_anomaly_score(features)
anomaly_score = ml_result["anomaly_score"]
decision = ml_result["decision"]
```

**หลัง (4 ชั้น):**
```python
features = extract_session_features(...)
risk = await evaluate_login_risk(features, user_id, db)
anomaly_score = risk["breakdown"]["iforest_raw"]  # backward compatible
risk_score = risk["score"]
decision = risk["decision"]
reasons = risk["reasons"]
```

---

## Frontend Changes

### Session Detail Panel
- เพิ่มแสดง `risk_score` (ตัวเลขรวม) + `risk_breakdown` (แยก 3 ชั้น)
- แสดง `risk_reasons` เป็น list

### ML Overview API
- เพิ่ม `risk_score`, `risk_breakdown` ใน top_anomalies response

---

## References (5 ปีย้อนหลัง)

| # | งานวิจัย | ปี | ใช้ที่ |
|---|---------|-----|------|
| 1 | **Wiefling et al.** "Pump Up Password Security!" ACM TOPS | 2022 | Layer 1 (country change), Layer 2 (temporal behavior), Dataset |
| 2 | **F-RBA** Federated Risk-Based Authentication Framework | 2024 | Multi-layer architecture, 95% accuracy, 30% less FP |
| 3 | **NIST SP 800-63B-4** Digital Identity Guidelines | 2024 | Layer 1 (failed login threshold, adaptive auth) |
| 4 | **NIST SP 800-228** API Protection Guidelines | 2024 | API monitoring, continuous telemetry |
| 5 | **OWASP API Security Top 10** | 2023 | API4 (rate limiting), API1 (BOLA) |
| 6 | **Microsoft Entra ID Protection** | 2024 | Impossible travel, anomalous token, multi-layer risk |
| 7 | **Freeman et al.** Risk-based auth at LinkedIn | 2016 | Layer 1 scoring weights, aggregation thresholds |
| 8 | **Laperdrix et al.** Browser Fingerprinting | 2020 | UA family change signal |
| 9 | **Liu, Ting, Zhou** Isolation Forest | 2008 | Layer 3 algorithm |
| 10 | **Hariri et al.** Extended Isolation Forest | 2018 | IForest bias correction |

---

## ลำดับ Implementation

| Phase | ไฟล์ | หมายเหตุ |
|-------|------|---------|
| 1 | `security/__init__.py` | โฟลเดอร์ใหม่ |
| 1 | `security/rule_engine.py` | Layer 1: hard block + risk score |
| 1 | `security/behavior_profiling.py` | Layer 2: behavior baseline |
| 1 | `security/iforest_scorer.py` | Layer 3: score mapping |
| 2 | `security/risk_aggregator.py` | Layer 4: aggregate + decide |
| 2 | `security/risk_engine.py` | orchestrator |
| 3 | `models.py` — เพิ่ม 3 columns | risk_score, risk_breakdown, risk_reasons |
| 3 | `routers/oauth.py` — แก้ flow | เปลี่ยนจาก ML เดี่ยว → risk_engine |
| 4 | Frontend — Session Detail Panel | แสดง risk breakdown |
| 4 | Frontend — ML Overview API | เพิ่ม risk data |

---

## Verification

```bash
# 1. restart backend
docker compose restart hub-backend

# 2. ALTER TABLE (เพิ่ม columns ถ้า create_all ไม่ทำให้)
docker compose exec postgres psql -U hub -d hub_db -c "
  ALTER TABLE login_sessions ADD COLUMN IF NOT EXISTS risk_score NUMERIC(4,3);
  ALTER TABLE login_sessions ADD COLUMN IF NOT EXISTS risk_breakdown JSON;
  ALTER TABLE login_sessions ADD COLUMN IF NOT EXISTS risk_reasons JSON;
"

# 3. Login ผ่าน subsystem → ตรวจว่า login_sessions มี risk_score + breakdown
docker compose exec postgres psql -U hub -d hub_db -c "
  SELECT risk_score, risk_breakdown, risk_reasons
  FROM login_sessions ORDER BY created_at DESC LIMIT 5;
"

# 4. ทดสอบ hard block:
#    - เพิ่ม IP เข้า blacklist → login → ถูก block ทันที (Layer 1)

# 5. เปิด /ml → คลิก session → เห็น risk breakdown ใน panel

# 6. Shadow mode: decision = would_block/would_challenge (ไม่ block จริง)
```

---

## หมายเหตุ

- **Backward compatible**: anomaly_score เดิมยังเก็บเหมือนเดิม
- **Shadow mode**: ยังทำงานตามเดิม — risk engine output เป็น would_* แทน
- **ไม่ต้องเพิ่ม dependency**: ใช้ Python standard library + SQLAlchemy ที่มี
- **Reuse ทั้งหมด**: feature_extraction.py, ml_client.py, ip_blacklist.py ไม่แก้
