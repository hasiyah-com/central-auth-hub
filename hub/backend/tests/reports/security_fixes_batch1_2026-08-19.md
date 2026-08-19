# Security fixes — Batch 1 (#2 Starlette CVE + #1 token-in-URL)

**วันที่:** 2026-08-19
**ที่มา:** ตรวจสอบตาราง audit 10 ข้อ → แก้ตามลำดับความสำคัญ (prod-facing ก่อน)
**สถานะ:** ✅ #2 + #1 เสร็จ · full suite 674 passed

---

## #2 — Starlette CVE-2025-62727 (Range-header DoS) 🔴 สูง

### ปัญหา
- `starlette==0.48.0` อยู่ในช่วงที่โดน CVE-2025-62727 (0.39.0–0.49.0):
  O(n²) เมื่อ parse/merge HTTP Range header ใน `FileResponse`/`StaticFiles`
  → attacker ยิง Range ที่มี range ย่อยจำนวนมาก = CPU 100% ต่อ request **โดยไม่ต้อง login**
- ระบบหอพัก + ห้องสมุดใช้ `StaticFiles`/`FileResponse` จริง → prod-facing
- **คอมเมนต์ในโค้ดเดิมอ้างผิด** ว่า pin 0.48.0 = แก้แล้ว (จริงๆ patch อยู่ที่ **0.49.1**)

### ยืนยันแหล่งอ้างอิง
- patched version = **starlette 0.49.1** (Snyk / Aqua AVD / SQLMesh #5812)
- fastapi 0.118 cap `starlette<0.49` → ต้อง bump **fastapi ≥ 0.120.1** ถึงเอื้อมถึง

### แก้
`hub/backend`, `hub/subsystem-dorm`, `hub/subsystem-library` requirements.txt:
```
fastapi   0.118.0 → 0.120.1
starlette 0.48.0  → 0.49.3   (> 0.49.1 = patched)
```

### ยืนยันเวอร์ชันจริงใน container
```
$ docker compose exec hub-backend python -c "import fastapi, starlette; print(...)"
fastapi 0.120.1
starlette 0.49.3
```

---

## #1 — Access/Refresh token ส่งผ่าน URL 🔴 สูง

### ปัญหา
login สำเร็จ redirect `/auth/callback?token=<JWT>&refresh_token=<...>`
→ token รั่วผ่าน **browser history / Referer header / reverse-proxy & access log**
(3 จุด: Google callback, LINE callback (legacy), passkey risk-stepup)

### แก้ — One-time code exchange (แทน token-in-URL)
```
login สำเร็จ → mint_frontend_login_code(): เก็บ token คู่ใน Redis
             key = "frontend_login_code:"+<token_urlsafe(32)>  TTL 60s
           → redirect /auth/callback?code=<code>          ← ไม่มี token ใน URL
frontend  → POST /auth/frontend/exchange {code}
backend   → redis.getdel(key)  [atomic single-use, B9]
           → คืน token JSON + Cache-Control: no-store
errors    → ใช้แล้ว/หมดอายุ/ไม่รู้จัก = 400 · payload เสีย = 400 · redis ล่ม = 503 (fail closed)
```
- URL เหลือแค่ `code` สุ่มที่ใช้ครั้งเดียวหมดค่า + อายุ 60 วิ → หลุดไปก็ไร้ประโยชน์
- frontend `/auth/callback` แลก code แล้วเก็บ token ใน **httpOnly cookie** เหมือนเดิม
  (รองรับ legacy `?token=` ระหว่าง rollout)

### ไฟล์ที่แก้
| ไฟล์ | เปลี่ยน |
|------|---------|
| `app/routers/auth.py` | + `FRONTEND_LOGIN_CODE_PREFIX`, `mint_frontend_login_code()`, `POST /auth/frontend/exchange` · เปลี่ยน redirect Google+LINE callback → `?code=` |
| `app/routers/passkey.py` | risk-stepup redirect (frontend branch) → `?code=` (fallback `/auth/me` API คง token) |
| `hub/frontend/app/auth/callback/page.tsx` | อ่าน `code` → แลกผ่าน `/api/proxy/auth/frontend/exchange` → set-token |

### เทส — RED → GREEN (test มีอยู่ก่อน, implement ให้ผ่าน)
`tests/test_frontend_code_exchange.py` (4 tests):
```
test_frontend_code_exchange_is_single_use ................ PASSED
test_frontend_code_exchange_rejects_expired_or_unknown_code PASSED
test_frontend_code_exchange_rejects_malformed_payload .... PASSED
test_frontend_code_exchange_fails_closed_when_redis_is_unavailable PASSED
========================= 4 passed =========================
```
- single-use (replay = 400), fail-closed (redis down = 503), no-store header ✅
- frontend: `tsc --noEmit` exit 0

---

## Regression — full suite

```
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py

================= 674 passed, 41 skipped in 193.61s =================
```
ไม่มี regression จาก fastapi minor bump + auth/passkey redirect change

---

## เหลือใน batch (ยังไม่ทำ)
- **#5 SSRF** ผ่าน subsystem health checker (บล็อก private/link-local IP)
- **#9 Open redirect** ใน `return_to` (allowlist origin ของ subsystem)

## ต้องทำเอง
- Redeploy Dokploy (rebuild image เพื่อให้ starlette 0.49.3 + code-exchange ขึ้น prod)

## Reproduce
```bash
docker compose up -d --build postgres redis hub-backend
docker compose exec hub-backend pytest tests/test_frontend_code_exchange.py -v
docker compose exec hub-backend python -c "import starlette; print(starlette.__version__)"  # 0.49.3
```
