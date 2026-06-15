# ML Explained — Hybrid RBA (Central Auth Hub)

**อธิบายระบบ ML ทั้งหมด: 4 Layers + 22 features (ข้อมูล/สูตร/ตัวอย่าง/หน่วย) + SHAP**
Version 1.0 · 2026-06-15 · คู่กับ `ML_FEATURE_DATA_SOURCES.md`

---

## 1. ภาพรวม — 4 Layers

ทุก login ถูกประเมินผ่าน 4 ชั้น แล้วรวมเป็น decision เดียว:

```
login → [Layer 1 Rule] → ถ้า hard block → block ทันที
             ↓ (ไม่ block)
        [Layer 2 Behavior] เทียบ baseline ส่วนตัว 30 วัน
             ↓
        [Layer 3 Isolation Forest] โมเดล anomaly (22 features) + SHAP
             ↓
        [Layer 4 Aggregation] total = rule + behavior + iforest → decision
```

| Layer | ทำอะไร | output |
|---|---|---|
| 1 Rule | กฎตายตัว (จับ known attack เร็ว) | hard block หรือ score 0–1 |
| 2 Behavior | เทียบ pattern ส่วนตัว (เวลา/วัน/ประเทศ) | score 0–1 |
| 3 IForest | โมเดล unsupervised บน 22 features | score 0–0.4 + SHAP |
| 4 Aggregate | รวม 3 ชั้น cap 1.0 → ตัดสิน | allow/warn/challenge/block |

**Decision thresholds** (Layer 4): `block ≥ 0.8 · challenge ≥ 0.5 · warn ≥ 0.3 · else allow`
(Shadow Mode → would_block / would_challenge / would_warn)

---

## 2. แต่ละ Layer ใช้ข้อมูล/feature อะไร

### Layer 1 — Rule Engine
- **ข้อมูลนอก feature:** IP blacklist (ipsum), impossible travel (geo+เวลา), multi-account จาก IP เดียว
- **feature ที่อ่าน:** `is_new_device` `is_new_country` `is_new_user_agent_family` `failed_logins_24h` `is_thailand`
- **hard block ถ้า:** `failed_logins_24h ≥ 10` หรือ `login_count_24h ≥ 50` หรือ `country_change_count_30d ≥ 8` หรือ IP blacklist

### Layer 2 — Behavior Profiling
- ต้องมี history ≥ 5 session (ไม่งั้น cold start score = 0.20)
- **feature ที่อ่าน:** `hours_from_typical_login_time` `is_new_country` `is_new_device` `day_of_week` (คำนวณ weekend)

### Layer 3 — Isolation Forest
- ใช้ **ครบทั้ง 22 features** → anomaly score → map เป็น 0–0.4 + SHAP per-feature

### Layer 4 — Aggregation
- `total = min(rule + behavior + iforest, 1.0)` → decision

---

## 3. 22 Features — ข้อมูล / สูตร / ตัวอย่าง / หน่วย

> ค่าทั้งหมดสกัดตอน login จาก **request ปัจจุบัน + ประวัติใน DB** (`feature_extraction.py`)

### 🕐 Temporal (เวลา)

**1. hour_of_day** — ชั่วโมงที่ login
- ข้อมูล: timestamp ของ login (UTC) · สูตร: `now.hour`
- ตัวอย่าง: login 14:30 UTC → **14**
- หน่วย: ชั่วโมงของวัน (0–23)

**2. day_of_week** — วันในสัปดาห์
- ข้อมูล: timestamp · สูตร: `now.weekday()` (จันทร์=0)
- ตัวอย่าง: วันพุธ → **2**
- หน่วย: เลขวัน (0–6)

**3. hours_from_typical_login_time** — ห่างจากเวลาที่ใช้ประจำ
- ข้อมูล: `login_sessions.created_at` (50 ครั้งล่าสุด) · สูตร: `min(|now.hour − median(ชม.ในอดีต)|, 24−diff)` · cold start (<5) = 0
- ตัวอย่าง: ปกติ login ~9 โมง, วันนี้ 21 โมง → \|21−9\|=12, min(12, 24−12=12) = **12**
- หน่วย: ชั่วโมง (0–12)

### 🌍 Geographic (ภูมิศาสตร์)

**4. is_thailand** — login จากไทยไหม
- ข้อมูล: GeoIP(IP) → geo_country · สูตร: 1 ถ้า ∈{TH}; geo NULL → 1
- ตัวอย่าง: geo=JP → **0** · geo=TH → **1**
- หน่วย: boolean (0/1)

**5. is_new_country** — ประเทศที่ไม่เคยเห็น
- ข้อมูล: `login_sessions.geo_country` (distinct history) · สูตร: 1 ถ้า geo ปัจจุบันไม่อยู่ใน history
- ตัวอย่าง: เคย TH ตลอด วันนี้ US → **1**
- หน่วย: boolean (0/1)

**6. country_change_count_30d** — จำนวนประเทศใน 30 วัน
- ข้อมูล: geo_country (30 วันล่าสุด) · สูตร: นับประเทศ distinct
- ตัวอย่าง: 30 วันมี {TH, JP, US} → **3**
- หน่วย: จำนวนประเทศ (count, 0–30)

### 💻 Device (อุปกรณ์)

**7. is_new_device** — อุปกรณ์ใหม่
- ข้อมูล: `login_sessions.user_agent` (history) · สูตร: 1 ถ้า UA ไม่เคยเห็น
- ตัวอย่าง: login จากเครื่องใหม่ → **1**
- หน่วย: boolean (0/1)

**8. is_new_user_agent_family** — เบราว์เซอร์ใหม่
- ข้อมูล: user_agent → browser family · สูตร: 1 ถ้า family (Chrome/Firefox/Edge/Safari/Opera) ไม่เคยเห็น
- ตัวอย่าง: เคยใช้ Chrome วันนี้ Firefox → **1**
- หน่วย: boolean (0/1)

### ⚡ Velocity (ความถี่)

**9. log_minutes_since_last_login** — เวลาห่างจาก login ก่อน (log)
- ข้อมูล: created_at ของ session ล่าสุด · สูตร: `ln(max(Δนาที, 0.5))` · ไม่มี login เก่า = 6.0
- ตัวอย่าง: ห่าง 60 นาที → ln(60) = **4.09**
- หน่วย: ln(นาที) — log scale

**10. login_count_24h** — จำนวนล็อกอินใน 24 ชม.
- ข้อมูล: นับ session ใน 24 ชม. · สูตร: COUNT
- ตัวอย่าง: login 5 ครั้งวันนี้ → **5**
- หน่วย: จำนวนครั้ง (count)

### 🛡️ Brute Force

**11. failed_logins_24h** — ล็อกอินล้มเหลวใน 24 ชม.
- ข้อมูล: `login_sessions.decision` · สูตร: นับ `decision ∈ {block, would_block}` ใน 24 ชม.
- ตัวอย่าง: ถูกบล็อก 3 ครั้ง → **3**
- หน่วย: จำนวนครั้ง (count)

### 🔑 Passkey (ความน่าเชื่อถืออุปกรณ์)

**12. passkey_count** — จำนวน Passkey
- ข้อมูล: `passkey_credentials` (active) · สูตร: COUNT · ตัวอย่าง: มี 2 → **2** · หน่วย: count (0–20)

**13. passkey_age_days** — อายุ Passkey เก่าสุด
- ข้อมูล: `passkey_credentials.created_at` · สูตร: `(now − เก่าสุด)/86400`
- ตัวอย่าง: สร้าง 30 วันก่อน → **30** · หน่วย: วัน

**14. new_passkey_recently_added** — เพิ่งเพิ่ม Passkey
- ข้อมูล: passkey ใหม่สุด · สูตร: 1 ถ้า < 1 ชม. · ตัวอย่าง: เพิ่มเมื่อ 10 นาที → **1** · หน่วย: boolean

**15. passkey_last_used_days** — ใช้ Passkey ล่าสุดกี่วัน
- ข้อมูล: `last_used_at` · สูตร: `(now − ใช้ล่าสุด)/86400`
- ตัวอย่าง: ใช้เมื่อวาน → **1** · หน่วย: วัน

### 👥 Session

**16. concurrent_session_count** — เซสชันที่ active พร้อมกัน
- ข้อมูล: `logout_at` + `created_at` · สูตร: นับ `logout_at IS NULL ∧ created < 60 นาที`
- ตัวอย่าง: เปิดค้าง 2 ที่ → **2** · หน่วย: จำนวน session (count)

**17. active_subsystem_count** — ระบบย่อยที่ใช้พร้อมกัน
- ข้อมูล: `subsystem_id` ของ session active · สูตร: COUNT DISTINCT
- ตัวอย่าง: active ที่หอพัก + ห้องสมุด → **2** · หน่วย: จำนวนระบบ (count)

### 📊 Behavioral

**18. weekday_usage_score** — วันนี้ผิดจากวันที่ใช้ประจำ
- ข้อมูล: created_at (history) · สูตร: `1 − (login วันเดียวกับวันนี้ / login ทั้งหมด)` · cold start = 0
- ตัวอย่าง: 20 login ที่ผ่านมา ตรงวันจันทร์ 2 ครั้ง, วันนี้จันทร์ → 1 − 2/20 = **0.9**
- หน่วย: สัดส่วน (0–1)

### 🔓 OAuth

**19. scope_sensitivity_score** — ความอ่อนไหวของ scope ที่ระบบย่อยขอ
- ข้อมูล: `subsystems.scope` (ของ subsystem ที่ login) · สูตร: `Σ น้ำหนัก` cap 1.0
  (email/name=0.1 · faculty/major=0.3 · student_id/employee_id=0.6)
- ตัวอย่าง: scope=[email, name, student_id] → 0.1+0.1+0.6 = **0.8** · Hub-direct (ไม่มี subsystem) → **0**
- หน่วย: คะแนนถ่วงน้ำหนัก (0–1)

### 🔐 Privilege (แยก sentinel เป็น 2 ตัว)

**20. ever_changed_permission** — เคยเปลี่ยนสิทธิ์ไหม
- ข้อมูล: `access_list.granted_at/revoked_at` · สูตร: 1 ถ้ามีบันทึกการเปลี่ยน, ไม่งั้น 0
- ตัวอย่าง: ไม่เคยเปลี่ยน role → **0** · เคยได้/ถูกถอน role → **1**
- หน่วย: boolean (0/1)

**21. permission_change_age** — วันตั้งแต่เปลี่ยนสิทธิ์ล่าสุด
- ข้อมูล: `access_list` (granted/revoked ล่าสุด) · สูตร: `min((now − ล่าสุด)/86400, 365)` · ไม่เคยเปลี่ยน = 365
- ตัวอย่าง: เปลี่ยน role 3 วันก่อน → **3** · ไม่เคยเปลี่ยน → **365** (= เก่าสุด/ปลอดภัย)
- หน่วย: วัน (0–365) — **เปลี่ยนจาก sentinel 9999 เดิม กัน outlier ใน tree**

### 🚨 History (ground-truth)

**22. confirmed_incident_count** — เหตุการณ์เสี่ยงจริงในอดีต
- ข้อมูล: `login_sessions.is_account_takeover` / `is_attack_ip` (admin ยืนยัน) · สูตร: นับที่เป็น true
- ตัวอย่าง: เคยถูก mark เป็น attack 1 ครั้ง → **1** · หน่วย: จำนวนครั้ง (count)

---

## 4. สรุปประเภทหน่วย (7 แบบ)

| หน่วย | features |
|---|---|
| boolean (0/1) | is_thailand, is_new_country, is_new_device, is_new_user_agent_family, new_passkey_recently_added, ever_changed_permission |
| จำนวน/count | country_change_count_30d, login_count_24h, failed_logins_24h, passkey_count, concurrent_session_count, active_subsystem_count, confirmed_incident_count |
| วัน (days) | passkey_age_days, passkey_last_used_days, permission_change_age |
| ชั่วโมง (hours) | hour_of_day, hours_from_typical_login_time |
| เลขวัน (ordinal) | day_of_week |
| สัดส่วน/คะแนน (0–1) | weekday_usage_score, scope_sensitivity_score |
| log-scale | log_minutes_since_last_login |

---

## 5. อธิบาย SHAP (Layer 3)

SHAP บอกว่า **แต่ละ feature ดันคะแนน anomaly ของ login นี้ไปทางไหน เท่าไหร่** (per-login, ไม่ใช่ค่าคงที่)

### วิธีอ่าน 1 แถว
```
จำนวนประเทศใน 30 วัน = 1            +1.689
└─ ชื่อ feature(ไทย) ┘ └ค่าจริง┘    └ค่า SHAP┘
```
- **ซ้าย** = ชื่อ feature + **ค่าจริงของ login นี้**
- **ขวา** = **SHAP value** — ดันคะแนนเท่าไหร่
- 🔴 **แดง / +** = ดันให้ดู **ผิดปกติมากขึ้น** (toward anomaly)
- 🟢 **เขียว / −** = ดันให้ดู **ปกติ** (toward normal)
- เรียงจาก |ค่า| มาก → น้อย (top 5)
- **additive:** base + Σ(SHAP ทุกตัว) = anomaly score สุดท้าย

### ตัวอย่างจริง (ก่อน vs หลังแก้ permission)
| feature | ค่า | SHAP เดิม | SHAP หลังแก้ |
|---|---|---|---|
| permission (ไม่เคยเปลี่ยน) | 9999 → ever=0,age=365 | 🔴 +0.467 (ผิด!) | 🟢 −0.231 (ถูก: ปลอดภัย) |

→ การแยก `ever_changed_permission` + cap 365 ทำให้ "ไม่เคยเปลี่ยนสิทธิ์" อ่านเป็น **ปกติ** ตามที่ควร (เดิม sentinel 9999 เป็นเลขโดด tree เลยมองว่าแปลก)

### ⚠️ ข้อควรรู้เรื่อง SHAP
- SHAP อธิบาย **เหตุผลของโมเดล** ไม่ใช่ "ความจริง" — ถ้า feature ออกแบบไม่ดี SHAP ก็สะท้อนความเพี้ยนนั้น
- ค่า SHAP เป็นสเกลของ decision function (ไม่ใช่ 0–1) — ดู **เครื่องหมาย + ขนาดเทียบกัน** พอ
- top 5 = ตัวขับหลัก; ตัวอื่นมีผลแต่เล็ก

---

## 6. หมายเหตุสำคัญ
- **เทรนบน synthetic data** — ดู `ML_IMPROVEMENT_PLAN.md` (รากฐานที่ยังขาด: real labeled eval)
- **Cold start** (history < 5) → personalized features = neutral (ไม่ลงโทษ user ใหม่)
- **Dev**: IP `172.18.0.1` ไม่มี geo → feature geo เป็น neutral; prod ที่มี IP จริงจะแม่นกว่า
- **Contract (B49)**: เปลี่ยน feature order ต้อง sync 4 ไฟล์ (features.py / generate_data.py / feature_extraction.py / rule_engine.FEAT)
