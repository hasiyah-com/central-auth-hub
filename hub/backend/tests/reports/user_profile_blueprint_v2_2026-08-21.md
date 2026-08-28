# เค้าโครงโปรไฟล์ผู้ใช้ (User Profile Blueprint) — Feature Contract V2 · FINAL

> จัดทำ 21 ส.ค. 2026 · สอดคล้องกับ `RBA_Feature_Contract_V2_Experiment_Report_TH`
> แหล่งอ้างอิงพฤติกรรม: `users.xlsx` (114 คน), `login_sessions1.csv` (62 sessions / 7 คนจริง), `audit_logs.csv` (454 แถว)

**พารามิเตอร์ที่ยืนยันแล้ว:** 12 คน · **60–100 แถว/คน** · ช่วง **1 เดือน** · ไม่มี `SUB_C` · ใช้ email/user_id จริง (เก็บนอก git)

---

## 1. ข้อจำกัดที่ยึดตายตัว

| ข้อ | ค่า | เหตุผล |
|---|---|---|
| IP | **`192.168.10.1` ทุกเหตุการณ์** | scope NAT/shared network — ตรงข้อมูลจริง (62/62 sessions) |
| Geo | **ไม่มี** (`geo_country = NULL`) | campus NAT บัง client IP → ไม่เดาประเทศจาก private IP |
| ตัวตน | **alias `U01`–`U12`** ในเอกสาร · email/user_id จริงตอนสร้างข้อมูล | เอกสารนี้อยู่ใน git จึงห้ามมี PII — mapping alias→email เก็บที่ `ml-service/data/roster_v2.json` (gitignored) |
| ช่วงเวลา | **2026-07-22 → 2026-08-21** (30 วัน) | 1 เดือนล่าสุด |

> ⚠️ **PII** — ไฟล์ผลลัพธ์มีอีเมล/ชื่อจริง/UUID จริง → **ต้องอยู่ใน `.gitignore` ห้าม commit**

**ผลต่อฟีเจอร์ — 5 ตัวเป็นค่าคงที่ (ไม่ใช่ข้อมูลหาย แต่ "ไม่มีสัญญาณ"):**

```
is_thailand              = 1.0   (default เมื่อ geo = NULL)
is_new_country           = 0.0
country_change_count_30d = 0.0
impossible_travel_score  = 0.0
is_attack_ip             = 0.0   (IP เดียวและเป็น private)
```

คงคอลัมน์ไว้ใน contract เพื่อ portability · **ไม่มี train/serve skew** เพราะคงที่ทั้งตอนเทรนและตอนใช้

---

## 2. Schema ของโปรไฟล์ 1 คน (knob → ป้อนชั้นไหน)

ตาม Feature Contract V2 — **เจ้าของชั้นเดียว ห้าม double-count**

| กลุ่ม | Knob | ป้อนชั้น |
|---|---|---|
| **Temporal** | `hour_peaks`, `hour_spread` | Behavior (hour rarity) · ML (cyclic hour residual) |
| | `weekend_rate` | Behavior (weekday rarity) |
| | `logins_per_day` (λ) | ML (interarrival, 7d count) · Rule (success 10m) |
| **Device** | `device_pool` + weights | Rule (new device/UA) · Behavior (device-signature rarity) |
| | `browser_drift_rate` | ML (entropy) — **ต้องไม่ทำให้ `is_new_device` เด้ง** (B56) |
| **Subsystem** | `subsystem_mix`, `sticky` | Behavior (subsystem rarity, transition surprise) · ML (switch rate, entropy) |
| | `scope_sensitivity` | ML (scope) |
| **Session** | `duration_lognormal(μ,σ)` | ML (duration) |
| | `benign_overlap_rate`, `active_subsystem_typical` | Rule (concurrent, active subsystems) |
| **Auth** | `method_mix`, `passkey_state` | Rule (new passkey) · ML (passkey gap) |
| | `benign_fail_rate` | Rule (failed 1h) — **ต่ำกว่า threshold เสมอ** |
| **Policy** | `permission_change_age`, `confirmed_incident_count` | Rule (permission age, incident→block) |

---

## 3. Roster 12 คน

| # | role | ตำแหน่ง/คณะ | ที่มาพฤติกรรม | แถว |
|---|---|---|---|---|
| **U01** | admin | Hub admin | 🔵 **anchor A** — 34 sessions จริง | 100 |
| **U02** | admin | A01 | archetype | 78 |
| **U03** | teacher | ผศ. · วิศวฯ คอม | 🔵 anchor (hour 15) | 60 |
| **U04** | teacher | วิศวฯ คอม | 🔵 anchor (hour 14) | 66 |
| **U05** | staff | **จนท. ฝ่ายหอพัก** | archetype → SUB_A | 78 |
| **U06** | staff | **บรรณารักษ์ สำนักหอสมุด** | archetype → SUB_B | 72 |
| **U07** | student | วิศวฯ คอม ปี4 | 🔵 **anchor B** — 14 sessions (เช้ามืด) | 66 |
| **U08** | student | วิศวฯ คอม ปี3 | 🔵 **anchor C** — 10 sessions | 99 |
| **U09** | student | วิศวฯ คอม ปี4 | 🔵 anchor (hour 9, desktop) | 72 |
| **U10** | student | วิศวฯ คอม ปี4 | 🔵 anchor (hour 9, desktop) | 78 |
| **U11** | student | วิศวฯ คอม ปี4 | archetype (ดึก, mobile) | 84 |
| **U12** | student | **แพทยศาสตร์ ปี4** | archetype (multi-device) | 75 |

🔵 = พฤติกรรมสกัดจากข้อมูลจริง (7 คน) · รวม normal ≈ **928 แถว**
> ตัวตนจริง (email/user_id) อยู่ใน `ml-service/data/roster_v2.json` เท่านั้น — **ไม่อยู่ใน git**
**Subsystem:** `HUB` (admin/dev console) · `SUB_A` = ระบบหอพัก · `SUB_B` = ระบบห้องสมุด

> **หมายเหตุ λ:** teacher/staff ในข้อมูลจริงมี session น้อยเพราะระบบเพิ่งใช้ ไม่ใช่เพราะบทบาทล็อกอินน้อย
> จึงตั้ง λ ≈ 2.0–2.6/วัน (เช้า+บ่าย) ให้อยู่ในกรอบ 60–100 แถว/คนตามที่กำหนด

---

## 4. รายละเอียดรายคน

ค่า 🔵 = วัดจากข้อมูลจริง · ค่าอื่น = archetype ของบทบาท

### U01 — admin (anchor A)
```yaml
scope_sensitivity: 0.8 ·  mfa_always: true
temporal: hour_peaks [8, 15] 🔵 · spread 3.5h (7–22) · weekend 0.20 🔵 · λ 3.4 🔵
device_pool:
  desktop/Win10/Chrome 151  w=0.72  🔵      # 33 ครั้ง
  desktop/Win10/Chrome 150  w=0.28  🔵      # 13 ครั้ง = version drift ของเครื่องเดิม
  browser_drift_rate: 0.15                  # ไม่นับเป็น new device (B56)
subsystem_mix: {HUB: 0.90, SUB_A: 0.10} 🔵 · sticky 0.85
session: lognormal(ln 25, 1.8) 🔵 หางยาว (จริง p50 11.5 / p90 748 / max 1302 นาที)
  overlap 0.10 · active_sub 1
auth: {google 0.82, passkey 0.18} 🔵 · passkey {count 1, age 30+, last_used 0–7}
  benign_fail 0.03
policy: {permission_change_age 365, incident 0}
```

### U02 — admin
```yaml
scope_sensitivity: 0.8 ·  mfa_always: true
temporal: peaks [9, 16] · spread 2.5h · weekend 0.10 · λ 2.6
device_pool: desktop/Win11/Edge 130 w=1.0 · drift 0.10
subsystem_mix: {HUB: 1.00}
session: lognormal(ln 20, 1.5) · overlap 0.08 · active_sub 1
auth: {google 0.70, passkey 0.30} · passkey {count 1, age 90, last_used 0–5} · fail 0.02
policy: {permission_change_age 365, incident 0}
```

### U03 — teacher (ผศ.)
```yaml
scope_sensitivity: 0.3
temporal: peaks [10, 15] 🔵 · spread 2h · weekend 0.05 · λ 2.0
device_pool: desktop/Win10/Chrome 151 🔵 w=1.0 · drift 0.12
subsystem_mix: {HUB: 0.60, SUB_B: 0.40} · sticky 0.80
session: lognormal(ln 15, 1.4) · overlap 0.05 · active_sub 1
auth: {google 0.85, passkey 0.15} 🔵 (มี passkey_registered + backup codes)
  passkey {count 1, age 14, last_used 0–10} · fail 0.02
policy: {permission_change_age 365, incident 0}
```

### U04 — teacher
```yaml
scope_sensitivity: 0.3
temporal: peaks [11, 14] 🔵 · spread 2h · weekend 0.00 · λ 2.2
device_pool: desktop/Win10/Chrome 150 w=0.85 · mobile/iOS 18.7 w=0.15
subsystem_mix: {SUB_B: 0.70, HUB: 0.30} · sticky 0.80
session: lognormal(ln 12, 1.3) · overlap 0.04 · active_sub 1
auth: {google 1.00} · passkey {count 0} · fail 0.02
policy: {permission_change_age 365, incident 0}
```

### U05 — staff (จนท. ฝ่ายหอพัก)
```yaml
scope_sensitivity: 0.6
temporal: peaks [9, 14] (ราชการ 8–17) · spread 2h · weekend 0.00 · λ 2.6
device_pool: desktop/Win10/Chrome 151 w=1.0 · drift 0.10
subsystem_mix: {SUB_A: 0.65, HUB: 0.35} · sticky 0.70   ← switch rate สูง (ดูแลหอพัก + portal)
session: lognormal(ln 18, 1.4) · overlap 0.06 · active_sub 1–2
auth: {google 1.00} · passkey {count 0} · fail 0.03
policy: {permission_change_age 120, incident 0}   ← เคยเปลี่ยนสิทธิ์ (ให้ Rule layer มีเคสจริงทดสอบ)
```

### U06 — staff (บรรณารักษ์)
```yaml
scope_sensitivity: 0.6
temporal: peaks [8, 16] · spread 2h · weekend 0.05 · λ 2.4
device_pool: desktop/Win11/Chrome 151 w=1.0 · drift 0.08
subsystem_mix: {SUB_B: 0.85, HUB: 0.15} · sticky 0.88
session: lognormal(ln 16, 1.4) · overlap 0.05 · active_sub 1
auth: {google 0.80, passkey 0.20} · passkey {count 1, age 60, last_used 0–14} · fail 0.02
policy: {permission_change_age 365, incident 0}
```

### U07 — student (anchor B) ⭐ เคสเวลาผิดแผน
```yaml
scope_sensitivity: 0.2
temporal:
  hour_peaks [5, 6] 🔵   # จริง [4,4,5,5,5,5,6,6,6,6,6,8,8,15] — ตื่นเช้ามืด
  spread 1.5h + outlier บ่าย ~7% · weekend 0.00 🔵 · λ 2.2 🔵
device_pool:
  mobile/iOS 18.7/FB in-app (FBAV 574)  w=0.62  🔵
  mobile/iOS 18.7/FB in-app (FBAV 573)  w=0.17  🔵  ← app version drift เครื่องเดิม
  tablet/iOS 18.7/FB in-app (iPad)      w=0.21  🔵
subsystem_mix: {SUB_A: 0.95, HUB: 0.05} 🔵
session: lognormal(ln 8, 1.0) · overlap 0.03 · active_sub 1
auth: {google 1.00} · passkey {count 0} · fail 0.04
policy: {permission_change_age 365, incident 0}
```
> ⭐ ชั่วโมงปกติของเขา (04–06) **ทับกับ "off_hours" ของคนอื่น** → ใช้พิสูจน์ว่า Behavior ตัดสิน
> จาก *ความเบี่ยงเบนรายคน* ไม่ใช่กฎเวลากลาง

### U08 — student (anchor C)
```yaml
scope_sensitivity: 0.2
temporal: peaks [8, 16] 🔵 · spread 2h · weekend 0.15 🔵 · λ 3.3 🔵
device_pool:
  desktop/Win10/Chrome 151        w=0.60  🔵
  mobile/Android 15/Chrome 123    w=0.25  🔵  (Vivo V2322)
  mobile/Android 10/Chrome 150    w=0.15  🔵
subsystem_mix: {SUB_A: 0.70, HUB: 0.30} 🔵 · sticky 0.75
session: lognormal(ln 10, 1.2) · overlap 0.05 · active_sub 1
auth: {google 1.00} · passkey {count 0} · fail 0.05
policy: {permission_change_age 365, incident 0}
```

### U09 — student
```yaml
scope_sensitivity: 0.2
temporal: peaks [9, 16] 🔵(anchor hour 9) · spread 2h · weekend 0.10 · λ 2.4
device_pool: desktop/Win10/Chrome 151 🔵 w=1.0 · drift 0.12
subsystem_mix: {SUB_B: 0.90, HUB: 0.10} · sticky 0.90   ← subsystem rarity ชัดมาก
session: lognormal(ln 14, 1.2) · overlap 0.03 · active_sub 1
auth: {google 1.00} · passkey {count 0} · fail 0.04
policy: {permission_change_age 365, incident 0}
```

### U10 — student
```yaml
scope_sensitivity: 0.2
temporal: peaks [9, 13] 🔵(anchor hour 9) · spread 2h · weekend 0.10 · λ 2.6
device_pool: desktop/Win10/Chrome 150 🔵 w=1.0 · drift 0.12
subsystem_mix: {SUB_A: 0.75, HUB: 0.25} · sticky 0.80
session: lognormal(ln 12, 1.2) · overlap 0.04 · active_sub 1
auth: {google 1.00} · passkey {count 0} · fail 0.04
policy: {permission_change_age 365, incident 0}
```

### U11 — student (ดึก, มือถือล้วน)
```yaml
scope_sensitivity: 0.2
temporal: peaks [20, 22] · spread 1.5h · weekend 0.30 · λ 2.8
device_pool: mobile/iOS 18.7/Safari w=1.0 · drift 0.05
subsystem_mix: {SUB_A: 1.00}
session: lognormal(ln 7, 1.0) · overlap 0.02 · active_sub 1
auth: {google 1.00} · passkey {count 0} · fail 0.06
policy: {permission_change_age 365, incident 0}
```

### U12 — student แพทยศาสตร์ ⭐ เคสยากของ device rarity
```yaml
scope_sensitivity: 0.2
temporal: peaks [9, 14, 19] (3 ช่วง) · spread 3h · weekend 0.20 · λ 2.5
device_pool:
  desktop/Win10/Chrome 151      w=0.40
  mobile/iOS 18.7/Safari        w=0.40
  tablet/iOS 18.7/FB in-app     w=0.20
  browser_drift_rate: 0.15
subsystem_mix: {SUB_A: 0.50, SUB_B: 0.50} · sticky 0.55
session: lognormal(ln 11, 1.3) · overlap 0.06 · active_sub 1–2
auth: {google 1.00} · passkey {count 0} · fail 0.05
policy: {permission_change_age 365, incident 0}
```
> ⭐ พิสูจน์ว่า Behavior ไม่ยิง false positive กับคนที่ *ปกติก็ใช้หลายเครื่องอยู่แล้ว*

---

## 5. Normal condition 2 แบบ (ตามรายงาน V2)

| แบบ | วิธีสร้าง | ใช้ตอบคำถาม |
|---|---|---|
| `staggered` | เวลาล็อกอินกระจายตาม `hour_peaks` ของแต่ละคน | baseline |
| `nat_burst` | 50% ของ login ถูกดึงเข้า **ชั่วโมง peak ร่วมของ campus** `[8, 9, 13, 16]` | พิสูจน์ว่า shared-IP burst **ไม่ถูกใช้เป็นหลักฐานเดี่ยว** ในการ challenge |

ทั้ง 2 แบบสร้างครบ 60–100 แถว/คน → เทียบ Recall/FPR ระหว่างกัน (รายงาน V2 พบต่างกันเพียง 0.2 จุด%)

---

## 6. Attack ที่แปะต่อคน (frozen — ไม่ปนกลับ history)

**20 แถว/คน × 12 คน = 240 แถว** · ทุกชนิดต่อยอดจาก snapshot ของ *คนนั้นเอง*
(9 scenario แรก × 2 แถว + 2 scenario สุดท้าย × 1 แถว = 20)

| # | scenario | ขั้นต่ำที่คาด | วิธีสร้าง (อิงโปรไฟล์คนนั้น) |
|---|---|---|---|
| 1 | `combined_ato` | **block** | new device + off-hours + velocity + subsystem ใหม่ พร้อมกัน |
| 2 | `new_device` | challenge | อุปกรณ์นอก `device_pool` (Linux/Firefox) |
| 3 | `new_ua_family` | challenge | device type เดิม แต่ browser family ใหม่ |
| 4 | `new_os` | warn | browser family เดิม OS ใหม่ (Win → macOS) |
| 5 | `off_hours` | warn | ชั่วโมงห่างจาก `hour_peaks` ของคนนั้น ≥8 ชม. |
| 6 | `failed_spike` | challenge | fail หลายครั้งใน 1 ชม. เกิน rule threshold |
| 7 | `login_velocity` | challenge | success หลายครั้งใน 10 นาที |
| 8 | `concurrent_sessions` | challenge | session ซ้อนเกิน `active_subsystem_typical` |
| 9 | `new_passkey` | challenge | passkey เพิ่งลงทะเบียนก่อน login ไม่กี่นาที |
| 10 | `permission_change` | challenge | `permission_change_age` = 0–1 วัน |
| 11 | `subsystem_lateral` | challenge | เข้า subsystem ที่ไม่เคยใช้ (weight = 0) |
| — | ~~`impossible_travel`~~ / ~~`new_country`~~ | — | ❌ **ตัดออก — ไม่มี geo** |

---

## 7. Output ที่จะสร้าง

```
ml-service/data/profiles_v2.json     โปรไฟล์ 12 คน (knob ทั้งหมด)
ml-service/data/logins_v2.csv        normal ~928×2 condition (label 0)
ml-service/data/attacks_v2.csv       attack 240 แถว (label 1, frozen, แยก scenario)
```
> ⚠️ ทั้ง 3 ไฟล์มี **PII จริง** → เพิ่มใน `.gitignore` ก่อนสร้าง

**สิ่งที่คาดหวังตามรายงาน V2 ที่ n≈60–100:** policy success ≈ **94.8–95.9%** · FPR ≈ 0.08–0.17%
(ต่ำกว่าโซน n=500–1,000 ที่ได้ 99.6% — เป็น trade-off ที่รับไว้เพื่อความสมจริงของช่วง 1 เดือน)
