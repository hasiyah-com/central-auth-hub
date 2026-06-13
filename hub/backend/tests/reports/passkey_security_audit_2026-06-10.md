# Passkey Security Audit & Bug Fixes — 2026-06-10

**Scope**: Login flow input validation + attack surface + bug sweep หลัง Phase 2
**Trigger**: user report `Unexpected token '<'...` ตอน login + ขอตรวจ SQLi/attack
**Status**: ✅ ALL FIXED & VERIFIED (81/81 tests pass)

---

## Bugs found & fixed (4)

### BUG-1 — Middleware บล็อก public Passkey login proxy (the `<!DOCTYPE` error)

**อาการ**: `Unexpected token '<', "<!DOCTYPE "... is not valid JSON` ตอนกด login ด้วย Passkey

**สาเหตุ**: `hub/frontend/middleware.ts` redirect ทุก request ที่ไม่มี JWT cookie ไป `/auth/login` (307).
`/api/proxy/auth/passkey/login/*` เป็น public flow (user ยังไม่มี token ตอน login) →
โดน redirect → fetch ได้ HTML หน้า login กลับมาแทน JSON → `JSON.parse` ระเบิด

**แก้**: เพิ่ม `/api/proxy/auth/passkey/` เข้า public allowlist ใน middleware
(แยกจาก `/api/proxy/account/passkeys/*` ที่ register/manage ยังต้อง auth)

**ไฟล์**: `hub/frontend/middleware.ts`

---

### BUG-2 — ไม่มี email format validation (ใส่อะไรก็ได้)

**อาการ**: ใส่ `"notanemail"`, SQLi, XSS payload → ตอบ 200 + challenge (ไม่ reject)

**สาเหตุ**: endpoint ใช้ `body: dict = Body(...)` — ไม่ validate อะไรเลย, แค่เช็ค `if not email`

**แก้**: เปลี่ยนเป็น Pydantic models + `EmailStr`:
- `LoginStartRequest(email: EmailStr)`
- `LoginFinishRequest(email: EmailStr, credential: dict)`
- `RegisterFinishRequest(device_name: str[1..100], credential: dict)`
+ `max_length=255` กัน oversized DoS

**ผล**: non-email → 422 พร้อม detail ชัดเจน, email format ถูก → 200 (คง anti-enumeration)

**ไฟล์**: `hub/backend/app/routers/passkey.py`

**หมายเหตุ**: ต้องลบ `from __future__ import annotations` ออก เพราะทำให้ FastAPI
resolve Pydantic model ใน route signature ไม่ได้ (forward-ref / PydanticUndefinedAnnotation).
Python 3.11 รองรับ `dict` / `X | Y` แบบ native อยู่แล้ว ไม่ต้องใช้ future import

---

### BUG-3 — `get_client_ip` ไม่ validate IP → INET insert crash + malformed-header DoS 🔴

**อาการ**: ค้นพบตอนรัน API test — `psycopg2.errors.InvalidTextRepresentation:
invalid input syntax for type inet: "testclient"` → 500

**สาเหตุ**: `get_client_ip()` คืนค่าจาก `X-Forwarded-For` / `request.client.host` ตรงๆ
โดยไม่ validate. คอลัมน์ `audit_logs.ip`, `login_sessions.ip`, `request_logs.ip` เป็น type
`INET` — ถ้าค่าไม่ใช่ IP จริง → DataError → 500 ทั้ง request

**Security impact (สำคัญ)**: attacker ส่ง `X-Forwarded-For: garbage` →
audit/log insert ล้ม → 500 ทุก request = **malformed-header DoS** + เลี่ยงการถูก log

**แก้**: เพิ่ม `_valid_ip_or_none()` ใช้ `ipaddress.ip_address()` validate —
ถ้าไม่ใช่ IPv4/IPv6 ที่ถูกต้อง คืน `None` (INET รับ NULL ได้).
XFF garbage → fallback ไป `request.client.host` → ถ้ายังไม่ใช่ IP → None

**ไฟล์**: `hub/backend/app/deps.py` (+ `request_logger.py` ให้ใช้ helper เดียวกัน
แทน duplicate logic ที่มี bug เดียวกัน)

**Verified**: `curl -H "X-Forwarded-For: not-an-ip-garbage"` → 200 (ไม่ 500 แล้ว)

---

### BUG-4 — Test fixtures ใช้ `create_access_token` เป็น string (pre-existing)

**อาการ**: 8 tests (test_rbac.py × 5, test_jwt_service.py × 3) fail ด้วย 401 / TypeError

**สาเหตุ**: `create_access_token` / `create_subsystem_token` คืน `tuple[str, str]` (token, jti)
ตั้งแต่เพิ่ม jti/revocation แต่ test fixtures + tests ยังเก็บทั้ง tuple →
`Bearer ('token','jti')` → token ผิด → 401

**แก้**: unpack `token, _jti = create_*_token(...)` ใน:
- `conftest.py` — admin_token / teacher_token / staff_token fixtures
- `test_jwt_service.py` — 4 จุด

**หมายเหตุ**: pre-existing bug ไม่เกี่ยวกับ Passkey — เจอตอน regression sweep

---

## Security verification — input attack matrix

ทดสอบ `/auth/passkey/login/start` + `/finish` (direct backend + via frontend proxy):

| Attack input | Response | ผล |
|---|---|---|
| `notanemail` (no @) | 422 value_error | ✅ reject |
| `x' OR '1'='1` (SQLi) | 422 value_error | ✅ reject |
| `a@b.com'; DROP TABLE users;--` (SQLi DROP) | 422 value_error | ✅ reject |
| `<script>alert(1)</script>` (XSS) | 422 value_error | ✅ reject |
| `<img src=x>` (XSS) | 422 value_error | ✅ reject |
| `admin@` (no domain) | 422 value_error | ✅ reject |
| `@uni.ac.th` (no local) | 422 value_error | ✅ reject |
| `a b@uni.ac.th` (space) | 422 value_error | ✅ reject |
| `../../etc/passwd` (path traversal) | 422 value_error | ✅ reject |
| `{{7*7}}` (template injection) | 422 value_error | ✅ reject |
| `user@uni..ac.th` (double dot) | 422 value_error | ✅ reject |
| email 320+ chars (oversized DoS) | 422 too long | ✅ reject |
| `{}` (missing field) | 422 missing | ✅ reject |
| non-JSON body | 422 | ✅ reject |
| **valid email (มีหรือไม่มีใน DB)** | **200 + challenge** | ✅ **anti-enumeration คงอยู่** |
| `X-Forwarded-For: garbage` | 200 (ip=NULL) | ✅ ไม่ 500 (DoS fixed) |

**SQLi proof**: หลังยิง `DROP TABLE users;--` →
`SELECT COUNT(*) FROM users` ยังคืน 104 rows (ORM parameterize, ไม่มี injection)

---

## Why SQLi เป็นไปไม่ได้ (defense layers)

1. **Pydantic EmailStr** — reject ก่อนถึง DB (format invalid → 422)
2. **SQLAlchemy ORM** — `func.lower(User.email) == email` ใช้ parameterized query
   (psycopg2 bind param) — input เป็น data ไม่ใช่ SQL เสมอ
3. **แม้ format ผ่าน** (เช่น `a@b.com`) — query แค่หา user ที่ email ตรง → ไม่เจอ → opaque 401

---

## Anti-enumeration preserved

การเพิ่ม format validation **ไม่ขัด** กับ anti-enumeration:
- format ผิด (`notanemail`) → 422 — ไม่ leak ว่ามี account ไหม (ผิด format ชัดเจน)
- format ถูกแต่ไม่มีใน DB (`ghost@uni.ac.th`) → 200 + challenge (เหมือน email จริง)
- `auth_complete` opaque 401 ทั้ง wrong-email และ wrong-credential

→ attacker เดาไม่ได้ว่า valid-format email ไหนมี account จริง

---

## Test files

| File | Tests | Purpose |
|---|---|---|
| `tests/test_passkey_security.py` | 20 | **ใหม่** — input validation + SQLi/XSS/DoS matrix |
| `tests/test_passkey_login.py` | 11 | service-layer guards (Phase 2) |
| `tests/test_passkey_register.py` | 10 | register + backup codes (Phase 1) |
| `tests/test_stepup_cache.py` | 6 | step-up cache (Phase 0) |
| `tests/test_critical_action_policy.py` | 7 | critical action gate (Phase 0) |

---

## Full regression result

```bash
docker compose exec -T hub-backend pytest \
  tests/test_passkey_register.py tests/test_passkey_login.py \
  tests/test_passkey_security.py tests/test_stepup_cache.py \
  tests/test_critical_action_policy.py tests/test_health.py \
  tests/test_rbac.py tests/test_pkce.py tests/test_jwt_service.py \
  tests/test_secret_service.py tests/test_rate_limit.py
```

```
============================= 81 passed in 15.17s ==============================
```

(หมายเหตุ: `test_e2e_full_stack.py` + `test_l1_oidc.py` เป็น standalone script
ที่มี `sys.exit(0)` ระดับ module — รันแยกผ่าน host runner ไม่ใช่ pytest collection)

---

## Files changed

### Backend
- `app/routers/passkey.py` — Pydantic request models (EmailStr) + ลบ `from __future__ import annotations`
- `app/deps.py` — `_valid_ip_or_none()` + `get_client_ip` validate IP
- `app/services/request_logger.py` — ใช้ `get_client_ip` helper (ลบ duplicate buggy logic)
- `conftest.py` — unpack token tuple ใน fixtures
- `tests/test_jwt_service.py` — unpack token tuple (4 จุด)
- `tests/test_passkey_security.py` — **ใหม่** (20 tests)

### Frontend
- `middleware.ts` — public allowlist `/api/proxy/auth/passkey/`

---

## Compliance

- **OWASP ASVS V5.1.3** — input validation ที่ server (Pydantic)
- **OWASP ASVS V5.3.4** — parameterized queries (SQLAlchemy ORM)
- **OWASP ASVS V2.1.5** — error ไม่ enumerate account
- **OWASP API4:2023** — unrestricted resource consumption (max_length + rate limit)
- **CWE-89** SQLi — mitigated (ORM + format validation)
- **CWE-79** XSS — input rejected at format layer
- **CWE-20** Improper Input Validation — fixed (EmailStr + IP validation)
- **CWE-117** Log Injection — fixed (IP validation before INET insert)
