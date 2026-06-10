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
