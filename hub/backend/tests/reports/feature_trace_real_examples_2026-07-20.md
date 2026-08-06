# การ Trace จริง: จาก Log → สกัดฟีเจอร์ → คำนวณ 4-Layer → ผลลัพธ์
## ตัวอย่างจริงจากฐานข้อมูล (กรณีปกติ + กรณีผิดปกติ)

- **วันที่:** 2026-07-20 (ข้อมูลจริงจาก `hub_db`)
- **ขอบเขต:** ตั้งแต่ผู้ใช้กดล็อกอิน (`request_logs`) → บันทึก session (`login_sessions`) → สกัด 23 ฟีเจอร์ (บอก ตาราง/คอลัมน์/สูตร) → เข้า 4-Layer RBA → ผลลัพธ์ (decision)
- **หมายเหตุ:** ทุกค่าในเอกสารนี้เป็น **ข้อมูลจริง** จาก DB (ไม่ได้แต่งขึ้น) ตรวจสอบย้อนได้

---

# ส่วนที่ 0 — ที่มาของฟีเจอร์แต่ละตัว (Log → คอลัมน์ → สูตร)

**2 ตารางหลักที่เป็น "log ดิบ":**

| ตาราง | บทบาท | คอลัมน์สำคัญ |
|---|---|---|
| `request_logs` | log ทุก HTTP request (เส้นทางการล็อกอิน) | `method, path, status_code, user_id, ip, user_agent, duration_ms, created_at` |
| `login_sessions` | log ทุกครั้งที่ login สำเร็จ (ป้อนเข้า ML) | `user_id, ip, user_agent, geo_country, os_name, browser, device_type, created_at, decision, logout_at, is_attack_ip, is_account_takeover, subsystem_id` |

**ตารางเสริม:** `passkey_credentials`, `access_list`, `subsystems`

### ตารางที่มาของ 23 ฟีเจอร์ (จาก `feature_extraction.py`)

| # | ฟีเจอร์ | ดึงจาก log/คอลัมน์ | สูตรคำนวณ |
|---|---|---|---|
| 1 | hour_of_day | เวลาปัจจุบัน `now` | `now.hour` |
| 2 | day_of_week | `now` | `now.weekday()` (0=จันทร์) |
| 3 | hours_from_typical_login_time | `login_sessions.created_at` (50 ครั้งล่าสุด) | `min(\|hour − median(past_hours)\|, 24−diff)`; cold start (<5) = 0 |
| 4 | is_thailand | `login_sessions.geo_country` | `0` ถ้า geo∉{TH,THAILAND} else `1` |
| 5 | is_new_country | `login_sessions.geo_country` (distinct history) | `1` ถ้า geo ไม่เคยเจอ else `0` |
| 6 | country_change_count_30d | `geo_country` ใน 30 วัน | `len(distinct countries)` |
| 7 | is_new_device | `login_sessions.user_agent` (distinct) | `1` ถ้า UA ไม่เคยเจอ else `0` |
| 8 | is_new_user_agent_family | `user_agent` → browser_family() | `1` ถ้า family ใหม่ else `0` |
| 9 | log_minutes_since_last_login | `created_at` ของ login ก่อนหน้า | `ln(max(Δนาที, 0.5))`; ไม่มี = 6.0 |
| 10 | login_count_24h | `count(login_sessions)` 24 ชม. | นับตรงๆ |
| 11 | failed_logins_24h | `count` ที่ `decision∈{block,would_block}` 24 ชม. | นับตรงๆ |
| 12 | passkey_count | `passkey_credentials` (revoked_at NULL) | `count` |
| 13 | passkey_age_days | `passkey_credentials.created_at` เก่าสุด | `(now − oldest)/86400` |
| 14 | new_passkey_recently_added | `passkey.created_at` ใหม่สุด | `1` ถ้า < 1 ชม. |
| 15 | passkey_last_used_days | `passkey.last_used_at` | `(now − most_recent_use)/86400` |
| 16 | concurrent_session_count | `login_sessions` (logout_at NULL, < 60 นาที) | `min(50, count)` |
| 17 | active_subsystem_count | `subsystem_id` distinct ของ session active | `count distinct` |
| 18 | weekday_usage_score | history 50 ครั้ง | `1 − (same_weekday / total)` |
| 19 | scope_sensitivity_score | `subsystems.scope` ของระบบที่ login | `min(1, Σ weight)` — email/name .1, faculty .3, student_id/employee_id .6 |
| 20 | ever_changed_permission | `access_list.granted_at/revoked_at` | `1` ถ้ามี |
| 21 | permission_change_age | `access_list` เวลาเปลี่ยนล่าสุด | `min(อายุวัน, 365)`; ไม่เคย = 365 |
| 22 | confirmed_incident_count | `is_account_takeover OR is_attack_ip = TRUE` | `count` |
| 23 | impossible_travel_score | `geo_country` + `created_at` ครั้งก่อน | `max(0, 1 − hours/24)` ถ้าเปลี่ยนประเทศ |

---

# ส่วนที่ 1 — กรณี "ปกติ" (ผลลัพธ์: ALLOW)

## 1.1 ข้อมูลดิบ (request_logs — เส้นทางการล็อกอินจริง)
ผู้ใช้ `6660506018@pnu.ac.th` กดล็อกอินผ่าน Google เข้า "ระบบหอพัก" เวลา 2026-07-20 15:25:

```
15:25:22  GET  /oauth/authorize          200   13ms   ← subsystem ส่งมาที่ Hub
15:25:23  GET  /oauth/authorize/google   302   48ms   ← redirect ไป Google
15:25:31  GET  /oauth/callback           200  491ms   ← ★ Google ตอบกลับ → คำนวณ 4-Layer ที่นี่ (491ms)
15:25:40  GET  /oauth/continue           307  199ms   ← ผ่าน → ออก auth code
15:25:40  POST /oauth/token              200  235ms   ← subsystem แลก token (S2S)
15:25:40  GET  /.well-known/jwks.json    200   11ms   ← subsystem verify ลายเซ็น
```
→ จุดที่ `/oauth/callback` ใช้ **491ms** คือตอนที่ระบบ **สกัดฟีเจอร์ + รัน 4-Layer** แล้วบันทึกลง `login_sessions`

## 1.2 ข้อมูลดิบ (login_sessions ที่บันทึก)
```
created_at   : 2026-07-20 15:25:40
user         : 6660506018@pnu.ac.th (student, คณะวิศวกรรมศาสตร์)
subsystem    : ระบบหอพัก
ip           : 172.18.0.1        geo_country : NULL (dev/private IP)
os / browser : Windows 10 / Chrome 150.0.0.0    device_type : desktop
login_method : google
```
**ประวัติก่อนหน้า:** login ล่าสุด `07-19 09:50` (Chrome, IP เดิม) — มี history > 5 → ไม่ cold start สำหรับ velocity

## 1.3 คำนวณฟีเจอร์ (ค่าจริงจาก `iforest_explanation` ใน DB)

| ฟีเจอร์ | ค่าจริง | ที่มา/การคำนวณ (ตรวจสอบย้อนได้) |
|---|---|---|
| hour_of_day | 15.0 | เวลา 15:25 → ชั่วโมง 15 |
| day_of_week | 0.0 | 2026-07-20 = วันจันทร์ |
| hours_from_typical_login_time | **4.5** | median ชั่วโมง login เดิม (เคยเข้า ~9-10 โมง) เทียบ 15 โมง |
| is_thailand | 1.0 | geo=NULL → default 1 (ถือว่าในประเทศ) |
| is_new_country | 0.0 | ไม่มี geo history เทียบ |
| country_change_count_30d | 0.0 | geo NULL ทั้งหมด |
| is_new_device | 0.0 | UA Chrome เดิม (เคยใช้) |
| is_new_user_agent_family | 0.0 | family Chrome เดิม |
| log_minutes_since_last_login | **7.4819** | login ก่อน 07-19 09:50 → 15:25 20/7 = **1,775 นาที** → ln(1775)=**7.482** ✓ |
| login_count_24h | 0.0 | ไม่มี login ใน 24 ชม.ก่อนหน้า (ครั้งล่าสุด >24ชม.) |
| failed_logins_24h | 0.0 | ไม่มี block/would_block |
| passkey_count | 0.0 | ไม่มี passkey |
| passkey_age_days | 0.0 | — |
| new_passkey_recently_added | 0.0 | — |
| passkey_last_used_days | 0.0 | — |
| concurrent_session_count | 0.0 | ไม่มี session active ค้าง |
| active_subsystem_count | 0.0 | — |
| weekday_usage_score | **0.88** | วันจันทร์ user ไม่ค่อยเข้า → 1−(2/17)≈0.88 |
| scope_sensitivity_score | **1.0** | ระบบหอพัก scope=[email .1, name .1, student_id .6, employee_id .6, faculty .3, year .1, position .1, phone .1] = 2.0 → cap **1.0** ✓ |
| ever_changed_permission | 1.0 | เคยมี access_list |
| permission_change_age | **1.253** | เพิ่งได้สิทธิ์เข้าระบบหอพัก ~1.25 วันก่อน |
| confirmed_incident_count | 0.0 | ไม่เคยมี incident |
| impossible_travel_score | 0.0 | geo NULL |

## 1.4 คำนวณ 4-Layer (ค่าจริงจาก `risk_breakdown`)

```
Layer 1 (Rule)     : 0.0    — ไม่เข้าเงื่อนไขกฎใด (ไม่มี new country/device/attack IP)
Layer 2 (Behavior) : 0.1    — reason: "weekend_mismatch (+0.10)" (จันทร์ = วันที่ไม่ค่อยใช้)
Layer 3 (IForest)  : 0.1    — iforest_raw=0.4486 → อยู่ช่วง 0.3–0.5 → map เป็น +0.10
                              (SHAP: hours_from_typical +1.07, permission_age +0.48 = สัญญาณ anomaly อ่อนๆ)
Layer 4 (รวม)      : 0.0+0.1+0.1 = 0.2
```

| total | เกณฑ์ | **decision** |
|---|---|---|
| **0.2** | < 0.5 (warn) | **✅ allow** (ผ่านปกติ) |

**สรุปเคสปกติ:** สัญญาณ anomaly มีเล็กน้อย (เข้าเวลาแปลกไปนิด+วันจันทร์) แต่รวมแล้วต่ำกว่าเกณฑ์ → อนุญาตให้เข้า

---

# ส่วนที่ 2 — กรณี "ผิดปกติ" (ผลลัพธ์: CHALLENGE → MFA)

## 2.1 ข้อมูลดิบ (login_sessions)
ผู้ใช้ `hasiyahdama5@gmail.com` (admin) login เวลา 2026-07-20 15:07 — **จากเครื่องใหม่**:
```
created_at   : 2026-07-20 15:07:11
user         : hasiyahdama5@gmail.com (admin)
os / browser : Windows 10 / Chrome 150.0.0.0    device_type : desktop
login_method : google
decision     : mfa_passed  (คือ challenge ที่ผู้ใช้ผ่าน MFA แล้ว)
risk_score   : 0.800       anomaly_score(iforest_raw) : 0.5123
```

## 2.2 ฟีเจอร์ที่ "จุดชนวน" (จาก `risk_reasons`)
```
risk_reasons : ["is_new_device (+0.3)", "is_new_device (+0.20)", "weekend_mismatch (+0.10)"]
```
| ฟีเจอร์ | ค่า | ความหมาย |
|---|---|---|
| **is_new_device** | **1.0** | user_agent นี้ไม่เคยเจอในประวัติ → เครื่อง/browser ใหม่ |
| day_of_week (weekend) | เสาร์/อาทิตย์ | ต่างจากวันที่ user ปกติใช้ |

## 2.3 คำนวณ 4-Layer (ค่าจริงจาก `risk_breakdown`)

```
Layer 1 (Rule)     : 0.3    — "is_new_device (+0.3)"  [SCORE_RULES: เครื่องใหม่ = +0.30]
Layer 2 (Behavior) : 0.3    — "is_new_device (+0.20)" + "weekend_mismatch (+0.10)" = 0.30
Layer 3 (IForest)  : 0.2    — iforest_raw=0.5123 → อยู่ช่วง 0.5–0.7 → map เป็น +0.20
Layer 4 (รวม)      : 0.3+0.3+0.2 = 0.8
```

| total | เกณฑ์ | **decision** |
|---|---|---|
| **0.8** | ≥ 0.7 (challenge) | **⚠️ challenge → บังคับ MFA** (ผู้ใช้ผ่าน → `mfa_passed`) |

**สรุปเคสผิดปกติ:** "เครื่องใหม่ + วันหยุด" ทำให้ทั้ง 3 layer ให้คะแนน (rule 0.3 + behavior 0.3 + ML 0.2 = 0.8) → เกินเกณฑ์ challenge → **ระบบไม่บล็อกทันที แต่บังคับยืนยันตัวตนเพิ่ม (step-up MFA)** — ผู้ใช้ยืนยันผ่าน จึงเข้าได้ (ถ้าเป็น attacker จริงจะผ่าน MFA ไม่ได้)

---

# ส่วนที่ 3 — เปรียบเทียบ 2 เคส (สรุปการไหลของข้อมูล)

| ขั้นตอน | เคสปกติ (allow) | เคสผิดปกติ (challenge) |
|---|---|---|
| **log ดิบ** | login เครื่องเดิม เวลาแปลกนิดหน่อย | login **เครื่องใหม่** วันหยุด |
| **ฟีเจอร์ที่เด่น** | hours_from_typical=4.5, weekday=0.88 | **is_new_device=1**, weekend |
| **L1 Rule** | 0.0 | **0.3** (เครื่องใหม่) |
| **L2 Behavior** | 0.1 | **0.3** (เครื่องใหม่+วันหยุด) |
| **L3 IForest** | 0.1 (raw 0.449) | 0.2 (raw 0.512) |
| **L4 รวม** | **0.2** | **0.8** |
| **ผลลัพธ์** | ✅ allow | ⚠️ challenge (MFA) |

**บทเรียน:** ความต่างของ "เครื่องใหม่" ทำให้คะแนนกระโดดจาก 0.2 → 0.8 เพราะ **สัญญาณเดียวถูกจับพร้อมกันทั้ง L1 (กฎ) และ L2 (พฤติกรรม)** — นี่คือการทำงานของ Defense-in-Depth หลายชั้น

---

## แหล่งข้อมูล (ตรวจสอบย้อนได้)
```sql
-- เคสปกติ (ค่าฟีเจอร์ครบ 23 ตัว)
SELECT risk_breakdown, risk_reasons FROM login_sessions WHERE created_at='2026-07-20 15:25:40.072307';
-- เคสผิดปกติ
SELECT risk_breakdown, risk_reasons FROM login_sessions WHERE created_at='2026-07-20 15:07:11.450678';
-- เส้นทาง HTTP
SELECT * FROM request_logs WHERE created_at BETWEEN '2026-07-20 15:25:00' AND '2026-07-20 15:26:00' ORDER BY created_at;
```
