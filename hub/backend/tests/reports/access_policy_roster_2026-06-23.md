# Report — Subsystem Access Policy + Roster Sync (Week 11, P0-P4)

- **วันที่:** 2026-06-23
- **ขอบเขต:** implement แนวคิด Access Policy 4 แบบ + Roster Sync API ตาม `docs/subsystem-access-policy-plan.md`
- **ผลรวม:** ✅ **81 passed** (access_policy 14 + roster 6 + regression 61)

## Phase ที่ทำ

| Phase | งาน | สถานะ |
|---|---|---|
| **P0** | schema: `subsystems.access_policy/access_policy_config/api_key_hash/api_key_prefix` · `access_list.entry_type` (allow/deny) | ✅ ALTER (default explicit → backward compat) |
| **P1** | role_in_sub → user_type (ทำก่อนหน้า) | ✅ |
| **P2** | Access Policy engine + login-time check + register/update | ✅ |
| **P3** | Roster Sync API (api key + `/api/v1/roster`) | ✅ |
| **P4** | Frontend — policy selector + config + API key UI | ✅ |

## P2 — Access Policy engine

`services/access_policy.py`:
- `evaluate_access_policy(db, user, subsystem) → (allowed, reason)` — explicit/all/role/attribute + **deny-list ทับ** + active check
- `list_allowed_users(db, subsystem)` — สำหรับ roster (เกณฑ์เดียวกับ login)
- wire ใน `oauth.py::_finalize_subsystem_login` แทน access_list check ตรง ๆ
- `developer.py`: register/update รับ `access_policy` + `access_policy_config` + `_validate_access_policy` (role ⊆ user_types, attribute ต้องมี ≥1 เงื่อนไข)
- เปลี่ยน policy = immediate apply + **kick ทุก session** (re-auth ผ่าน policy ใหม่)

| policy | เกณฑ์ | config |
|---|---|---|
| explicit | อยู่ใน access_list (entry_type=allow) | — |
| all | user active | — |
| role | user_type ∈ roles | {"roles":[...]} |
| attribute | faculty/major ตรง | {"faculty":[...],"major":[...]} |
| (deny) | access_list entry_type=deny → ทับทุก policy | — |

## P3 — Roster Sync API

- `secret_service.generate_api_key()` → `rsk_<32>` + prefix(12) · เก็บ Argon2 hash + prefix(index)
- ออกตอน register (response `api_key` ครั้งเดียว) + `POST /developer/subsystems/{id}/rotate-api-key`
- `routers/roster.py` — `GET /api/v1/roster` (header `X-Api-Key`):
  - auth: lookup prefix → verify Argon2 · opaque 401
  - กรองด้วย `list_allowed_users` (policy เดียวกับ login)
  - ส่ง **3 field**: `user_id, email, user_type` (ข้อมูลเต็มไหลตอน login)
  - subsystem ไม่ active → 403 · rate-limit 30/min · audit `roster_pulled`

## P4 — Frontend

`subsystems/[id]/_components/AccessPolicyCard.tsx` (admin console detail):
- selector 4 policy (radio card) + config (role=checkbox user_type · attribute=faculty/major input)
- save → `mutateWithStepup` PATCH (step-up)
- Roster API key: แสดง prefix + rotate (แสดง key ใหม่ครั้งเดียว + copy)
- serializer: `/admin/subsystems` + `/developer/subsystems` คืน access_policy/config/api_key_prefix

## ผลทดสอบ

| ชุด | ผล |
|---|---|
| `test_access_policy.py` | ✅ 14 (validate + engine 4 policy + deny + inactive + list_allowed) |
| `test_roster.py` | ✅ 6 (auth 401, filtered roster, 3 fields, count, inactive 403) |
| `test_oauth_policy_integration.py` | ✅ 2 (เรียก `_finalize_subsystem_login` จริง → deny role-policy + suspended user = 403) |
| regression (jwt/oauth/rbac/auth_policy/activity) | ✅ 61 |
| **รวม** | ✅ **83 passed** |
| OAuth authorize chooser render (active subsystem) | ✅ 200 + ปุ่ม Passkey/Google ครบ |
| frontend tsc | ✅ 0 errors |
| roster API smoke (no key) | ✅ 401 |

### Manual verify
- ตั้ง หอพัก policy=role(teacher,staff) → roster คืน 27 teacher/staff (ทุกคนตรง policy) ✅
- key ผิด/ไม่มี → 401 ✅ · reset หอพัก กลับ explicit แล้ว ✅

## Backward compat
- subsystem เดิมทุกตัว = `explicit` → login เดิมไม่เปลี่ยน (ใช้ access_list whitelist)
- JWT `role_in_subsystem` = user_type (transition alias) — subsystem code เดิมยังรันได้

## ยังไม่ทำ (optional)
- P5: subsystem "ระบบเกรด" + roster receiver demo
- policy badge บนหน้า list subsystems (polish)
- developer portal register form: policy selector (ตอนนี้ register รับ policy ได้ผ่าน API แล้ว แต่ฟอร์ม /new ยังไม่มี UI — admin detail แก้ได้)
