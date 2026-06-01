# Secret Rotation Runbook — Production Grade (Zero-downtime)

> Operational runbook สำหรับ rotate JWT signing key + Fernet encryption key
> โดย **ไม่มี downtime** + **ไม่ disrupt active sessions**

---

## 1. Architecture Overview

### JWT keys — Multi-kid JWKS (RFC 7517 §6)
- **Active key**: ใช้ sign token ใหม่ (`JWT_ACTIVE_KID` + `JWT_PRIVATE_KEY_PATH`)
- **Extra public keys**: verify-only (`JWT_EXTRA_PUBLIC_KEYS`) — รองรับ token ที่ sign ด้วย key เก่ายังอยู่
- **JWKS endpoint** คืน**ทุก kid** → subsystem cache 10 นาที + match `kid` จาก JWT header

### Fernet keys — MultiFernet (cryptography lib)
- **Primary** (`SECRET_ENCRYPTION_KEY`): ใช้ encrypt ใหม่ + ลอง decrypt ก่อน
- **Legacy** (`SECRET_ENCRYPTION_KEYS_LEGACY`, comma-separated): decrypt fallback
- ciphertext เก่า → MultiFernet ลอง primary → fail → ลอง legacy → คืน plaintext
- `rotate()` API: decrypt+encrypt atomic → ciphertext ใหม่ใช้ primary

### Recommended cadence
- **90 days** สำหรับ production
- **180 days** สำหรับ staging
- **Immediately** เมื่อสงสัยว่า key หลุด

---

## 2. JWT Signing Key Rotation

### 🟢 Phase 1: BEGIN (T+0) — Add new key as verify-only

```bash
bash scripts/security/rotate-jwt.sh begin hub-key-2
```

**สิ่งที่เกิดขึ้น:**
1. Generate RSA-2048 key pair ใหม่ → `/app/keys/hub-key-2_{private,public}.pem`
2. Append `hub-key-2:/app/keys/hub-key-2_public.pem` ใน `JWT_EXTRA_PUBLIC_KEYS` ของ `.env`
3. Recreate `hub-backend` + 2 subsystems → โหลด extra key
4. JWKS endpoint คืน **2 keys** ทันที (old active + new extra)

**Verify:**
```bash
curl -s http://localhost:8000/.well-known/jwks.json | python -m json.tool | grep '"kid"'
# ต้องเห็น 2 keys:
#   "kid": "hub-key-1"  (active)
#   "kid": "hub-key-2"  (extra, verify-only)
```

**Token state:** ยังใช้ `hub-key-1` sign — token ใหม่ทุกตัวยัง verify ได้ทั้ง Hub และ subsystem

⏱️ **รอ 5 นาที** — subsystem JWKS cache (10min TTL) จะมี hub-key-2 ก่อนเปลี่ยน active

---

### 🟡 Phase 2: ACTIVATE (T+5m) — Switch signing to new key

```bash
bash scripts/security/rotate-jwt.sh activate hub-key-2
```

**สิ่งที่เกิดขึ้น:**
1. Update `.env`:
   ```
   JWT_ACTIVE_KID=hub-key-2
   JWT_PRIVATE_KEY_PATH=/app/keys/hub-key-2_private.pem
   JWT_PUBLIC_KEY_PATH=/app/keys/hub-key-2_public.pem
   JWT_EXTRA_PUBLIC_KEYS=hub-key-1:/app/keys/jwt_public.pem  # old as extra now
   ```
2. Recreate services
3. ทุก token ใหม่หลังจากนี้ → sign ด้วย `hub-key-2`
4. Token เก่า (sign ด้วย `hub-key-1`) → verify ผ่านอยู่ (key อยู่ใน extra)

**Verify:**
```bash
# Login ใหม่ → ดู kid ของ token ใหม่
TOKEN=$(curl -s ...)
echo "$TOKEN" | cut -d. -f1 | base64 -d 2>/dev/null
# ต้องเห็น "kid":"hub-key-2"

# Token เก่ายัง verify ผ่าน:
curl -s http://localhost:8000/auth/me -H "Authorization: Bearer <old-token>"
# → 200 OK
```

⏱️ **รอ 65 นาที** — JWT TTL = 60 นาที + buffer 5 นาที — ทุก token เก่า expire แล้ว

---

### 🔴 Phase 3: FINALIZE (T+70m) — Remove old key

```bash
bash scripts/security/rotate-jwt.sh finalize hub-key-1
```

**สิ่งที่เกิดขึ้น:**
1. ลบ `hub-key-1:...` ออกจาก `JWT_EXTRA_PUBLIC_KEYS`
2. Recreate services
3. JWKS endpoint คืนเฉพาะ `hub-key-2`

**Optional cleanup:**
```bash
docker compose exec hub-backend mv /app/keys/jwt_public.pem  /app/keys/archived_hub-key-1_public.pem
docker compose exec hub-backend mv /app/keys/jwt_private.pem /app/keys/archived_hub-key-1_private.pem
```
เก็บ archive ไว้ 90 วันเผื่อ audit / forensics

---

### Status check ตลอดเวลา
```bash
bash scripts/security/rotate-jwt.sh status
```
แสดง: active kid, paths, extra keys, JWKS endpoint output

---

## 3. Fernet (Secret Encryption) Rotation

ใช้สำหรับ `secret_retrieval_tokens.secret_encrypted` (เข้ารหัส client_secret)

### 🟢 Phase 1: BEGIN

```bash
bash scripts/security/rotate-fernet.sh begin
```

- Generate new key (32 bytes hex)
- เพิ่ม old key ใน `SECRET_ENCRYPTION_KEYS_LEGACY`
- Set new key เป็น `SECRET_ENCRYPTION_KEY` (primary)
- Recreate `hub-backend`
- ciphertext ใหม่ → encrypt ด้วย new key
- ciphertext เก่า → decrypt fallback ผ่าน legacy

### 🟡 Phase 2: MIGRATE

```bash
bash scripts/security/rotate-fernet.sh migrate
```

รัน `re_encrypt_secrets.py` ใน container:
- Query: `SecretRetrievalToken` ที่ `used_at IS NULL` + `expires_at > NOW()`
- Loop: `rotate_ciphertext()` ทุก row → decrypt (legacy) + encrypt (primary)
- Commit

**Log output:**
```
Found 3 active secret_retrieval_tokens to re-encrypt
✅ Re-encrypted 3 tokens (0 unchanged, 0 failed)
```

### 🔴 Phase 3: FINALIZE

```bash
bash scripts/security/rotate-fernet.sh finalize
```
- ลบ `SECRET_ENCRYPTION_KEYS_LEGACY=` (ว่าง)
- Recreate `hub-backend`
- หลังจากนี้ — ถ้ามี ciphertext เก่าค้างจะ decrypt ไม่ได้ (ปกติ token เก่าทั้งหมดหมดอายุ 15 นาที + ผ่าน migrate แล้ว)

---

## 4. Quick Rotation Reference

| Action | Command | Wait | Notes |
|--------|---------|------|-------|
| JWT begin | `rotate-jwt.sh begin hub-key-2` | 5min | JWKS เห็น 2 keys |
| JWT activate | `rotate-jwt.sh activate hub-key-2` | 65min | Token ใหม่ใช้ hub-key-2 |
| JWT finalize | `rotate-jwt.sh finalize hub-key-1` | — | ลบ key เก่า |
| Fernet begin | `rotate-fernet.sh begin` | — | MultiFernet เห็น 2 keys |
| Fernet migrate | `rotate-fernet.sh migrate` | 15min | re-encrypt DB tokens |
| Fernet finalize | `rotate-fernet.sh finalize` | — | ลบ legacy ออก |

**รวมเวลา:** JWT ~70 นาที / Fernet ~15 นาที — ทั้งหมด **0 downtime**

---

## 5. Emergency Rotation (Key Compromised)

หากสงสัยว่า key หลุด — **ทำ rotation ทันที** ข้าม grace period:

```bash
# JWT — fast-track
bash scripts/security/rotate-jwt.sh begin hub-key-emergency
bash scripts/security/rotate-jwt.sh activate hub-key-emergency
# (skip 65min wait — accept user re-login)
bash scripts/security/rotate-jwt.sh finalize hub-key-1

# Fernet — same fast-track
bash scripts/security/rotate-fernet.sh begin
bash scripts/security/rotate-fernet.sh migrate
bash scripts/security/rotate-fernet.sh finalize
```

**Trade-off:** Active session ทั้งหมดจะ invalidate (token เก่า verify ไม่ผ่าน) — user ต้อง login ใหม่

ส่ง notification ก่อน rotate:
```
[Central Auth Hub] ตรวจพบเหตุการณ์ผิดปกติ — ระบบความปลอดภัยกำลัง refresh
กรุณา login ใหม่ภายใน 5 นาที
```

---

## 6. Verification Checklist

หลังทำ rotation ทุกครั้ง:

- [ ] `bash rotate-jwt.sh status` — JWKS shows expected keys
- [ ] `curl /health` → 200
- [ ] Login flow ใหม่ → JWT มี kid ใหม่
- [ ] Token เก่ายัง verify ผ่าน (ระหว่าง grace)
- [ ] subsystem OAuth flow ใช้งานได้ (`/oauth/authorize → /callback → /token`)
- [ ] Audit log มี entry: `key_rotation_begin`, `key_rotation_activate`, `key_rotation_finalize`
- [ ] ไม่มี ERROR ใน `docker logs hub-backend`
- [ ] subsystems decode JWT ผ่าน (Subsystem A หอพัก + Subsystem B ห้องสมุด)

---

## 7. References

- **RFC 7517** — JSON Web Key Set (JWK Set), §6 "Key Rotation"
- **RFC 7515** — JSON Web Signature (`kid` header)
- **OWASP Cryptographic Storage Cheat Sheet** — Key Management
- **NIST SP 800-57 Part 1** — Recommendation for Key Management
- **cryptography library docs** — [`MultiFernet`](https://cryptography.io/en/latest/fernet/#cryptography.fernet.MultiFernet)
