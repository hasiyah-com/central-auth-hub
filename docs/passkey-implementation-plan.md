# Passkey (WebAuthn/FIDO2) Implementation Plan v3

**Status**: Approved (design decisions finalized 2026-06-09, review-revised 2026-06-10)
**Supersedes**: v2 (incorporates `PASSKEY_DESIGN2.txt` review — 10 improvements)
**Estimated effort**: 26-30 hours (~4-5 working days) — เพิ่มจาก v2 (22h) เพราะ Phase 0 Foundation + Lifecycle + Audit Trail

---

## What's new in v3 (vs v2)

ปรับตาม `PASSKEY_DESIGN2.txt` review — 10 ข้อ:

| # | Improvement | Priority | จัดอยู่ใน Phase |
|---|---|---|---|
| 1 | Future-ready Discoverable Credential API | Low | Phase 7 (deferred) |
| 2 | **Step-up session cache** (`step_up_until`) | **High** | **Phase 0 + 5** |
| 3 | **Mandatory backup code generation** | **High** | **Phase 1** |
| 4 | Passkey lifecycle (rename, last_used, history) | Medium | Phase 3 |
| 5 | Device Trust Score ML features | Medium | Phase 5 |
| 6 | **Environment separation** (`auth.local` / dev / prod) | **High** | **Phase 0** |
| 7 | Recovery audit trail (specific events) | Medium | Phase 4 + 7 |
| 8 | **Critical Action Policy layer** | **High** | **Phase 0 + 5** |
| 9 | Passkey registration limit (10/user — adjusted from 5) | Low | Phase 3 |
| 10 | Sign counter monitoring (lenient + risk +0.2) | Medium | Phase 5 |

**สิ่งที่ผมเพิ่มเองนอก review:**
- Backup code rotation reminder (7/10 used → prompt regenerate)
- Last-Passkey deletion guard (block UI ถ้าจะลบตัวสุดท้าย)
- WebAuthn browser feature detection (graceful fallback)
- Origin allowlist per RP ID (subdomain support)

---

## 0. Context & ทำไม Passkey

### โจทย์เดิม
- LINE Login ใช้ไม่ได้ stable (email scope edge case ที่หาทางออกไม่ลงตัว)
- Email OTP เป็น MFA หลัก แต่ phishable + พึ่ง SMTP relay
- Defense story อ่อน — IdP ที่มี OAuth ทุกที่ มี

### ทำไมเลือก Passkey
- ✅ **Phishing-resistant by design** — cryptographic credential, ไม่มี shared secret
- ✅ **ไม่มี external dependency** — ไม่ต้องการ LINE/Google/Microsoft/SMTP
- ✅ **Modern auth standard** — NIST SP 800-63-4 + FIDO Alliance + ใช้ที่ Apple/Google/Microsoft ปี 2024
- ✅ **Integrate กับ RBA ได้** — เป็นทั้ง primary auth + step-up auth
- ✅ **Defense storytelling แข็ง** — "post-password auth platform"

### ข้อจำกัดที่ต้องรองรับ (สำคัญสำหรับ user นักศึกษา)
- โทรศัพท์ไม่รองรับ biometric (Android เก่า, iPhone < SE2)
- คอม lab ไม่มี Windows Hello / ไม่มี webcam
- Browser เก่า (ห้องเรียนคอม IE / old Edge)
- User ทำมือถือหาย / device พัง

→ **ต้องไม่บังคับ Passkey** + Google ยังเป็น fallback หลัก

---

## 1. Design Decisions (10 ข้อ — finalized) + Review adjustments

| # | Decision | เลือก | เหตุผล |
|---|---|---|---|
| 1 | Discoverable Credential | **B** — email ก่อน → challenge ต่อ account นั้น | กัน account enumeration. **API จะออกแบบรองรับ discoverable ในอนาคต (Improvement #1)** |
| 2 | User Verification | **`required`** | นโยบาย "Passkey = strong MFA" — ต้อง biometric/PIN ทุกครั้ง |
| 3 | Authenticator Type | **ทั้งสองแบบ** — user เลือก | รองรับนักศึกษาที่ใช้ YubiKey หรือ TouchID หรือทั้งคู่ |
| 4 | Backup Code | **10 codes** · format `AB3D-7K9P` · Argon2id hash · **show once + บังคับสร้างหลัง register Passkey แรก** (Improvement #3) | 8 chars (32^8 ≈ 40 bits), human-readable, ปลอดภัยใน DB. **ปุ่ม Skip ไม่มี — ต้อง download/copy ก่อนปิด modal** |
| 5 | Step-up threshold | **Hybrid** — ML score ≥ 0.7 OR critical action **OR sign counter regression (+0.2 boost, Improvement #10)** | ครอบคลุมทั้ง risk-based + action-based + clone-detection |
| 6 | Recovery priority | **B** — Backup code → Email OTP → Admin | Backup code self-service สุด ลด admin load |
| 7 | Mobile-as-Passkey | **รองรับ** (WebAuthn hybrid transport) | นักศึกษามีมือถือทุกคน — QR code login จาก PC lab |
| 8 | RP ID + Domain | **Environment separation (Improvement #6)** — `auth.local` (dev) / `auth-dev.uni.ac.th` (staging) / `auth.uni.ac.th` (prod) | Passkey ไม่ portable cross-env — กำหนดชัดตั้งแต่ day 1 ลด migration pain |
| 9 | Sign counter regression | **Lenient + audit + risk boost +0.2 (Improvement #10)** | กัน false positive จาก iCloud sync แต่ยังตรวจจับ clone ได้ |
| 10 | No Passkey + No verified email | **บังคับ verify email ก่อนใช้ระบบ** | ทุก user ต้องมี recovery channel เสมอ |

### Review-added decisions

| # | New decision | ค่า |
|---|---|---|
| 11 | **Step-up cache TTL** (Improvement #2) | **15 นาที** (env: `STEPUP_CACHE_TTL_SEC=900`) — ปรับได้ |
| 12 | **Critical actions list** (Improvement #8) | 6 actions — ตรวจ Section 6.3 |
| 13 | **Max Passkeys per user** (Improvement #9 + my refinement) | **10** (review บอก 5 — ขอแก้เพราะ modern user ใช้หลาย device) |
| 14 | **Counter regression risk boost** (Improvement #10) | **+0.2 to risk_score** (ไม่ block) |
| 15 | **Last-Passkey deletion** (my add) | Block UI + require backup code confirm |

---

## 2. Architecture Overview

### Authentication Matrix

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  Login page (/auth/login)                                        │
│  ┌─────────────────────┐    ┌─────────────────────┐             │
│  │ 🔑 Sign in Passkey │    │ 🔵 Sign in Google  │             │
│  └─────────────────────┘    └─────────────────────┘             │
│        ▲                            ▲                            │
│        │                            │                            │
│   email-first prompt           OAuth flow                        │
│        │                            │                            │
│        ▼                            ▼                            │
│   Challenge issued            Issue JWT                          │
│        │                            │                            │
│        ▼                            ▼                            │
│   Browser does WebAuthn       /dashboard                         │
│        │                                                         │
│        ▼                                                         │
│   POST /passkey/login/complete                                   │
│        │                                                         │
│        ▼                                                         │
│   Verify signature + counter                                     │
│        │                                                         │
│        ▼                                                         │
│   Issue JWT (+ step_up_until=NOW+15m if just verified)          │
│        │                                                         │
│        ▼                                                         │
│   /dashboard                                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  High-risk login OR Critical Action (Hybrid trigger)             │
│                                                                  │
│  Check session "step_up_until" first (Improvement #2)            │
│  ├─ step_up_until > NOW → BYPASS (trusted session, 15 min)      │
│  └─ step_up_until <= NOW OR missing → require step-up:          │
│     ├─ has_passkey=true → require Passkey re-auth               │
│     ├─ has_passkey=false + email_verified=true → Email OTP      │
│     └─ neither → 403 + force email verify                       │
│                                                                  │
│  After success: SET step_up_until = NOW + 15 min                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Critical Actions (Improvement #8 — bypass risk score)           │
│                                                                  │
│  These ALWAYS require step-up regardless of ML score:           │
│  1. delete_passkey (any)                                        │
│  2. register_new_passkey                                        │
│  3. change_mfa_settings (regenerate backup codes)               │
│  4. rotate_oauth_secret (subsystem secret)                      │
│  5. promote_to_admin                                            │
│  6. bulk_permission_change (mass whitelist edit)                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Lost device recovery                                            │
│                                                                  │
│  Priority B order (try in sequence):                            │
│                                                                  │
│  1️⃣  Backup code (10 codes generated mandatorily at first       │
│      Passkey register — Improvement #3)                         │
│     → กรอก code → ลบ Passkey เก่าทั้งหมด → ต้อง register ใหม่   │
│     → Audit: PASSKEY_RECOVERY_STARTED → ..._SUCCESS             │
│                                                                  │
│  2️⃣  Email OTP                                                   │
│     → ส่ง 6-digit code → 5 นาที expire                          │
│     → 5 attempts max → lockout                                  │
│                                                                  │
│  3️⃣  Admin reset (require_hub_admin)                             │
│     → /admin/users/{id}/reset-passkeys                          │
│     → user ต้อง verify email next login → register Passkey ใหม่ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Model

### New Tables

```sql
-- passkey_credentials: 1 user → N devices
CREATE TABLE passkey_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- WebAuthn standard fields (binary stored as bytea)
    credential_id BYTEA UNIQUE NOT NULL,
    public_key BYTEA NOT NULL,
    sign_count BIGINT NOT NULL DEFAULT 0,
    aaguid UUID,                          -- authenticator GUID (TouchID, YubiKey, etc.)
    transports VARCHAR[] DEFAULT '{}',    -- ['usb','nfc','ble','internal','hybrid']

    -- User-facing metadata (Improvement #4 — lifecycle)
    device_name VARCHAR(100) NOT NULL,    -- "iPhone 14 Pro" (user-typed, renameable)
    device_type VARCHAR(50),              -- "platform" | "cross-platform"
    nickname_history JSONB DEFAULT '[]',  -- audit: [{from, to, at}]

    -- Timestamps + lifecycle
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,
    last_used_ip INET,                    -- Improvement #4 — registration history
    last_used_user_agent TEXT,
    revoked_at TIMESTAMP,                 -- soft delete (audit trail)
    revoked_reason VARCHAR(50),           -- 'user_deleted' | 'admin_reset' | 'backup_recovery' | 'email_recovery'

    -- For risk scoring (Section 6)
    backup_eligible BOOLEAN,              -- ตาม flag จาก attestation
    backup_state BOOLEAN,                 -- ตาม flag — ถ้า device sync ขึ้น cloud

    -- Improvement #10 — counter monitoring
    counter_regression_count INT DEFAULT 0,
    last_counter_regression_at TIMESTAMP
);

CREATE INDEX ix_passkey_user_id ON passkey_credentials(user_id);
CREATE INDEX ix_passkey_credential_id ON passkey_credentials(credential_id);
CREATE INDEX ix_passkey_active ON passkey_credentials(user_id) WHERE revoked_at IS NULL;

-- passkey_backup_codes: 10 codes per user (mandatory — Improvement #3)
CREATE TABLE passkey_backup_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    code_hash TEXT NOT NULL,              -- Argon2id (memory=64MB, t=3)
    used_at TIMESTAMP,                    -- NULL = unused
    used_ip INET,
    used_user_agent TEXT,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    generation INTEGER NOT NULL DEFAULT 1,  -- เผื่อ user re-generate ทั้ง batch

    -- Acknowledged tracking (Improvement #3 — mandatory)
    acknowledged_at TIMESTAMP             -- user confirmed "I saved these" — required to leave modal
);

CREATE INDEX ix_passkey_backup_user ON passkey_backup_codes(user_id);
CREATE INDEX ix_passkey_backup_unused ON passkey_backup_codes(user_id) WHERE used_at IS NULL;
```

### Redis structures (challenge + step-up cache)

```
Key                              | TTL  | Value
─────────────────────────────────|──────|─────────────────────────────
passkey:reg:challenge:{user_id}  | 300s | {challenge, options}
passkey:auth:challenge:{email}   | 300s | {challenge, allow_credentials[]}
passkey:auth:challenge:{user_id} | 300s | {challenge, allow_credentials[]}

# NEW (Improvement #2) — Step-up trusted session cache
stepup:granted:{user_id}:{jti}   | 900s | {granted_at, method, ip}
                                          # method: "passkey" | "otp"
                                          # ใช้ตอน critical action: HEXISTS → bypass
```

### Add column to `users` table

```sql
ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP;
-- จะ backfill = true สำหรับ user ที่ login Google สำเร็จแล้ว (Google เป็นคน verify ให้)
```

---

## 4. Backend Implementation

### 4.1 Dependencies (`hub/backend/requirements.txt`)

```python
# Passkey / WebAuthn — FIDO Alliance reference impl
webauthn==2.5.0
```

### 4.2 Settings (`config.py`) — Environment Separation

**Decision (Q1 + Q6, 2026-06-10):** ตอนนี้ยังไม่มี production domain → ใช้ `localhost` ก่อน
(WebAuthn allow localhost ตาม spec — ไม่ต้อง hosts override). โครงสร้าง env-separation
จะ ready ในไฟล์ config — แค่เปลี่ยน env var → switch ได้ตอนมี prod domain.
**คาดว่าตอน migrate prod → Passkey ทั้งหมดจะ invalidate** (รับเงื่อนไขนี้แล้ว).

```python
# WebAuthn / Passkey
webauthn_rp_id: str = "localhost"                # dev/staging/prod ทั้งหมดยังใช้ตอนนี้
                                                 # future prod: เปลี่ยนเป็น "auth.uni.ac.th"
                                                 # future staging: "auth-dev.uni.ac.th"
webauthn_rp_name: str = "Central Auth Hub"
webauthn_origins: list[str] = ["http://localhost:3000"]  # allowlist — รองรับ subdomain
                                                 # future prod: ["https://auth.uni.ac.th"]
webauthn_challenge_ttl_sec: int = 300            # 5 นาที
webauthn_backup_codes_count: int = 10
webauthn_max_passkeys_per_user: int = 10         # Improvement #9 (adjusted from 5)

# Step-up Authentication Cache (Improvement #2)
stepup_cache_ttl_sec: int = 900                  # 15 นาที (Q7 — ปรับ env ได้ทีหลัง)
stepup_counter_regression_risk_boost: float = 0.2  # Improvement #10
```

**.env.example:**
```bash
# WebAuthn — change for staging/prod
WEBAUTHN_RP_ID=localhost
WEBAUTHN_ORIGINS=http://localhost:3000

# Step-up cache (configurable per env, e.g. 300 for high-security admin)
STEPUP_CACHE_TTL_SEC=900
```

### 4.3 Service Layer

#### `services/webauthn_service.py`

```python
# REGISTRATION FLOW
def register_begin(user, db) -> dict:
    """สร้าง challenge + options สำหรับ navigator.credentials.create()
    - Check user.passkey_count < webauthn_max_passkeys_per_user (Improvement #9)
      → raise 400 if exceeded
    - exclude_credentials: list ของ credential_id ที่ user มีอยู่แล้ว
    - authenticator_selection: {residentKey: "preferred", userVerification: "required"}
    - เก็บ challenge ใน Redis (TTL 300s)
    """

def register_complete(user, client_data, device_name, db) -> tuple[PasskeyCredential, list[str] | None]:
    """Verify attestation จาก browser
    - ตรวจ challenge match Redis
    - Verify signature ด้วย webauthn lib
    - Extract: credential_id, public_key, sign_count, aaguid, transports
    - Save → passkey_credentials
    - **MANDATORY backup codes** (Improvement #3): ถ้า user.backup_code_count == 0
      → generate 10 codes → return plaintext list (frontend จะ force modal)
      → ถ้ามีอยู่แล้ว → return None
    - Audit: PASSKEY_REGISTERED
    """

# AUTHENTICATION FLOW
def auth_begin(email, db) -> dict:
    """Email-first (Decision #1) — แต่ API ออกแบบรองรับ discoverable future
    - หา user from email; allow_credentials list with transports
    - user_verification: "required"
    - Redis key = "passkey:auth:challenge:{email}"
    """

def auth_complete(email, client_data, request, db) -> tuple[User, dict]:
    """Verify assertion + counter monitoring
    - Find credential, verify signature
    - **Counter check** (Improvement #10):
      if new_count > 0 and new_count <= stored_count:
          log.warning(...)
          credential.counter_regression_count += 1
          audit: PASSKEY_LOGIN_COUNTER_REGRESSION
          # return extra meta: {"counter_regression": True, "risk_boost": 0.2}
    - Update sign_count, last_used_at, last_used_ip
    - Return (user, metadata)
    """

# STEP-UP AUTH (Improvement #2 — session-aware)
def stepup_check_cached(user_id, jti, redis) -> bool:
    """ตรวจว่ามี trusted session คงเหลืออยู่ไหม
    Redis: stepup:granted:{user_id}:{jti}
    """

def stepup_begin(user_id, db) -> dict:
    """Generate challenge — เหมือน auth_begin แต่ user รู้แล้ว"""

def stepup_complete(user_id, jti, client_data, redis, db) -> bool:
    """Verify + set Redis stepup:granted:{user_id}:{jti} TTL=900s
    Audit: PASSKEY_STEPUP_SUCCESS
    """
```

#### `services/critical_action_policy.py` (NEW — Improvement #8)

```python
"""Critical Action Policy Layer — bypass ML, always require step-up.

ใช้ตอน endpoint admin / sensitive ก่อนทำ action จริง:

    require_stepup(request, user, action="delete_passkey")
"""

CRITICAL_ACTIONS = {
    "delete_passkey",
    "register_new_passkey",
    "regenerate_backup_codes",
    "rotate_oauth_secret",
    "promote_to_admin",
    "bulk_permission_change",
}

async def require_stepup(request, user, action: str, db, redis):
    """
    Check if action requires step-up. If yes:
      1. Check Redis stepup:granted:{user_id}:{jti} — bypass if exists
      2. Else raise 403 with code="stepup_required" + action="..."
    """
    jti = request.state.jwt_jti  # set by JWT middleware
    if action not in CRITICAL_ACTIONS:
        return  # not critical, pass through

    if await stepup_check_cached(user.id, jti, redis):
        return  # trusted session, bypass

    raise HTTPException(
        status_code=403,
        detail={
            "code": "stepup_required",
            "action": action,
            "redirect": "/auth/passkey/stepup?return_to=" + request.url.path,
        },
    )
```

#### `services/passkey_recovery.py`

```python
# BACKUP CODES
def generate_backup_codes(user_id, db) -> list[str]:
    """10 codes format AB3D-7K9P, Argon2id hash, generation += 1, mandatory ack"""

def verify_backup_code(user_id, code, request, db) -> bool:
    """Constant-time check, revoke all Passkeys with reason='backup_recovery'
    Audit: PASSKEY_RECOVERY_STARTED → BACKUP_CODE_USED → PASSKEY_RECOVERY_SUCCESS
    """

def check_low_codes(user_id, db) -> bool:
    """Improvement #7 — return True if used >= 7/10 (prompt regenerate)"""

# EMAIL OTP (reuse mfa_service.py)
def email_otp_begin(user_id, db) -> str: ...
def email_otp_verify(challenge_id, otp, request, db) -> bool: ...

# ADMIN RESET
def admin_reset_passkeys(target_user_id, admin_id, db) -> int:
    """Audit: PASSKEY_ADMIN_RESET → revoke all + reason='admin_reset'"""
```

### 4.4 Router (`routers/passkey.py`)

```python
router = APIRouter()

# Registration (require login JWT + critical action check)
@router.post("/account/passkeys/register/start",
             dependencies=[Depends(critical_action_policy.gate("register_new_passkey"))])
async def register_start(user=Depends(get_current_user)): ...

@router.post("/account/passkeys/register/finish")
async def register_finish(body, user=Depends(get_current_user)): ...

# Authentication (no JWT — email-first)
@router.post("/auth/passkey/login/start")
async def login_start(body: {email}): ...

@router.post("/auth/passkey/login/finish")
async def login_finish(body): ...

# Future: Discoverable Credential (Improvement #1 — API ready, not wired yet)
@router.post("/auth/passkey/login/discoverable/start")
async def login_discoverable_start():
    """Reserved for Phase 7. Returns 501 Not Implemented for now."""
    raise HTTPException(501, "Discoverable Credential login coming in Phase 7")

# Step-up (JWT required)
@router.post("/auth/passkey/stepup/start")
async def stepup_start(user=Depends(get_current_user)): ...

@router.post("/auth/passkey/stepup/finish")
async def stepup_finish(body, request, user=Depends(get_current_user)):
    """หลัง verify → Redis SET stepup:granted:{uid}:{jti} TTL=900"""

# Management — Lifecycle (Improvement #4)
@router.get("/account/passkeys")
async def list_passkeys(user=Depends(get_current_user)):
    """Return [{id, device_name, device_type, created_at, last_used_at,
              last_used_ip_country, transports, is_current}]"""

@router.patch("/account/passkeys/{id}")
async def rename_passkey(id, body, user=Depends(get_current_user)):
    """Append to nickname_history JSONB"""

@router.delete("/account/passkeys/{id}",
               dependencies=[Depends(critical_action_policy.gate("delete_passkey"))])
async def delete_passkey(id, user=Depends(get_current_user)):
    """Decision #15 — block if user.active_passkey_count == 1
    Return 400 {code: "last_passkey", message: "Use backup codes to recover access"}
    """

# Backup codes
@router.post("/account/passkeys/backup-codes/regenerate",
             dependencies=[Depends(critical_action_policy.gate("regenerate_backup_codes"))])
async def regenerate_backup_codes(user=Depends(get_current_user)): ...

@router.get("/account/passkeys/backup-codes/status")
async def backup_codes_status(user=Depends(get_current_user)):
    """{used: 3, remaining: 7, low: false, generation: 1}
    low=true ถ้า used >= 7 (Improvement #7 — prompt regenerate)"""

# Recovery (no JWT)
@router.post("/auth/passkey/recover/backup-code")
async def recover_via_backup(body: {email, code}): ...

@router.post("/auth/passkey/recover/email-otp/start")
async def recover_email_otp_start(body: {email}): ...

@router.post("/auth/passkey/recover/email-otp/verify")
async def recover_email_otp_verify(body: {challenge_id, otp}): ...

# Admin
@router.post("/admin/users/{user_id}/reset-passkeys",
             dependencies=[Depends(require_hub_admin),
                          Depends(critical_action_policy.gate("admin_reset"))])
async def admin_reset_passkeys_endpoint(user_id): ...
```

---

## 5. Frontend Implementation

### 5.1 WebAuthn browser wrapper (`lib/passkey.ts`)

```typescript
// Feature detection (my add — graceful fallback for old browsers)
export function isPasskeySupported(): boolean {
  return typeof window !== "undefined"
    && !!window.PublicKeyCredential
    && !!navigator.credentials?.create;
}

export async function registerPasskey(
  beginUrl: string,
  finishUrl: string,
  deviceName: string,
): Promise<{ id: string; backupCodes?: string[] }>;

export async function loginWithPasskey(
  email: string,
  beginUrl: string,
  finishUrl: string,
): Promise<{ token: string }>;

export async function stepUpWithPasskey(): Promise<void>;

export function bufferToBase64URL(buffer: ArrayBuffer): string;
export function base64URLToBuffer(b64: string): ArrayBuffer;
```

### 5.2 Pages

| Path | Purpose | Effort |
|---|---|---|
| `auth/login/page.tsx` | + 🔑 Passkey button (conditional on `isPasskeySupported()`) | 1.5 ชม. |
| `auth/passkey/page.tsx` | WebAuthn login dance | 1 ชม. |
| `auth/passkey/stepup/page.tsx` | Step-up re-auth | 1 ชม. |
| `auth/passkey/recover/page.tsx` | Backup + Email OTP recovery | 2 ชม. |
| `(console)/account/security/page.tsx` | List + Add + Delete + Backup codes status | 4 ชม. |
| `(console)/account/security/_components/BackupCodesModal.tsx` | **Mandatory ack** (Improvement #3) — no skip button | 1.5 ชม. |
| `(console)/account/security/_components/AddPasskeyDialog.tsx` | Name input + WebAuthn trigger | 1 ชม. |
| `(console)/account/security/_components/PasskeyCard.tsx` | Per-Passkey row: rename inline, last used, delete confirm | 1.5 ชม. |

### 5.3 Step-up integration

`middleware.ts` หรือ `lib/api.ts`:
- API 403 `{code: "stepup_required", action, redirect}` → push to `/auth/passkey/stepup?return_to=...`
- Step-up success → redirect back

### 5.4 BackupCodesModal — Mandatory UX (Improvement #3)

```tsx
// State machine: "shown" → "downloaded_OR_copied" → "ack_checkbox" → close enabled
// ห้ามมีปุ่ม X / ESC / Cancel ก่อน acknowledged
// POST /account/passkeys/backup-codes/acknowledge → set acknowledged_at
```

---

## 6. ML / Risk Engine Integration

### 6.1 New features (extend `feature_extraction.py`) — Improvement #5

| Feature ใหม่ | Range | Risk implication |
|---|---|---|
| `has_passkey` | 0/1 | 1 = trusted, ลด risk |
| `passkey_count` | 0-10 | มากกว่า = mature account |
| `passkey_age_days` (oldest active) | 0-365 | ใหม่ = น่าสงสัย |
| `new_passkey_recently_added` | 0/1 | < 5 นาที + login จาก device อื่น = takeover sign |
| `passkey_last_used_days` | 0-365 | นานไม่ใช้ = device อาจเปลี่ยน |
| `passkey_verified_recently` (NEW) | 0/1 | Verified ใน 24h = trust++ |
| `device_trust_score` (NEW — composite) | 0-1 | Weighted: passkey_age + last_used + counter_regression |

→ **ต้อง retrain model** หลังเพิ่ม features (B27 rule)

→ Cold start: user ที่ยังไม่มี Passkey → features = 0, neutral risk contribution

### 6.2 Step-up trigger logic (Hybrid — Decision #5)

```python
# ใน oauth.py / login flow หลังคำนวณ risk
HIGH_RISK_THRESHOLD = 0.7

# Apply counter regression boost (Improvement #10)
if metadata.get("counter_regression"):
    risk_score = min(1.0, risk_score + settings.stepup_counter_regression_risk_boost)

# Trigger decision (3-way)
needs_stepup = (
    risk_score >= HIGH_RISK_THRESHOLD
    or current_action in CRITICAL_ACTIONS
)

if needs_stepup:
    # Check step-up session cache first (Improvement #2)
    if await stepup_check_cached(user.id, jti, redis):
        pass  # trusted session, allow
    elif user.has_passkey:
        # Issue token with "stepup_pending: true" claim
    elif user.email_verified:
        # Fall back to Email OTP
    else:
        # Block + force email verification (Decision #10)
        raise HTTPException(403, "Email verification required")
```

### 6.3 Critical Actions list (Improvement #8 — Section 4.3)

ครบทั้ง 6 actions ใน `critical_action_policy.py`. ทุก action ใส่ `Depends(critical_action_policy.gate(...))` ที่ router level.

---

## 7. Audit Events ใหม่ (Improvement #7 — recovery trail)

```python
# services/audit_service.py — เพิ่ม action constants

# Passkey lifecycle
PASSKEY_REGISTERED = "passkey_registered"
PASSKEY_DELETED = "passkey_deleted"
PASSKEY_RENAMED = "passkey_renamed"
PASSKEY_LAST_DELETION_BLOCKED = "passkey_last_deletion_blocked"  # my add

# Auth
PASSKEY_LOGIN_SUCCESS = "passkey_login_success"
PASSKEY_LOGIN_FAILED = "passkey_login_failed"
PASSKEY_LOGIN_COUNTER_REGRESSION = "passkey_login_counter_regression"  # Improvement #10

# Step-up
PASSKEY_STEPUP_SUCCESS = "passkey_stepup_success"
PASSKEY_STEPUP_FAILED = "passkey_stepup_failed"
PASSKEY_STEPUP_CACHE_HIT = "passkey_stepup_cache_hit"  # Improvement #2

# Backup codes
PASSKEY_BACKUP_CODES_GENERATED = "passkey_backup_codes_generated"
PASSKEY_BACKUP_CODES_REGENERATED = "passkey_backup_codes_regenerated"
PASSKEY_BACKUP_CODES_ACKNOWLEDGED = "passkey_backup_codes_acknowledged"  # Improvement #3
BACKUP_CODE_USED = "backup_code_used"                                    # Improvement #7
BACKUP_CODES_LOW = "backup_codes_low"  # 7+/10 used

# Recovery (Improvement #7 — full trail)
PASSKEY_RECOVERY_STARTED = "passkey_recovery_started"
PASSKEY_RECOVERY_SUCCESS = "passkey_recovery_success"
PASSKEY_RECOVERY_FAILED = "passkey_recovery_failed"
PASSKEY_RECOVERY_VIA_BACKUP_CODE = "passkey_recovery_via_backup_code"
PASSKEY_RECOVERY_VIA_EMAIL_OTP = "passkey_recovery_via_email_otp"
PASSKEY_ADMIN_RESET = "passkey_admin_reset"

# Edge
PASSKEY_REQUIRED_NO_PASSKEY = "passkey_required_no_passkey"
CRITICAL_ACTION_STEPUP_REQUIRED = "critical_action_stepup_required"  # Improvement #8
```

---

## 8. Phase Plan (7 phases — v3)

### Phase 0 — Foundation (NEW — 4 ชม.) — Phase 1 from review "Must Have"

ทำก่อนเริ่ม Passkey จริง — infrastructure foundation:

- [ ] **Environment Separation** (Improvement #6):
  - `config.py`: `webauthn_rp_id`, `webauthn_origins` (list)
  - `.env.example`: ตัวอย่าง 3 env (auth.local / auth-dev / auth)
  - `docs/guides/passkey-env-setup.md`: hosts file override + Cloudflare tunnel guide
- [ ] **Step-up Cache Infrastructure** (Improvement #2):
  - `services/stepup_cache.py`: `set_granted()` / `check_cached()`
  - `config.py`: `stepup_cache_ttl_sec`
  - Unit test
- [ ] **Critical Action Policy Layer** (Improvement #8):
  - `services/critical_action_policy.py`: `CRITICAL_ACTIONS` set + `gate()` dependency
  - Unit test
- [ ] **Email Verification Backfill**:
  - SQL: `ALTER TABLE users + email_verified`
  - Backfill: `UPDATE users SET email_verified=true WHERE google_sub IS NOT NULL`
- **Verify**: Step-up cache returns True/False correctly; gate() raises 403; env switch works

---

### Phase 1 — Schema + Registration + **Mandatory Backup Codes** (6 ชม.)

- [ ] `requirements.txt`: + `webauthn==2.5.0`
- [ ] DB migration: `passkey_credentials` + `passkey_backup_codes`
- [ ] `models.py`: PasskeyCredential + PasskeyBackupCode
- [ ] `services/webauthn_service.py`: register_begin + register_complete + max 10 check
- [ ] `services/passkey_recovery.py`: generate_backup_codes + acknowledge endpoint
- [ ] `routers/passkey.py`: register/{start,finish} + backup-codes/acknowledge
- [ ] `lib/passkey.ts`: registerPasskey + isPasskeySupported + base64URL helpers
- [ ] `(console)/account/security/page.tsx`: minimal Add Passkey button
- [ ] **`BackupCodesModal.tsx`: mandatory acknowledge UX** (no skip — Improvement #3)
- **Verify**: register Passkey → backup modal pops → cannot close without ack → DB has 10 codes + acknowledged_at set

### Phase 2 — Login Flow (3 ชม.)

- [ ] `webauthn_service.py`: auth_begin + auth_complete + counter check
- [ ] `routers/passkey.py`: /auth/passkey/login/{start,finish}
  + reserved `/auth/passkey/login/discoverable/start` returns 501 (Improvement #1 API-ready)
- [ ] `auth/login/page.tsx`: + Passkey button (conditional on browser support)
- [ ] `auth/passkey/page.tsx`: WebAuthn login dance
- **Verify**: logout → login Passkey → JWT issued → dashboard

### Phase 3 — Lifecycle Management (3 ชม.) — Improvement #4 + #9

- [ ] `webauthn_service.py`: list/rename/soft-delete + active count check
- [ ] `routers/passkey.py`: GET/PATCH/DELETE /account/passkeys
  + **Last-Passkey deletion guard** (my add: 400 last_passkey)
  + **Max 10 check** at register (Improvement #9)
- [ ] `(console)/account/security/page.tsx`: full table — name, type, last_used, last_country
- [ ] `AddPasskeyDialog.tsx`: name input + WebAuthn trigger
- [ ] `PasskeyCard.tsx`: rename inline, delete confirm modal
- [ ] Audit: nickname_history append on rename
- **Verify**: register 2 devices, rename, see history, delete one, try delete last → blocked

### Phase 4 — Recovery + **Audit Trail** (Improvement #7) (4 ชม.)

- [ ] `passkey_recovery.py`: verify_backup_code + email_otp_{begin,verify} + check_low_codes
- [ ] `routers/passkey.py`: /auth/passkey/recover/* endpoints
- [ ] `routers/admin.py`: /admin/users/{id}/reset-passkeys
- [ ] `auth/passkey/recover/page.tsx`: backup code + email OTP UI
- [ ] Audit: full trail (STARTED → ... → SUCCESS / FAILED)
- [ ] **Backup code rotation reminder** (my add): if used >= 7/10 → toast "regenerate now"
- [ ] Admin dashboard: "Reset Passkeys" button per user
- **Verify**: 3 recovery paths work; audit trail complete; low-codes warning shows

### Phase 5 — Step-up Auth + ML + **Critical Action Policy** (5 ชม.) — Improvement #2, #5, #8, #10

- [ ] `feature_extraction.py`: + 7 features (Improvement #5)
- [ ] Retrain model + restart ML service (regenerate_data + train_model)
- [ ] `webauthn_service.py`: stepup_begin + stepup_complete + cache write
- [ ] `routers/passkey.py`: /auth/passkey/stepup/{start,finish}
- [ ] `oauth.py` callback:
  + stepup detection (risk ≥ 0.7 OR critical action)
  + counter regression boost (+0.2)
  + check cache first → bypass if granted
- [ ] Apply `critical_action_policy.gate(...)` to 6 critical endpoints (Improvement #8)
- [ ] `middleware.ts`: handle 403 stepup_required → redirect
- [ ] `auth/passkey/stepup/page.tsx`: WebAuthn re-auth dance
- **Verify**:
  - High-risk login → step-up → trusted 15 min
  - 2nd critical action within 15 min → no prompt (cache hit)
  - 16 min later → step-up again
  - Counter regression → audit logged + risk +0.2
  - User without Passkey → fallback OTP

### Phase 6 — Integration Tests + Polish (5 ชม.)

- [ ] `tests/conftest.py`: + mock authenticator fixture (webauthn lib test utils)
- [ ] `tests/test_passkey_register.py`: 5 tests (success/expired/duplicate/invalid_attestation/exceed_max_10)
- [ ] `tests/test_passkey_login.py`: 5 tests (success/wrong/counter_regression_lenient/expired/no_passkey)
- [ ] `tests/test_passkey_recovery.py`: 7 tests (backup success/used/invalid + otp success/lockout + admin reset + audit_trail_complete)
- [ ] `tests/test_passkey_stepup.py`: 5 tests (success/cache_hit_bypass/critical_action/expired_cache_re_prompt/no_passkey_fallback_otp)
- [ ] `tests/test_critical_action_policy.py`: 3 tests (gate_blocks/gate_bypasses_with_cache/not_critical_passes)
- [ ] CI: pytest in GitHub Actions
- **Verify**: pytest hub/backend/tests/test_passkey*.py → all pass (~25 tests)

### Phase 7 — Future Work (deferred, not part of v3 sprint)

- [ ] Discoverable Credentials (Improvement #1) — wire `/auth/passkey/login/discoverable`
- [ ] Advanced counter analytics dashboard
- [ ] Force adoption flow (Q5)

---

## 9. Security Implementation Notes

### 9.1 Challenge expiry & replay protection
- TTL 300s ใน Redis
- ลบ challenge ทันทีหลังใช้สำเร็จ (`getdel` — atomic, B9)

### 9.2 Sign counter — Lenient + monitored (Improvement #10)
```python
if new_count > 0 and new_count <= stored_count:
    log.warning(
        "Passkey sign counter regression: user=%s credential=%s "
        "stored=%d received=%d (lenient mode — allowing login, +0.2 risk)",
        user.id, credential.id, stored_count, new_count,
    )
    log_action(db, action=PASSKEY_LOGIN_COUNTER_REGRESSION, ...)
    credential.counter_regression_count += 1
    credential.last_counter_regression_at = utcnow()
    return user, {"counter_regression": True}  # caller applies +0.2 boost
credential.sign_count = new_count
```

### 9.3 Origin / RP ID validation — Environment Separation (Improvement #6)
- **RP ID** = domain ที่ Passkey ผูกอยู่ — cryptographically bound, เปลี่ยน = invalidate ทุกตัว
- **Origin allowlist** = `webauthn_origins: list[str]` — รองรับ subdomain (staff.auth.uni.ac.th + auth.uni.ac.th)
- Env config:
  - Dev: `rp_id="auth.local"`, hosts file + chrome --allow-insecure-localhost
  - Staging: `rp_id="auth-dev.uni.ac.th"`
  - Prod: `rp_id="auth.uni.ac.th"`
- ทำ `docs/guides/passkey-env-setup.md` แยก

### 9.4 Backup code — Mandatory acknowledge (Improvement #3)
```python
# Phase 1 — backup codes ต้องมี endpoint ack ก่อนปิด modal
@router.post("/account/passkeys/backup-codes/acknowledge")
async def acknowledge_backup_codes(user=Depends(get_current_user), db):
    """Mark all unused codes' acknowledged_at = now (or upsert one ack row).
    Frontend: required before close BackupCodesModal."""
```

### 9.5 Step-up Session Cache (Improvement #2)
```python
# Set after successful step-up
await redis.setex(f"stepup:granted:{user_id}:{jti}", 900, json.dumps({
    "granted_at": utcnow().isoformat(),
    "method": "passkey",
    "ip": get_client_ip(request),
}))

# Check before critical action
cached = await redis.get(f"stepup:granted:{user_id}:{jti}")
if cached:
    log_action(db, action=PASSKEY_STEPUP_CACHE_HIT, ...)
    return  # bypass
```

### 9.6 Argon2id usage (reuse existing `secret_service.py`)
```python
from app.services.secret_service import argon2_hash, argon2_verify
```

---

## 10. Decisions (locked 2026-06-10)

| # | Question | Decision |
|---|---|---|
| Q1 | Production domain | **`localhost` ก่อน** — migrate ทีหลัง (รับเงื่อนไข Passkey จะ invalidate ตอน switch) |
| Q2 | ML retrain ใน Phase 5 | **ใช่** — regenerate data + train_model หลังเพิ่ม features |
| Q3 | LINE button | **Comment out frontend button** — code อยู่ใน git/router, revisit เมื่อ LINE fix email scope ได้ |
| Q4 | Email verification backfill | **ใช่** — `email_verified=true` for users with `google_sub IS NOT NULL` |
| Q5 | Force adoption | **ใช่ — Phase 7+** — ตอนนี้ opt-in ทั้งหมด |
| Q6 | Dev RP ID strategy | **localhost ก่อน** (สอดคล้อง Q1) — env config ready สำหรับ switch ภายหลัง |
| Q7 | Step-up TTL | **15 นาที default** — env var `STEPUP_CACHE_TTL_SEC=900`, ปรับได้ทีหลัง |

---

## 11. Files Created / Modified Summary

### New files (20 — เพิ่มจาก v2 = 16)
```
Backend:
  hub/backend/app/services/webauthn_service.py            (~450 lines)
  hub/backend/app/services/passkey_recovery.py            (~250 lines)
  hub/backend/app/services/stepup_cache.py                (~100 lines)   [NEW Phase 0]
  hub/backend/app/services/critical_action_policy.py      (~120 lines)   [NEW Phase 0]
  hub/backend/app/routers/passkey.py                      (~400 lines)
  hub/backend/tests/test_passkey_register.py              (~180 lines)
  hub/backend/tests/test_passkey_login.py                 (~200 lines)
  hub/backend/tests/test_passkey_recovery.py              (~240 lines)
  hub/backend/tests/test_passkey_stepup.py                (~200 lines)
  hub/backend/tests/test_critical_action_policy.py        (~120 lines)   [NEW]

Frontend:
  hub/frontend/lib/passkey.ts                                          (~200 lines)
  hub/frontend/app/auth/passkey/page.tsx                               (~200 lines)
  hub/frontend/app/auth/passkey/stepup/page.tsx                        (~150 lines)
  hub/frontend/app/auth/passkey/recover/page.tsx                       (~280 lines)
  hub/frontend/app/(console)/account/security/page.tsx                 (~400 lines)
  hub/frontend/app/(console)/account/security/_components/BackupCodesModal.tsx       (~200 lines)
  hub/frontend/app/(console)/account/security/_components/AddPasskeyDialog.tsx       (~120 lines)
  hub/frontend/app/(console)/account/security/_components/PasskeyCard.tsx            (~180 lines)  [NEW]

Docs:
  docs/guides/setup-passkey.md  (user guide)
  docs/guides/passkey-env-setup.md  (Improvement #6 — env separation)   [NEW Phase 0]
  docs/passkey-implementation-plan.md  (this file)
```

### Modified files (9)
```
hub/backend/requirements.txt        + webauthn==2.5.0
hub/backend/app/config.py           + webauthn_*, stepup_*, max_passkeys (8 fields)
hub/backend/app/models.py           + PasskeyCredential + PasskeyBackupCode + User.email_verified
hub/backend/app/routers/auth.py     + email verification flow
hub/backend/app/routers/admin.py    + admin_reset_passkeys + gate("admin_reset")
hub/backend/app/routers/oauth.py    + stepup detection + cache check + counter boost
hub/backend/app/routers/developer.py + gate("rotate_oauth_secret")
hub/backend/app/services/feature_extraction.py  + 7 Passkey features
hub/backend/app/services/audit_service.py       + ~20 new event constants
hub/frontend/app/auth/login/page.tsx            + Passkey button (conditional) + email-first prompt
hub/frontend/middleware.ts                       + handle 403 stepup_required
hub/frontend/components/Sidebar.tsx              + /account/security nav entry
docs/p2-session-downgrade-plan.md   (deprecate — Passkey replaces this)
docs/bugs-encountered.md            + B42, B43 etc.
```

### SQL migrations
```
docs/sql-migrations/2026-06-XX-passkey.sql
  - CREATE TABLE passkey_credentials (+ Improvement #4 lifecycle fields)
  - CREATE TABLE passkey_backup_codes (+ acknowledged_at)
  - ALTER TABLE users ADD COLUMN email_verified, email_verified_at
  - Backfill: UPDATE users SET email_verified=true WHERE google_sub IS NOT NULL
```

---

## 12. End-to-End Verification Plan

หลัง Phase 6 จบ:

```bash
# 1. ระบบยังขึ้นปกติ
bash scripts/routine/test_workflow.sh   # 7/7 PASS

# 2. Pytest ผ่านครบ (เพิ่มจาก v2 = 18 → v3 = 25 tests)
docker compose exec hub-backend pytest hub/backend/tests/test_passkey*.py tests/test_critical_action_policy.py -v
# expect: ~25 tests pass

# 3. Phase 0 — Foundation verify
docker compose exec hub-backend pytest hub/backend/tests/test_stepup_cache.py tests/test_critical_action_policy.py -v
# RP ID env switch: APP_ENV=staging → webauthn_rp_id == auth-dev.uni.ac.th

# 4. Phase 1 — Register + mandatory backup
#    Login Google → /account/security → Add Passkey "MacBook" → TouchID
#    → BackupCodesModal pops: ไม่มีปุ่ม X — ต้อง download/copy → tick ack → close
#    DB: SELECT acknowledged_at FROM passkey_backup_codes ... → NOT NULL

# 5. Phase 2 — Login
#    Logout → /auth/login → Passkey → email → TouchID → /dashboard
#    Audit: hub_login_success metadata.provider="passkey"

# 6. Phase 3 — Lifecycle (Improvement #4)
#    Register 2 devices → /account/security: เห็น 2 รายการ (name, last_used, country)
#    Rename → audit nickname_history เพิ่ม entry
#    Delete 1 → 1 รายการ
#    Try delete last → UI blocks + 400 last_passkey
#    Register 11th → 400 max_passkeys_exceeded

# 7. Phase 4 — Recovery + audit trail (Improvement #7)
#    Path A: backup code → revoke all → DB audit log shows full trail:
#            STARTED → BACKUP_CODE_USED → SUCCESS
#    Path B: email OTP → same trail
#    Path C: admin reset → PASSKEY_ADMIN_RESET
#    ใช้ codes 7/10 → toast "regenerate now" (low codes warning)

# 8. Phase 5 — Step-up + cache + critical actions
#    Login จาก VPN → ML 0.8 → require Passkey → success
#    Within 15 min: critical action (regenerate backup codes) → no prompt (cache hit)
#    Audit: PASSKEY_STEPUP_CACHE_HIT
#    Wait 16 min: same action → step-up required again
#    User ไม่มี Passkey + ไม่ verify email → 403 force email verify
#    Counter regression test (manual): risk score +0.2 visible in ML log

# 9. Final smoke + commit + push
bash scripts/routine/test_workflow.sh
git log --oneline | head -25  # Phase 0-6 commits
```

---

## 13. Critical Files Reference

| Phase | File | Purpose |
|---|---|---|
| 0 | `services/stepup_cache.py` | Trusted session cache (Improvement #2) |
| 0 | `services/critical_action_policy.py` | Bypass-ML policy gate (Improvement #8) |
| 0 | `docs/guides/passkey-env-setup.md` | Environment separation (Improvement #6) |
| 1 | `services/webauthn_service.py` | core WebAuthn lib wrapper |
| 1 | `services/passkey_recovery.py` | backup code generation (mandatory ack) |
| 1 | `BackupCodesModal.tsx` | mandatory UX (Improvement #3) |
| 2 | `auth/login/page.tsx` | Passkey button + feature detection |
| 3 | `(console)/account/security/page.tsx` | management UI (lifecycle) |
| 3 | `PasskeyCard.tsx` | rename history + last_used display (Improvement #4) |
| 4 | `passkey_recovery.py` | recovery flows + audit trail |
| 5 | `oauth.py` | stepup detection + cache + counter boost |
| 5 | `feature_extraction.py` | 7 new ML features (Improvement #5) |
| 6 | `tests/conftest.py` | mock authenticator fixture |

---

## 14. Patterns to Reuse

- **Argon2id hash** — `services/secret_service.py:argon2_hash` (backup codes)
- **Email OTP** — `services/mfa_service.py` scaffold (recovery via email)
- **Audit log B6** — `log_action()` → `db.commit()` → `raise` (ทุก path)
- **`get_client_ip()` B20** — log IP ทุก event
- **Redis `getdel` B9** — challenge cleanup atomic
- **JWT `verify_aud` B4** — stepup token validation
- **Audit metadata pattern** — `{"provider": "passkey", "credential_id": ..., "device_name": ..., "stepup_method": ...}`
- **Dependency injection gate** — `Depends(critical_action_policy.gate("..."))` reusable across routers

---

## 15. NOT modified ใน plan นี้

- `docker-compose.yml` — Strategy A คงเดิม
- `CLAUDE.md § Roadmap` — update เมื่อ Phase 1 จบ
- LINE login code (`routers/auth.py:/line/*`) — comment out ปุ่ม frontend, code คงไว้ใน git history

---

## 16. Summary of Changes (v2 → v3)

**Added Sections / Major changes:**
1. § What's new in v3 (top — review change matrix)
2. § 1 — 5 new decisions (rows 11-15)
3. § 2 — 2 new flowchart blocks (step-up cache + critical actions)
4. § 3 — schema: `nickname_history`, `revoked_reason`, `counter_regression_*`, `acknowledged_at`, Redis `stepup:granted:*`
5. § 4 — new services: `stepup_cache.py`, `critical_action_policy.py`
6. § 4 — new endpoints: `discoverable/start` (501 placeholder), `backup-codes/acknowledge`, last-Passkey guard
7. § 5 — `isPasskeySupported()`, `PasskeyCard.tsx`, mandatory modal UX
8. § 6 — 2 new ML features (`passkey_verified_recently`, `device_trust_score`)
9. § 7 — ~10 new audit events (recovery trail + cache hit + ack + critical action)
10. § 8 — **Phase 0 (Foundation) NEW** + restructured Phase 1/3/4/5 + Phase 7 deferred
11. § 9 — new subsections: 9.4 ack, 9.5 cache, env separation in 9.3
12. § 10 — Q6, Q7 added
13. § 11 — 4 new files, 8 modified
14. Effort estimate: 22h → 30h (+8h for Phase 0 + lifecycle + tests)

**Priority summary (review's Phase categorization):**
- **Phase 1 Must Have** (review) → my **Phase 0 + portion of 1, 3, 5**
- **Phase 2 Should Have** (review) → my **Phase 3, 4, 5**
- **Phase 3 Nice to Have** (review) → my **Phase 7 (deferred)**

This v3 plan is now ready to start with **Phase 0 — Foundation** หลัง user confirm.
