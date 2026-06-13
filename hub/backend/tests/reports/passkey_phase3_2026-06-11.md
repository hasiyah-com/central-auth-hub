# Passkey Phase 3 — Lifecycle Management

**Date**: 2026-06-11
**Plan**: `docs/passkey-implementation-plan.md` v3
**Phase**: 3 — Lifecycle Management (list / rename / delete) — Improvement #4 + #9 + Decision #15
**Status**: ✅ ALL PASS (125/125 รวม regression)

---

## Scope

จัดการ Passkey ที่ลงทะเบียนไว้ (admin console, admin-only):
- **List** — ดูทุก passkey + last_used + country + counter regression
- **Rename** — เปลี่ยนชื่อ + เก็บ nickname_history (Improvement #4)
- **Delete** — soft delete + **last-Passkey guard** (Decision #15)

**หมายเหตุ:** `critical_action_policy.gate("delete_passkey")` ยัง**ไม่ wire** ใน Phase 3
เพราะ step-up flow อยู่ Phase 5 (ถ้าใส่ตอนนี้ admin จะลบไม่ได้เลย — ไม่เคยมี step-up cache).
Phase 5 จะ apply gate + step-up พร้อมกัน. Phase 3 มี last-Passkey guard ซึ่งไม่พึ่ง step-up.

---

## Endpoints (admin-only — require_hub_admin)

```
GET    /account/passkeys              → {passkeys:[...], count, max}
PATCH  /account/passkeys/{id}         {device_name} → renamed passkey
DELETE /account/passkeys/{id}         → soft delete (last-Passkey guard)
```

Serialize ไม่ส่ง `credential_id`/`public_key` ออก (เฉพาะ metadata ปลอดภัย).

---

## Service helpers (webauthn_service.py)

| Function | หน้าที่ |
|---|---|
| `get_owned_passkey(user_id, id, db)` | หา active passkey scoped to user → 404 ถ้าไม่เจอ/ของคนอื่น/revoked/bad uuid |
| `rename_passkey(...)` | เปลี่ยนชื่อ + append nickname_history {from,to,at} |
| `count_active_excluding(user_id, id, db)` | นับ active ที่ไม่ใช่ id (last-Passkey guard) |
| `revoke_passkey(..., allow_last=False)` | soft delete + guard; allow_last=True สำหรับ admin reset/recovery |

---

## Security — cross-user isolation 🔒

`get_owned_passkey` filter `user_id` เสมอ → admin A **ลบ/แก้ passkey ของ admin B ไม่ได้**
แม้รู้ UUID (404). Test `test_get_owned_passkey_wrong_user_404` ยืนยัน.

---

## Test Execution

```bash
docker compose exec -T hub-backend pytest tests/test_passkey_lifecycle.py -v
```

### test_passkey_lifecycle.py — 11 tests

| Test | ตรวจ |
|---|---|
| `get_owned_passkey_found` | หาเจอ |
| `get_owned_passkey_wrong_user_404` | **cross-user isolation** |
| `get_owned_passkey_bad_uuid_404` | bad uuid → 404 |
| `get_owned_passkey_revoked_404` | revoked → 404 |
| `rename_appends_history` | nickname_history {from,to,at} |
| `rename_same_name_noop` | ชื่อเดิม → ไม่ append |
| `rename_blank_raises` | ชื่อว่าง → 400 |
| `revoke_last_passkey_blocked` | **ลบตัวสุดท้าย → 400 + ไม่ถูก revoke** |
| `revoke_non_last_succeeds` | มี 2 → ลบ 1 ได้ |
| `revoke_allow_last_override` | allow_last=True → ลบตัวสุดท้ายได้ (recovery) |
| `count_active_excluding` | นับถูก |

### test_passkey_security.py — +RBAC (admin-only)
`/account/passkeys` (list) เพิ่มใน RBAC matrix → no-token 403, staff 403, admin 200.

### Full regression

```
============================= 125 passed in 17.39s =============================
```

---

## Frontend

| ไฟล์ | สิ่งที่ทำ |
|---|---|
| `lib/passkey.ts` | + listPasskeys / renamePasskey / deletePasskey + PasskeyInfo type |
| `(console)/account/security/page.tsx` | full UI: list + add inline + backup codes status + max guard |
| `_components/PasskeyCard.tsx` | per-passkey: rename inline (Enter/Esc), delete confirm, last_used relative time, platform/key badge, counter-regression warn, last-Passkey delete disabled |
| `components/Sidebar.tsx` | + "🔑 Passkey" ใน ADMIN_NAV (admin console) |

UX:
- ลบตัวสุดท้าย → ปุ่ม disabled + tooltip "ลบตัวสุดท้ายไม่ได้"
- rename inline (กด ✏️ → แก้ → Enter save / Esc cancel)
- delete → confirm 2 ขั้น ("แน่ใจ? ลบ/ไม่")

---

## Security checks

- ✅ **admin-only** — ทุก endpoint `require_hub_admin` (RBAC tested)
- ✅ **cross-user isolation** — get_owned_passkey scoped to user_id
- ✅ **last-Passkey guard (Decision #15)** — block + audit `passkey_last_deletion_blocked`
- ✅ **soft delete** — revoked_at + revoked_reason (preserve audit, B: soft delete)
- ✅ **B6 audit order** — log → commit → raise (last-passkey block path)
- ✅ **no secret leak** — serialize ไม่ส่ง credential_id/public_key
- ✅ **input validation** — RenamePasskeyRequest Pydantic (1-100 chars)
- ⏳ **critical action gate** — Phase 5 (step-up) จะ apply `gate("delete_passkey")`

---

## Audit events ใหม่

```python
PASSKEY_RENAMED = "passkey_renamed"
PASSKEY_DELETED = "passkey_deleted"
PASSKEY_LAST_DELETION_BLOCKED = "passkey_last_deletion_blocked"
```

---

## Manual test (operator)

```
1. Login Hub เป็น admin (Google หรือ passkey)
2. Sidebar → "🔑 Passkey" → /account/security
3. เห็นรายการ passkey ที่มี (เช่น Windows Laptop) + last used
4. กด "+ เพิ่ม Passkey" → ตั้งชื่อ → register (virtual authenticator/Windows Hello)
5. rename: กด ✏️ → แก้ชื่อ → Enter → ชื่อเปลี่ยน
6. delete (มี ≥2 ตัว): กด 🗑️ → "แน่ใจ?" → ลบ → หายจากรายการ
7. ลองลบจนเหลือ 1 → ปุ่ม 🗑️ disabled (last-Passkey guard)
8. audit: SELECT action FROM audit_logs WHERE action LIKE 'passkey_%name%' OR action LIKE 'passkey_delet%'
```

---

## Phase 3 — Acceptance criteria

- [x] GET/PATCH/DELETE /account/passkeys[/{id}] — admin-only
- [x] rename + nickname_history (Improvement #4)
- [x] last-Passkey guard (Decision #15) — block + audit
- [x] cross-user isolation (scoped to user_id)
- [x] soft delete (revoked_at + reason)
- [x] frontend: list + add + rename inline + delete confirm + Sidebar nav
- [x] 11 lifecycle tests + RBAC + 125/125 regression
- [ ] critical_action gate → deferred Phase 5 (step-up)

---

## Next: Phase 4 — Recovery (~4 hours)

- backup code recovery (login ด้วย backup code → revoke all → re-register)
- email OTP recovery
- admin reset passkeys
- recovery audit trail (Improvement #7)
