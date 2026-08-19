# B56 — `is_new_device` false-positive สวิง (Chrome auto-update) — Fix + Test Report

**วันที่:** 2026-08-19
**อาการ (prod):** เครื่องเดิม login แต่ risk score สวิง `0.9 (mfa_passed)` ↔ ต่ำ (`allow`) สลับกันตลอด

---

## 1. Root cause (ยืนยันด้วยข้อมูล prod จริง)

Query `login_sessions` ของ user ที่เทสต์ → เจอ 2 UA จากเครื่องเดียวกัน:

| sessions | user_agent |
|---|---|
| 23 | Windows NT 10.0; Win64; x64 … **Chrome/151.0.0.0** Safari/537.36 |
| 13 | Windows NT 10.0; Win64; x64 … **Chrome/150.0.0.0** Safari/537.36 |

เครื่อง/OS/เบราว์เซอร์เดิมทุกอย่าง — Chrome auto-update build `150 → 151` เท่านั้น

**กลไกบั๊ก 2 จุด:**
1. `feature_extraction.py` คำนวณ `is_new_device` โดยเทียบ **UA string เต็มแบบเป๊ะ** (`user_agent not in seen_ua_set`) → build ต่าง = "เครื่องใหม่" ทันที
2. flag `is_new_device` ตัวเดียวถูกให้คะแนน **2 ชั้น**: Rule Engine (+0.30) + Behavior Profiling (+0.20) = 0.5 แล้ว Isolation Forest ยังเห็น `is_new_device=1` (synthetic baseline ตั้งไว้ 5% rare) → รวม ~0.9

ผล: ทุกครั้งที่ login ด้วย build ที่ต่างจาก session ก่อนหน้า → score พุ่ง → decision สวิง

---

## 2. การแก้

**Fix A — `app/services/feature_extraction.py`**
- เพิ่ม `_device_signature(ua)` = `parse_os_name | parse_device_type | browser_family` (ตัดเลขเวอร์ชันออก)
- `is_new_device` เทียบ signature แทน UA string เต็ม → Chrome 150/151 บนเครื่องเดิม = signature เดียวกัน = `0`
- range คง 0/1 · ไม่กระทบ feature contract (B49) · ไม่ต้อง retrain (synthetic gen เป็น Bernoulli อิสระ) — แถมตรงกับ baseline 95%-not-new มากขึ้น

**Fix B — `app/security/behavior_profiling.py`**
- ตัดการให้คะแนน `is_new_device` (+0.20) ออกจาก Layer 2 — เก็บไว้ที่ Rule Engine ชั้นเดียว (+0.30)
- เครื่องใหม่จริงยังจับได้ที่ +0.30 (ไม่ถึงเกณฑ์ MFA เองโดยไม่มี signal อื่นร่วม)

---

## 3. Test

ไฟล์: `tests/test_feature_extraction.py` (เพิ่ม 2 test)

| test | ยืนยัน |
|---|---|
| `test_new_device_ignores_browser_build_bump` | Chrome 150→151 เครื่องเดิม → `is_new_device=0`, `is_new_ua_family=0` |
| `test_new_device_detects_genuinely_new_device` | Windows Chrome → iPhone Safari → `is_new_device=1` (ยังจับเครื่องใหม่จริง) |

**ผลรัน (reproducible):**
```bash
docker compose exec -T hub-backend pytest \
  tests/test_feature_extraction.py tests/test_feature_point_in_time.py \
  tests/test_risk_scenarios.py tests/test_e2e_rba.py tests/test_feature_contract.py -q
```
```
tests/test_feature_extraction.py .........(11)          [ new 2 tests ]
tests/test_feature_point_in_time.py ............(12)     [ is_new_device_ignores_future ยังผ่าน ]
tests/test_risk_scenarios.py ..............(14)
tests/test_e2e_rba.py ...........(11)
tests/test_feature_contract.py ...(3)
=== 51 passed ===
```

---

## 4. ผลคาดหวังหลัง deploy

- เครื่องนี้ (Chrome ที่อัปเดตต่อไปเรื่อยๆ) → `is_new_device=0` → score ต่ำ → `allow` เสถียร ไม่สวิง
- เครื่อง/เบราว์เซอร์/OS ใหม่จริง (login ครั้งแรกจากมือถือ ฯลฯ) → `is_new_device=1` (+0.30) ยังจับได้
- แนะนำ re-verify: login 1 ครั้งหลัง redeploy แล้วเช็ค panel Risk Analysis ว่า `is_new_device` ไม่ขึ้นแล้ว
