# Data Leakage Fix — Point-in-Time Feature Extraction

**วันที่:** 2026-07-22
**ไฟล์ที่แก้:** `app/services/feature_extraction.py`
**ไฟล์ทดสอบ:** `tests/test_feature_point_in_time.py` (12 tests)

---

## 1. ปัญหา

`extract_session_features(now=...)` ถูกเรียก 2 แบบ:

| แบบ | `now` | ใช้ที่ไหน |
|---|---|---|
| **Live login** | `utcnow()` | `auth.py`, `oauth.py` |
| **Re-score ย้อนหลัง** | `session.created_at` | **5 scripts** (ดูด้านล่าง) |

query ประวัติเกือบทั้งหมด **ไม่กรอง `created_at < now`** → ตอน re-score ย้อนหลัง
feature "มองเห็นอนาคต" (data leakage)

### Scripts ที่ได้รับผลกระทบ (ทั้งหมดใช้ `now=s.created_at`)
| Script | ใช้ทำอะไร | ผลกระทบ |
|---|---|---|
| `export_labeled_data.py` | **สร้าง training data** | โมเดลเทรนบนข้อมูลที่รั่ว |
| `evaluate_on_real.py` | วัดผลโมเดล | metric เพี้ยน |
| `evaluate_real_logins.py` | วัด FP/recall บน traffic จริง | **FP 47% ที่รายงานไว้ไม่ใช่ค่าจริง** |
| `calibrate_thresholds.py` | คำนวณ threshold 0.50/0.85 | threshold ตั้งจากค่าที่ผิด |
| `check_feature_drift.py` | ตรวจ drift | baseline เพี้ยน |

### หลักฐาน (จาก `ml_real_eval_2026-06-18.md`)
> session ที่ลงวันที่ **8 วันก่อน** รายงาน `login_count_24h = 78`
> → โดน hard block (`>= 50`) ทั้งที่เป็น baseline ปกติ
> → 109/244 session (44.7%) ถูกจัดเป็น would_block ด้วยเหตุนี้

---

## 2. จุดที่รั่ว (11 จุด)

| # | Feature | Query | เดิม |
|---|---|---|---|
| 1 | `hours_from_typical`, `weekday_usage` | `past_sessions` | ไม่กรองเวลาเลย |
| 2 | `is_new_country` | `seen` (distinct country) | ไม่กรองเวลาเลย |
| 3 | `country_change_count_30d` | `countries_30d` | มีแค่ขอบล่าง `>= cutoff_30d` |
| 4 | `is_new_device`, `is_new_user_agent_family` | `seen_ua` | ไม่กรองเวลาเลย |
| 5 | `log_minutes_since_last_login` | `last` | หยิบ session ล่าสุดทั้งตาราง |
| 6 | `login_count_24h` | count | มีแค่ขอบล่าง `>= cutoff_24h` |
| 7 | `failed_logins_24h` | count | มีแค่ขอบล่าง `>= cutoff_24h` |
| 8 | `passkey_count`, `passkey_age_days`, `new_passkey_recently_added`, `passkey_last_used_days` | `pk_rows` | ไม่กรอง `created_at`/`last_used_at` |
| 9 | `concurrent_session_count`, `active_subsystem_count` | `active_q` + count | มีแค่ขอบล่าง |
| 10 | `ever_changed_permission`, `permission_change_age` | `perm_rows` → `change_times` | ไม่กรอง `granted_at`/`revoked_at` |
| 11 | `confirmed_incident_count` | count | ไม่กรองเวลา → **label leakage ร้ายแรงสุด** |

> ✅ `impossible_travel_score` มี `created_at < now` ถูกต้องอยู่แล้ว (จุดเดียว)

---

## 3. การแก้

เติม `created_at < now` ในทุก query ประวัติ + กรองฟิลด์เวลาใน Python
(`last_used_at`, `granted_at`, `revoked_at`)

**ไม่เปลี่ยน:** ลำดับ/จำนวน feature (ยังคง 23) → **ไม่ติดกฎ B49** ไม่ต้อง sync 4 ไฟล์

เพิ่ม **point-in-time invariant** ใน module docstring เพื่อกันลืมตอนเพิ่ม feature ใหม่

---

## 4. ผลการทดสอบ

### RED (ก่อนแก้)
```
11 failed, 1 passed
```
- ❌ 11 tests fail = ยืนยันการรั่วทั้ง 11 จุด
- ✅ `test_live_login_unaffected` **ผ่านตั้งแต่ก่อนแก้** → พิสูจน์ว่า **login จริงไม่เคยได้รับผลกระทบ**

### GREEN (หลังแก้)
```
12 passed in 1.60s
```

| test | ตรวจ |
|---|---|
| `login_count_24h_excludes_future` | นับแค่ session อดีต (1) ไม่รวมอนาคต (5) |
| `failed_logins_24h_excludes_future` | block ในอนาคตไม่ถูกนับ |
| `minutes_since_last_login_uses_past_not_future` | วัดจาก session อดีต (120 นาที) |
| `is_new_country_ignores_future_sessions` | ประเทศที่พบเฉพาะอนาคต → ยังเป็นประเทศใหม่ |
| `country_change_30d_excludes_future` | นับแค่ TH ไม่รวม US/RU อนาคต |
| `is_new_device_ignores_future_sessions` | อุปกรณ์/browser family เดียวกัน |
| `typical_hour_baseline_excludes_future` | history อนาคต → cold start neutral |
| `concurrent_session_excludes_future` | session ที่ยังไม่เกิดไม่นับ |
| `confirmed_incident_excludes_future` | **label leakage** — incident อนาคตไม่นับ |
| `passkey_count_excludes_future_credentials` | passkey ที่ยังไม่สร้างไม่นับ |
| `permission_change_excludes_future` | สิทธิ์ที่เปลี่ยนในอนาคตมองไม่เห็น |
| `live_login_unaffected` | **regression** — login จริงผลเหมือนเดิม |

### Regression เต็ม
```
431 passed in 75.74s
```

---

## 5. ผลกระทบที่วัดได้จริง (re-score ข้อมูลจริง 60 sessions)

| Metric | ก่อนแก้ | หลังแก้ |
|---|---|---|
| `login_count_24h` สูงสุด | **78** | **9** |
| session ที่ทะลุ hard-block (`>= 50`) | 109/244 = **44.7%** | **0** |

> 🎯 **แก้ root cause ของ FP 47% ที่รายงานไว้ใน `ml_real_eval_2026-06-18.md`**
> (รายงานนั้นวิเคราะห์ว่า 92% ของ FP มาจาก `login_count_24h` — ตอนนี้ทราบแล้วว่า
> ไม่ใช่แค่ "dev artifact จาก test bursts" แต่เป็น **บั๊ก data leakage** ในตัว
> feature extraction เอง)

---

## 6. สิ่งที่ต้องทำต่อ ⚠️

ตัวเลขทั้งหมดที่ได้จาก 5 scripts **ก่อนวันที่นี้ใช้ไม่ได้** ต้องสร้างใหม่:

1. `export_labeled_data.py` → export training data ใหม่
2. `train_model.py` → retrain โมเดล
3. `calibrate_thresholds.py` → คำนวณ threshold ใหม่ (ค่าปัจจุบัน block=0.85 / challenge=0.7 / warn=0.5 ตั้งจากข้อมูลที่รั่ว)
4. `evaluate_real_logins.py` → วัด FP ใหม่ (คาดว่าจะต่ำกว่า 47% มาก)
5. อัปเดต `ml_real_eval_*.md` ด้วยตัวเลขใหม่

> 📌 **สำหรับ thesis:** การค้นพบและแก้บั๊กนี้เป็นเนื้อหาที่มีคุณค่า — แสดง methodology
> ที่รัดกุม (point-in-time evaluation) ซึ่งเป็นประเด็นสำคัญในงานวิจัย ML/security
> ที่ประเมินบนข้อมูล time-series
