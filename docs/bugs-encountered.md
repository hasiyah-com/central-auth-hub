# Bugs Encountered & Lessons Learned

ลำดับเหตุการณ์การ bug ที่เจอจริงในการพัฒนา + วิธีแก้ — กันบั๊กเดิมกลับมา

**โครงสร้าง:** แต่ละ bug มี อาการ → สาเหตุ → กฎที่ป้องกันไม่ให้เกิดอีก
**Critical bugs** (ที่กระทบ design philosophy + ห้ามให้เกิดซ้ำ) → สรุปสั้นใน `CLAUDE.md § Bugs Encountered`
**ไฟล์นี้** = full list ทุกบั๊ก + รายละเอียดเต็ม สำหรับ deep reference

---

## 🔒 Security Bugs (ห้ามให้กลับมา)

**B1. Admin endpoints accessible without auth** — `/admin/users/count`, `/admin/overview` ลืมใส่ `Depends(require_hub_admin)` ทำให้ใครก็เปิด URL ตรงๆ ได้ข้อมูล
→ **กฎ:** ทุก endpoint ใหม่ต้องมี Depends — ถ้า "public" จริง comment ให้ชัดว่า public

**B2. Token in URL query string** — `/secret/retrieve?token=xxx` token โผล่ใน address bar + browser history + Referer header
→ **กฎ:** sensitive token ใน URL → HTML response + `history.replaceState()` ลบทันที + DB เก็บ HMAC ไม่ใช่ plaintext

**B3. PKCE used `==` for compare** — timing attack ที่ทฤษฎีหา code_challenge ได้
→ **กฎ:** ทุกการเปรียบเทียบ secret ใช้ `hmac.compare_digest()`

**B4. JWT missing `aud` claim verification** — token จาก subsystem A ใช้ที่ subsystem B ได้
→ **กฎ:** ทุก `jwt.decode()` ต้อง `verify_aud=True` + ระบุ `audience=...`

**B5. Secret retrieval token stored plaintext** — ใครเข้า DB ได้ ก็ได้ secret ของทุก subsystem
→ **กฎ:** เก็บ HMAC-SHA256 ของ token ใน DB; verify โดย hash input แล้วเทียบ

**B6. Audit log lost on HTTPException** — เรียก `log_action()` แต่ `raise` ก่อน `commit()` → transaction rollback → log หาย
→ **กฎ:** order ต้องเป็น `log_action(db, ...)` → `db.commit()` → `raise HTTPException(...)`

**B7. Failed login attempts not logged** — login ผิด email หรือไม่อยู่ใน whitelist ไม่มี audit entry
→ **กฎ:** ทุก failure path ต้อง `log_action()` ด้วย (B6 + ความครบถ้วน)

**B8. Production secrets default to dev values** — เผลอ deploy ด้วย `SECRET_KEY=dev-secret-change-me`
→ **กฎ:** `config.validate_production()` fail-fast ถ้า `APP_ENV=production` แต่ secret ยัง default

**B9. Race condition on /oauth/token** — code ใช้พร้อมกัน 2 request → ทั้งคู่ผ่าน
→ **กฎ:** atomic operations ใช้ Redis `getdel` (ดึง+ลบ atomic) แทน `get` then `delete`

**B10. /docs exposed everything in production** — Swagger UI โชว์ admin endpoints ให้คนภายนอกเห็น
→ **กฎ:** `ENABLE_DOCS=false` ใน production `.env`; `docs_url=None` if not enabled

---

## 🗄️ Database Bugs

**B11. FK constraint violation on re-seed** — `DELETE FROM users` fail เพราะมี access_list, login_sessions ยังอ้างอยู่
→ **กฎ:** ลำดับลบ: children ก่อน parents (ดู `seed_users.py` หัวข้อ "Re-seed order" ใน Conventions)

**B12. `database "hub" does not exist` log spam** — healthcheck `pg_isready -U hub` ไม่ระบุ `-d` → default ไป db ชื่อเดียวกับ user
→ **กฎ:** healthcheck `pg_isready -U hub -d hub_db` เสมอ

**B13. POSTGRES_DB mismatch with Docker volume** — เปลี่ยน `POSTGRES_DB` ใน `.env` หลัง volume สร้างไปแล้ว → backend ต่อ db ที่ไม่มี
→ **กฎ:** เปลี่ยน `POSTGRES_DB` แล้วต้อง `docker compose down -v` (ลบ volume) + reseed

**B14. `metadata` is reserved on Declarative Base** — `metadata = Column("metadata", JSON)` runtime error
→ **กฎ:** ใช้ Python attr อื่น เช่น `metadata_json` + `Column("metadata", JSON)` alias

---

## 🌐 Auth / OAuth Bugs

**B15. Google "Access blocked: Authorization Error"** — OAuth app ในโหมด Testing แต่ Gmail ที่ทดสอบไม่อยู่ใน Test users
→ **กฎ:** เพิ่ม Gmail ทุกอันที่จะทดสอบใน Google Console → OAuth consent screen → Test users

**B16. Authlib OAuth state lost between tabs** — เปิด 2 tabs ทำ OAuth พร้อมกัน → state ทับกัน → tab แรกพัง
→ **กฎ:** state ของ Hub เก็บใน Redis โดย key คือ hub_state ของแต่ละ flow ไม่พึ่ง session cookie

**B17. Redirect URI mismatch with Google** — เพิ่ม `/oauth/callback` ใน app แต่ลืมเพิ่มใน Google Console
→ **กฎ:** ทุก redirect URI ใหม่ ต้องเพิ่มใน Google Cloud Console → Credentials → Authorized redirect URIs

**B18. SessionMiddleware required by Authlib** — ลบออกแล้ว OAuth flow พัง (state ไม่ถูกเก็บ)
→ **กฎ:** `main.py` มี `SessionMiddleware` เสมอ — ห้ามลบ

**B19. Student bypassed Hub direct check** — ลืมเพิ่ม block ใน `/auth/google/callback`
→ **กฎ:** RBAC ที่ Hub callback บล็อก student ก่อนออก JWT (Defense in Depth ชั้น 1) + `require_developer` ที่ endpoint (ชั้น 2)

---

## 🐳 Docker / Infrastructure (Week 5-7)

**B20. `request.client.host` = `172.18.0.1`** — Docker bridge network IP ไม่ใช่ client จริง
→ **กฎ:** ใช้ `get_client_ip(request)` helper ที่อ่าน `X-Forwarded-For` ก่อน fallback

**B21. ML service down → Hub crash** — `httpx.RequestError` propagate ทำ /oauth/callback 500
→ **กฎ:** `ml_client.py` มี `try/except` ทุกชนิด ป้องกัน + คืน `{score: 0.0, decision: pass}` (fail-safe)

**B22. ENABLE_DOCS=false but `/docs` still up** — ต้อง recreate container, ไม่ใช่แค่ restart
→ **กฎ:** เปลี่ยน config FastAPI app object ใช้ตอน startup; recreate ด้วย `docker compose up -d --force-recreate hub-backend`

---

## 📦 Git / Repo

**B23. `.env.example` deleted via GitHub web UI** — push ครั้งหลัง conflict (modify/delete)
→ **กฎ:** แก้ไฟล์ที่เครื่องตัวเองเท่านั้น push ผ่าน git ห้ามแก้ไฟล์ใน github.com directly

**B24. Wrong branch from example command** — `git checkout -b feature/ml-integration` รันคำสั่งตัวอย่างจริง → ทำงาน Week 2 บน branch ผิดชื่อ
→ **กฎ:** ตรวจ `git branch` ก่อนเริ่มงาน; โปรเจคคนเดียวอยู่บน `main` ตลอด

**B25. Push rejected (fetch first)** — remote มี commit ที่ local ไม่มี (จาก B23)
→ **กฎ:** `git pull --no-rebase` ก่อน push เสมอถ้าทำงานหลายเครื่อง

---

## 🧠 ML

**B26. Cold-start: new user → score 0.5+** — `hours_from_typical_login_time` ใช้ median ของ history 0-2 session → ค่าไม่เสถียร
→ **กฎ:** features ที่ต้องใช้ history ต้องมี `MIN_HISTORY_FOR_PERSONALIZATION` (5) — ต่ำกว่านี้ใช้ค่า neutral

**B27. Feature count mismatch crash** — train model ด้วย 8 features แล้วเพิ่มเป็น 12 ใน feature_extraction.py
→ **กฎ:** เปลี่ยน feature ต้อง regenerate data + retrain ก่อน restart Hub

**B28. Sample CSV uses old email format** — เปลี่ยน email pattern ของ seed แต่ลืมแก้ `docs/sample_whitelist.csv` → upload แล้ว skipped ทุกแถว
→ **กฎ:** อัปเดต `sample_whitelist.csv` ทุกครั้งที่เปลี่ยน email pattern ของ seed

---

## 🔧 Config / Misc

**B29. UTC timestamp confusion** — เห็น `07:45 UTC` คิดว่าเวลาผิด ที่จริงคือ `14:45` ตามเวลาไทย
→ **กฎ:** เก็บ UTC ใน DB; แปลง timezone ที่ display layer (`AT TIME ZONE 'Asia/Bangkok'`)

**B30. `pydantic[email]` install order in requirements.txt** — `pydantic==2.9.2` หลัง `pydantic[email]` ไม่ install email-validator
→ **กฎ:** ใช้ `pydantic[email]==2.9.2` หรือ pin email-validator แยก

**B31. Swagger token persists tomorrow** — UX confusion: ดูเหมือน token ยังอยู่จริงๆ JWT exp ถูก enforce server-side
→ **กฎ:** อธิบายผู้ใช้/ดู doc ก่อนตกใจ — Swagger UI's local state ≠ server validation

**B32. `created_at` ไม่ตรงเวลา** (เคสที่ user ถามจริง) — ดู `2026-05-17 07:45` คิดว่าผิด → +7 ชม. = `14:45 BKK`
→ **กฎ:** เดียวกับ B29 (เป็นปัญหาเดียวกัน)

---

## 🐳 Docker / Container State (Week 8-9)

**B33. `docker compose` attach container เดิม → อ่าน `.env` จาก folder ผิด**
- อาการ: รัน `docker compose up -d` จาก main folder แต่ `hub-backend` container อ่าน `GOOGLE_REDIRECT_URI=http://localhost:8020/...` (จาก worktree folder อื่น)
- สาเหตุ: `container_name:` ใน base `docker-compose.yml` hardcoded (เช่น `hub-backend`) → Docker เห็น name ตรงกับ container ที่มีอยู่ → attach ตัวเดิมแทนสร้างใหม่ → ใช้ env จาก folder ที่สร้างครั้งแรก
- **กฎ:** ถ้าเปลี่ยน folder ที่ start Docker → `docker compose -p <old-project> down` ก่อน แล้วค่อย `docker compose up -d --force-recreate` จาก folder ใหม่
- **Verify:** `docker exec hub-backend env | grep GOOGLE_REDIRECT` ต้องตรงกับ `.env` ใน folder ที่กำลังทำงาน

**B34. Pytest path ใน dev-routine skill ผิด**
- อาการ: `docker compose exec hub-backend pytest hub/backend/ -v` → `ERROR: file or directory not found`
- สาเหตุ: container WORKDIR = `/app` (COPY จาก `./hub/backend` → `/app`) → path `hub/backend/` ไม่มีใน container
- **กฎ:** ใน container ใช้ `pytest .` หรือ `pytest tests/`

**B35. `.gitignore` หาย entries หลัง merge feature branches**
- อาการ: หลัง merge `feature/ml-dev` กลับ main → `.gitignore` กลับไปเป็นเวอร์ชั่นเก่า → `.claude/settings.local.json`, `tmp_*.py`, `docker-compose.override.yml` โผล่เป็น untracked อีกครั้ง
- สาเหตุ: branch feature/* เริ่มต้นก่อน commit ที่เพิ่ม entries → merge ทับ
- **กฎ:** ทุกครั้งหลัง merge → `git status` ตรวจ untracked ที่ควรเป็น ignored → fix ทันที (`git check-ignore -v <file>` ดู rule ที่ match)

**B36. `docker compose restart` ไม่อ่าน `.env` ใหม่**
- อาการ: แก้ค่าใน `.env` (เช่น `LINE_CLIENT_ID`) → restart container → app ยังเห็นค่าเก่า/ไม่มีเลย
- สาเหตุ: env vars inject ตอนสร้าง container (`docker create`) — `restart` แค่ kill+start process ไม่ re-read env_file
- **กฎ:** เมื่อแก้ env vars → `docker compose up -d --force-recreate <service>` (ไม่ใช่ restart)
- **Verify:** `docker exec <container> env | grep <VAR>` ต้องมีค่าตามที่ตั้ง

**B37. Docker volume namespace เปลี่ยน → ข้อมูลหาย**
- อาการ: เปลี่ยน project name (e.g. Migration B) → `docker compose up` สร้าง volume ใหม่ชื่อ `cah-hub_postgres_data` แทน `central-auth-starter_postgres_data` → DB ว่างเปล่า ทั้งๆที่ volume เก่ายังอยู่
- สาเหตุ: Docker prefix volume name ด้วย project name → ชื่อ volume เปลี่ยนตาม
- **กฎ:** ใช้ `name:` + `external: true` ใน compose declaration เพื่อ pin volume name เดิม:
  ```yaml
  volumes:
    postgres_data:
      name: central-auth-starter_postgres_data
      external: true
  ```

---

## 🔄 Auth / OAuth (Week 9 — LINE Login)

**B38. Frontend files in worktree never committed → lost when discarded**
- อาการ: Week 8 ทำ Next.js admin dashboard บน worktree `feature/hub-dev` แต่ไม่ commit → ครั้งหลัง folder ถูกลบจาก disk → ไฟล์หายหมด
- สาเหตุ: worktree files = untracked ทั่วไป — ลบ folder = data loss permanent
- **กฎ:** Commit งานทุก work session แม้ยังไม่เสร็จ (WIP commit) — ใช้ `git add -p` เลือกเฉพาะที่พร้อม

**B39. SHAP sign convention สับสน (positive/negative direction)**
- อาการ: SHAP top features ใน UI สลับ red/green ผิด — feature ที่ผลักไป "anomaly" แสดงสีเขียว
- สาเหตุ: `shap_value` บน `decision_function` ของ IForest:
  - `> 0` → feature ผลัก output ทาง **NORMAL** (decision_function สูง = ปกติมาก)
  - `< 0` → feature ผลัก output ทาง **ANOMALY**
- **กฎ:** ใน `predict_with_explanation()` ใช้ `anomaly_contrib = -shap_value` เพื่อ flip → UI "positive = anomaly" (intuitive)

**B40. LINE Channel ID vs Bot User ID confused**
- อาการ: ส่ง `LINE_CLIENT_ID=U40f2d407a844c7fe4e36b04eb1dded2d` → 400 Bad Request: "Failed to convert property value of type 'java.lang.String' to required type 'java.lang.Integer' for property 'clientId'"
- สาเหตุ: User copy "Bot User ID" จาก Messaging API channel (รูปแบบ `U` + 32 hex chars) — แต่ LINE Login OAuth ต้องการ **Channel ID** เป็นตัวเลขล้วน 10 หลัก (เช่น `2010297925`)
- **กฎ:** LINE Channel ID อยู่ที่ Console → channel **LINE Login** type → tab **Basic settings** → field **Channel ID** (numeric only)
- หลังแก้ `.env` → ต้อง `force-recreate` (ดู B36)

**B41. `docker-compose.yml` `hub-frontend` block ไม่ถูก commit → ภัยเงียบ**
- อาการ: Week 8 เพิ่ม `hub-frontend` service ใน docker-compose.yml + รัน Docker ปกติ → working tree มี service แต่ไม่ commit
- สาเหตุ: working ได้ทันที (Docker เห็นจากไฟล์ local) → ลืม commit → ถ้า reset/clone จะหาย
- **กฎ:** หลังเพิ่ม service ใน docker-compose → `git status` ตรวจ + commit ทันที (ก่อน restart Docker)

**B42. LINE Login + Authlib → `UnsupportedAlgorithmError` ที่ parse_id_token**
- อาการ: หลัง redirect กลับ `/auth/line/callback` → 500 Internal Server Error → log: `authlib.jose.errors.UnsupportedAlgorithmError: unsupported_algorithm:` ที่ `oauth.line.authorize_access_token()`
- สาเหตุ: LINE sign ID token ด้วย **HS256** (HMAC + channel secret) แต่ Authlib's default JWS registry รองรับแค่ **RS256** (Google/Microsoft ใช้แบบนั้น) → parse_id_token() ภายใน authorize_access_token() ตายตอน `_prepare_algorithm_key`
- **กฎ:** สำหรับ LINE (และ IdP อื่นที่ใช้ HMAC algorithm) — bypass Authlib's auto parse_id_token:
  1. ดึง `code` + `state` จาก query params เอง
  2. POST ไป `https://api.line.me/oauth2/v2.1/token` ผ่าน `httpx` ตรงๆ
  3. GET `https://api.line.me/oauth2/v2.1/userinfo` พร้อม Bearer access_token
  4. State validation ใช้ session ที่ Authlib เก็บไว้ตอน `authorize_redirect` (key pattern `_state_<provider>_*`)
- **Verify:** `curl -s https://access.line.me/.well-known/openid-configuration | jq .id_token_signing_alg_values_supported` → `["HS256", "ES256"]` ← ไม่มี RS256
- **ทางเลือก:** ถ้าอยากใช้ Authlib's auto parse → register HS256 ใน JWS registry globally:
  ```python
  from authlib.jose.rfc7518.jws_algs import HS256
  # อาจต้องใช้ JWS_ALGORITHMS.register(HS256()) หรือ patch ตามเวอร์ชั่น
  ```
  แต่ approach นี้ขัด security model ของ Authlib (HS256 ใน ID token = client_secret leak risk ถ้าหลุด) — ใช้ manual approach ดีกว่า

**B43. User Enumeration ผ่าน Passkey `login/start` — `allowCredentials` empty vs non-empty**
- อาการ: ยิง `POST /auth/passkey/login/start` ตรงๆ แล้วดู `allowCredentials` ใน response → email ที่มี passkey คืน list ไม่ว่าง, email ที่ไม่มี/ไม่มีบัญชี คืน `[]` → ผู้โจมตี enumerate ได้ว่า email ไหนลงทะเบียน passkey แล้ว (OWASP — Information Disclosure, Medium)
- สาเหตุ: ข้อความ error opaque อยู่แล้ว (auth_complete คืน `401 invalid_credential` เหมือนกันทุกกรณี) **แต่ shape ของ response ที่ login/start ยัง leak** — `auth_begin` คืน `allowCredentials` ตาม passkey จริงของ user → ว่าง=ไม่มี, ไม่ว่าง=มี
- **กฎ:** auth-failure ต้อง opaque **ทั้งข้อความ + shape**:
  1. `login/start` คืน `allowCredentials` ไม่ว่างเสมอ — ไม่มี passkey → `_dummy_descriptors(email)` (decoy id = `HMAC-SHA256(SECRET_KEY, "passkey-decoy:"+email)[:20]`, deterministic ต่อ email, ไม่ตรง credential จริงใน DB → จบที่ 401 เหมือน wrong cred)
  2. frontend รวม `invalid_credential` + `assertion_verify_failed` → generic "ไม่สามารถเข้าสู่ระบบได้ กรุณาลองใหม่อีกครั้ง"
  3. OTP/recovery begin คืน `True` เสมอ (anti-enum อยู่แล้ว)
- **Verify:** `curl ... login/start -d '{"email":"ghost@x.com"}'` 2 ครั้ง → `allowCredentials` ไม่ว่าง + id เดิม (deterministic); คนละ email → id ต่าง
- **Test:** `tests/test_passkey_login.py::test_auth_begin_dummy_*` (deterministic / unique / not-in-DB / non-empty)

---

## 🔄 Risk-Triggered Passkey (Week 9-10)

**B44. Risk hard-block threshold ต้องอยู่ที่ finalizer ไม่ใช่ aggregator**
- อาการ: ก่อนแก้ — aggregator คืน `decision="block"` ที่ `risk_score >= 0.80` → finalizer raise 403 ทันที (ไม่มี mfa flow); แต่ต้องการ block จริงเฉพาะ `>= 0.85` และ 0.80-0.84 ให้เข้า mfa flow
- สาเหตุ: ถ้าแก้ `THRESHOLDS["block"] = 0.85` ใน `risk_aggregator.py` จะกระทบ tests + alert thresholds เดิมทั่ว codebase
- **กฎ:** Decision enforcement อยู่ที่ **finalizer** (single source of truth) — risk_aggregator คงไว้ที่ 0.80 (ใช้สำหรับ "would_block" alert); finalizer ตรวจ `risk_score >= settings.risk_block_hard_threshold (0.85)` แยกอีกชั้น
- **Implementation:** `oauth.py:_finalize_subsystem_login()` + `auth.py:google_callback()` + `line_callback()` — เพิ่ม `is_hard_block` + `is_mfa_required` ก่อน raise/redirect
- **Verify:** `pytest tests/test_risk_passkey_flow.py::test_config_risk_block_hard_threshold_is_085`

**B45. Force Enrollment ต้องผ่าน OTP ก่อน register/start (กัน attacker enroll)**
- อาการ: ถ้าให้ user ที่ trigger mfa branch + ไม่มี passkey → register passkey ได้เลย → attacker ที่ phish session → enroll passkey ของตัวเอง → bypass ตลอด lifetime ของบัญชี
- สาเหตุ: mfa decision = "อาจมี attacker" → ปล่อยให้ register passkey โดยไม่ verify email = mass account takeover
- **กฎ:** `/auth/passkey/force-enroll/register/start` ต้องตรวจ Redis flag `force_enroll_otp_passed:{challenge_id}` → ไม่มี → 403 `{code: "otp_required"}`; user ต้องเรียก `send-otp` → `verify-otp` (OTP 6 หลัก ทาง email user) ก่อน
- **Implementation:** `passkey.py:_require_otp_passed()` + `force_enroll_register_start/complete`
- **Verify:** `pytest tests/test_risk_passkey_flow.py::test_force_enroll_register_start_requires_otp_passed`

**B46. Browser ไม่รองรับ WebAuthn — บังคับ Account Recovery (ไม่ fallback OTP login)**
- อาการ: ถ้า user เปิด browser เก่า (IE / มือถือเก่า) → ไม่มี `window.PublicKeyCredential` → ผ่าน mfa flow ไม่ได้
- สาเหตุ: ถ้า fallback ไป OTP login (เหมือน MFA OTP flow เดิม) = ลด security model จาก phishing-resistant → channel-bound OTP; attacker ที่ control email = bypass
- **กฎ:** หน้า Risk Re-Auth + Force Enrollment ตรวจ `PublicKeyCredential` ถ้าไม่มี → แสดง "Browser นี้ไม่รองรับ Passkey กรุณาใช้อุปกรณ์ที่รองรับ หรือใช้ Account Recovery" + ลิงก์ `/auth/passkey/recover` (backup codes + email OTP **เฉพาะตอน recovery จริง**)
- **Implementation:** `passkey.py:_risk_stepup_html()` + `_force_enroll_html()` — JS `pkSupported()` check
- **Verify:** `pytest tests/test_risk_passkey_flow.py::test_risk_stepup_page_renders_reasons_and_score` (HTML contains "เบราว์เซอร์นี้ไม่รองรับ Passkey" + "Account Recovery")

**B47. risk_challenge consume ต้องเป็น atomic getdel หลัง WebAuthn verify ผ่าน**
- อาการ: ถ้า consume ก่อน WebAuthn verify → verify fail → user ต้อง login ใหม่ (เสียประสบการณ์); ถ้า consume หลัง verify ผ่าน + ไม่ใช้ getdel atomic → race condition: 2 requests verify ผ่านพร้อมกัน → ออก JWT 2 ตัวจาก challenge เดียว
- สาเหตุ: B9 pattern เดียวกับ authorization_code
- **กฎ:** ลำดับ: `peek()` → WebAuthn verify → `consume()` (atomic getdel) → raise 410 ถ้า None (กัน race) → finalize
- **Implementation:** `passkey.py:risk_stepup_verify` + `force_enroll_register_complete`
- **Verify:** `pytest tests/test_risk_passkey_flow.py::test_risk_challenge_replay_after_consume_returns_none`

**B48. Grace Period ใช้ `account_age < N days` ห้ามใช้ `is_new_user` flag**
- อาการ: ถ้าเก็บ flag `is_new_user` ใน DB แล้ว user ใช้งานเกิน 7 วันก็ยัง True (ถ้าไม่มี cron clear) → bypass force enroll ได้ไม่จำกัด
- สาเหตุ: เก็บ state ที่ derived ได้จาก `user.created_at` = ซ้ำซ้อน + เสี่ยง stale
- **กฎ:** ใช้ `(now - user.created_at).days < settings.passkey_grace_period_days` คำนวณ runtime; ไม่เก็บ flag; helper `webauthn_service.in_grace_period(user, db)` เป็นจุดเดียวที่ตัดสิน
- **Verify:** `pytest tests/test_risk_passkey_flow.py::test_in_grace_period_*`

---

## 🧠 ML Feature Expansion (Week 10-11)

**B49. เปลี่ยน feature order ลืม sync `rule_engine.FEAT` + train/serve skew**
- อาการ: หลังตัด feature (`is_weekend`) แล้ว retrain — score สวิงหนัก (login ปกติพุ่ง `risk_score=1.0`) ทั้งที่ ML/IForest นิ่ง (~0.5)
- สาเหตุ 2 จุด:
  1. **FEAT misalign** — `rule_engine.py:FEAT` (และ `behavior_profiling.py` import ไปใช้) เป็น index map ที่ hardcode ลำดับเก่า → ตัด feature กลางทำให้ทุก index เลื่อน → rule/behavior อ่าน feature **ผิดตำแหน่ง** (อ่าน index 11 ว่า `failed_logins_24h` แต่จริงคือ `passkey_count`) → rule+behavior score มั่ว → aggregate ถึง 1.0
  2. **Train/serve skew** — `generate_data.py` (synthetic) gen ค่าไม่ตรงกับที่ `feature_extraction.py` ส่งจริง: `permission_change_age=9999` (ส่วนใหญ่ไม่เคยเปลี่ยนสิทธิ์) แต่ synthetic max ~800 → OOD; `scope=0` Hub-direct, `concurrent=0` fresh login ก็ไม่อยู่ใน train → normal user ดูเป็น anomaly
- **กฎ:** feature order = contract **4 ไฟล์** ต้อง sync: `features.py` + `generate_data.py` headers + `feature_extraction.py` + **`rule_engine.py:FEAT`**. และ synthetic ต้อง gen ค่าตรง distribution จริง (รวม neutral values เช่น 9999, 0)
- **Verify:** `pytest tests/test_feature_extraction.py::test_rule_engine_feat_map_aligned tests/test_feature_extraction.py::test_benign_login_low_rule_score`

---

## 🎓 Subsystem C (ระบบเกรด) + SOC Dashboard + User 360 / Cross-system (Week 10-11)

**B50. Access policy script ขัดกับ docstring จริงของ subsystem — teacher เข้าระบบเกรดไม่ได้**
- อาการ: teacher login เข้า "ระบบเกรด" (Subsystem C) ไม่ได้ ทั้งที่ระบบต้องการให้ teacher เข้าดูมุมมองอาจารย์ได้ (ตรวจดู login flow แล้วโดน reject ที่ access policy check ก่อนถึง handler)
- สาเหตุ: `scripts/register_grade_subsystem.py` ตั้ง `ACCESS_POLICY_CONFIG = {"roles": ["student"]}` (+ `allowed_roles=["student"]`) — แต่ `app/roster.py:sync()` docstring เขียนไว้ชัดว่า "Access Policy ของ subsystem นี้เปิดทั้ง student + teacher (teacher ต้อง login ได้เพื่อดูมุมมองอาจารย์)" สองไฟล์นี้ขัดกันเอง เพราะ register script ถูกเขียนขึ้นก่อนแล้วไม่ได้ sync ตาม intent ที่ระบุใน docstring ของ roster.py ภายหลัง — เจอจาก manual code review ก่อน commit ไม่ใช่จาก error message ตรงๆ (คนละ endpoint กับที่ throw)
- **กฎ:** เมื่อ docstring/comment ของไฟล์หนึ่งอธิบาย behavior ของ config ที่มาจากอีกไฟล์ (เช่น access policy, feature flags) ต้อง cross-check ว่าไฟล์ config จริงตรงกับที่ comment บอกไว้เสมอ — ห้ามเขียน comment ตาม intent แล้วสมมติว่า config จะตามมาเอง ตรวจคู่กันทุกครั้งตอน code review ก่อน commit (โดยเฉพาะ subsystem registration script ที่รันครั้งเดียวแล้วมักไม่มีใครกลับมาดูซ้ำ)
- **Fix:** `ACCESS_POLICY_CONFIG = {"roles": ["student", "teacher"]}` + `allowed_roles=["student", "teacher"]` (roster.py ยังกรอง `user_type == "student"` เองตอน pre-create เกรด — เปิด login ให้ teacher ไม่ทำให้ grade data รั่วไปหา role อื่น)

**B51. Dashboard KPI แสดง "—" ทั้งที่ค่าจริงคือ 0 (falsy-zero กับ `||`)**
- อาการ: KPI "บุคลากร" (teacher+staff+admin รวม) บนหน้า Dashboard แสดง "—" เหมือนยังโหลดไม่เสร็จ ทั้งที่ data โหลดมาแล้วจริง — เกิดเฉพาะกรณีผลรวมบังเอิญเป็น 0 จริง (เช่น DB fresh-seed ที่ยังไม่มี teacher/staff/admin เพิ่ม)
- สาเหตุ: `dashboard/page.tsx` เขียน `value: (counts?.teacher ?? 0) + (counts?.staff ?? 0) + (counts?.admin ?? 0) || "—"` — ตั้งใจใช้ `||` fallback ตอน `counts` ยังเป็น `null` (กำลังโหลด) แต่ JS/TS ถือว่า `0` เป็น falsy เหมือนกัน → ผลรวมที่เป็น `0` จริง (มีความหมาย ไม่ใช่ "ไม่มีข้อมูล") ถูก `||` จับไปแสดง "—" แทน
- **กฎ:** ห้ามใช้ `computed_value || fallback` เพื่อเช็คสถานะ "ยังไม่โหลด" ถ้า `computed_value` อาจเป็น `0` ที่ถูกต้องตามธรรมชาติ (count, sum, percentage ฯลฯ) — ต้องเช็คสถานะโหลดจาก **source object เอง** เช่น `data ? computed_value : "—"` แยกเรื่อง "ไม่มีข้อมูล" ออกจาก "ข้อมูลคือศูนย์" ให้ชัดเจน
- **Fix:** เปลี่ยนเป็น `counts ? (counts.teacher ?? 0) + (counts.staff ?? 0) + (counts.admin ?? 0) : "—"`
- **Verify:** seed DB ให้เหลือเฉพาะ student (teacher/staff/admin = 0) → เปิด `/` (Dashboard) → การ์ด "บุคลากร" ต้องแสดง `0` ไม่ใช่ `—`

**B52. Admin force-logout เตะ Hub session แต่ subsystem cookie ยังใช้ได้ต่อ (ขาด back-channel)**
- อาการ: กด "Force Logout ทั้งหมด" ในหน้า User 360 → Hub ขึ้นว่าปิด session หมด + revoke JWT แล้ว แต่ผู้ใช้ยัง**ใช้งานระบบย่อยต่อได้** (เปิดหน้าใน subsystem ไม่เด้งออก) จน JWT หมดอายุเอง — user รายงานเอง ("แสดงว่าออกแล้ว...แต่ในระบบย่อยยังไม่เด้งออก")
- สาเหตุ: `force_logout_user` ปิด `login_sessions.logout_at` + `revoke_jti` **ที่ Hub เท่านั้น** — subsystem มี session cookie ของตัวเอง (stateless signed cookie) ที่ Hub เอื้อมไปลบไม่ได้ (คนละ trust domain, ไม่ใช่ SSO) และ Hub ก็ **ไม่ได้แจ้ง** subsystem ว่า user ถูก logout → subsystem ไม่รู้ ยอมให้ใช้ต่อ. jti blacklist มีผลเฉพาะตอน subsystem verify token กับ Hub ใหม่ (ซึ่งไม่เกิดทุก request หลังตั้ง session แล้ว)
- **กฎ:** action ที่ Hub ทำแล้วต้องมีผล**ข้าม trust domain** (force-logout, revoke, ban) ต้อง **ยิง webhook back-channel** ให้ทุก subsystem ที่ user มี session ค้าง เสมอ — Hub เปลี่ยน state ฝั่งตัวเองอย่างเดียวไม่พอ เพราะไม่ใช่ SSO (Hub สั่ง subsystem ตรงๆ ไม่ได้ ทำได้แค่ "แจ้ง" ให้ subsystem invalidate session เอง)
- **Fix:** หลังปิด session — เก็บ `sub_ids` ของ subsystem ที่มี session ค้าง แล้ว loop ยิง `send_access_updated` (= บังคับ re-auth, login ใหม่ได้ ต่างจาก `access_revoked` ที่ถาวร) ให้แต่ละตัว (fail-safe: ยิงไม่สำเร็จ = log ไม่ raise, B21)
- **Verify:** login subsystem → admin force-logout → เปิดหน้า subsystem ซ้ำ → ต้อง 307 ไป `/login` (ตรวจ grade `reauth_after` เปลี่ยน None → timestamp; response `subsystems_notified`/`webhook_delivered` > 0)

**B53. Relative-time เพี้ยน +7 ชม. — frontend parse naive-UTC เป็น local time**
- อาการ: หน้า User 360 "Recent Login" แสดง login ที่พึ่งเกิด (< 1 นาที) ว่า "7 ชม.ที่แล้ว"
- สาเหตุ: backend ส่ง timestamp เป็น **naive UTC** (`datetime.isoformat()` ไม่มี `Z`/offset เช่น `2026-07-11T03:30:00`) — JS `new Date("2026-07-11T03:30:00")` ตาม ECMAScript ตีความ date-time string ที่**ไม่มี tz designator เป็น local time** → ที่ไทย (UTC+7) จึงกลายเป็น 03:30 เวลาไทย = ห่างจากตอนนี้ (10:30) ไป 7 ชม. (ต่างจาก B29/B32 ที่เป็น "คน**อ่าน**ค่า UTC ผิด" — อันนี้คือ "JS **parse** UTC ผิดเป็น local")
- **กฎ:** timestamp จาก backend เป็น UTC เสมอ (CLAUDE.md) — ฝั่ง frontend ก่อน `new Date()` ต้อง**บังคับ parse เป็น UTC**: เติม `Z` ถ้า string ไม่มี tz designator (regex `/[zZ]$|[+-]\d{2}:?\d{2}$/`) แล้วค่อยแปลงเป็น local ตอนแสดง — อย่าปล่อยให้ JS เดา timezone เอง
- **Fix:** helper `parseUTC(iso)` เติม `Z` เมื่อไม่มี tz → ใช้แทน `new Date()` ใน `relTime()` (ครอบทุกจุดที่โชว์เวลา: created_at, last_login, session, passkey)
- **Verify:** node — `new Date(naiveUTCnow)` diff = 420 นาที (bug), `parseUTC(naiveUTCnow)` diff = 0 นาที (ถูก)

**B54. Subsystem ใหม่โดน 503 maintenance ตอน OAuth — Hub health-check เข้า `localhost:PORT` จาก container ไม่ได้**
- อาการ: ระบบเกรด (port 8003) พึ่ง register → กด login → Hub ตอบหน้า 503 maintenance แทนที่จะเริ่ม OAuth flow
- สาเหตุ: Hub มี health-gate — ถ้า subsystem = `down` จะกัน OAuth (503). `subsystem_health.py` ยิง `GET {origin ของ redirect_uri}/health` = `http://localhost:8003/health` แต่โค้ดรันใน **container** — `localhost` ใน container ชี้ตัวมันเอง ไม่ใช่ host → connection refused → mark `down`. (redirect_uri ต้องเป็น `localhost:8003` เพราะ browser เข้าถึง แต่ Hub-ใน-container เข้าด้วย URL เดียวกันไม่ได้ — เหมือน B20/B33 ตระกูล Docker networking)
- **กฎ:** dev/Docker — ทุกที่ที่ Hub (ใน container) เรียก subsystem ด้วย URL `localhost:PORT` (health-check, webhook) ต้องผ่าน docker-service-name mapping (`_DEV_LOCALHOST_MAP`) แปลง `localhost:8003` → `subsystem-grade:8000` ก่อน — **เพิ่ม subsystem ใหม่ต้องเพิ่ม mapping ด้วย**. prod ใช้ URL จริงที่ Hub เข้าถึงได้ (ไม่มีปัญหานี้)
- **Fix:** เพิ่ม `("localhost","8003")` + `("127.0.0.1","8003")` → `subsystem-grade:8000` ใน `webhook_dispatcher._DEV_LOCALHOST_MAP` (health-check reuse mapping เดียวกัน) + ล้าง cached `down` ใน Redis (`subsystem:health:{id}`) ให้ re-check รอบใหม่
- **Verify:** กด login ระบบเกรด → เข้า OAuth flow ได้ (ไม่ 503); ตรวจ Redis health status = `online`

**B55. Subsystem ใหม่ (grade) ไม่มี `session_cookie_secure` เลย — ต่างจาก dorm/library**
- อาการ: ตอนเตรียม production compose ให้ subsystem-grade (สำหรับ deploy ขึ้น VM) พบว่า `config.py`
  ไม่มี field `session_cookie_secure` เลยแม้แต่ตัวเดียว (ต่างจาก dorm/library ที่มี field + fail-fast
  validation) และ `_set_session()` ใน `main.py` เรียก `resp.set_cookie(...)` โดยไม่ตั้ง `secure=` เลย
  — เจอจาก manual code review ตอนเตรียม prod infra ไม่ใช่จาก error ตรงๆ (ยังไม่เคย deploy จริงจึงไม่มีใครสังเกต)
- สาเหตุ: subsystem-grade เขียนแยกทีหลัง dorm/library แบบ copy pattern บางส่วนแต่ไม่ครบ — เอา session
  cookie logic มาแต่ไม่เอา `session_cookie_secure` + `validate_production()` มาด้วย ถ้า deploy ขึ้น VM
  (HTTPS) โดยไม่แก้ session cookie จะไม่มี `Secure` flag → คุกกี้ auth หลุดผ่าน MITM บน network ที่ไม่ปลอดภัยได้
  (ตัด HTTPS-only guarantee ของ session)
- **กฎ:** subsystem ใหม่ทุกตัวที่ copy pattern จาก dorm/library ต้องเอา **ทั้งชุด production hardening**
  มาด้วยเสมอ ไม่ใช่แค่ business logic — โดยเฉพาะ `session_cookie_secure` + `validate_production()`
  fail-fast (กัน deploy ขึ้น prod ทั้งที่ยังไม่ตั้งค่าปลอดภัย) เช็คด้วย diff กับ subsystem อ้างอิงก่อน commit
  subsystem ใหม่ทุกครั้ง
- **Fix:** เพิ่ม `session_cookie_secure: bool = False` + `validate_production()` (เช็ค secret/cookie-secure/
  client_id/client_secret) ใน `config.py` ตาม pattern dorm/library เป๊ะ + ผูก `secure=settings.session_cookie_secure`
  เข้า `resp.set_cookie()` ใน `main.py:_set_session()`
- **Verify:** `docker compose exec subsystem-grade python -c "from app.config import Settings; Settings(app_env='production', session_cookie_secure=False, ...)"` ต้อง raise `ValueError` (fail-fast ทำงาน)

---

## 🧠 RBA False-Positive / Trust History (Week 12 — prod tuning)

**B56. `is_new_device` เด้ง 1 ทุกครั้งที่ browser อัปเดต build → risk score สวิง**
- อาการ: prod เครื่องเดิม login แต่ risk score สวิง `0.900 (would_block)` ↔ ต่ำ (`allow`) สลับตลอด — decision ไม่นิ่ง แม้ไม่ได้เปลี่ยนเครื่อง/เบราว์เซอร์
- สาเหตุ (ยืนยันจากข้อมูล prod): `feature_extraction.py` คำนวณ `is_new_device` โดยเทียบ **user_agent string เต็มแบบเป๊ะ** (`user_agent not in seen_ua_set`). Chrome auto-update build number เอง (`Chrome/150.0.0.0` → `151.0.0.0`) OS/เครื่อง/เบราว์เซอร์เดิมทุกอย่าง แต่ string ต่าง → ตีเป็น "เครื่องใหม่" ทันที. ซ้ำร้าย flag ตัวเดียวถูกให้คะแนน **2 ชั้น** (Rule Engine +0.30 + Behavior Profiling +0.20 = 0.5) แล้ว Isolation Forest ยังเห็น `is_new_device=1` (synthetic baseline ตั้งไว้ 5% rare) → รวม ~0.9
- **กฎ:** feature ที่เป็น "trust signal เชิงอุปกรณ์" ต้องเทียบ **device signature ที่เสถียร** (`OS + device_type + browser_family` — ตัดเลขเวอร์ชันออก) ไม่ใช่ UA string เต็ม. และ flag binary ตัวเดียวห้ามให้คะแนนซ้ำหลาย layer — เลือก layer เดียวเป็นเจ้าของ
- **Fix:** (A) เพิ่ม `_device_signature()` + `is_new_device` เทียบ signature (Chrome 150/151 = signature เดียว). (B) ตัด `is_new_device (+0.20)` ออกจาก Layer 2 `behavior_profiling.py` เก็บให้คะแนนที่ Rule Engine ชั้นเดียว. range คง 0/1 → ไม่กระทบ feature contract (B49), ไม่ต้อง retrain (synthetic gen เป็น Bernoulli อิสระ) — แถมตรงกับ baseline 95%-not-new มากขึ้น
- **Verify:** `tests/test_feature_extraction.py::test_new_device_ignores_browser_build_bump` (150→151 = `is_new_device=0`) + `test_new_device_detects_genuinely_new_device` (Windows Chrome→iPhone Safari = 1)

**B57. Session ที่ถูก flag (would_block) whitelist ตัวเองในครั้งถัดไป — seen-query ไม่กรอง decision**
- อาการ: login เครื่องแปลกครั้งแรก score 0.9 (would_block, ถูกต้อง) แต่ครั้งที่สองจากเครื่องเดิมร่วงเหลือ 0.1 ทันที ทั้งที่เครื่องเพิ่งถูกเตือน
- สาเหตุ: `is_new_device`/`is_new_user_agent_family`/`is_new_country` เป็น **trust signal** (ตอบ "เครื่อง/ประเทศนี้เคยผ่านการยืนยันแล้วหรือยัง") แต่ seen-query นับ **ทุก session ที่มี row** โดยไม่กรอง `decision` → session ที่เพิ่งถูก flag ก็นับเป็น "เคยเห็น". เห็นชัดใน **shadow mode**: `would_block` ไม่ block จริง → row ถูกบันทึก → ครั้งที่สอง `is_new_device=0` → score ร่วง (device whitelist ตัวเอง). สัญญาณ "บัญชีเพิ่งโดนโจมตี" ก็ไม่ติด (failed_24h ต้อง ≥3, confirmed_incident ต้องมี label จริง)
- **กฎ:** trust signal ต้องนับเฉพาะ session ที่ **พิสูจน์แล้วว่า login สำเร็จ** — `TRUSTED_DECISIONS = (allow, mfa_passed, pass)` เท่านั้น. `challenge`/`would_challenge` นับก็ต่อเมื่อถูกเขียนทับเป็น `mfa_passed` จริง (passkey verify ผ่าน). **ห้าม**เอา trusted-filter ไปกรอง signal เชิง "ปริมาณ/การเคลื่อนไหว" (country_change_count_30d, impossible_travel, login_count_24h, failed_24h, concurrent) — attacker ที่ login หลายประเทศแล้วโดน would_block ทุกครั้งจะถูกกรองจนนับได้ 0 = ดูปลอดภัยขึ้น (ผิดทาง)
- **Fix:** ใน seen-device/UA/country query ดึง `(value, decision)` มาแยกใน Python — `has_history` (cold-start guard) แยกจาก `seen_set` (trusted เท่านั้น). ผลลัพธ์: user ที่มีประวัติแต่ยังไม่เคย login สำเร็จ → ทุกเครื่องเป็นเครื่องใหม่ (ไม่ตกเป็น neutral ที่ให้คะแนน attacker ต่ำ), user ใหม่จริง (ไม่มี row) → ยัง neutral ปกติ
- **Verify:** `test_flagged_session_does_not_trust_its_own_device` (would_block → ครั้งถัดไปยัง is_new_device=1), `test_mfa_passed_makes_device_trusted`, `test_warn_is_not_trusted`, `test_no_trusted_history_treats_every_device_as_new`, `test_true_cold_start_still_neutral`

**B58. `would_mfa` ที่ไม่มีใครผลิตแล้ว → shadow-mode refresh gate ไม่เคย log เลย**
- อาการ: `_refresh_risk_gate()` (auth.py) ใน shadow mode ควร log `risk_refresh_would_stepup` เมื่อ refresh มีความเสี่ยง — แต่ audit_logs เงียบสนิท ไม่เคยมี entry นี้
- สาเหตุ: 4-layer aggregator emit decision เป็น `challenge` แล้วเติม prefix `would_` ใน shadow mode → ได้ **`would_challenge`**. แต่ refresh gate ยังเช็ค `decision in (..., "would_mfa")` — vocab ยุคเก่าที่ aggregator ปัจจุบันไม่ผลิตแล้ว → เงื่อนไขไม่เคยเป็นจริง (dead branch เงียบ ไม่ error)
- **กฎ:** decision vocab ที่ canonical คือ `allow/warn/challenge/block` + คู่ `would_*` (shadow). โค้ดที่ match decision ต้องใช้ vocab ปัจจุบัน — `would_mfa`/`mfa`/`mfa_required` เป็น legacy ที่ aggregator เลิกผลิตแล้ว (เก็บไว้ match ได้เพื่อ backward-compat แต่อย่าใช้ **แทน** ตัวปัจจุบัน). แก้ feature ที่แตะ decision string ต้อง grep หา literal ทุกจุดให้ครบ
- **Fix:** เปลี่ยน `would_mfa` → `would_challenge` ใน refresh gate (auth.py) + เพิ่ม `would_challenge` ให้ `incident_service.py` (build_recommendations / _build_impact / _build_attack_path) ที่ยัง match แต่ vocab เก่า
- **Verify:** shadow mode + refresh ที่ risk elevated → มี audit action `risk_refresh_would_stepup` โผล่ใน audit_logs

**B60. 15/23 ฟีเจอร์ไม่มีชั้นไหนให้คะแนน → recall ตกเหลือ 25% + multi_account_ip ยิงใส่ normal ใต้ NAT**
- อาการ: 4-layer จับ attack ที่ควร step-up ได้แค่ 25% ทั้งที่ IForest จัดอันดับถูก (PR-AUC 0.88). attack แบบ concurrent/velocity/new_passkey/permission_change ได้ recall 0% · และ `multi_account_ip` ยิงใส่ login ปกติ ~26% เมื่ออยู่หลัง campus NAT (ทุกคน IP เดียวกัน)
- สาเหตุ: `rule_engine.SCORE_RULES` ให้คะแนนแค่ 6 ฟีเจอร์ (device/geo/failed) · `behavior_profiling` แค่ 3 → เหลือ **15/23 ฟีเจอร์** (velocity, session, passkey, permission, ฯลฯ) ที่ไปถึงคำตัดสินได้ทางเดียวคือผ่าน IForest (สูงสุด +0.40) ซึ่งไม่พอถึง challenge (0.7). และ `risk_aggregator` ไม่มี policy floor → deterministic security event ที่คะแนนรวมไม่ถึง threshold ถูกลดเหลือ allow
- **กฎ:** (1) ทุกฟีเจอร์ที่บ่งชี้ความเสี่ยงต้องมี "เจ้าของกฎ" ใน `SCORE_RULES` (ไม่ปล่อยให้พึ่ง IForest ชั้นเดียว) — เพิ่ม concurrent/active_subsystem/new_passkey/permission_age/login burst + velocity compound. (2) deterministic security event ต้องมี `min_action` (policy floor) ใน `RuleResult` → `aggregate()` บังคับ min decision แม้คะแนนรวมไม่ถึง threshold. (3) `multi_account_ip` ต้องปิดเมื่อ `settings.shared_nat=True` (deployment หลัง NAT ร่วม) — shared-IP ไม่ใช่หลักฐาน attack. (4) `SCORE_RULES` เป็น 5-tuple `(feat, op, threshold, weight, min_action)` รองรับ op `<=` ด้วย
- **Verify:** `ml-service/scripts/eval_production_v2.py` (import โค้ด production ตรงๆ) บนชุด V2 → recall 25%→**85%**, policy 33%→85%, FPR 2.11%. Unit: `tests/test_rule_engine_v2_signals.py` (12 tests). scenario ที่ยัง 0% = `subsystem_lateral` (ต้องเพิ่มฟีเจอร์ที่ 24 `is_new_subsystem`, B49) + `off_hours` (ต้องจูน behavior temporal)

**B61. โค้ด ML ที่ import numpy อยู่ใน service ที่ไม่มี numpy → abstain เงียบตลอดกาล (ผ่านเทสบน host แต่ไม่เคยทำงานจริง)**
- อาการ: L3 sequence channel เขียนเสร็จ ผ่านเทสบนเครื่อง host ครบ 14 ตัว มีผลการทดลอง 5 seeds รองรับ — แต่พอรันในคอนเทนเนอร์จริงได้ `ModuleNotFoundError: No module named 'numpy'` ทุกครั้ง. เพราะเขียน `_numeric()` เป็น lazy import ที่ **fail-safe คืน `None` → abstain** (ตาม B21) ระบบจึงไม่พังและไม่มี error log อะไรเลย — L3 แค่ "ไม่ยิงสักครั้ง" ตลอดกาลโดยไม่มีใครรู้
- สาเหตุ: `hub-backend` image **ไม่มี numpy/sklearn โดยตั้งใจ** — ML ถูกแยกเป็นคอนเทนเนอร์ `ml-service` ตั้งแต่ Week 5 (IForest 23 ฟีเจอร์อยู่ที่นั่นมาตลอด) แต่โค้ด L3 ใหม่ถูกเขียนไว้ใน `hub/backend/app/security/l3_sequence.py` แล้วทดสอบบน host ที่มี numpy ติดตั้งอยู่ (จากงาน harness ทดลอง) → **สภาพแวดล้อมทดสอบ ≠ สภาพแวดล้อมรัน** ในมิติที่เทสมองไม่เห็น
- **กฎ:** (1) fail-safe ที่ "เงียบ" ต้องมีเทสที่ยืนยันว่า **เส้นทางสำเร็จ** ทำงานได้ในสภาพแวดล้อมจริง ไม่ใช่เทสแค่ว่า "พังแล้วไม่ระเบิด" — เพราะ abstain 100% กับ fail-safe ที่ทำงานถูกต้อง ให้ผลลัพธ์ภายนอกเหมือนกันเป๊ะ. (2) โค้ดที่ต้องใช้ ML dependency ต้องอยู่ใน service ที่มี dependency นั้นจริง — ห้ามพึ่ง lazy import เพื่อ "แชร์ไฟล์" ข้าม service. (3) เทสที่ต้องมี optional dependency ถ้า `skip` ในคอนเทนเนอร์ ต้องมีเทสคู่ที่ **ไม่ต้องพึ่ง dependency นั้น** ครอบเส้นทาง production ให้ครบ
- **Fix:** ย้าย numeric core ไป `ml-service/app/sequence.py` + `POST /v1/sequence-score`; hub เหลือส่วน pure python (`residual_raw` · `apply_channel` · `to_contract` · `record_residual`) แล้วเรียกผ่าน `app/services/l3_sequence_client.py` (httpx, fail-safe ตาม pattern `ml_client.py`). ml-service อ่าน history จาก Redis เอง (`l3resid:{user_id}`, อยู่ `cah-net` เดียวกัน) แทนการส่ง history 1,500 แถว (~70KB) ไปกับทุก request — hub ยังเป็นผู้เขียนเจ้าเดียว
- **บั๊กลูกที่เจอตอนย้าย:** `to_contract()` คำนวณ `eligible` จาก `model is not None` — remote path ไม่มี `L3Model` object ในมือ (โมเดลอยู่ที่ ml-service) → `eligible=False` **ทุกแถว** ทั้งที่ L3 ยิงจริง = ข้อมูล production replay เพี้ยนทั้งชุด. **กฎย่อย:** ฟิลด์ที่บอก "สถานะของโมเดล" ต้องยืนยันจาก**ข้อมูลที่ service เจ้าของโมเดลส่งกลับมา** (`n_history`) ไม่ใช่จากการมี object อยู่ในหน่วยความจำฝั่งผู้เรียก
- **กฎเสริม (constant drift):** ค่าคงที่ที่กำหนดพฤติกรรมโมเดล (`DIMS`, `WINDOW`, `CAL_FPR`, `EXTREME_FPR`, `TIER_*`, `MODEL_VERSION`) อยู่สองไฟล์คนละ service — ต้องมี parity test บังคับให้ตรงกัน มิฉะนั้นกลายเป็นคนละโมเดลโดยไม่รู้ตัว (บทเรียนเดียวกับ B49 feature order)
- **Verify:** `tests/test_l3_sequence_client.py::test_evaluate_login_remote_without_numpy` (บังคับ `_numeric()` คืน `None` → เส้นทาง production ต้องยังได้ผลครบ) · `test_constants_parity_hub_vs_ml_service` · `tests/test_l3_remote_e2e.py` (integration ข้ามคอนเทนเนอร์จริง ไม่ mock: เขียน residual 1,500 แถว → ml-service fit/score → ยืนยันยก `allow`→`warn` และ **ไม่แตะ** `challenge`/`block`) · รายงาน `hub/backend/tests/reports/l3_service_split_2026-08-29.md`

**B62. Model cache refit เฉพาะตอนข้อมูล "โต" → history หดแล้วโมเดลเก่าค้างพร้อม n_history ผิด**
- อาการ: ลบ/รีเซ็ต history ของผู้ใช้จาก 2,000 เหลือ 400 แถว แต่ L3 ยังรายงาน `n_history=2000` และ `eligibility=challenge` — คือยังใช้โมเดลเดิมตัดสินอยู่ นานได้ถึง 1 ชั่วโมง (TTL ของ cache)
- สาเหตุ: เงื่อนไข cache เขียนไว้ว่า `len(history) < cached_n * 1.1` ซึ่งเป็นการถามว่า "ข้อมูลโตพอจะ refit หรือยัง" ทางเดียว — history ที่ **หด** (Redis eviction / key ถูกลบ / รีเซ็ตผู้ใช้ / เปลี่ยน retention) ผ่านเงื่อนไขนี้สบายๆ เพราะเลขน้อยลง. ปัญหาไม่ใช่แค่คะแนนเก่า: `n_history` เป็นตัวกำหนด **eligibility** (abstain/diagnostic/warn/challenge) → ผู้ใช้ที่ประวัติหายไปแล้วยังถูกตัดสินด้วย tier สูงเกินจริง
- **กฎ:** cache ที่ใช้ "ขนาดข้อมูล" เป็น invalidation key ต้องเช็ค**ทั้งสองทิศทาง** — `cached_n <= now_n < cached_n * 1.1` ไม่ใช่ `now_n < cached_n * 1.1`. โดยเฉพาะเมื่อขนาดข้อมูลไม่ได้เป็นแค่ตัวชี้วัดความสดของโมเดล แต่ถูกใช้เป็น **input ของการตัดสินใจ** ด้วย
- **Verify:** `tests/test_l3_stability.py::test_concurrent_requests_multi_user_no_crosstalk` (user ที่ history หด 2000→400 ต้องได้ `n_history=400`)

**B63. fit โมเดลรายคนอยู่บน login path → cache-miss storm ทำ L3 timeout ทั้งชุด**
- อาการ: ยิง 20 request พร้อมกันของผู้ใช้ที่ cache ยังว่าง → **timeout ทุกอัน** (L3 เงียบทั้งหมด). และแม้ cache อุ่นแล้ว request ที่มาพร้อมกันก็ยังช้าผิดปกติ
- สาเหตุ (สองชั้น):
  1. **fit ซ้ำซ้อน** — uvicorn รัน endpoint แบบ sync ใน threadpool → request ที่มาพร้อมกัน N อันเข้า `get_model()` พร้อมกัน เห็น cache ว่างเหมือนกันหมด แล้ว fit ซ้ำ N ครั้ง (fit วัดได้ ~270ms ที่ history 2,000 → 20 อัน = ~5.4 วิ)
  2. **อ่าน history เต็มทุก request** — ทาง warm ก็ยัง `lrange -2000 -1` + `json.loads` 2,000 แถวทุกครั้ง ทั้งที่ต้องการแค่ท้าย window 4 แถว (คอขวดจริงที่ทำให้แม้ cache อุ่นก็ยังหน่วง)
  3. L3 ใช้ `ml_timeout_seconds` (2 วิ) ร่วมกับ IForest หลัก → กรณีแย่สุด L3 ถ่วง login ได้ถึง 2 วินาที ทั้งที่เป็นแค่ช่องเฝ้าระวังที่ยกได้สูงสุด warn
- **กฎ:** (1) งานหนักที่ cache ได้ ต้องมี **ล็อกต่อคีย์** + double-check หลังได้ล็อก ไม่ใช่ปล่อยให้ทุก request แข่งกันคำนวณ. (2) ทาง warm ต้องไม่จ่ายราคาของทาง cold — ใช้ `llen` (O(1)) ตรวจขนาดแทนการโหลดทั้งก้อนมานับ. (3) **ส่วนประกอบที่เป็น "monitoring" ต้องมี timeout ของตัวเอง แยกจากส่วนที่เป็น "ตัวตัดสิน"** — ไม่มีสิทธิ์ถ่วง critical path เท่ากัน
- **Fix:** `_user_lock()` ต่อ user + double-check ใน `get_model()` · `_load_tail()` อ่านแค่ท้าย window ตอน cache อุ่น (fallback ไปอ่านเต็มถ้าท้ายลิสต์มีแถวเสีย) · เพิ่ม `settings.l3_timeout_seconds = 0.5` แยกจาก `ml_timeout_seconds`
- **ผลที่วัดได้:** p95 latency **44ms** (จากเดิม timeout) · 20 request พร้อมกัน = สำเร็จ 20/20 ใน 586ms · ผู้ใช้ cold 8 คนพร้อมกันกลับมาปกติภายในไม่กี่วินาที
- **ข้อแลกเปลี่ยนที่ยอมรับ:** หลัง ml-service restart มีช่วง warm-up สั้นๆ ที่ L3 abstain — ยอมเสียการเฝ้าระวัง 1-2 เหตุการณ์ ดีกว่าถ่วงทุก login
- **Verify:** `tests/test_l3_stability.py` — `test_cache_miss_storm_degrades_gracefully`, `test_cold_capacity_many_distinct_users`, `test_latency_within_login_budget`

---

## วิธีเพิ่ม bug ใหม่

1. เพิ่มที่ section ที่เหมาะสม (สร้าง section ใหม่ถ้าจำเป็น)
2. ตั้งหมายเลขลำดับถัดไป (BN+1)
3. รูปแบบ:
   ```
   **B<N>. <ชื่ออาการสั้นๆ>**
   - อาการ: ...
   - สาเหตุ: ...
   - **กฎ:** ...
   - **Verify:** ... (optional)
   ```
4. ถ้าเป็น critical bug (กระทบ design philosophy) → เพิ่มสรุปสั้นใน `CLAUDE.md § Bugs Encountered` ด้วย
