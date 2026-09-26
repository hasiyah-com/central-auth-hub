# แก้ `failed_logins_24h` ให้นับการยืนยันตัวตนที่ล้มเหลวจริง (B85) — 2026-09-26

**branch:** `fix/failed-logins-24h` แยกจาก `origin/main` (04872af) · **ขอบเขต:** ฟีเจอร์ลำดับ 10 ของเวกเตอร์ 23 ตัว และกฎชั้นที่ 1 ที่อ่านฟีเจอร์นี้ (ตัวกฎไม่ได้แก้)
**ที่มา:** ตรวจขั้น 2 ของแผนพัฒนา L3 (`l3_audit_step2_step6_2026-09-26.md` บน branch การทดลอง)

## 1. บั๊ก

```python
failed_24h = count(LoginSession where decision in ("block", "would_block") and created_at in [now-24h, now))
```

- ผลตัดสินของระบบกลายเป็นฟีเจอร์ของการตัดสินครั้งถัดไป (วงป้อนกลับ) — ถูกเตือนเพิ่มเพราะเคยถูกเตือน
- shadow `would_block` คือผู้ใช้ที่เข้าได้จริง แต่ถูกนับเป็น "ล้มเหลว"
- การยืนยันตัวตนที่ล้มเหลวจริงใน `audit_logs` ไม่ถูกนับเลย
- การทดลองนับ `login_successful == False` → ระบบที่วัดกับระบบที่ใช้จริงคนละความหมาย (B66)

## 2. นิยามใหม่ (ตามที่เจ้าของระบบกำหนด)

นับแถว `audit_logs` ในช่วง `[now-24h, now)` ที่ผูกกับบัญชีที่ถูกพยายามเข้า:

| กลุ่ม | action | ผูกบัญชีด้วย |
|---|---|---|
| ยืนยันตัวตนไม่ผ่านหลังรู้ตัวผู้ใช้ | `passkey_stepup_failed` · `risk_mfa_verify_failed` · `stepup_totp_failed` · `risk_force_enroll_otp_failed` | `actor_id` |
| passkey login ไม่ผ่าน (ยังไม่รู้ตัวผู้ใช้ · บันทึกด้วย actor_id NULL) | `passkey_login_failed` · `oauth_passkey_login_failed` | email ใน metadata (ไม่สนตัวพิมพ์) |

**ไม่นับ:**

| รายการ | เหตุผล |
|---|---|
| `block` / `would_block` | ผลตัดสินของระบบเอง ไม่ใช่การยืนยันตัวตนล้มเหลว |
| IdP subject ไม่ตรง (`*_google_sub_mismatch`, `*_line_sub_mismatch`) · กู้บัญชีไม่ผ่าน (`passkey_recovery_failed`) | ความหมายและผู้ถูกกระทบต่างกัน → ควรเป็นสัญญาณความเสี่ยงแยกประเภท (ยังไม่ได้ทำ) |
| ถูกปฏิเสธสิทธิ์ (`*_access_policy`) · บัญชีถูกปิด (`*_inactive`) | ไม่ใช่การยืนยันตัวตนล้มเหลว |
| discoverable passkey ที่ไม่ผ่าน | ไม่มี email → ผูกบัญชีไม่ได้ |

## 3. ไฟล์ที่แก้

| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `hub/backend/app/services/feature_extraction.py` | query ใหม่จาก `audit_logs` · ค่าคงที่ `FAILED_AUTH_ACTOR_ACTIONS` / `FAILED_AUTH_EMAIL_ACTIONS` พร้อมเหตุผลที่ไม่นับ · docstring point-in-time รวม AuditLog |
| `hub/backend/tests/test_failed_logins_24h.py` (ใหม่) | 7 tests |
| `hub/backend/tests/test_feature_point_in_time.py` | `test_failed_logins_24h_excludes_future` เดิมใส่ `block` ในอนาคต → หลังแก้จะผ่านโดยไม่ได้ทดสอบอะไร จึงเปลี่ยนเป็น audit อดีต 1 + อนาคต 3 คาด **1** |
| `hub/backend/scripts/measure_failed_logins_24h_2026-09-26.py` (ใหม่) | วัดผลกระทบ (อ่านอย่างเดียว) |
| `ml-service/app/features.py` · `docs/guides/ML_FEATURE_DATA_SOURCES.md` · `docs/guides/ML_EXPLAINED.md` | คำอธิบายนิยาม |
| `docs/bugs-encountered.md` | B85 |

## 4. เทส

| เทส | ผล |
|---|---|
| `test_failed_logins_24h.py` บนโค้ดเดิม (RED) | 5 failed · 2 passed — ข้อแรก: would_block/block 12 แถว นับได้ **12** |
| หลังแก้ (GREEN) + `test_feature_extraction.py` + `test_feature_point_in_time.py` | 36 passed |
| mutation: ตัด `< now` | ถูกจับ 2 ข้อ |
| mutation: เทียบ email แบบสนตัวพิมพ์ | ถูกจับ 1 ข้อ |
| mutation: ตัดเงื่อนไข `actor_id IS NULL` ของกลุ่ม email | **รอด** → ไม่มีเส้นทางจริงที่บันทึก action กลุ่มนี้ด้วย actor อื่น จึงตัดเงื่อนไขนี้ออกจากโค้ดแทนการเขียนเทสกรณีที่เกิดไม่ได้ |
| **ชุดเทสเต็มของ hub-backend ในคอนเทนเนอร์** (ยกเว้น 2 ไฟล์ด้านล่าง) | **909 passed · 0 failed** · 13 skipped |
| `test_e2e_full_stack.py` · `test_l1_oidc.py` (สคริปต์ที่ `sys.exit` ตอน import) | ล้ม 2 และ 6 ข้อ — **เหมือนกันทุกบรรทัดกับ `origin/main`** · สาเหตุคือ stack Dorm/Library ไม่ได้เปิด (DNS ไม่พบ · `/oauth/authorize` ได้ 503 จาก health gate) ไม่เกี่ยวกับการแก้นี้ |

`test_concurrent_requests_agree` ที่ล้มในรอบ `fix/l3-hub-direct` ผ่านในรอบนี้ (สอดคล้องกับบันทึกว่าไม่เสถียรตาม timeout)

## 5. ผลกระทบต่อระดับกฎชั้นที่ 1 (ฐานข้อมูล dev · 1,910 session · อ่านอย่างเดียว)

คำนวณทั้งค่าเดิมและค่าใหม่ที่ `now = session.created_at` ของแต่ละ session

| ระดับของกฎ | นิยามเดิม | นิยามใหม่ |
|---|---|---|
| ≥ 10 บล็อก | 162 | **0** |
| 5–9 บังคับยืนยันตัวตน | 378 | 9 |
| 3–4 +0.20 | 298 | 7 |
| < 3 ไม่มีผล | 1,072 | 1,894 |

| การเปลี่ยนระดับ | จำนวน session |
|---|---|
| บล็อก → ไม่มีผล | 162 |
| บังคับยืนยันตัวตน → ไม่มีผล | 378 |
| +0.20 → ไม่มีผล | 298 |
| ไม่มีผล → บังคับยืนยันตัวตน | 9 |
| ไม่มีผล → +0.20 | 7 |

- 838 session เคยได้โทษจากฟีเจอร์นี้เพราะวงป้อนกลับ — หายทั้งหมด
- 16 session ที่ได้ระดับใหม่มาจากการยืนยันตัวตนที่ล้มเหลวจริงซึ่งนิยามเดิมมองไม่เห็น (3 บัญชี · ไม่ระบุตัวตน)
- แถว audit ที่นับได้ทั้งฐานข้อมูล: `passkey_login_failed` 151 · `oauth_passkey_login_failed` 158 · `risk_force_enroll_otp_failed` 39 · `passkey_stepup_failed` 6
- **ไม่ได้ replay ผลตัดสินรวม** เพราะกฎอื่นใน `evaluate_rules` อ้างเวลาปัจจุบัน (multi-account IP) จึงให้ผลย้อนหลังไม่ตรงเวลา · ตารางนี้คือส่วนที่ฟีเจอร์นี้ควบคุมโดยตรง (บล็อกทันที · บังคับขั้นต่ำ · คะแนน)
- ฐานข้อมูล dev มีข้อมูลจากเทสและการสาธิตปน → ยืนยันกลไก ไม่ใช่อัตราของผู้ใช้จริง

## 6. ข้อจำกัดที่เหลือ

1. **กฎ ≥ 10 = บล็อก คงเดิม** (ตามที่เจ้าของระบบเลือก) → ผู้ที่รู้ email ของเหยื่อสามารถลอง passkey ผิดโดยเจตนา 10 ครั้งเพื่อให้การเข้าสู่ระบบครั้งถัดไปของเจ้าของบัญชีถูกบล็อก (lockout DoS) · rate limit ต่อ IP ช่วยชะลอได้บางส่วน
2. ~~step-up OTP ทาง email ที่ไม่ผ่านยังไม่ถูกบันทึกใน audit~~ → แก้แล้วใน commit ถัดไป (ข้อ 9)
3. IdP subject ไม่ตรงและกู้บัญชีไม่ผ่านยังไม่มีสัญญาณความเสี่ยงของตัวเอง
4. โมเดล `iforest_v1.pkl` ฝึกจากข้อมูลที่ฟีเจอร์นี้มีความหมายตามตัวสร้างข้อมูล ไม่ใช่นิยามเดิมของระบบจริง → การแก้นี้ทำให้ระบบจริงใกล้การทดลองขึ้น แต่ยังไม่ได้วัดผลต่อคะแนน IForest (ตาม RBA freeze)

## 7. สภาพแวดล้อมที่ใช้รัน

ไม่แตะ stack ที่เปิดให้บริการ · สำเนา `hub_db` ด้วย `pg_dump` ไปฐานข้อมูลชั่วคราว `hub_failfix_test` · Redis DB 12 ที่ว่าง ·
ml-service ชั่วคราว (`ml-failfix`) จากโค้ด branch นี้ · Hub ชั่วคราวใน container เทสเดียวกันที่ `127.0.0.1:8000` · ไฟล์ env ชั่วคราวตัดตัวแปร SMTP/Telegram/webhook ออก ·
หลังรันลบฐานข้อมูลชั่วคราว ล้าง Redis DB 12 ลบคอนเทนเนอร์ ไฟล์ env และ worktree ฐานเทียบแล้ว

```bash
# เทสเฉพาะเรื่อง (ใน container ที่ชี้ฐานข้อมูลทดสอบ)
pytest tests/test_failed_logins_24h.py tests/test_feature_extraction.py tests/test_feature_point_in_time.py -v
# วัดผลกระทบ
PYTHONPATH=. python scripts/measure_failed_logins_24h_2026-09-26.py
```

## 8. ยังไม่ได้ทำ

- commit / push / merge — รอเจ้าของระบบ
- deploy

## 9. commit ถัดไป: audit ของ step-up OTP ทาง email

**ปัญหา:** `/auth/stepup/otp/verify` ที่ OTP ผิดเพิ่มตัวนับใน Redis แล้ว `raise` ทันที ไม่มี audit event → ไม่ถูกนับใน `failed_logins_24h` และตรวจย้อนหลังไม่ได้ (B7)

**แก้:** กรณี `otp_invalid` บันทึก `stepup_otp_failed` (actor_id = ผู้ใช้ · metadata `code`, `attempts`) ตามลำดับ `log_action` → `commit` → `raise` (B6) และเพิ่มใน `FAILED_AUTH_ACTOR_ACTIONS`

| กรณี | บันทึก/นับ | เหตุผล |
|---|---|---|
| `otp_invalid` | นับ | ตรวจ OTP แล้วผิดจริง |
| `otp_locked` | ไม่นับ | ปฏิเสธจากสถานะล็อกก่อนตรวจ OTP ใหม่ · นับจะเพิ่มความล้มเหลวซ้ำจากสถานะเดิม |
| `otp_expired` | ไม่นับ | ไม่มี OTP ให้ตรวจ ไม่ใช่การเดาผิด |

**เทส** `tests/test_stepup_otp_failed_audit.py` (ผ่าน HTTP จริงด้วย TestClient · ปิด rate limit ในเทส):

| เทส | ผล |
|---|---|
| RED (ก่อนแก้) | 1 failed · 3 passed — ข้อ `otp_invalid` ไม่มีแถว audit |
| GREEN | 4 passed |
| ถอด `passkey.py` ที่แก้ออก (stash) แล้วรันซ้ำ | 1 failed — ยืนยันว่าเทสขึ้นกับการแก้จริง |
