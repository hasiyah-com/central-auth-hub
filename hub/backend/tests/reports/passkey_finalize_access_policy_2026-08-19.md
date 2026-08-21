# B59 — Passkey re-auth finalizer เช็คสิทธิ์ด้วย raw AccessList แทน policy engine

**วันที่:** 2026-08-19
**อาการ (prod):** force-enroll passkey (user ไม่มี passkey) → ตั้ง passkey เสร็จ → ขึ้น
`403 "ไม่มีสิทธิ์เข้า subsystem นี้"` ทั้งที่ subsystem เปิด policy = **all user**

---

## 1. Root cause (ตระกูล B50 — สอง code path เช็คสิทธิ์ไม่ตรงกัน)

| ด่าน | ที่ | วิธีเช็คสิทธิ์ |
|---|---|---|
| **entry** (เริ่ม OAuth) | `oauth.py:_check_access_policy_or_raise` | `evaluate_access_policy` ✅ honor all/role/attribute/explicit |
| **finalize** (หลัง passkey ผ่าน) | `passkey.py:_finalize_after_reauth` | **raw AccessList lookup** 🔴 ต้องมี allow row |

policy `all` = เปิดให้ทุกคน → **ไม่มี AccessList row เลย** → ด่าน finalize `access = None` → 403
กระทบทุก policy ที่ไม่ใช่ `explicit` (all / role / attribute) — user ผ่านด่านแรกมาได้ แต่มาตายด่านจบ

`_finalize_after_reauth` เป็น finalizer ตัวเดียวของ **3 flow** (audit ยืนยัน):
`risk_stepup_verify` · `risk_stepup_verify_totp` · `force_enroll_register_complete` → แก้จุดเดียวครอบหมด

**Audit จุด raw AccessList อื่น** (กันตกหล่น): oauth entry = ถูก (policy engine), oidc.py:250 =
แค่ enrich claim ไม่ deny, admin/developer/change_request = CRUD whitelist เอง (ควร raw) → **ไม่มี login-gate ดิบอื่น**

---

## 2. การแก้

`passkey.py:_finalize_after_reauth`:
- แทน raw AccessList check ด้วย `evaluate_access_policy(db, user, subsystem_obj)` (engine เดียวกับ entry)
- เพิ่ม import `Subsystem` + `evaluate_access_policy`; ลบ `AccessList` (ไม่ใช้แล้ว)
- `role_in_sub` ใน authcode: `access.role_in_sub` → `user.user_type` (ปลายทาง `/oauth/token`
  ใช้ `user.user_type` อยู่แล้ว — field นี้ dead ไม่มีใครอ่าน)
- เพิ่ม `log_action(action="oauth_login_failed_access_policy", stage="passkey_finalize")` →
  `db.commit()` → `raise` ตอน deny (B6/B7 — failure path ต้อง audit ตามลำดับ log→commit→raise)

---

## 3. Test

ไฟล์ใหม่: `tests/test_passkey_finalize_policy.py` (เรียก `_finalize_after_reauth` ตรง ๆ)

| test | ยืนยัน |
|---|---|
| `test_finalize_allows_policy_all_without_accesslist_row` | policy=all + user ไม่มี allow row → finalize ผ่าน (ออก `code=`) ไม่ 403 |
| `test_finalize_still_denies_explicit_not_whitelisted` | policy=explicit + ไม่อยู่ whitelist → ยัง 403 (deny ไม่พัง) |

**ผลรัน (reproducible):**
```bash
docker compose exec -T hub-backend pytest \
  tests/test_passkey_finalize_policy.py \
  tests/test_risk_passkey_flow.py tests/test_oauth_policy_integration.py \
  tests/test_access_policy.py tests/test_scope_conformance.py -q
```
```
tests/test_passkey_finalize_policy.py ..            [ B59: 2 passed ]
=== 131 passed, 14 skipped ===
```

---

## 4. ผลคาดหวังหลัง deploy

- subsystem policy `all` (หรือ role/attribute): user ที่มีสิทธิ์ตาม policy → ตั้ง passkey เสร็จ
  แล้ว login ต่อได้ ไม่โดน 403
- subsystem policy `explicit`: ยังบังคับ whitelist ตามเดิม (deny ทำงานปกติ + มี audit log)
- ครอบทั้ง risk-stepup (passkey/OTP) และ force-enroll — flow เดียวกัน
