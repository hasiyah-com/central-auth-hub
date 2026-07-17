# CI Fix — Passkey Account RBAC test (stale after 53ab5cd)

วันที่: 2026-07-17
ไฟล์ที่แก้: `tests/test_passkey_security.py`, `conftest.py`

## อาการ (GitHub Actions — Backend CI)

`5 failed, 308 passed, 20 skipped` — fail ทั้ง 5 อยู่ที่ parametrize เดียว:

```
FAILED test_account_endpoints_reject_non_admin[post-/account/passkeys/register/finish]     assert 422 == 403
FAILED test_account_endpoints_reject_non_admin[post-/account/passkeys/backup-codes/acknowledge] assert 200 == 403
FAILED test_account_endpoints_reject_non_admin[get-/account/passkeys/backup-codes/status]  assert 200 == 403
FAILED test_account_endpoints_reject_non_admin[get-/account/passkeys]                       assert 200 == 403
FAILED test_account_endpoints_reject_non_admin[post-/account/passkeys/register/start]       (เดียวกัน)
```

## Root cause — test เก่าล้าสมัย ไม่ใช่โค้ด regression

| หลักฐาน | ค่า |
|---|---|
| Test เขียน | `71f5736` (2026-06-13) — ตอนนั้น `/account/passkeys/*` = admin-only |
| โค้ดเปลี่ยน | `53ab5cd` (2026-07-05) `fix(passkey): allow developer role to manage own passkeys (not admin-only)` |
| เหตุผล | deadlock จริง: developer (teacher/staff) ต้องมี passkey ก่อนลงทะเบียน subsystem ผ่าน step-up gate แต่เดิมเพิ่ม passkey ไม่ได้เพราะไม่ใช่ admin |
| docstring ยืนยัน | `passkey.py:10-16` — ใช้ `require_developer` (กัน student เท่านั้น) |

`require_developer` (deps.py:110) raise 403 เฉพาะ student — ก่อน body validation ด้วย ฉะนั้น
student โดน 403 ทุก endpoint, ส่วน staff ผ่าน RBAC → `register/finish` เจอ body ว่างเลย 422, GET เลย 200

## การแก้

1. `conftest.py` — เพิ่ม fixture `student_token` (มี `student_user` อยู่แล้ว)
2. `test_passkey_security.py`:
   - `test_account_endpoints_reject_non_admin` (staff→403) → **`test_account_endpoints_reject_student`** (student→403) ตรง RBAC ปัจจุบัน
   - เพิ่ม **`test_account_endpoints_allow_developer`** (staff→ไม่ใช่ 403) เป็น positive coverage ของ fix `53ab5cd`
   - อัปเดต comment block อธิบายที่มา

## ผลทดสอบ (local, stack ครบ)

```
tests/test_passkey_security.py — 36 passed (5 รอบติดต่อกันเสถียร)
Full suite (CI exclusions) — 338 passed, 0 failed in 59.55s
```

หมายเหตุ: เคยเห็น `test_account_status_allows_admin` fail 401 ครั้งเดียวตอน container เพิ่งขึ้น
(state ค้างใน Redis จาก session ก่อน) — รันซ้ำ 5 รอบ + full suite ไม่ reproduce อีก
CI ใช้ postgres/redis container สดทุก run จึงไม่มี state ค้างแบบนี้

## Reproduce

```bash
docker compose exec hub-backend pytest tests/test_passkey_security.py -v
docker compose exec hub-backend pytest \
  --ignore=tests/test_e2e_full_stack.py \
  --ignore=tests/test_l1_oidc.py \
  --ignore=tests/test_l1_oidc_authlib.py -q
```
