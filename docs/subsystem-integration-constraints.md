# คู่มือพัฒนาระบบย่อย (Subsystem Integration Guide)

คู่มือสำหรับทีมที่ต้องการพัฒนา **ระบบย่อย (subsystem)** เพื่อเชื่อมกับ Central Auth Hub
ครอบคลุม: สิ่งที่ Hub มอบให้, สิ่งที่ dev ต้องสร้างเอง, ข้อจำกัด, และ checklist

> อัปเดต: 2026-07-12 · อ้างอิงระบบจริง 3 ตัว (หอพัก/ห้องสมุด/เกรด) + PHP/Node/Python SDK
> ครอบคลุมเพิ่ม: Roster Sync API (X-Api-Key), Health check จาก Hub, webhook `access_restored`

---

## 0. ภาพรวมสถาปัตยกรรม

**ไม่ใช่ SSO** — Hub ทำหน้าที่ authenticate + authorize เท่านั้น แต่ละ subsystem มี session
ของตัวเอง Hub เป็น **Authorization Server (AS)**, subsystem เป็น **Client / Resource Server (RS)**
ที่ทีมอื่นเป็นเจ้าของ รันคนละเครื่อง/โดเมน/ฐานข้อมูล

```
┌──────────┐  redirect        ┌──────────┐   OAuth     ┌──────────┐
│ Subsystem│─────────────────▶│   Hub    │────────────▶│  Google  │
│ (ของคุณ) │◀──Token (S2S)────│ (Central)│             │          │
│          │                  │          │             └──────────┘
│          │  GET /api/v1/roster (X-Api-Key) ─────────▶│ ML / RBA
│          │◀── users[] ──────│          │             │ Passkey
│  /health │◀── ping ทุก 5นาที│          │
└────┬─────┘                  └────┬─────┘
     │  webhook (back-channel: revoked / updated / restored)
     ◀──────────────────────────────┘
```

**4 ช่องทางการสื่อสาร Hub ⇄ subsystem:**
1. **OAuth flow** (subsystem → Hub → subsystem) — login + แลก token
2. **Webhook back-channel** (Hub → subsystem) — revoke/update/restore แบบ real-time
3. **Health check** (Hub → subsystem `/health`) — Hub ถามสุขภาพทุก 5 นาที
4. **Roster Sync** (subsystem → Hub `/api/v1/roster`) — ดึงรายชื่อล่วงหน้า (optional)

**หลักการสำคัญ:** Hub **เอื้อมเข้าไปทำงานในเครื่อง subsystem ไม่ได้** (คนละ trust domain)
→ Hub มอบ "เครื่องมือ + ข้อมูล" ให้ แต่ subsystem ต้อง "ลงมือทำ" ในระบบตัวเอง

---

## 0.1 ระบบย่อยต้องมีอะไรบ้าง ถึงจะเชื่อมต่อ Hub ได้ (Minimum Requirements)

สรุปสั้น — จะเป็น subsystem ที่ Hub ยอมรับได้ ต้องมีครบ **4 ข้อบังคับ** + **2 ข้อแนะนำ**:

### ✅ บังคับ (ไม่มี = เชื่อมไม่ได้)

| # | ต้องมี | ทำไม | อ้างอิง |
|---|--------|------|---------|
| 1 | **ลงทะเบียนกับ Hub** → ได้ `client_id` + `client_secret` + `redirect_uri` ที่ approve แล้ว | Hub รู้จัก client + ออก token ให้เฉพาะที่ลงทะเบียน · redirect_uri ต้อง match เป๊ะ | §1.1, §2.1 |
| 2 | **OAuth callback endpoint** (`/oauth/callback` หรือ path ที่ลงทะเบียน) — public, browser + Hub เข้าถึงได้ | ปลายทางที่ Hub ส่ง `code` กลับ · exchange เป็น JWT ที่นี่ | §2.1 |
| 3 | **JWT verification** (RS256 ผ่าน JWKS + ตรวจ `aud`=client_id, `iss`, `exp`) | พิสูจน์ว่า token จริง + ไม่ใช่ของระบบอื่น (audience confusion) | §2.2 |
| 4 | **Session ของตัวเอง + enforce `exp`** (Hub ไม่ใช่ SSO — ไม่ถือ session ให้) | หลัง login user คุยกับ subsystem ตรงๆ Hub มองไม่เห็น | §2.3 |

### 🟡 แนะนำอย่างยิ่ง (production ควรมี)

| # | ควรมี | ได้อะไร | อ้างอิง |
|---|--------|---------|---------|
| 5 | **`GET /health` endpoint** (public, ตอบ 200 เร็ว < 1s) | Hub ping ทุก 5 นาที → โชว์สถานะ online/degraded/down ใน admin console + ถ้า down จะกัน login (503 maintenance) | §1.6, §2.7 |
| 6 | **Webhook receiver** (`/internal/access-*`, verify HMAC) | รับ event revoke/scope-change → เตะ session ทันที (ไม่ต้องรอ token หมดอายุ) | §1.4, §2.4 |

> **ขั้นต่ำสุดที่ "login ได้"** = ข้อ 1–4. แต่ **ข้อ 5 (health) สำคัญมาก** เพราะถ้าไม่มี
> `/health` Hub จะมองว่า subsystem `down` → บล็อก OAuth flow (503) ในโหมดที่เปิด health-gate.
> ดังนั้นในทางปฏิบัติ **`/health` ก็เกือบจะบังคับ** (ดู §1.6).

**ข้อกำหนดเชิงเทคนิคที่ตายตัว (บังคับทุกข้อ):**
- Algorithm: **RS256** (JWT) · **PKCE S256** (flow) · **HMAC-SHA256** (webhook)
- `redirect_uri` ต้อง match กับที่ลงทะเบียนเป๊ะ (รวม scheme/host/port/path)
- เก็บ `hub_user_id` (= JWT `sub`) เป็น **UUID อิสระ ไม่มี FK ไป Hub**
- `client_secret` + PKCE verifier + API key **อยู่ server-side เท่านั้น** (ห้ามใน JS/HTML)

---

## 1. สิ่งที่ subsystem ได้รับจาก Hub

### 1.1 ตอนลงทะเบียน (Registration → `POST /developer/subsystems`)

| ได้รับ | รายละเอียด | ใช้ทำอะไร |
|---|---|---|
| **client_id** | `cli_xxxxxxxx` | ระบุตัวตน subsystem ใน OAuth flow |
| **client_secret** | `sec_xxxxxxxx` | one-time link 15 นาที (ดูครั้งเดียว) | ใช้ token exchange (server-side เท่านั้น) |
| **subsystem_id** | UUID | reference ภายใน |
| **api_key** | roster read-only key — one-time (DB เก็บ Argon2 hash) | ดึง roster ล่วงหน้าผ่าน `X-Api-Key` (ดู §1.5) |
| **access_policy** | `explicit` / `all` / `role` / `attribute` (+ config) | ตัดสินว่าใครเข้าได้ (login + roster ใช้เกณฑ์เดียวกัน) |
| **status** | `pending` → admin approve → `active` | ใช้ login / ดึง roster ได้เมื่อ active |
| **webhook_endpoints** | `{access_revoked, access_updated, access_restored}` URL ที่แนะนำ | บอกว่าควรสร้าง receiver ที่ไหน |
| **webhook_note** | คำแนะนำการ verify HMAC | |

### 1.2 ตอน OAuth flow (runtime)

| ได้รับ | จาก | รายละเอียด |
|---|---|---|
| **authorization code** | `GET /oauth/authorize` → callback | อายุ 60 วินาที ใช้ครั้งเดียว |
| **access_token (JWT)** | `POST /oauth/token` | RS256, อายุ 60 นาที, มี claims ตาม scope |
| **scope + role_in_subsystem** | token response | บอก field ที่ได้ + role ของ user |
| **passkey_grace_remaining_days** | token response (optional) | banner เตือนตั้ง passkey (ถ้ามี) |

### 1.3 Endpoint สาธารณะของ Hub (เรียกได้ตลอด)

| Endpoint | ใช้ทำอะไร |
|---|---|
| `GET /.well-known/openid-configuration` | OIDC Discovery — โหลด endpoint ทั้งหมดอัตโนมัติ |
| `GET /.well-known/jwks.json` | public key (RS256) สำหรับ verify JWT — cache 10 นาที |
| `GET /oauth/authorize` | เริ่ม flow (client_id, redirect_uri, state, code_challenge) |
| `POST /oauth/token` | แลก code → JWT (server-to-server) |
| `POST /oauth/logout` | back-channel logout (optional) |

### 1.4 Webhook ที่ Hub จะ "ส่งมาหา" subsystem (back-channel)

| Event | เมื่อไหร่ | payload หลัก | subsystem ควรทำ |
|---|---|---|---|
| `access_revoked` | user ถูกถอนสิทธิ์ (**ทุกนโยบาย** — whitelist หรือ deny-list ทับ policy) | `hub_user_id`, `reason`, `revoked_by` | mark re-auth **ถาวร** (login ใหม่จะโดน Hub block อยู่แล้ว) |
| `access_updated` | role/scope เปลี่ยน (เฉพาะคน) · scope-config เปลี่ยน (`hub_user_id`=null = ทุกคน) · **admin force-logout** | `hub_user_id`, `reason`, `new_role?` | บังคับ re-auth เพื่อเอา claim ชุดใหม่ (login ใหม่ได้) |
| `access_restored` | admin **คืนสิทธิ์** (grant กลับหลัง revoke) | `hub_user_id` | ยกเลิก re-auth marker → session เดิมกลับมาใช้ได้ |

Headers: `X-Hub-Event`, `X-Hub-Signature-256` (HMAC-SHA256 ของ raw body), `X-Hub-Timestamp` (epoch — กัน replay, ต้องห่างปัจจุบัน ≤ `webhook_max_age_sec`)

> **access_revoked vs access_updated:** revoked = "ถอนถาวร" (deny-list — login ใหม่ก็เข้าไม่ได้จนกว่า
> admin คืนสิทธิ์) · updated = "เตะออกตอนนี้แต่ login ใหม่ได้" (claim เปลี่ยน / force-logout).
> ทั้งคู่ subsystem จัดการเหมือนกันคือ **mark session เก่าให้หมดสิทธิ์** ต่างกันแค่ยอมให้ login ใหม่ไหม
> (Hub เป็นคนตัดสินตอน login ใหม่ผ่าน Access Policy — subsystem ไม่ต้องจำเอง).

### 1.5 Roster Sync API — ดึงรายชื่อผู้ใช้ล่วงหน้า (S2S, read-only)

สำหรับระบบที่ต้อง **สร้างข้อมูลก่อน user login** (เช่น **ระบบเกรด** — เกรดถูก pre-create
ผูก `hub_user_id` ก่อนนักศึกษาเข้าครั้งแรก · JIT provisioning ตอน login อย่างเดียวไม่พอ):

| รายการ | ค่า |
|---|---|
| Endpoint | `GET /api/v1/roster` |
| Auth | header **`X-Api-Key: <api_key>`** (ได้ตอนลงทะเบียน — one-time) |
| Rate limit | 30 ครั้ง/นาที |
| เงื่อนไข | subsystem ต้อง `status=active` (ไม่งั้น 403) |
| คืนเฉพาะ | `user_id` (UUID), `email`, `user_type` — **data minimization** (ข้อมูลเต็มไหลตอน login ตาม scope) |
| กรองด้วย | **Access Policy** ของ subsystem (เกณฑ์เดียวกับ login-time — ตัด deny-list ออกให้แล้ว) |

```json
GET /api/v1/roster    (X-Api-Key: ...)
→ { "subsystem": "ระบบเกรด", "access_policy": "role", "count": 41,
    "users": [ {"user_id": "c15c...", "email": "650015@uni.ac.th", "user_type": "student"}, ... ] }
```

> **หลักการ:** *Hub ตัดสินว่าใครเข้าระบบได้ · subsystem ตัดสินว่าข้อมูลเป็นของใคร* — เช่นระบบเกรด
> policy เป็น `role:[student]` แต่ถ้าดึงมาแล้วมี user_type อื่นปน subsystem ควร filter เอง
> (เกรดเป็น business data ของนักศึกษา). deny-list ที่ admin ตั้ง (ถอนสิทธิ์รายคน) จะทำให้ user
> คนนั้น **หลุดจาก roster อัตโนมัติ** — sync รอบถัดไปจะไม่เห็นเขา.

### 1.6 Health Check — Hub ping /health ของ subsystem (monitoring)

Hub มี background task เช็คสุขภาพ subsystem ทุกตัวที่ `status=active`:

| รายการ | ค่า |
|---|---|
| Hub ยิงไปที่ | `GET {origin ของ redirect_uris[0]}/health` (เอา scheme+host จาก redirect_uri ตัวแรก) |
| ความถี่ | ทุก **5 นาที** (background scheduler) |
| Timeout | **3 วินาที** |
| เก็บผล | Redis `subsystem:health:{id}` (cache 30 นาที) → โชว์ในหน้า admin |
| จัดสถานะ | `online` (200 + latency < 1s) · `degraded` (200 + ≥ 1s, หรือ 5xx ครั้งเดียว) · `down` (timeout / connection refused / 5xx 3 ครั้งซ้อน) |
| สรุปรายวัน | snapshot 3 รอบ (เช้า 08:00 / บ่าย 13:00 / เย็น 18:00 ICT) → audit log → หน้า `/notifications` |

**subsystem ต้องมีอะไร:** แค่ **endpoint `GET /health` (public, ไม่ต้อง auth) ที่ตอบ `200 OK` เร็ว**
(ควร < 1s ไม่งั้นถูกจัดเป็น `degraded`). ตัวอย่างที่พอแล้ว:

```python
@app.get("/health")
def health():
    return {"status": "ok"}          # ตอบเร็ว ไม่ต้องแตะ DB ก็ได้ (หรือ + db.stats() ถ้าอยาก)
```

> ⚠️ **ผลถ้าไม่มี `/health`:** Hub จะเช็คไม่ผ่าน → mark `down`. ในโหมดที่เปิด **health-gate**
> Hub จะกัน OAuth flow (ตอบ **503 maintenance**) ไม่ให้ user login เข้า subsystem ที่ down
> → ในทางปฏิบัติ `/health` **เกือบบังคับ**. (เคยเจอบั๊ก: ระบบเกรดตอน dev โดน 503 เพราะ Hub
> ใน container เข้า `localhost:8003` ไม่ได้ — dev แก้ด้วย docker service-name mapping)
>
> **หมายเหตุ dev/Docker:** Hub ใช้ mapping เดียวกับ webhook (`localhost:8001` → `subsystem-dorm:8000`)
> เวลา ping /health จาก container — prod ต้องเป็น URL จริงที่ Hub เข้าถึงได้.

### 1.7 SDK สำเร็จรูป (ลด boilerplate)

| ภาษา | path | ครอบคลุม |
|---|---|---|
| PHP | `hub/sdk/php-client/` | OAuth + PKCE + JWT verify + JWKS cache + WebhookReceiver + RevocationStore |
| Node | `hub/sdk/node-client/` | เหมือนกัน |
| Python | `hub/sdk/python-client/` | เหมือนกัน |

---

## 2. สิ่งที่ dev ต้องพัฒนาเอง (Hub ทำแทนไม่ได้)

> เหตุผลที่ Hub ทำแทนไม่ได้: code เหล่านี้ต้อง execute บน **เครื่อง/โดเมน/runtime ของ subsystem**

### 2.0 ใช้ SDK ช่วยได้แค่ไหน — "ไม่ต้องเขียน logic แต่ยังต้อง wire เอง"

ถ้าใช้ SDK ที่ Hub ให้ (PHP/Node/Python) จะ **ไม่ต้องเขียน logic crypto/protocol เอง**
(PKCE, signature verify, HMAC ฯลฯ SDK จัดให้) — **แต่ยังต้องประกอบ SDK เข้าแอป + host
บนเซิร์ฟเวอร์ตัวเอง + config** เพราะ SDK รันบน runtime ของ subsystem ไม่ใช่บน Hub

```
SDK = ครัวสำเร็จรูป (เตา หม้อ สูตร) · dev = ต้องตั้งในบ้านตัวเอง + เปิดเตา + กดปุ่ม
```

| ส่วน                  | SDK ทำให้ (ไม่ต้องเขียน logic)            | dev ยังต้อง wire เอง                                            | งานที่เหลือ |
|---|---|---|---|
| **OAuth Flow**       | PKCE, state, code exchange            | สร้าง login/callback/logout (เรียก SDK) + host + config          | น้อย (~10 บรรทัด/ไฟล์) |
| **JWT Verify**       | signature + aud + iss + exp ✅       | แค่เรียก `handleCallback()`                                      | **≈ 0** |
| **Session + Expiry** | เก็บ session + เช็ค exp/max_age/revoke  | เรียก `isAuthenticated()` guard ทุกหน้า + ตั้ง session_max_age      | น้อย |
| **Webhook Receiver** | verify HMAC + RevocationStore         | สร้าง webhook.php (เรียก SDK) + host + ตั้ง revocation_store_path  | ปานกลาง |

**ทำไม SDK ทำให้ 100% ไม่ได้:**
1. SDK รันบนเครื่อง subsystem — ต้อง include + เรียกในแอปเอง (Hub สั่งแอปคนอื่นรันโค้ดไม่ได้)
2. endpoint ต้อง host บนโดเมน subsystem (browser + Hub ต้องเข้าถึง)
3. ต้องเลือกเองว่า guard หน้าไหน (SDK บังคับทุกหน้าให้เช็คเองไม่ได้)
4. ต้อง config ค่าเฉพาะ subsystem (client_id/secret/redirect/scope/keys)

**ข้อจำกัดของการ "ส่ง SDK ให้":**
- SDK มีเฉพาะ **PHP / Node / Python** — ภาษาอื่น (Go/.NET/Ruby) ต้องเขียนเอง หรือใช้
  **Go auth-proxy sidecar** (subsystem แค่อ่าน header ที่ proxy ใส่ → ไม่ต้องแตะ OAuth เลย)
- **webhook URL ที่ Hub "สร้างให้" = แค่บอก address** ที่ควรสร้าง receiver — Hub ไม่ได้
  ไปสร้าง endpoint ให้ (สร้างบนเครื่องคนอื่นไม่ได้) dev ยังต้องทำ receiver เอง

> สรุป: SDK เปลี่ยนงานจาก **"เขียนระบบ auth"** → **"ต่อท่อ + ตั้งค่า"** แต่ไม่ใช่ศูนย์
> เพราะต้องรันในบ้านของ subsystem เสมอ

---

### 2.1 OAuth Login Flow ⭐ บังคับ

สร้าง 3 จุดบนเซิร์ฟเวอร์ตัวเอง:

```
1. /login         → สร้าง PKCE (verifier+challenge) + state → redirect ไป Hub /oauth/authorize
2. /callback      → รับ code → verify state → POST /oauth/token (แนบ client_secret + verifier) → ได้ JWT
3. /logout        → ล้าง session ของตัวเอง
```

**ทำไม Hub ทำแทนไม่ได้:** callback ลงที่ URL ของ subsystem · client_secret + PKCE verifier
อยู่ฝั่ง subsystem · การ exchange code คือการพิสูจน์ว่าเป็น client จริง

> ใช้ SDK: `$hub->startLogin()` / `$hub->handleCallback()` — เหลือ ~10 บรรทัด

### 2.2 JWT Verification ⭐ บังคับ (security critical)

ทุก token ที่ได้ ต้อง verify:
- **signature** (RS256) ผ่าน JWKS ของ Hub
- **`aud` = client_id ของตัวเอง** ← กัน audience confusion (token ระบบอื่นมาใช้)
- **`iss`** = issuer ของ Hub
- **`exp`** = ยังไม่หมดอายุ

**ทำไม Hub ทำแทนไม่ได้:** subsystem คือผู้ไว้ใจ (relying party) — ต้องตรวจ ณ จุดที่ใช้
token เอง · มีแต่ subsystem ที่รู้ว่า client_id ตัวเองคืออะไร

> ใช้ SDK: verify อัตโนมัติใน `handleCallback()`

### 2.3 Session Management + Expiry ⭐ บังคับ

หลังได้ JWT → สร้าง session ของตัวเอง (cookie/server session) แล้ว:
- เก็บ claims + `logged_in_at`
- **enforce expiry เอง** — เช็ค JWT `exp` ทุก request (+ optional session_max_age)
- ตั้ง cookie: HttpOnly + SameSite + Secure (prod)

**ทำไม Hub ทำแทนไม่ได้:** หลัง login แล้ว user คุยกับ subsystem ไม่ใช่ Hub — Hub
มองไม่เห็น request เหล่านั้น และอ่าน/ลบ cookie ข้ามโดเมนไม่ได้

> ⚠️ บั๊กที่พบบ่อย: ไม่เช็ค exp → session ค้างตลอด (ดู PHP SDK `isAuthenticated()` ที่เช็ค exp + max_age)

### 2.4 Webhook Receiver (ถ้าต้องการ real-time revoke/update)

สร้าง endpoint รับ webhook:
- `/internal/access-revoked` + `/internal/access-updated` (หรือ single-file รับทั้ง 2)
- **verify HMAC-SHA256** ด้วย `WEBHOOK_SHARED_KEY` + ตรวจ timestamp (replay)
- เมื่อได้ event → แก้ state ของตัวเอง (mark user ต้อง re-auth / kill session)

**ทำไม Hub ทำแทนไม่ได้:** Hub เป็นผู้ส่ง ต้องมีผู้รับ · Hub เข้าถึง session store/DB
ของ subsystem ไม่ได้ → แจ้งได้อย่างเดียว subsystem ต้อง act เอง

> ถ้าไม่ทำ webhook: role/scope change จะ propagate ช้า (รอ session/token หมดอายุ)

### 2.5 Business Logic + Database ของตัวเอง

- ตาราง/ข้อมูลของ subsystem (เช่น หอพัก: rooms/reservations; ห้องสมุด: books/borrowings)
- **ห้ามมี FK ไป Hub** — เก็บ `hub_user_id` (= JWT `sub`) เป็น UUID อิสระ
- map JWT claims → user profile ของตัวเอง (sync ตอน login)

### 2.6 RBAC ภายใน subsystem (ถ้ามีหลาย role)

- ใช้ `role_in_subsystem` จาก token → จำกัดสิทธิ์ภายใน (เช่น resident vs staff)
- Hub ส่ง role มาให้ แต่ enforce เป็นของ subsystem

### 2.7 Health endpoint 🟡 แนะนำอย่างยิ่ง (เกือบบังคับ)

สร้าง `GET /health` (public, ไม่ต้อง auth) ตอบ `200 OK` เร็ว < 1s — Hub ping ทุก 5 นาที
เพื่อโชว์สถานะ + gate การ login (ดู §1.6).

**ทำไม Hub ทำแทนไม่ได้:** Hub เป็นคน "ถาม" ต้องมีคน "ตอบ" ที่ origin ของ subsystem —
Hub รัน endpoint บนเครื่องคนอื่นไม่ได้ · ต้องเป็น URL ที่ Hub เข้าถึงได้จริง (prod = HTTPS จริง)

> ระบบตัวอย่างทั้ง 3 (หอพัก/ห้องสมุด/เกรด) มี `/health` ครบ — ก็อปแพตเทิร์นได้เลย

### 2.8 Roster pre-provisioning (เฉพาะระบบที่สร้างข้อมูลก่อน login)

ถ้าระบบต้องมี record รอ user อยู่ก่อน login ครั้งแรก (เช่นเกรด) → เขียน job ดึง
`GET /api/v1/roster` (X-Api-Key) เป็นระยะ แล้ว pre-create record ผูก `hub_user_id` (ดู §1.5).
ระบบที่ provision ตอน login พอ (หอพัก/ห้องสมุด) **ไม่ต้องทำข้อนี้**.

---

## 3. ข้อจำกัด (Constraints)

### 3.1 ข้อจำกัดที่ Hub กำหนด (ควบคุมไม่ได้ฝั่ง subsystem)

| ข้อจำกัด | ค่า | หมายเหตุ |
|---|---|---|
| อายุ access token | 60 นาที | คงที่ |
| authorization code | 60 วินาที + ใช้ครั้งเดียว | atomic (กัน replay) |
| client_secret | ดูครั้งเดียว 15 นาที | พลาด = rotate ใหม่ |
| scope ที่ได้จริง | admin approve | ขอเกินจำเป็นไม่ได้ |
| ใครเข้าได้ | **Access Policy** (explicit/all/role/attribute) | ไม่ผ่าน policy = 403 · admin ถอนรายคนได้ทุกนโยบายผ่าน deny-list |
| status ของ subsystem | ต้อง `active` | `pending`/`suspended` = login + roster ถูก reject |
| algorithm | RS256 / PKCE S256 / HMAC-SHA256 | บังคับ |
| redirect_uri | ต้อง match เป๊ะ | แก้ต้อง re-approve |

### 3.2 ข้อจำกัด Dev Environment (Docker/XAMPP)

| ข้อจำกัด | สาเหตุ | ทางแก้ |
|---|---|---|
| IP จริงเก็บไม่ได้ (เห็น 172.x) | Docker Desktop NAT mask client IP | prod ผ่าน nginx ตั้ง X-Forwarded-For |
| subsystem ต้อง start หลัง DB | start ก่อน postgres ขึ้น = crash | `up -d` ยก stack ให้ครบก่อน |
| localhost ใน webhook URL | container เข้า localhost ของ host ไม่ได้ | Hub แปลงเป็น host.docker.internal อัตโนมัติ (dev) |
| Google OAuth test mode | เฉพาะ email ใน test_users | เพิ่ม email ใน Google Console |
| PHP subfolder redirect | `/myapp/callback.php` → path ไม่ตรง convention | ใช้ relative path + ตั้ง access_revoke_webhook_url เอง |

### 3.3 ข้อจำกัดเชิงพฤติกรรม

- **ไม่ใช่ SSO** — login subsystem A ไม่ carry ไป B
- **เปลี่ยน scope ไม่ revoke token เดิม** — มีผลกับ login ครั้งถัดไป (หรือใช้ webhook access_updated)
- **session แยกต่อ subsystem** — แต่ละระบบจัดการเอง

---

## 4. สิ่งที่ควรทำ (Security Best Practices — บังคับ)

- [ ] verify JWT ครบ: signature + `aud` + `iss` + `exp`
- [ ] PKCE S256 ทุก flow · verifier เก็บ server-side
- [ ] state (CSRF) + verify ด้วย constant-time (`hash_equals`)
- [ ] client_secret อยู่ server-side เท่านั้น (ห้ามใน JS/HTML)
- [ ] session cookie: HttpOnly + SameSite=Lax + Secure (prod)
- [ ] enforce JWT exp ทุก request (+ session_max_age ถ้าต้องการสั้นลง)
- [ ] webhook receiver: verify HMAC + timestamp ก่อน act
- [ ] expose `GET /health` (public, ตอบ 200 เร็ว < 1s) — ไม่งั้น Hub mark down + gate login (§1.6)
- [ ] API key (roster) อยู่ server-side เท่านั้น · ดึง roster ผ่าน HTTPS
- [ ] HTTPS ใน production
- [ ] เก็บ hub_user_id เป็น UUID อิสระ (ไม่มี FK ไป Hub)
- [ ] log ทุก state-changing action ของ subsystem (audit)

---

## 5. ขั้นตอนเริ่มต้น (Quick Start — PHP/XAMPP)

```
1. ขอ admin ลงทะเบียน subsystem → ได้ client_id + secret (one-time link) + webhook URLs
2. คัดลอก SDK: hub/sdk/php-client/ → htdocs/<myapp>/sdk/
3. สร้าง config.php (hub_url, client_id, client_secret, redirect_uri, scope, session_max_age,
   webhook_shared_key, revocation_store_path)
4. สร้าง index/login/callback/dashboard/logout.php (ดู examples/)
5. (optional) webhook.php — รับ access_revoked/access_updated → RevocationStore
6. admin: เพิ่ม email เข้า whitelist + ตั้ง access_revoke_webhook_url ถ้า path ไม่ตรง convention
7. ทดสอบ: localhost/<myapp>/ → login → callback → dashboard
```

> ตัวอย่างครบชุดดูที่ `hub/sdk/php-client/examples/` + `hub/sdk/php-client/README.md`

---

## 6. ตารางสรุป — Hub ให้ vs Dev ทำ

| เรื่อง              | Hub ให้ (เครื่องมือ)                                          | Dev ต้องทำ (ใน runtime ตัวเอง) |
|---               |---                                                        |---|
| OAuth            | authorize/token endpoint, SDK, JWKS                       | initiate + รับ callback + exchange |
| JWT              | เซ็น + เปิด JWKS/discovery                                  | verify signature + aud + exp |
| Session          | ออก JWT มี exp                                             | สร้าง session + enforce expiry |
| Scope            | ใส่ field ตาม scope ใน JWT                                 | map claims → profile + แสดงผล |
| Webhook          | ส่ง + เซ็น event (revoked/updated/restored) + แนะนำ URL      | host receiver + verify + act |
| Revoke real-time | push event                                                | invalidate session ของตัวเอง |
| **Health check** | ping `/health` ทุก 5 นาที + โชว์สถานะ + gate login          | **expose `GET /health` ตอบ 200 เร็ว** |
| **Roster sync**  | `/api/v1/roster` (X-Api-Key) กรองตาม Access Policy          | (ถ้าต้องการ) ดึง + pre-create record |
| Business logic   | —                                                         | ทั้งหมด (DB, UI, RBAC ภายใน) |

---

## 7. อ้างอิง

- `hub/sdk/php-client/README.md` — 5-minute integration
- `hub/subsystem-dorm/`, `hub/subsystem-library/` — ตัวอย่าง subsystem จริง (OAuth login)
- `hub/subsystem-grade/` — ตัวอย่างที่ใช้ **Roster Sync + API key** (pre-provisioning) + webhook receiver ครบ
- `hub/backend/app/routers/roster.py` — Roster Sync API (source)
- `hub/backend/app/services/subsystem_health.py` — Health check scheduler (source)
- `docs/backlog-traceability.md` — ข้อจำกัด IP ใน dev + webhook patterns
- RFC 6749 (OAuth), 7636 (PKCE), 7519 (JWT), OIDC Discovery 1.0
