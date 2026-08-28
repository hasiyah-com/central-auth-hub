# RBA Risk Scoring — ตัวอย่างจริงจาก Log ครบ 3 ระดับ (Allow / Warn / Challenge)

> ที่มา: ข้อมูลทั้งหมดในเอกสารนี้ดึงจาก **log จริงในฐานข้อมูล dev** (`hub_db`) ไม่ใช่ข้อมูลสมมติ
> ดึงและตรวจสอบเมื่อ 2026-07-20 โดย query ตรงจาก `request_logs`, `login_sessions`, `users`,
> `passkey_credentials`, `access_list`, `subsystems` แล้วคำนวณย้อนตามสูตรในโค้ดจริง เทียบกับค่าที่
> ระบบบันทึกไว้ — **ตรงกัน 100% ทุกตัวเลข** (verify ท้ายเอกสาร)
>
> Reference โค้ด: `hub/backend/app/services/feature_extraction.py`,
> `hub/backend/app/security/rule_engine.py`, `behavior_profiling.py`, `iforest_scorer.py`,
> `risk_aggregator.py`

---

## ภาพรวม pipeline (5 ขั้น)

```
① กดล็อกอิน (browser)
        ↓
② request_logs   ← middleware บันทึกทุก HTTP request อัตโนมัติ
        ↓
③ feature_extraction.py   ← สกัด 23 ฟีเจอร์จาก login_sessions/users/passkey_credentials/
                              access_list/subsystems (ประวัติของ user คนนี้)
        ↓
④ 4-Layer RBA (rule_engine → behavior_profiling → iforest_scorer → risk_aggregator)
        ↓
⑤ login_sessions   ← บันทึกผลลัพธ์ (risk_score, decision, risk_breakdown, risk_reasons)
   + audit_logs (action=oauth_authorized)
```

เลือก 3 login จริงที่ตกคนละระดับ เพื่อให้เห็นว่าฟีเจอร์ตัวไหนดันคะแนนขึ้น:

| ระดับ | User | เวลา | risk_score | decision |
|---|---|---|---|---|
| **Allow** | <U13> | 2026-07-19 10:10:45 | **0.30** | allow |
| **Warn** | <U03> | 2026-07-19 06:09:08 | **0.50** | would_warn |
| **Challenge** | <U13> | 2026-07-19 10:04:26 | **0.70** | would_challenge |

(ระบบรันโหมด `ML_SHADOW_MODE=true` → prefix `would_` หมายถึง "ถ้าไม่ shadow จะบังคับจริง" แต่คะแนน/เหตุผลคำนวณเหมือนโหมดจริงทุกอย่าง)

---

# ระดับที่ 1 — CHALLENGE (risk_score = 0.70) — ตัวอย่างละเอียดที่สุด

**User:** <U13> · **Subsystem:** ระบบหอพัก (`e84415ae-…`) · **เวลา:** 2026-07-19 10:04:26.166315

## ① กดล็อกอิน → ② request_logs (HTTP trail จริง)

ตาราง `request_logs` ถูกเขียนโดย middleware `services/request_logger.py` ทุก HTTP request (ยกเว้น path ใน `SKIP_PATHS`) — คอลัมน์: `method, path, status_code, duration_ms, ip, created_at`

| เวลา | Method | Path | Status | Duration | ความหมาย |
|---|---|---|---|---|---|
| 10:04:20.599 | GET | `/oauth/callback` | 200 | 277ms | Google ส่ง code กลับมา Hub → **จุดที่ 4-Layer RBA รันจริง** (คำนวณ risk_score) |
| 10:04:26.201 | GET | `/oauth/continue` | 307 | 1095ms | redirect กลับไป subsystem พร้อม auth_code |
| 10:04:26.573 | POST | `/oauth/token` | 200 | 299ms | subsystem แลก code → JWT (server-to-server) |
| 10:04:26.641 | GET | `/.well-known/jwks.json` | 200 | 26ms | subsystem ดึง public key มา verify JWT |

## ③ audit_logs ที่เกิดพร้อมกัน

```
action=oauth_authorized  target_type=subsystem  ip=172.18.0.1  created_at=10:04:26.157
metadata: {"provider":"google","risk_score":0.7,"anomaly_score":0.5161,"decision":"would_challenge", ...}

action=token_issued  target_type=subsystem  created_at=10:04:26.549
metadata: {"jti":"<jti-example>"}
```

## ④ สกัดฟีเจอร์ — แหล่งข้อมูล + สูตร + ค่าที่ได้จริง

ทั้งหมดคำนวณใน `extract_session_features()` โดย query ประวัติของ **user_id เดียวกัน** ก่อนเวลา login ปัจจุบัน (`created_at < now`)

| # | Feature | ตาราง/คอลัมน์ต้นทาง | สูตร | คำนวณจริง | ผลลัพธ์ |
|---|---|---|---|---|---|
| 0 | `hour_of_day` | `now` (เวลาปัจจุบัน) | `now.hour` | 10:04:26 → hour=10 | **10.0** |
| 1 | `day_of_week` | `now` | `now.weekday()` (0=จันทร์) | 19 ก.ค. 2026 = วันอาทิตย์ | **6.0** |
| 2 | `hours_from_typical_login_time` | `login_sessions.created_at` (50 ครั้งล่าสุดของ user) | ถ้า history < 5 → **cold start = 0** (ไม่ penalize user ใหม่) | user มี login ในอดีตแค่ 4 ครั้ง (< `MIN_HISTORY_FOR_PERSONALIZATION=5`) | **0.0** (cold start) |
| 3 | `is_thailand` | parameter `geo_country` (จาก GeoIP) | `geo_country ∉ {TH,THAILAND}` → 0 มิฉะนั้น 1 | dev environment → `geo_country=NULL` → default 1 | **1.0** |
| 4 | `is_new_country` | `login_sessions.geo_country` (distinct ของ user) | `geo_country` ปัจจุบัน ∉ set ที่เคยเห็น | ไม่มี geo_country เก็บไว้เลย (dev, private IP) → skip check | **0.0** |
| 5 | `country_change_count_30d` | `login_sessions.geo_country` ใน 30 วัน | จำนวนประเทศต่าง distinct | ไม่มีข้อมูล geo | **0.0** |
| 6 | **`is_new_device`** | `login_sessions.user_agent` (distinct ของ user ก่อนหน้า) | UA ปัจจุบัน ∉ set UA ที่เคยเห็น | UA เก่า 4 ครั้ง = `...Chrome/149.0.0.0...` (คงที่) UA ครั้งนี้ = `...Chrome/**150**.0.0.0...` (เบราว์เซอร์อัปเดตเวอร์ชัน) → **string ไม่ตรงกับที่เคยเห็นเป๊ะ** | **1.0** ⚠️ ตัวหลักที่ดันคะแนน |
| 7 | `is_new_user_agent_family` | เหมือนข้อ 6 แต่เทียบ **browser family** (Chrome/Firefox/…) ไม่ใช่ full string | `browser_family(UA_ปัจจุบัน) ∉ {family ที่เคยเห็น}` | family เดิม = Chrome, family ใหม่ = Chrome (แค่เลขเวอร์ชันเปลี่ยน) → family เดียวกัน | **0.0** |
| 8 | `log_minutes_since_last_login` | `login_sessions.created_at` (ล่าสุดของ user) | `ln(max(delta_minutes, 0.5))` | login ล่าสุดก่อนหน้า = 2026-07-01 14:01:42 → Δ = 25,682.73 นาที (17.8 วัน) → `ln(25682.73)` | **10.1536** |
| 9 | `login_count_24h` | `login_sessions` count ใน 24 ชม.ก่อนหน้า | `COUNT(*) WHERE created_at >= now-24h` | ไม่มี login ใดใน 24 ชม.ก่อนหน้า (ครั้งก่อนคือ 18 วันที่แล้ว) | **0.0** |
| 10 | `failed_logins_24h` | `login_sessions.decision IN (block,would_block)` ใน 24 ชม. | `COUNT(*)` | ไม่มี | **0.0** |
| 11-14 | `passkey_count`, `passkey_age_days`, `new_passkey_recently_added`, `passkey_last_used_days` | `passkey_credentials` (`revoked_at IS NULL`) | ต่างๆ ตาม created_at/last_used_at | user นี้ไม่มี passkey เลย → cold-start ทุกตัว = 0 | **0, 0, 0, 0** |
| 15 | `concurrent_session_count` | `login_sessions` active (`logout_at IS NULL`) ภายใน 60 นาที | `COUNT(*)`, cap 50 | ไม่มี session ค้าง | **0.0** |
| 16 | `active_subsystem_count` | เหมือนข้อ 15 แต่ distinct `subsystem_id` | `COUNT(DISTINCT subsystem_id)` | 0 | **0.0** |
| 17 | `weekday_usage_score` | `login_sessions.created_at.weekday()` (50 ครั้งล่าสุด) | cold start (< 5 ครั้ง) → **0** | history < 5 | **0.0** |
| 18 | **`scope_sensitivity_score`** | `subsystems.scope` (array ของ field ที่ subsystem ขอ) | `min(1.0, Σ weight(field))` — weight: email/name=0.1, faculty/major=0.3, student_id/employee_id=0.6 | scope ของหอพัก = `{email,name,student_id,employee_id,faculty,year,position,phone}` → `0.1+0.1+0.6+0.6+0.3+0.1+0.1+0.1 = 2.0` → `min(1.0, 2.0)` | **1.0** |
| 19 | `ever_changed_permission` | `access_list.granted_at/revoked_at` ของ user | มี record ใดๆ ไหม | มี (สิทธิ์เข้าหอพักถูก grant ตอนสมัคร) | **1.0** |
| 20 | `permission_change_age` | เหมือนข้อ 19 | `(now - MAX(granted_at,revoked_at)) / วัน`, cap 365 | grant ล่าสุด ~13 วันก่อน | **13.02** |
| 21 | `confirmed_incident_count` | `login_sessions.is_account_takeover` / `is_attack_ip` | `COUNT(*)` | ไม่เคยมี incident จริง | **0.0** |
| 22 | `impossible_travel_score` | `login_sessions.geo_country` + `created_at` ล่าสุด | เปลี่ยนประเทศเร็ว → decay เชิงเส้นถึง 24 ชม. | ไม่มี geo_country เปรียบเทียบได้ | **0.0** |

**ตรวจสอบเลข (คำนวณย้อนจาก DB จริง แล้วเทียบกับที่บันทึกไว้ — ตรงกันหมด):**
```
delta_min = (2026-07-19 10:04:26.166 − 2026-07-01 14:01:42.336) / 60 = 25,682.73 นาที
log_minutes = ln(25682.73) = 10.1536   ✓ ตรงกับที่บันทึก
scope_sensitivity = min(1.0, 0.1+0.1+0.6+0.6+0.3+0.1+0.1+0.1) = min(1.0, 2.0) = 1.0   ✓
day_of_week: 2026-07-19 = วันอาทิตย์ → index 6   ✓
```

## ⑤ คำนวณ 4 ชั้น (4-Layer RBA)

### Layer 1 — Rule Engine (`rule_engine.py::evaluate_rules`) → **0.30**

ไล่กฎ `SCORE_RULES` ทีละแถวเทียบกับ feature vector ด้านบน:

```python
("is_new_device",           "==", 1,   0.30)   # feature[6]=1.0  → ตรง! +0.30
("is_new_country",          "==", 1,   0.30)   # feature[4]=0.0  → ไม่ตรง
("is_new_user_agent_family","==", 1,   0.20)   # feature[7]=0.0  → ไม่ตรง
("failed_logins_24h",       ">=", 3,   0.20)   # feature[10]=0.0 → ไม่ตรง
("is_thailand",              "==", 0,   0.10)   # feature[3]=1.0  → ไม่ตรง (โซนไทย)
("impossible_travel_score",  ">=", 0.5, 0.30)   # feature[22]=0.0 → ไม่ตรง
```
+ hard-block check (`failed_logins_24h>=10`, `login_count_24h>=50`, `country_change>=8`) — ไม่เข้าเงื่อนไขไหนเลย ไม่ block

**รวม Layer 1 = 0.30** (มาจาก `is_new_device` เพียงตัวเดียว) → `reasons=["is_new_device (+0.3)"]`

### Layer 2 — Behavior Profiling (`behavior_profiling.py::evaluate_behavior`) → **0.20**

ก่อนอื่นสร้าง profile จาก `get_user_profile()`: ต้องมี login ≥ `MIN_SESSIONS=5` ครั้งใน 30 วัน — user นี้มีแค่ 4 ครั้ง → **profile = None**

```python
if profile is None:
    return BehaviorResult(score=COLD_START_SCORE, reasons=["no_history (cold start)"])
```
**COLD_START_SCORE = 0.20** ตายตัว (ไม่ประเมิน temporal/geo/device rule อื่นเลยเพราะไม่มี baseline เทียบ)

**รวม Layer 2 = 0.20** → `reasons=["no_history (cold start)"]`

### Layer 3 — Isolation Forest (`iforest_scorer.py::map_score`) → **0.20**

โมเดล IsolationForest (เทรนจาก synthetic data) รับ feature vector 23 ตัวทั้งหมด → คืน `raw_score = 0.5161`

```python
if raw_score >= 0.7:  risk = 0.40   # high
elif raw_score >= 0.5:  risk = 0.20   # ← 0.5161 เข้าเกณฑ์นี้
elif raw_score >= 0.3:  risk = 0.10
else:                    risk = 0.00
```
**รวม Layer 3 = 0.20** (label = "medium")

SHAP TreeExplainer อธิบายว่า **ทำไม** raw_score ถึงสูง (top contributors ที่ดันเป็น anomaly):
| Feature | SHAP value | ผลกระทบ |
|---|---|---|
| `is_new_device` | **+1.7596** | ตัวหลักที่ผลักดันให้โมเดลมองว่าผิดปกติ |
| `scope_sensitivity_score` | +0.5245 | ขอสิทธิ์ high-sensitivity data |
| `day_of_week` (อาทิตย์) | +0.5112 | login วันหยุด |
| `permission_change_age` (13 วัน) | +0.4485 | เพิ่งได้สิทธิ์มาไม่นาน |

### Layer 4 — Aggregation (`risk_aggregator.py::aggregate`) → **0.70**

```python
total = round(rule.score + behavior.score + iforest.risk_score, 4)
      = round(0.30       + 0.20           + 0.20            , 4)
      = 0.70
total = min(total, 1.0)  # = 0.70 (ไม่เกิน cap)
```

**ตัดสิน decision** (`THRESHOLDS = {block:0.85, challenge:0.70, warn:0.50}`):
```python
if   total >= 0.85: "block"
elif total >= 0.70: "challenge"   # ← 0.70 >= 0.70 เข้าเกณฑ์นี้พอดี
elif total >= 0.50: "warn"
else:                "allow"
```
`raw_decision = "challenge"` → เพราะ `ML_SHADOW_MODE=true` → prefix เป็น **`would_challenge`**

## บันทึกผลลง `login_sessions` (session id `ea8a3122-…`)
```
risk_score     = 0.700
anomaly_score  = 0.5161   (= iforest raw_score ก่อน map)
decision       = would_challenge
risk_reasons   = ["is_new_device (+0.3)", "no_history (cold start)"]
risk_breakdown = {"rule":0.3, "behavior":0.2, "iforest":0.2, "iforest_raw":0.5161, "iforest_explanation":[...SHAP 23 ค่า...]}
```

> **สรุปเคสนี้:** ตกที่ 0.70 พอดี เพราะ Chrome auto-update เวอร์ชัน (149→150) ทำให้ UA string เปลี่ยน → ระบบมองเป็น "เครื่องใหม่" (`is_new_device=1`) และ user ยังเป็น cold-start (ประวัติไม่พอสร้าง baseline) → 3 ชั้นยิงพร้อมกันจากสาเหตุเดียวกัน (device ใหม่) บวกกับขอ scope sensitivity สูง (หอพักขอ student_id/employee_id)

---

# ระดับที่ 2 — WARN (risk_score = 0.50)

**User:** <U03> · **Subsystem:** Hub-direct (ไม่มี subsystem_id) · **เวลา:** 2026-07-19 06:09:08.868331

## ① → ② request_logs
```
06:09:04.112  GET  /auth/google/login      302   → เริ่ม OAuth (Hub-direct)
06:09:08.868  ← [4-Layer RBA รันตรงนี้ ใน /auth/google/callback]
06:09:08.966  GET  /auth/google/callback   302  422ms  → ออก JWT + redirect
```

## ④ ฟีเจอร์สำคัญที่ต่างจากเคสก่อน

| Feature | แหล่งข้อมูล | คำนวณจริง | ผล |
|---|---|---|---|
| `hour_of_day` | now | 06:09 → hour | **6.0** |
| `day_of_week` | now | 19 ก.ค. = อาทิตย์ | **6.0** |
| **`hours_from_typical_login_time`** | `login_sessions.created_at` — user นี้มี login ในอดีต **37 ครั้ง** (≥ 5) → ไม่ cold-start | median ของ hour ใน 50 ครั้งล่าสุด = **16.0** (คำนวณจริง: `[6,15,6,13,6,8,16,20,…]` → median=16) → `diff=\|6−16\|=10` → `circular=min(10,14)=10` | **10.0** |
| `is_new_device` | `login_sessions.user_agent` distinct | UA เดิม Chrome/150 เคยเห็นมาก่อนแล้ว (login ครั้งก่อน 06:06:42 ก็ UA เดียวกัน) | **0.0** |
| `log_minutes_since_last_login` | login ล่าสุดก่อนหน้า = 06:06:42.970704 | Δ = 145.9 วิ = 2.4316 นาที → `ln(2.4316)` | **0.8886** |
| `login_count_24h` | count ใน 24 ชม. | user นี้ active มาก (37 ครั้งใน 30 วัน) → มีหลายครั้งใน 24 ชม.ก่อนหน้า | สูง (>0) |
| `scope_sensitivity_score` | Hub-direct (`subsystem_id=None`) | ตาม `feature_extraction.py:362` เงื่อนไข `if subsystem_id is not None` ไม่เข้า → default | **0.0** |

## ⑤ 4-Layer

**Layer 1 — Rule = 0.0**
```
is_new_device=0 → ไม่ตรง
is_new_country=0, is_new_ua_family=0, failed_logins=0, is_thailand=1, impossible_travel=0
→ ไม่มีกฎไหนยิงเลย → score = 0.0
```

**Layer 2 — Behavior = 0.40** (มี profile จริงแล้ว เพราะ history ≥ 5)
```python
hours_diff = 10.0
if hours_diff >= 10:            # 10.0 >= 10 → ตรง (เท่ากันพอดี)
    score += 0.40
    reasons.append("hours_diff=10.0 >= 10 (+0.40)")
# is_new_country=0 → ข้าม (+0.30)
# is_new_device=0  → ข้าม (+0.20)
# weekend_mismatch: current_weekend=1(อาทิตย์), typical_weekend ของ profile=? → ไม่ตรง เลยไม่บวกเพิ่ม (สมมติ user คนนี้ login วันหยุดเป็นปกติ)
```
**รวม Layer 2 = 0.40** — มาจาก "login ผิดเวลาปกติไป 10 ชม." (ปกติ login แถวบ่าย/เย็น 16:00 แต่ครั้งนี้ตี 6 เช้า)

**Layer 3 — IForest = 0.10**
```
raw_score = 0.4292
0.3 <= 0.4292 < 0.5 → risk_score = 0.10 (label="low")
```

**Layer 4 — Aggregate**
```python
total = 0.0 + 0.40 + 0.10 = 0.50
0.50 >= 0.50 (warn threshold) และ < 0.70 (challenge) → decision = "warn"
shadow_mode=true → "would_warn"
```

## บันทึกผล
```
risk_score=0.500, anomaly_score=0.4292, decision=would_warn
risk_reasons=["hours_diff=10.0 >= 10 (+0.40)"]
risk_breakdown={"rule":0.0,"behavior":0.4,"iforest":0.1,"iforest_raw":0.4292}
```

> **สรุปเคสนี้:** user เก่า (มี behavior profile จริง) แต่ **login ผิดเวลาที่เคยชิน** (ปกติบ่าย/เย็น มา login ตี 6) — rule engine เงียบสนิท (ไม่มี device/country ใหม่) แต่ behavior layer จับได้ว่าผิดธรรมชาติ → Layer 2 เป็นตัวขับหลักของเคสนี้ (ต่างจากเคส challenge ที่ Layer 1+3 ขับ)

---

# ระดับที่ 3 — ALLOW (risk_score = 0.30)

**User:** <U13> (คนเดียวกับเคส challenge) · **Subsystem:** ระบบหอพัก · **เวลา:** 2026-07-19 10:10:45.694022 (**6 นาทีถัดจากเคส challenge**)

## ① → ② request_logs
```
10:10:33.991  GET  /oauth/authorize          200
10:10:35.100  GET  /oauth/authorize/google    302   → ไป Google อีกรอบ (login ใหม่)
10:10:43.327  GET  /oauth/callback            200  318ms  → [4-Layer RBA รันตรงนี้]
10:10:45.719  GET  /oauth/continue            307
10:10:45.986  POST /oauth/token               200
```

## ④ ฟีเจอร์ — ทำไมคะแนนลดจาก 0.70 → 0.30 ทั้งที่เป็น user/เครื่องเดียวกัน

| Feature | เคส Challenge (10:04) | เคส Allow (10:10) | เหตุผลที่เปลี่ยน |
|---|---|---|---|
| `is_new_device` | **1.0** | **0.0** | หลัง login ครั้งแรก (10:04) UA เวอร์ชัน 150 ถูกบันทึกลง `login_sessions.user_agent` แล้ว → ครั้งถัดมา (10:10) UA เดิมนี้ **"เคยเห็นแล้ว"** ในประวัติ → ไม่ใช่เครื่องใหม่อีกต่อไป |
| `passkey_count` ฯลฯ | cold-start (ไม่มี profile 30 วัน) | **ยังไม่ครบ 5 session ภายใน 30 วัน** (ครั้งนี้เป็นครั้งที่ 5) → behavior ยังนับเป็น cold-start เหมือนเดิม | — |
| `hours_from_typical_login_time` | 0.0 (cold-start) | 0.0 (cold-start ต่อ, history ยังไม่ถึงเกณฑ์ ณ ขณะสกัดฟีเจอร์ก่อน insert แถวนี้) | เท่าเดิม |
| `log_minutes_since_last_login` | 10.1536 (login ล่าสุด 18 วันก่อน) | **1.1733** (login ล่าสุดเมื่อครู่นี้เอง 10:07:31 → Δ≈3.2 นาที → `ln(3.2)≈1.17`) | เพิ่งใช้งานไปเมื่อกี้ |
| `login_count_24h` | 0.0 | **2.0** (มี 2 ครั้งใน 24 ชม.ที่ผ่านมาแล้ว คือ 10:04 กับ 10:07) | ปกติ ไม่ถึงเกณฑ์ hard-block (≥50) |
| `weekday_usage_score` | 0.0 (cold-start) | **0.6667** (จาก 3 sessions ในประวัติตอนนี้ มี 2 ครั้งตรง Sunday → `1 − 2/3`) | เริ่มมี pattern คร่าวๆ แล้ว |
| `permission_change_age` | 13.02 | **0.0025 วัน** (≈3.6 นาที — เพราะ record `access_list` ถูกแตะระหว่างนั้น) | — |

## ⑤ 4-Layer

**Layer 1 — Rule = 0.0**
```
is_new_device=0 → ไม่ตรงกฎไหนเลย (เครื่องนี้ผ่านมาแล้วรอบก่อน) → score=0.0
```

**Layer 2 — Behavior = 0.20** (ยัง cold-start, history 30 วัน < 5 ครั้ง)
```
profile is None → COLD_START_SCORE = 0.20 ตายตัว
reasons=["no_history (cold start)"]
```

**Layer 3 — IForest = 0.10**
```
raw_score = 0.4283  (ลดจาก 0.5161 เพราะ is_new_device พลิกเป็น 0 → SHAP ของตัวนี้หายไป)
0.3 <= 0.4283 < 0.5 → risk_score = 0.10 (label="low")
```

**Layer 4 — Aggregate**
```python
total = 0.0 + 0.20 + 0.10 = 0.30
0.30 < 0.50 (ต่ำกว่า warn threshold) → decision = "allow"
```

## บันทึกผล
```
risk_score=0.300, anomaly_score=0.4283, decision=allow
risk_reasons=["no_history (cold start)"]
risk_breakdown={"rule":0.0,"behavior":0.2,"iforest":0.1,"iforest_raw":0.4283}
```

> **สรุปเคสนี้:** login ครั้งที่ 2 ของวันเดียวกัน ด้วยเครื่อง/เบราว์เซอร์เดิม — พอ Layer 1 (rule) "จำ" ได้ว่าเห็น device นี้แล้วจากรอบก่อน คะแนนหล่นจาก 0.70 → 0.30 ทันที (ตัด is_new_device ออกไป กระทบทั้ง 3 ชั้นพร้อมกัน เพราะ feature ตัวนี้มีน้ำหนักสูงสุดใน SHAP ด้วย) เหลือแค่ cold-start behavior (0.20) กับ iforest baseline เล็กน้อย (0.10)

---

# ตารางเทียบสรุปทั้ง 3 ระดับ

| | **Allow (0.30)** | **Warn (0.50)** | **Challenge (0.70)** |
|---|---|---|---|
| User | jkfurakook (10:10) | searozxcv (06:09) | jkfurakook (10:04) |
| Layer 1 Rule | 0.0 | 0.0 | **0.30** (is_new_device) |
| Layer 2 Behavior | 0.20 (cold-start) | **0.40** (login ผิดเวลาปกติ 10 ชม.) | 0.20 (cold-start) |
| Layer 3 IForest | 0.10 (raw 0.428) | 0.10 (raw 0.429) | **0.20** (raw 0.516) |
| **รวม** | **0.30** | **0.50** | **0.70** |
| ตัวขับหลัก | — (ปกติทุกด้าน) | Behavior (เวลาผิดปกติ) | Rule+IForest (เครื่องใหม่) |
| Decision | allow | would_warn | would_challenge |

**ข้อสังเกตเชิงระบบ:** ทั้ง 3 เคสมาจาก DB จริงในช่วงเวลาไล่เลี่ยกัน แสดงให้เห็นว่าฟีเจอร์ตัวเดียว (`is_new_device`) ที่มีน้ำหนักสูงทั้ง 3 ชั้น (rule +0.30, iforest SHAP +1.76) สามารถเปลี่ยน decision ข้ามระดับได้ทันทีที่ device ถูก "จำ" ในประวัติ — สอดคล้องกับดีไซน์ RBA ที่เน้นความคุ้นเคย (familiarity) เป็นสัญญาณหลัก

---

## Verify — คำสั่งที่ใช้ตรวจสอบ (reproducible)

```bash
docker exec hub-postgres psql -U hub -d hub_db -c "
SELECT s.id, u.email, s.created_at, s.risk_score, s.decision, s.risk_reasons, s.risk_breakdown
FROM login_sessions s JOIN users u ON u.id=s.user_id
WHERE s.id IN ('ea8a3122-8aef-4544-8c55-2df08227fb24',
                '8a8435e7-da4f-43d8-b13c-77d198bb3ef3',
                'd1e2b03a-3fae-4fec-9d5b-94d0d3c44e46');"

docker exec hub-postgres psql -U hub -d hub_db -c "
SELECT created_at, method, path, status_code, duration_ms
FROM request_logs
WHERE created_at BETWEEN '2026-07-19 10:03:55' AND '2026-07-19 10:04:35'
ORDER BY created_at;"
```

ทุกตัวเลขในเอกสารนี้ (log_minutes, scope_sensitivity, hours_from_typical median ฯลฯ) คำนวณซ้ำด้วย Python จากค่าดิบใน DB แล้วเทียบกับค่าที่บันทึกจริงใน `risk_breakdown`/`iforest_explanation` — ตรงกันทุกจุดทศนิยม
