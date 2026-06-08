# คู่มือเพิ่ม LINE Login — ทำเอง step-by-step

**เป้าหมาย**: พิสูจน์ว่าระบบ Hub เปลี่ยน IdP ได้ — เพิ่ม LINE เป็น 2nd OAuth provider โดยใช้ pattern เดียวกับ Google ที่มีอยู่
(LINE Login เป็น OIDC compliant — ใช้ Authlib ตัวเดียวกับ Google ได้เลย)

**ทำไมเลือก LINE** (แทน Microsoft):
- ฟรี 100% ไม่ต้องการบัตรเครดิตเพื่อ verify
- ตรงโจทย์มหา'ลัยไทย — user ใช้ LINE เกือบทุกคน
- Setup เร็วกว่า Microsoft (LINE Developers Console straightforward)

**Effort คาดการณ์**: 1-1.5 ชั่วโมง

**สิ่งที่จะได้**:
- `/auth/line/login` endpoint ที่ redirect ไป LINE
- `/auth/line/callback` ที่รับ user info → ออก Hub JWT (เหมือน Google ทุกประการ)
- ML/RBA 4-Layer scoring ยังทำงานต่อไปได้เลย

---

## Phase 0 — Pre-flight check

**ก่อนเริ่ม ตรวจว่าระบบพร้อม:**

```bash
# Hub backend up?
curl http://localhost:8000/health  # → 200

# มี LINE account (ใครๆ ก็มี — ถ้าไม่มี โหลด app LINE แล้วสมัครฟรี)
# ไม่ต้องใช้บัตรเครดิต ไม่ต้อง verify identity
```

**เอกสาร LINE Login อ่านควบคู่:**
- Overview: https://developers.line.biz/en/docs/line-login/overview/
- OIDC discovery: https://access.line.me/.well-known/openid-configuration
- LINE Developers Console: https://developers.line.biz/console/

---

## Phase 1 — สร้าง LINE Login Channel (~10 นาที, ไม่แตะ code)

### 1.1 เข้า LINE Developers Console

ไปที่ **https://developers.line.biz/console/** → login ด้วย LINE account
(จะให้ scan QR code จากมือถือเพื่อ login ครั้งแรก)

### 1.2 สร้าง Provider

**Provider** = "องค์กร/เจ้าของ" ของ Channel ทั้งหมด — สร้างครั้งเดียวใช้ได้หลาย channel

1. หน้า Console → คลิก **Create a new provider**
2. กรอก **Provider name**: `Central Auth Hub` (เปลี่ยนได้)
3. คลิก **Create**

### 1.3 สร้าง Channel (LINE Login type)

ภายใน provider ที่เพิ่งสร้าง:

1. คลิก **Create a new channel**
2. เลือก **LINE Login**
3. กรอก:
   - **Channel name**: `Central Auth Hub Dev`
   - **Channel description**: `Hub OAuth client - dev`
   - **App types**: ✅ ติ๊ก **Web app** (สำคัญ — ห้ามลืม)
   - **Email address**: email ของคุณ
   - **Region**: Thailand (หรือตามที่อยู่)
4. ติ๊กยอมรับ **LINE Developers Agreement**
5. คลิก **Create**

### 1.4 จด Channel ID + Channel secret

หลัง create จะเด้งหน้า channel — จดค่า 2 ตัวนี้:

- แท็บ **Basic settings**:
  - **Channel ID** → จะเอาไปใส่เป็น `LINE_CHANNEL_ID`
  - **Channel secret** → คลิก **Issue** ถ้ายังไม่มี → จะเอาไปใส่เป็น `LINE_CHANNEL_SECRET`

**หมายเหตุ**: LINE ใช้คำว่า "Channel ID/secret" แต่จริงๆ เทียบเท่า `client_id`/`client_secret` ใน OAuth ทั่วไป

### 1.5 ตั้ง Callback URL

1. แท็บ **LINE Login** (ในเมนูซ้ายของ channel)
2. หา **Callback URL** → คลิก **Edit**
3. กรอก:
   ```
   http://localhost:8000/auth/line/callback
   ```
4. คลิก **Update**

**⚠️ สำคัญ**: ตัวพิมพ์เล็ก, ไม่มี `/` ลงท้าย, ใช้ `http://` (dev)

### 1.6 เปิด Email scope (เพราะ Hub ต้องใช้ email match user)

1. แท็บ **OpenID Connect** ใน channel
2. หา **Email address permission** → คลิก **Apply**
3. กรอกเหตุผล (ภาษาอังกฤษ ระบบจะ auto-approve สำหรับ dev account):
   ```
   Used as primary identifier to match users in the university Hub auth system.
   ```
4. ติ๊กยอมรับ + Submit
5. รอ status เปลี่ยนเป็น **Applied** (ปกติ instant สำหรับ developer account)

**ถ้าไม่ขอ email scope** → LINE จะส่งแค่ `userId` + `displayName` กลับมา (ไม่มี email) → Hub จะ match user ไม่ได้

### 1.7 (Optional) เปิด Channel ให้ใช้ได้

แท็บ **Basic settings** → ปุ่ม **Developing** ที่มุมขวาบน
- **Developing** = เฉพาะ admin (คุณ) login ได้
- **Published** = ใครก็ได้ login (ต้องผ่าน review สำหรับ production)

สำหรับ dev ปล่อย **Developing** ไว้ — login ด้วย LINE account ของคุณเองได้

---

## Phase 2 — เพิ่ม config ใน Hub backend (~5 นาที)

### 2.1 เพิ่ม env variables

**ไฟล์ `.env.example`** (commit ได้ — เป็น template):

```env
# ─── LINE Login (OIDC) ───
# LINE เรียก client_id ว่า "Channel ID" และ client_secret ว่า "Channel secret"
# ดู developers.line.biz/console → Channel → Basic settings
LINE_CLIENT_ID=your-line-channel-id
LINE_CLIENT_SECRET=your-line-channel-secret
LINE_REDIRECT_URI=http://localhost:8000/auth/line/callback
```

**ไฟล์ `.env`** (จริง — gitignored):

```env
LINE_CLIENT_ID=<paste Channel ID from 1.4>
LINE_CLIENT_SECRET=<paste Channel secret from 1.4>
LINE_REDIRECT_URI=http://localhost:8000/auth/line/callback
```

### 2.2 เพิ่ม settings เข้า config.py

เปิด **`hub/backend/app/config.py`** → หาส่วนที่มี `google_client_id` → เพิ่มข้างใต้:

```python
# LINE Login — Week 9 alternate IdP
# Channel ID/secret จาก LINE Developers Console (ใช้ชื่อ client_* เพื่อให้
# code pattern เหมือน Google ที่มีอยู่)
line_client_id: str = ""
line_client_secret: str = ""
line_redirect_uri: str = "http://localhost:8000/auth/line/callback"
```

**ทำไม default = ""** : ถ้า user ยังไม่ตั้ง env, ระบบไม่ crash — แค่ /auth/line/login จะ fail ตอนเรียก (graceful degradation)

**Pydantic field mapping** — `line_client_id` ใน Python จะอ่านจาก env `LINE_CLIENT_ID` อัตโนมัติ (case-insensitive, underscore → underscore)

### 2.3 (Optional) ปรับ `validate_production()`

ถ้าคุณ deploy production และอยาก LINE เป็น mandatory → ตรวจใน `validate_production()` ว่ามี secret. ตอนนี้ skip ได้

---

## Phase 3 — เพิ่ม OAuth client + endpoints ใน auth.py (~30 นาที)

**ไฟล์: `hub/backend/app/routers/auth.py`**

### 3.1 Register LINE client

หา block `oauth.register(name="google", ...)` (ราวบรรทัด 46) → เพิ่มข้างใต้:

```python
oauth.register(
    name="line",
    client_id=settings.line_client_id,
    client_secret=settings.line_client_secret,
    # LINE Login เป็น OIDC compliant — มี OpenID discovery endpoint
    # ใช้ pattern เดียวกับ Google/Microsoft, Authlib จัดการ token/userinfo เอง
    server_metadata_url=(
        "https://access.line.me/.well-known/openid-configuration"
    ),
    client_kwargs={"scope": "openid email profile"},
)
```

**ทำไมเหมือน Google เป๊ะ**: Authlib ใช้ OIDC discovery — ทั้ง Google และ LINE ต่างก็เป็น OIDC compliant → pattern เดียวกัน

**Scope ที่ขอ:**
- `openid` — เปิด OIDC flow (LINE จะส่ง id_token กลับมาด้วย)
- `email` — ดึง email (ต้องเปิด permission ใน Console ขั้น 1.6 ก่อน)
- `profile` — ดึง displayName + pictureUrl

### 3.2 เพิ่ม endpoint `/line/login`

หาด้านล่าง `/google/login` (ราวบรรทัด 58) → copy แล้ว rename:

```python
# ============ LINE login — redirect ไป LINE ============


@router.get("/line/login")
@limiter.limit(settings.rate_limit_login)
async def line_login(request: Request):
    """พาผู้ใช้ไปหน้า login ของ LINE. (rate-limited per-IP)"""
    await emit(
        EVT_LOGIN_PRE,
        {
            "ip": get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
            "provider": "line",  # ← เพิ่ม field เพื่อ track ว่ามาจาก IdP ไหน
        },
    )
    redirect_uri = settings.line_redirect_uri
    return await oauth.line.authorize_redirect(request, redirect_uri)
```

### 3.3 เพิ่ม endpoint `/line/callback`

หา `/google/callback` (ราวบรรทัด 76) → **copy ทั้ง function** แล้วเปลี่ยน:

1. Function name: `google_callback` → `line_callback`
2. Path: `/google/callback` → `/line/callback`
3. `oauth.google.authorize_access_token` → `oauth.line.authorize_access_token`
4. ตัวแปร `google_sub` → `line_sub` (และ field ที่ใช้)

**ความแตกต่างของ userinfo:**

| Field | Google | LINE |
|---|---|---|
| Unique ID | `userinfo["sub"]` | `userinfo["sub"]` = LINE userId (OIDC standard) ✅ |
| Email | `userinfo["email"]` | `userinfo["email"]` (ต้องเปิด permission 1.6) ⚠️ |
| Name | `userinfo["name"]` | `userinfo["name"]` = LINE display name ✅ |
| Picture | `userinfo["picture"]` | `userinfo["picture"]` = LINE avatar URL ✅ |
| Email verified | `userinfo["email_verified"]` | ❌ ไม่ส่ง — assume true (LINE verify email ตอน user เปิด permission) |

**ระวัง — LINE บาง case ไม่ส่ง email:**
- User ยังไม่ verify email ใน LINE app
- Email permission ใน Console ยังไม่ได้ Apply (Phase 1.6)
- ถ้า `email` is None → ไม่มี fallback แบบ Microsoft → **ต้องบอก user**

Code snippet สำหรับ email extraction:

```python
email = userinfo.get("email")
if not email:
    # LINE didn't return email — user hasn't verified yet, or scope was denied
    raise HTTPException(
        status_code=400,
        detail=(
            "LINE ไม่ส่ง email มาให้ — กรุณา verify email ใน LINE app ก่อน "
            "หรือ revoke permission แล้ว login ใหม่"
        ),
    )
line_sub = userinfo["sub"]  # LINE userId — globally unique per LINE account
```

### 3.4 อัปเดต `User` model (Optional — ถ้าอยาก track provider)

**ไฟล์: `hub/backend/app/models.py`**

ถ้าอยาก track ว่า user login ผ่าน IdP ไหน → เพิ่ม column:

```python
class User(Base):
    # ... existing fields ...
    google_sub = Column(String, nullable=True, index=True)
    line_sub = Column(String, nullable=True, index=True)  # ← ใหม่ (LINE userId)
```

ใน callback set:
```python
if not user.line_sub:
    user.line_sub = line_sub
```

**SQL migration:**
```sql
ALTER TABLE users ADD COLUMN line_sub VARCHAR;
CREATE INDEX ix_users_line_sub ON users(line_sub);
```

**⚠️ ต้องทำ DB migration** — ถ้ายังไม่อยากแตะ schema → skip ส่วนนี้ ใช้ `google_sub` column รวมก็ได้ (เก็บ LINE sub ลงไป — แต่ชื่อ column จะตีความผิด ไม่แนะนำ)

หรือใช้ alembic ถ้าตั้งไว้

### 3.5 Audit log — ใส่ provider ใน metadata

**แนะนำ**: เก็บ provider ใน metadata ดีกว่าเปลี่ยน action name (จะ filter ใน audit dashboard ได้ง่าย):

```python
metadata={"email": email, "line_sub": line_sub, "provider": "line"}
```

ทุก log_action ใน callback (success + failure paths) ควรมี `"provider": "line"` ใน metadata เพื่อแยกจาก Google login

---

## Phase 4 — Frontend: ปุ่ม "Login with LINE" (~15 นาที)

**ไฟล์: `hub/frontend/app/auth/login/page.tsx`**

หา button "Sign in with Google" → copy + ปรับเป็น LINE:

```tsx
<a
  href={`${HUB_URL}/auth/line/login`}
  className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg
             bg-[#06C755] hover:bg-[#05A647] text-white font-semibold transition"
>
  <LineLogo className="w-5 h-5" />
  Login with LINE
</a>
```

**LINE brand color** = `#06C755` (เขียวสด LINE) — ใช้ตัว Tailwind arbitrary value `bg-[#06C755]`

**LINE logo SVG** (วงกลมสีเขียวมีตัว LINE):
```tsx
function LineLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 320 320" className={className} fill="currentColor">
      <path d="M160 0C71.6 0 0 58.2 0 130c0 64.4 56.8 118.4 133.6 128.6
               5.2 1.1 12.3 3.4 14.1 7.9 1.6 4 1 10.3.5 14.4l-2.3 13.6
               c-.7 4-3.2 15.7 13.7 8.6 17-7.1 91.3-53.7 124.5-92
               23-25.2 33.9-50.7 33.9-79.1C320 58.2 248.4 0 160 0z" />
      <text x="160" y="180" textAnchor="middle" fontSize="100"
            fontWeight="bold" fill="#06C755">LINE</text>
    </svg>
  );
}
```

หรือใช้ official LINE button รูปภาพ (download จาก https://developers.line.biz/en/docs/line-login/login-button/):
```tsx
<img src="/btn_login_base.png" alt="Login with LINE" />
```

**ตำแหน่งวางปุ่ม** — ใน login page ใต้ปุ่ม Google:

```tsx
<div className="space-y-3 mt-6">
  <GoogleSigninButton />   {/* เดิม */}
  <LineLoginButton />      {/* ใหม่ */}
</div>
```

→ user เห็น 2 ทางเลือก: Google (เดิม) และ LINE (ใหม่)

หรือใช้ icon library: `pnpm add simple-icons` แล้ว `import { siLine } from "simple-icons"` (มี LINE icon สำเร็จ)

---

## Phase 5 — Test end-to-end (~15 นาที)

### 5.1 Restart backend

```bash
docker compose restart hub-backend
sleep 5
docker logs hub-backend --tail=10
# ดูว่า "Application startup complete" ไม่มี ERROR
```

### 5.2 Verify routes แสดงใน Swagger

ไปที่ http://localhost:8000/docs → หา section **Authentication** → ควรเห็น:
- `GET /auth/google/login` (เดิม)
- `GET /auth/google/callback` (เดิม)
- `GET /auth/line/login` (ใหม่) ✅
- `GET /auth/line/callback` (ใหม่) ✅

### 5.3 ดู email ของ LINE account ก่อน

LINE ไม่บอก email ของคุณตรงๆ ใน profile — ต้องเช็คใน app:

1. เปิด LINE app → เมนู Home (มุมล่างซ้าย)
2. คลิก ⚙️ (Settings) → **Account**
3. ดู **Email account** → ถ้ายังไม่มี → เพิ่มแล้ว verify ก่อน
4. จด email นี้ไว้ (เช่น `you@gmail.com`)

### 5.4 Manual flow test

**สำคัญ — pre-seed user ใน DB ก่อน** (Hub block email ที่ไม่อยู่ใน users table):

```bash
docker exec hub-postgres psql -U hub -d hub_db -c "
INSERT INTO users (id, email, full_name, user_type, identifier, status, is_hub_admin)
VALUES (gen_random_uuid(), 'your-line-email@gmail.com', 'Test LINE User',
        'admin', 'L001', 'active', true)
ON CONFLICT (email) DO NOTHING;
"
```

แทนที่ `your-line-email@gmail.com` ด้วย email ที่ผูกกับ LINE account ของคุณ (จากขั้น 5.3)

**Flow:**
1. ใน browser (Incognito) → http://localhost:3000/auth/login
2. คลิก **"Login with LINE"** (ปุ่มเขียว) → redirect ไป `access.line.me`
3. ถ้ายังไม่ login LINE บน browser → scan QR code จาก mobile (หรือใส่ email/password)
4. หน้า consent: LINE บอกว่า app นี้ขอข้อมูล (profile, email, openid) → คลิก **Authorize / อนุญาต**
5. LINE ส่งกลับ → `/auth/line/callback` → ระบบออก Hub JWT
6. Redirect ไป `/dashboard`
7. ดู `/admin/audit` → จะเห็น `hub_login_success` พร้อม metadata `provider: line`

### 5.5 ตรวจ ML/RBA ยังทำงาน

ใน `/admin/ml` → session ใหม่จะมี risk_score, breakdown, SHAP เหมือนเดิม — เพราะ flow callback ส่ง features เข้า `evaluate_login_risk` แบบเดียวกัน
(จะได้ feature `is_new_device=1` ครั้งแรกที่ login ผ่าน LINE เพราะ User-Agent ต่างจาก Google flow ที่เคยใช้)

### 5.6 Smoke test

```bash
bash scripts/routine/test_workflow.sh  # ควร 7/7 PASS
```

---

## Phase 6 — Common Gotchas

### ❌ "The callback URL is incorrect" (หน้า LINE error)

**สาเหตุ**: callback URL ใน LINE Console ไม่ตรงกับที่ส่งใน code

**แก้**: LINE Developers Console → channel → แท็บ **LINE Login** → **Callback URL**:
- `http://localhost:8000/auth/line/callback` (เป๊ะ ตัวพิมพ์เล็ก, ไม่มี `/` ลงท้าย)
- LINE รองรับ `http://` สำหรับ localhost (dev) — production ต้อง `https://`
- กดปุ่ม **Update** ทุกครั้งหลังแก้ — ไม่ auto-save

### ❌ LINE ไม่ส่ง email มาด้วย (`userinfo.get("email")` is None)

**สาเหตุ 1**: Email permission ยังไม่ Apply

**แก้**: LINE Console → channel → แท็บ **OpenID Connect** → **Email address permission** → คลิก **Apply** (Phase 1.6)

**สาเหตุ 2**: User ยังไม่มี email ผูกกับ LINE account

**แก้**: บอก user ให้ไป LINE app → Settings → Account → Email address → เพิ่มและ verify

**สาเหตุ 3**: User กด "Deny" ตอน consent screen ของ email scope

**แก้**: บอก user ให้ revoke permission แล้ว login ใหม่:
- LINE app → Settings → Privacy → Authorized Apps → ลบ Channel นี้ออก
- กลับมาที่ Hub login page → คลิก LINE login ใหม่ → ยอมรับ email scope

### ❌ "Login ได้แค่ admin" (user คนอื่นไม่ได้)

**สาเหตุ**: Channel ยัง status **Developing** — เฉพาะคนที่เป็น admin/tester ของ channel ใน Console เท่านั้นที่ login ได้

**แก้**:
- **Dev**: เพิ่ม email ของคนอื่นในแท็บ **Roles** → **Add user** (ต้องเป็น LINE Developer account)
- **Production**: ต้อง submit channel ให้ LINE review → status เปลี่ยนเป็น **Published** → ใครก็ login ได้

### ❌ ML/RBA score สูงผิดปกติตอน login ผ่าน LINE ครั้งแรก

**ไม่ใช่บั๊ก** — features `is_new_device` + `is_new_user_agent_family` = 1 เพราะ User-Agent ของ LINE in-app browser ต่างจาก Chrome ที่เคยใช้
- ครั้งแรก: score 0.3-0.5 (warn/challenge zone)
- หลังจาก login 5 ครั้ง: profile build แล้ว — score ปกติ

### ❌ JWT ออกได้แต่ ID ใน session แสดงผิด

**สาเหตุ**: `userinfo["sub"]` ของ LINE ต่างกับ Google → ถ้า user เคย login Google มาก่อน แล้ว login LINE จะ "match by email" → set `line_sub` ของ user เดิม ✅

ถ้าอยาก strict ให้ user 1 คน = 1 provider → check ก่อน:
```python
if user.google_sub and not user.line_sub:
    raise HTTPException(409, "User เคย register ด้วย Google ใช้ปุ่ม Google เถอะ")
```

### ❌ "Error: invalid_request" หลัง callback

**สาเหตุ**: state mismatch — Authlib session middleware ไม่ถูกต้อง

**แก้**: ตรวจ `main.py` มี `SessionMiddleware` (มีอยู่แล้วถ้า Google ทำงานได้ — ไม่ต้องเพิ่มใหม่)

### ⚠️ "ML รัน slow มากครั้งแรกที่ login"

**ไม่ใช่บั๊ก** — Authlib ต้อง fetch `https://access.line.me/.well-known/openid-configuration` ครั้งแรก → cache แล้วครั้งต่อไปเร็ว (~200ms)

---

## Phase 7 — Production considerations (Optional, อ่านก่อนเอาขึ้น prod)

### 7.1 จำกัด domain

Hub ของมหา'ลัยอาจอยากรับเฉพาะ @uni.ac.th + บาง provider → ใน callback:

```python
ALLOWED_DOMAINS = {"uni.ac.th", "gmail.com"}  # ตัวอย่าง
if email.split("@")[-1].lower() not in ALLOWED_DOMAINS:
    raise HTTPException(403, "domain ไม่ได้รับอนุญาต")
```

**ข้อสังเกต LINE**: email ที่ผูกกับ LINE ส่วนใหญ่เป็น Gmail/Hotmail ของส่วนตัว ไม่ใช่ @uni.ac.th
→ ถ้าจะรับเฉพาะ uni domain ให้บอก user ให้เปลี่ยน email ใน LINE app ก่อน หรือใช้ Google login แทน

### 7.2 Publish channel + LINE review

ก่อน production ต้องเปลี่ยน status จาก **Developing** → **Published**:

1. LINE Console → channel → **Basic settings** → ปุ่ม **Developing** ที่มุมขวาบน → คลิก
2. กรอกข้อมูล:
   - **Privacy policy URL** (จำเป็น): `https://hub.uni.ac.th/privacy`
   - **Terms of service URL** (จำเป็น): `https://hub.uni.ac.th/tos`
   - **App icon**: 240x240px PNG/JPG
3. ถ้าขอ email scope → ต้องส่ง **business verification** (LINE จะถาม company info)
4. รอ review (1-7 วัน) — LINE อาจขอ document เพิ่ม

**ทางลัดสำหรับ defense**: อยู่ใน **Developing** mode + add กรรมการเป็น tester ใน Console → demo ได้เลย ไม่ต้องรอ review

### 7.3 Email verification

LINE บอกว่า user verify email แล้วเท่านั้นถึงจะส่ง email มา (Phase 1.6) — ดังนั้น **assume `email_verified: true`** ได้

แต่ถ้าต้อง double-check ใน Hub:
```python
if not userinfo.get("email"):
    # ไม่มี email — แปลว่า user ปิด email scope หรือยังไม่ verify
    raise HTTPException(400, "Email ไม่ได้รับการ verify ใน LINE")
```

### 7.4 ID Token validation

Authlib ทำให้ auto แล้ว — JWKS ของ LINE อยู่ที่ `https://api.line.me/oauth2/v2.1/certs`
(อ่านได้จาก OIDC discovery: `https://access.line.me/.well-known/openid-configuration`)

ID token ของ LINE มี claims:
```json
{
  "iss": "https://access.line.me",
  "sub": "U1234abcd...",  // LINE userId
  "aud": "<your-channel-id>",
  "exp": 1234567890,
  "iat": 1234567890,
  "name": "Display Name",
  "picture": "https://profile.line-scdn.net/...",
  "email": "user@example.com"  // ถ้าเปิด email scope
}
```

### 7.5 HTTPS callback (สำคัญสำหรับ production)

LINE จะปฏิเสธ callback URL ที่เป็น `http://` ถ้า channel เป็น Published status (ยกเว้น localhost)
→ Production ต้องใช้ `https://` พร้อม cert ที่ valid (Let's Encrypt ฟรี)

### 7.6 Rate limit ของ LINE

LINE OAuth endpoint มี rate limit (ไม่ public แต่ ~100 req/sec ต่อ channel) — สำหรับ Hub ปกติเพียงพอ
ถ้า high traffic (> 100k user) → ปรึกษา LINE Sales

---

## เสร็จแล้ว — ทำไง?

1. ✅ Login ผ่าน LINE ได้ → ออก Hub JWT → เข้า dashboard
2. ✅ Audit log บันทึก `provider: line`
3. ✅ ML risk scoring ยังทำงาน (เห็นใน `/admin/ml`)
4. ✅ Google login เดิมก็ยังใช้ได้ — ทั้ง 2 IdP coexist

**Commit อย่างไร:**

```bash
git add hub/backend/app/config.py \
        hub/backend/app/routers/auth.py \
        hub/backend/app/models.py \
        hub/frontend/app/auth/login/page.tsx \
        .env.example \
        docs/guides/add-line-login.md

git commit -m "feat(auth): add LINE Login as alternate OAuth IdP

Demonstrates that the Hub auth platform is OAuth-provider-agnostic.
LINE uses the same OIDC discovery + Authlib pattern as Google,
preserving the full ML/RBA risk-scoring pipeline downstream.

Rationale: free signup (no credit card), familiar to Thai university
users, OIDC-compliant. Mirrors the proof Google did for Western users."
```

**Defense story ที่จะได้:**
- "ระบบรองรับการเปลี่ยน IdP โดยไม่กระทบ business logic ส่วนอื่น"
- "User เลือก provider ที่ตนใช้บ่อย — Gmail หรือ LINE"
- "ML/RBA pipeline ทำงานเหมือนกันทุก IdP" (แสดงด้วย SHAP breakdown)

---

## เปลี่ยนใจอยากลบทิ้ง?

ลบจุดเหล่านี้ก็พอ:
- Remove `oauth.register(name='line', ...)` block ใน `auth.py`
- Remove `/line/login` + `/line/callback` functions
- Remove ปุ่ม LINE ใน login page
- Remove env vars (optional — ไม่มีก็ไม่ break อะไร)
- (Optional) Drop `line_sub` column ใน DB: `ALTER TABLE users DROP COLUMN line_sub;`

ระบบ Google flow ไม่กระทบเลย

---

## Reference

- **LINE Login docs**: https://developers.line.biz/en/docs/line-login/
- **LINE Developers Console**: https://developers.line.biz/console/
- **OIDC well-known**: https://access.line.me/.well-known/openid-configuration
- **LINE brand assets** (logo + button): https://developers.line.biz/en/docs/line-login/login-button/

---

**คำถามขณะทำ?** เปิด terminal คุยกับผมได้ทุกขั้น
