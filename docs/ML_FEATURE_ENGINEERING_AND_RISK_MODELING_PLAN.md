# ML_FEATURE_ENGINEERING_AND_RISK_MODELING_PLAN.md

# Central Auth Hub

## Advanced Feature Engineering for Hybrid Risk-Based Authentication

Version: 1.0

Status: Design Proposal

---

# 1. Purpose

เอกสารฉบับนี้กำหนด Feature Engineering Strategy สำหรับระบบ Hybrid Risk-Based Authentication (Hybrid RBA)

เป้าหมายหลักคือ

* เพิ่มความแม่นยำของการตรวจจับพฤติกรรมผิดปกติ
* ลด False Positive
* ลด False Negative
* ลด Noise จากพฤติกรรมปกติของผู้ใช้
* เพิ่ม Explainability ของโมเดล
* รองรับ Passkey Authentication
* รองรับ Production Deployment

---

# 2. Current Hybrid RBA Architecture

ระบบปัจจุบันใช้การตัดสินใจ 4 ชั้น

```text
Layer 1
Rule Engine

Layer 2
Behavior Profiling

Layer 3
Isolation Forest
+ SHAP

Layer 4
Risk Aggregator
```

ผลลัพธ์

```text
PASS

MFA

BLOCK
```

---

# 3. Current Problem Analysis

ปัจจุบันระบบใช้ Feature หลักประเภท

```text
is_new_device

is_new_country

failed_logins

new_user_agent
```

ซึ่งมีข้อจำกัด

---

## Example 1

ผู้ใช้ซื้อโน้ตบุ๊กใหม่

```text
is_new_device = 1
```

ระบบมองว่าเสี่ยง

ทั้งที่เป็นพฤติกรรมปกติ

---

## Example 2

อาจารย์เดินทางไปประชุมต่างจังหวัด

```text
is_new_country = 1
```

ระบบมองว่าเสี่ยง

ทั้งที่เป็นกิจกรรมปกติ

---

## Example 3

นักศึกษาลืมรหัสผ่าน

```text
failed_logins_24h = 5
```

ระบบมองว่าเสี่ยง

ทั้งที่ไม่มีการโจมตี

---

ผลลัพธ์

```text
False Positive สูง

Noise สูง

User Friction สูง
```

---

# 4. Feature Engineering Strategy

Feature ใหม่ถูกแบ่งเป็น

```text
Device Trust Features

Behavior Features

Passkey Features

Session Features

OAuth Features

Threat Intelligence Features
```

---

# 5. Device Trust Features

จุดประสงค์

ลด False Positive จาก Device ใหม่

---

## device_age_days

จำนวนวันที่ Device ถูกใช้งาน

ตัวอย่าง

```text
1

30

300
```

---

เหตุผล

Device ที่ถูกใช้งานต่อเนื่องเป็นเวลานาน

มีความน่าเชื่อถือสูงกว่า

Device ที่เพิ่งพบครั้งแรก

---

## device_login_count

จำนวน Login สำเร็จจาก Device นี้

ตัวอย่าง

```text
2

50

400
```

---

เหตุผล

Device ที่ถูกใช้งานซ้ำหลายครั้ง

ควรมี Risk ต่ำลง

---

## device_last_seen_days

จำนวนวันตั้งแต่พบ Device ครั้งล่าสุด

ตัวอย่าง

```text
1

7

90
```

---

เหตุผล

Device ที่ไม่ได้ใช้งานนานมาก

อาจเพิ่มความเสี่ยง

---

## device_success_ratio

อัตราส่วน Login สำเร็จ

สูตร

```text
successful_logins
/
total_logins
```

---

เหตุผล

Device ที่มีอัตราความสำเร็จสูง

มักเป็น Device ของเจ้าของบัญชีจริง

---

## device_trust_score

คะแนนความน่าเชื่อถือของ Device

คำนวณจาก

```text
device_age_days

device_login_count

device_success_ratio

device_last_seen_days
```

---

เหตุผล

ใช้แทน

```text
is_new_device
```

ซึ่งหยาบเกินไป

---

# 6. Behavioral Features

จุดประสงค์

สร้าง Baseline ของผู้ใช้แต่ละคน

---

## login_hour_deviation

ความแตกต่างจากช่วงเวลาที่ Login ปกติ

ตัวอย่าง

```text
ปกติ

08:00 - 18:00

วันนี้

03:00
```

---

เหตุผล

พฤติกรรมเวลาใช้งาน

มีความเสถียรกว่า Country

---

## weekday_usage_score

พฤติกรรมวันใช้งาน

ตัวอย่าง

```text
Mon-Fri
```

แต่ Login วันอาทิตย์ตี 3

---

เหตุผล

ตรวจจับการใช้งานผิดปกติ

---

## subsystem_usage_pattern

Pattern การเข้าใช้ Subsystem

ตัวอย่าง

```text
Dorm

Library
```

แต่วันนี้เข้า

```text
Admin Portal
```

---

เหตุผล

เป็นสัญญาณที่แม่นกว่าการดูเวลา Login

---

## action_frequency_score

ความถี่ของ Action

ตัวอย่าง

```text
ปกติ

Delete User = 0
```

วันนี้

```text
Delete User = 200
```

---

เหตุผล

ช่วยตรวจจับ Account Takeover

---

# 7. Passkey Features

ใช้หลังจากเปิด Passkey

---

## has_passkey

```text
0

1
```

---

เหตุผล

Account ที่มี Passkey

มีความเสี่ยงต่ำกว่า

---

## passkey_count

จำนวน Passkey

ตัวอย่าง

```text
1

2

3
```

---

เหตุผล

มี Recovery Path มากขึ้น

---

## passkey_age_days

อายุของ Passkey

ตัวอย่าง

```text
1

180

500
```

---

เหตุผล

Passkey ใหม่มีความเสี่ยงมากกว่า

Passkey เก่า

---

## recent_passkey_added

```text
0

1
```

---

เหตุผล

Passkey ที่เพิ่งถูกเพิ่ม

เป็นสัญญาณของ Account Takeover ได้

---

## passkey_verified_recently

```text
0

1
```

---

ตัวอย่าง

```text
Step-up ผ่านแล้ว
เมื่อ 5 นาทีที่ผ่านมา
```

---

เหตุผล

ลดการถาม MFA ซ้ำ

---

# 8. Session Features

---

## session_age_minutes

อายุ Session

---

เหตุผล

Session ใหม่

เสี่ยงมากกว่า Session ที่ใช้งานมานาน

---

## concurrent_session_count

จำนวน Session พร้อมกัน

---

ตัวอย่าง

```text
1
```

ปกติ

---

```text
20
```

ผิดปกติ

---

## recent_mfa_success

```text
0

1
```

---

เหตุผล

Session ที่เพิ่งผ่าน MFA

ควรมี Trust สูงขึ้น

---

## step_up_completed

```text
0

1
```

---

เหตุผล

ช่วยลด False Positive

---

# 9. Geolocation Features

---

## geo_distance_km

ระยะทางระหว่าง Login ล่าสุด

และ Login ปัจจุบัน

---

## geo_velocity_kmh

ความเร็วในการเปลี่ยน Location

---

## impossible_travel_score

ตัวอย่าง

```text
Bangkok

↓

20 นาที

↓

London
```

---

เหตุผล

มนุษย์เดินทางไม่ได้เร็วขนาดนั้น

---

# 10. OAuth Features

---

## client_risk_score

ความเสี่ยงของแต่ละ Client

ตัวอย่าง

```text
Library = Low

Admin Portal = High
```

---

## new_client_access

```text
0

1
```

---

เหตุผล

ไม่เคยเข้าใช้งาน Client นี้มาก่อน

---

## scope_sensitivity_score

ตัวอย่าง

```text
read_profile
```

Risk ต่ำ

---

```text
manage_users
```

Risk สูง

---

# 11. Threat Intelligence Features

---

## ip_reputation_score

คะแนนความน่าเชื่อถือของ IP

---

## known_proxy

```text
0

1
```

---

## known_tor_exit_node

```text
0

1
```

---

## threat_feed_match

```text
0

1
```

---

เหตุผล

ใช้ร่วมกับ Rule Engine

---

# 12. Feature Priority

## Must Have

```text
device_trust_score

login_hour_deviation

subsystem_usage_pattern

passkey_age_days

passkey_verified_recently

impossible_travel_score

ip_reputation_score
```

---

## Should Have

```text
concurrent_session_count

client_risk_score

scope_sensitivity_score

device_success_ratio

recent_passkey_added
```

---

## Nice To Have

```text
geo_velocity_kmh

weekday_usage_score

action_frequency_score
```

---

# 13. Recommended Trust Layer

เพิ่ม Layer ใหม่

```text
Layer 1
Rule Engine

Layer 2
Behavior Profiling

Layer 2.5
Trust Profiling

Layer 3
Isolation Forest

Layer 4
Risk Aggregator
```

---

Trust Profiling

คำนวณจาก

```text
Device Trust

Passkey Trust

Session Trust
```

---

# 14. Risk Aggregation Formula

Current

```text
Rule
+
Behavior
+
ML
```

---

Recommended

```text
Final Risk

=
Threat Score
+
Behavior Score
+
ML Score
-
Trust Score
```

---

เหตุผล

ลด False Positive

โดยไม่ลดความสามารถในการตรวจจับการโจมตี

---

# 15. SHAP Explainability Example

```json
{
  "risk": 0.81,
  "top_factors": [
    {
      "feature": "new_country",
      "impact": "+0.31"
    },
    {
      "feature": "new_device",
      "impact": "+0.22"
    },
    {
      "feature": "passkey_age_days",
      "impact": "-0.18"
    },
    {
      "feature": "device_trust_score",
      "impact": "-0.14"
    }
  ]
}
```

---

# 16. Expected Benefits

หลังเพิ่ม Feature ตามเอกสารนี้

คาดหวังผลลัพธ์

* ลด False Positive
* ลด User Friction
* เพิ่ม Explainability
* เพิ่มความแม่นยำของ Isolation Forest
* เพิ่มประสิทธิภาพของ Hybrid RBA
* รองรับ Passkey-Based Authentication
* รองรับ Production Deployment
* เพิ่มคุณค่าทางวิชาการของงานวิจัย
* เพิ่มความพร้อมสำหรับ Enterprise IAM Architecture

```
```
