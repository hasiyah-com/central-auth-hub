# ML Feature Data Sources — Central Auth Hub (Hybrid RBA)

**เอกสารอ้างอิง: แต่ละ feature ใช้ข้อมูลจากไหน + คำนวณยังไง**
Version 2.0 · 2026-06-14 · สถานะ: ชุด 21 features (ตัด 2 เดิม + เพิ่ม 6 ใหม่)

> ใช้คู่กับ `ML_FEATURE_ENGINEERING_AND_RISK_MODELING_PLAN.md` (แผนภาพรวม)
> Feature order = contract: `ml-service/app/features.py` ↔ `hub/backend/app/services/feature_extraction.py` ต้องเรียงตรงกันเป๊ะ (B27)

---

## สรุปการเปลี่ยนแปลงรอบนี้

| รายการ | feature |
|---|---|
| ➖ ตัดออก (collinear 100%) | `is_weekend` (= f(day_of_week)), `has_passkey` (= f(passkey_count>0)) |
| ➕ เพิ่มใหม่ (6) | `concurrent_session_count`, `active_subsystem_count`, `weekday_usage_score`, `scope_sensitivity_score`, `permission_change_age`, `confirmed_incident_count` |
| ✅ คงไว้ | 15 เดิม (รวม `is_new_user_agent_family`) |

**รวม: 17 − 2 + 6 = 21 features**

---

## ตารางรวม 21 Features + แหล่งข้อมูล

| # | Feature | หมวด | แหล่งข้อมูลหลัก | สถานะ |
|---|---|---|---|---|
| 1 | hour_of_day | Temporal | login ปัจจุบัน (timestamp) | เดิม |
| 2 | day_of_week | Temporal | login ปัจจุบัน (timestamp) | เดิม |
| 3 | hours_from_typical_login_time | Temporal | `login_sessions.created_at` (history) | เดิม |
| 4 | is_thailand | Geo | GeoIP → `geo_country` | เดิม |
| 5 | is_new_country | Geo | `login_sessions.geo_country` (history) | เดิม |
| 6 | country_change_count_30d | Geo | `login_sessions.geo_country` (30d) | เดิม |
| 7 | is_new_device | Device | `login_sessions.user_agent` (history) | เดิม |
| 8 | is_new_user_agent_family | Device | `login_sessions.user_agent` (history) | เดิม |
| 9 | log_minutes_since_last_login | Velocity | `login_sessions.created_at` (ล่าสุด) | เดิม |
| 10 | login_count_24h | Velocity | `login_sessions` (24h count) | เดิม |
| 11 | failed_logins_24h | Brute | `login_sessions.decision` (24h) | เดิม |
| 12 | passkey_count | Passkey | `passkey_credentials` | เดิม |
| 13 | passkey_age_days | Passkey | `passkey_credentials.created_at` | เดิม |
| 14 | new_passkey_recently_added | Passkey | `passkey_credentials.created_at` | เดิม |
| 15 | passkey_last_used_days | Passkey | `passkey_credentials.last_used_at` | เดิม |
| 16 | **concurrent_session_count** | Session | `login_sessions.logout_at` (active 60m) | 🆕 |
| 17 | **active_subsystem_count** | Session | `login_sessions.subsystem_id` (active) | 🆕 |
| 18 | **weekday_usage_score** | Behavioral | `login_sessions.created_at` (history) | 🆕 |
| 19 | **scope_sensitivity_score** | OAuth | `subsystems.scope` (current client) | 🆕 |
| 20 | **permission_change_age** | Privilege | `access_list.granted_at/revoked_at` | 🆕 |
| 21 | **confirmed_incident_count** | History | `login_sessions.is_account_takeover/is_attack_ip` | 🆕 |

---

# รายละเอียดต่อ feature

## หมวด Temporal — เวลา login

### 1. hour_of_day
- **ข้อมูล:** timestamp ของ login ปัจจุบัน (`now.hour`)
- **คำนวณ:** `float(now.hour)` → 0–23
- **เหตุผล:** ช่วงเวลาผิดปกติ (เช่น ตี 3) = สัญญาณเสี่ยง [Wiefling 2022]

### 2. day_of_week
- **ข้อมูล:** timestamp ปัจจุบัน (`now.weekday()`)
- **คำนวณ:** 0=จันทร์ … 6=อาทิตย์
- **เหตุผล:** pattern รายวัน [Wiefling 2020]
- **หมายเหตุ:** `is_weekend` เดิม **ถูกตัด** เพราะ derive จากตัวนี้ได้ (day≥5) + `weekday_usage_score` (#18) ให้เวอร์ชัน personalized ที่ดีกว่า

### 3. hours_from_typical_login_time *(personalized)*
- **ข้อมูล:** `login_sessions.created_at` ของ user (50 session ล่าสุด)
- **คำนวณ:** `min(|hour − median(past_hours)|, 24 − diff)` (circular distance)
- **Cold start:** history < 5 session → `0.0` (ไม่ลงโทษ user ใหม่)
- **เหตุผล:** baseline เวลาส่วนตัว แม่นกว่าเวลา global [Wiefling 2022]

---

## หมวด Geographic — ภูมิศาสตร์

### 4. is_thailand
- **ข้อมูล:** `geo_country` (GeoIP lookup จาก IP ปัจจุบัน)
- **คำนวณ:** 1.0 ถ้า TH/THAILAND, ไม่งั้น 0.0
- **เหตุผล:** login ในประเทศ = เสี่ยงต่ำกว่า [Wiefling 2022]

### 5. is_new_country
- **ข้อมูล:** `login_sessions.geo_country` (distinct history ของ user)
- **คำนวณ:** 1.0 ถ้า geo_country ปัจจุบันไม่เคยอยู่ใน history
- **เหตุผล:** ประเทศใหม่ครั้งแรก = สัญญาณ [Freeman 2016]

### 6. country_change_count_30d
- **ข้อมูล:** `login_sessions.geo_country` (30 วันล่าสุด)
- **คำนวณ:** จำนวนประเทศ distinct ใน 30 วัน
- **เหตุผล:** เปลี่ยนประเทศบ่อย = travel-based anomaly [Wiefling 2022]

---

## หมวด Device — อุปกรณ์

### 7. is_new_device
- **ข้อมูล:** `login_sessions.user_agent` (distinct history)
- **คำนวณ:** 1.0 ถ้า user_agent ปัจจุบันไม่เคยเห็น
- **เหตุผล:** อุปกรณ์ใหม่ = เสี่ยง [Laperdrix 2020]

### 8. is_new_user_agent_family
- **ข้อมูล:** `login_sessions.user_agent` (history) → parse browser family
- **คำนวณ:** 1.0 ถ้า browser family (Chrome/Firefox/Edge/Safari/Opera) ไม่เคยเห็น
- **เหตุผล:** เปลี่ยน browser family = สัญญาณแยกจาก device [Iqbal 2021]
- **หมายเหตุ:** overlap สูงกับ #7 (value ต่ำสุดในชุด) — เก็บไว้เพราะ citation; เป็น candidate ตัดในอนาคต

---

## หมวด Velocity — ความถี่/ระยะเวลา

### 9. log_minutes_since_last_login
- **ข้อมูล:** `login_sessions.created_at` (session ล่าสุดของ user)
- **คำนวณ:** `log(max(นาทีตั้งแต่ login ล่าสุด, 0.5))` — log scale กัน log(0)
- **Cold start:** ไม่มี login เก่า → `6.0` (≈ neutral)
- **เหตุผล:** login ถี่ผิดปกติ = automation/brute [Microsoft Entra]

### 10. login_count_24h
- **ข้อมูล:** `login_sessions` (count ใน 24h ของ user)
- **คำนวณ:** จำนวน session ใน 24 ชม.
- **เหตุผล:** ปริมาณ login สูงผิดปกติ [Acien 2021]

---

## หมวด Brute Force

### 11. failed_logins_24h
- **ข้อมูล:** `login_sessions.decision` (24h)
- **คำนวณ:** count ที่ `decision IN ('block','would_block')` ใน 24 ชม.
- **เหตุผล:** ความพยายามที่ล้มเหลวซ้ำ = brute force [NIST SP 800-63B-4]

---

## หมวด Passkey / Device Trust

> ดึงจาก `passkey_credentials` ที่ `revoked_at IS NULL` (active เท่านั้น)
> Cold start: ไม่มี passkey → ทุกตัว `0.0`
> `has_passkey` เดิม **ถูกตัด** — `passkey_count > 0` แทนได้ 100%

### 12. passkey_count
- **ข้อมูล:** `passkey_credentials` (count active ของ user)
- **คำนวณ:** จำนวน passkey 0–10
- **เหตุผล:** account ที่มี passkey หลายตัว = mature, recovery path ดี = เสี่ยงต่ำ

### 13. passkey_age_days
- **ข้อมูล:** `passkey_credentials.created_at` (เก่าสุด)
- **คำนวณ:** วันตั้งแต่สร้าง passkey เก่าสุด
- **เหตุผล:** passkey ใหม่ = น่าสงสัยกว่า passkey เก่า

### 14. new_passkey_recently_added
- **ข้อมูล:** `passkey_credentials.created_at` (ใหม่สุด)
- **คำนวณ:** 1.0 ถ้าเพิ่ม passkey < 1 ชม.
- **เหตุผล:** เพิ่ม passkey ก่อน login = สัญญาณ **Account Takeover**

### 15. passkey_last_used_days
- **ข้อมูล:** `passkey_credentials.last_used_at`
- **คำนวณ:** วันตั้งแต่ใช้ passkey ล่าสุด (ถ้าไม่เคยใช้ = passkey_age_days)
- **เหตุผล:** passkey ที่ไม่ได้แตะนาน = เสี่ยงสูงขึ้น

---

## หมวด Session 🆕

### 16. concurrent_session_count
- **ข้อมูล:** `login_sessions.logout_at` + `created_at`
- **คำนวณ:**
  ```sql
  COUNT(*) WHERE user_id = :uid
    AND logout_at IS NULL
    AND created_at > now() - INTERVAL '60 minutes'   -- = JWT TTL
  ```
- **⚠️ ทำไมต้อง time-bound 60 นาที:** 154/219 session ใน DB ไม่มี logout_at (JWT หมดอายุเฉยๆ ไม่ logout) → ถ้าไม่ตัดด้วย JWT TTL session ค้างจะนับเป็น "concurrent" ตลอดกาล ทำให้ค่าพอง
- **Range:** 0–50
- **เหตุผล:** หลาย session พร้อมกันผิดปกติ = บัญชีถูกใช้หลายที่ (sharing/takeover)

### 17. active_subsystem_count
- **ข้อมูล:** `login_sessions.subsystem_id`
- **คำนวณ:** `COUNT(DISTINCT subsystem_id)` ของ session ที่ active (logout_at IS NULL, ภายใน 60m)
- **Range:** 0–N (จำนวน subsystem ในระบบ)
- **เหตุผล:** เข้าหลายระบบพร้อมกันผิดจาก pattern ปกติ = **lateral movement** signal

---

## หมวด Behavioral 🆕

### 18. weekday_usage_score *(personalized)*
- **ข้อมูล:** `login_sessions.created_at` (history ของ user)
- **คำนวณ:** สัดส่วนที่ "วันนี้ไม่ใช่วันที่ user มักใช้งาน"
  ```
  score = 1 − (จำนวน login ในอดีตที่ตรง weekday วันนี้ / total login)
  ```
  ค่าสูง = วันนี้เป็นวันที่ user แทบไม่เคย login (เช่น คนใช้จันทร์–ศุกร์ แต่ login วันอาทิตย์)
- **Cold start:** history < 5 → `0.0`
- **เหตุผล:** personalized weekday baseline — แม่นกว่า `is_weekend` เดิม (ที่ถูกตัด)

---

## หมวด OAuth 🆕

### 19. scope_sensitivity_score
- **ข้อมูล:** `subsystems.scope` (array) ของ subsystem ที่กำลัง login (`login_sessions.subsystem_id`)
- **คำนวณ:** ผลรวม weight ของแต่ละ scope ที่ขอ แล้ว normalize
  ```
  weight ตัวอย่าง (static map):
    email, name            = 0.1   (PII ทั่วไป)
    faculty, major         = 0.3   (PII ระดับกลาง)
    student_id, employee_id= 0.6   (identifier — sensitive)
  score = min(sum(weights), 1.0)
  ```
- **Range:** 0.0–1.0
- **เหตุผล:** subsystem ที่ขอข้อมูล sensitive มาก = ความเสียหายสูงถ้าถูกโจมตี → ควรเพิ่มน้ำหนักความเสี่ยง
- **หมายเหตุ:** Hub-direct login (ไม่มี subsystem) → `0.0`

---

## หมวด Privilege 🆕

### 20. permission_change_age
- **ข้อมูล:** `access_list.granted_at` + `revoked_at` ของ user
- **คำนวณ:** วันตั้งแต่การเปลี่ยนสิทธิ์ล่าสุด (max ของ granted_at/revoked_at ทั้งหมด)
  ```
  age_days = (now − latest_permission_change) / 1 day
  ```
- **Cold start:** ไม่เคยเปลี่ยนสิทธิ์ → ค่าใหญ่ (เช่น 9999 = neutral, เสี่ยงต่ำ)
- **เหตุผล:** สิทธิ์เพิ่งเปลี่ยน (age น้อย) + login ผิดปกติ = สัญญาณ privilege escalation / ATO
- **หมายเหตุ:** รวม `recent_role_change` ที่เสนอไว้เดิม (binary) เข้าเป็นตัวต่อเนื่องตัวเดียว — กัน collinearity

---

## หมวด History (Ground-Truth) 🆕

### 21. confirmed_incident_count
- **ข้อมูล:** `login_sessions.is_account_takeover` + `is_attack_ip` (history ของ user)
- **คำนวณ:**
  ```sql
  COUNT(*) WHERE user_id = :uid
    AND (is_account_takeover = true OR is_attack_ip = true)
  ```
- **Range:** 0–N
- **เหตุผล:** user ที่เคยมี incident จริง = profile เสี่ยง
- **⚠️ ทำไมไม่ใช้ `risk_history_score` (จาก anomaly_score เดิม):** การเอา **output ของโมเดลมาเป็น input ตัวเอง** = feedback loop / error amplification + train-serve skew → ใช้ **ground-truth label** (`is_account_takeover`) แทน = defensible กว่า ตอบกรรมการได้

---

# Features ที่ตัดออก (เก็บไว้อ้างอิง)

| Feature | เหตุผลที่ตัด |
|---|---|
| `is_weekend` | = `f(day_of_week)` (day ≥ 5) — collinear 100%; `weekday_usage_score` ให้เวอร์ชัน personalized ที่ดีกว่า |
| `has_passkey` | = `f(passkey_count > 0)` — collinear 100% |
| `recent_role_change` *(เคยเสนอ)* | ซ้ำ `permission_change_age` (แหล่ง+เหตุการณ์เดียวกัน) |
| `session_creation_rate` *(เคยเสนอ)* | ซ้ำ `login_count_24h` |
| `risk_history_score` *(เคยเสนอ)* | feedback loop → แทนด้วย `confirmed_incident_count` |

---

# ตารางอ้างอิงแหล่งข้อมูล (ใช้ table ไหนบ้าง)

| Table / Source | Columns ที่ใช้ | Features |
|---|---|---|
| **login ปัจจุบัน** (request) | timestamp, IP, user_agent | 1, 2, 7, 8 |
| **GeoIP** (offline) | geo_country | 4 |
| `login_sessions` | created_at | 3, 9, 10, 18 |
| `login_sessions` | geo_country | 5, 6 |
| `login_sessions` | user_agent | 7, 8 |
| `login_sessions` | decision | 11 |
| `login_sessions` | logout_at, created_at | 16 |
| `login_sessions` | subsystem_id, logout_at | 17 |
| `login_sessions` | is_account_takeover, is_attack_ip | 21 |
| `passkey_credentials` | created_at, last_used_at, revoked_at | 12, 13, 14, 15 |
| `subsystems` | scope | 19 |
| `access_list` | granted_at, revoked_at | 20 |

---

# Implementation Contract (B27)

เพิ่ม/ตัด feature ต้องแก้ **3 ที่พร้อมกัน** แล้ว **retrain** ไม่งั้น feature-count mismatch:

1. `ml-service/app/features.py` — `FEATURE_NAMES` + `FEATURE_RANGES` (เรียงลำดับ 1→21)
2. `ml-service/scripts/generate_data.py` — สร้างค่า synthetic ของ feature ใหม่ **ให้ ATO pattern โผล่จริง** (เช่น ATO = active_subsystem พุ่ง + permission_change_age ต่ำ + concurrent สูง + confirmed_incident > 0) ไม่งั้น feature ใหม่ = noise
3. `hub/backend/app/services/feature_extraction.py` — สกัดจาก DB ตามลำดับเดียวกัน
4. retrain: `generate_data` → `train_model` → restart `hub-backend`

**⚠️ หมายเหตุการประเมิน:** โมเดลเทรนบน synthetic data — ควรเพิ่ม feature **ทีละชุด + วัด AUC/feature-importance** ไม่ใช่ใส่รวด (กัน overfit + curse of dimensionality บน 21 มิติ)
