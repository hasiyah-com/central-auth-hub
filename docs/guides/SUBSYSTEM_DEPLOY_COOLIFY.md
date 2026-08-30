# Deployment Guide — ระบบย่อยที่เชื่อมต่อกับ Central IAM (ผ่าน Coolify)

> คู่มือสำหรับ **ทีมเจ้าของระบบย่อย** (subsystem team) ที่จะ deploy ระบบย่อยขึ้น production
> แล้วเชื่อมต่อกับ **Central Auth Hub** (Central IAM) ผ่าน OAuth 2.0 + PKCE
>
> **ทั้ง Central IAM (Hub) และระบบย่อย deploy บน Coolify เหมือนกัน — แค่คนละเซิร์ฟเวอร์:**
> ทีมกลาง run Hub บน Coolify server ของตัวเอง (`https://hub.example.ac.th`), ส่วนทีม
> เจ้าของระบบย่อยแต่ละทีม run ระบบย่อยของตัวเองบน Coolify server แยกอีกตัว แล้วชี้
> `HUB_*_URL` ข้ามมาที่ Hub ผ่าน HTTPS สาธารณะ — แยก server ทำให้ trust domain แยกจริง
> (subsystem team เข้าถึง DB/secret ของ Hub ไม่ได้) ตรงกับสถาปัตยกรรมจริงที่คนละทีมดูแล
>
> ไฟล์นี้โฟกัส flow ฝั่ง **subsystem team** (deploy เฉพาะระบบย่อยของตัวเอง). สำหรับขั้นตอน
> ภายในของฝั่ง Hub เอง (generate JWT keys, seed users, train ML, migration ฯลฯ) ดู
> [`DEPLOYMENT.md`](DEPLOYMENT.md) — หลักการ deploy เหมือนกัน (Coolify: Git → build →
> env → domain → TLS อัตโนมัติ) ต่างแค่รายการ service ที่ต้อง run
>
> สถาปัตยกรรม **ไม่ใช่ SSO** — ระบบย่อยมี session ของตัวเองแยกจาก Hub, Hub ทำหน้าที่
> authenticate + authorize เท่านั้น (ดู CLAUDE.md)

รองรับระบบย่อยทั้ง 3 ตัวในโปรเจกต์: **ระบบหอพัก (dorm)**, **ระบบห้องสมุด (library)**,
**ระบบเกรด (grade)** — และเป็นแม่แบบสำหรับระบบย่อยใหม่ที่จะ onboard เข้ามา

---

## Deployment Flow (ภาพรวม)

```
  ┌─────────────────┐   6. register    ┌──────────────────┐
  │  Subsystem Team │─────────────────▶│  Central IAM Hub │
  │ Coolify server 1│◀── client_id ────│ Coolify server 2 │
  └────────┬────────┘   + secret       └──────────────────┘
           │ 1. source → 2. Docker → 3. .env.production
           │ 4. DB+migration → 5. domain/DNS
           ▼
  ┌─────────────────┐   9. deploy      ┌──────────────────┐
  │     Coolify     │─────────────────▶│  Container(s)    │
  │  Git → Build    │                  │  backend+frontend│
  └─────────────────┘                  └────────┬─────────┘
           │ 8. HTTPS (auto TLS)                │ 11. GET /health
           │                                    ▼
           │ 12-16. ทดสอบ: OAuth login → JWT → access policy
           │        → data scope → webhook → logging
           ▼
  17. Monitoring → 18. Backup → 19. Security checklist → 20. Production ON
```

---

## Deployment Checklist (สรุป 20 ขั้นตอน)

| # | ขั้นตอน | สถานะในโปรเจกต์ | ทำที่ไหน |
|---|---------|----------------|----------|
| 1 | เตรียม source code | ✅ มีครบ (`hub/subsystem-*/`) | repo |
| 2 | เตรียม Docker | ✅ `Dockerfile` ทุกตัว + `docker-compose.*.prod.yml` | repo |
| 3 | เตรียม env (`.env.production`) | ✅ `.env.example` เป็นแม่แบบ → §3 | Coolify env |
| 4 | เตรียม DB + migration | ✅ Postgres (dorm/lib) / SQLite (grade) | Coolify / volume |
| 5 | เตรียม domain + DNS | ⚙️ ตั้งเอง (ชี้มา Coolify) | DNS provider |
| 6 | ลงทะเบียนกับ Central IAM | ✅ `/developer/subsystems` หรือ script (grade) | Hub console |
| 7 | ตั้งค่า OAuth | ✅ PKCE + redirect_uri validation | Hub + env |
| 8 | HTTPS / TLS | ✅ Coolify ออก cert อัตโนมัติ | Coolify |
| 9 | Deploy ผ่าน Coolify | ⚙️ ทำใน Coolify UI → §9 | Coolify |
| 10 | ตรวจ container ทำงาน | ⚙️ Coolify → Deployments | Coolify |
| 11 | Health Check | ✅ `GET /health` (ดูหมายเหตุ §11) | curl |
| 12 | ทดสอบเชื่อม Central IAM | ✅ OAuth flow เต็ม | browser |
| 13 | ทดสอบ Access Policy | ✅ 4 mode + deny-list | Hub console |
| 14 | ทดสอบ Data Scope | ✅ JWT claim ตาม scope | JWT decode |
| 15 | ทดสอบ Webhook | ✅ back-channel revoke/force-logout | log |
| 16 | ทดสอบ Logging | ✅ audit_logs + request_logs (Hub) | Hub DB |
| 17 | Monitoring | ⚙️ Coolify health + Hub SOC dashboard | Coolify |
| 18 | Backup | ✅ `scripts/backup.sh` (Postgres) | cron |
| 19 | Security Checklist | ✅ ส่วนใหญ่มีในโค้ด → §19 | audit |
| 20 | เปิด production | ⚙️ `APP_ENV=production` + ML enforce | env |

✅ = มีในโค้ด/พร้อมใช้  ⚙️ = ต้องตั้งค่าตอน deploy (per-environment)

---

## 1. เตรียม Source Code

โครงสร้างระบบย่อยแต่ละตัว (self-contained, deploy แยกได้):

```
hub/subsystem-dorm/         # ระบบหอพัก (FastAPI + Jinja2, Postgres)
├── Dockerfile
├── requirements.txt
├── .env.example            # แม่แบบ → คัดลอกเป็น .env.prod
├── app/
│   ├── main.py             # FastAPI + GET /health
│   ├── routers/            # auth (OAuth client), pages, reservation, staff
│   └── services/           # hub_client.py (PKCE+JWKS), session.py, audit.py
└── scripts/seed_rooms.py
```

ระบบย่อยเป็น **OAuth client** ของ Hub — โค้ดที่ต้อง deploy คือ backend (มี frontend
ในตัวสำหรับ dorm/library แบบ Jinja2, หรือแยก React SPA สำหรับบางตัว)

> ทีมเจ้าของระบบย่อยควร fork/clone **เฉพาะโฟลเดอร์ระบบย่อยของตัวเอง** ไม่ต้องเอา Hub
> ทั้งก้อนไป — production Hub host โดยทีมกลาง

## 2. เตรียม Docker

แต่ละระบบย่อยมี `Dockerfile` พร้อม + prod compose แยก stack:

| ระบบย่อย | Dockerfile | prod compose |
|----------|-----------|--------------|
| dorm | `hub/subsystem-dorm/Dockerfile` | `docker-compose.dorm.prod.yml` |
| library | `hub/subsystem-library/Dockerfile` | `docker-compose.library.prod.yml` |
| grade | `hub/subsystem-grade/Dockerfile` | `docker-compose.grade.prod.yml` |

prod compose ต่างจาก dev: **ไม่มี host port** (proxy ผ่านหน้า), **ไม่ mount source**,
**ไม่มี `--reload`**, รันด้วย `--proxy-headers --forwarded-allow-ips='*'` (ให้ `get_client_ip`
อ่าน X-Forwarded-For ที่ Coolify/proxy ตั้งให้ถูก — ดู B20)

> **Coolify:** ใช้ build จาก `Dockerfile` โดยตรงได้เลย (Coolify → Build Pack: Dockerfile)
> หรือชี้ไปที่ prod compose ก็ได้ (Build Pack: Docker Compose)

## 3. เตรียม Environment Variables (`.env.production`)

คัดลอกจาก `.env.example` แล้วเติมค่าจริง — ตัวอย่าง **ระบบหอพัก**:

```env
# ── App ──
APP_ENV=production
SESSION_SECRET_KEY=<random 64 chars>          # openssl rand -hex 32
SESSION_COOKIE_SECURE=true                     # ⚠️ ต้อง true บน HTTPS (B55)

# ── Database (ของระบบย่อยเอง แยกจาก Hub) ──
DORM_POSTGRES_USER=dorm
DORM_POSTGRES_PASSWORD=<strong password>
DORM_POSTGRES_DB=dorm_db
DATABASE_URL=postgresql+psycopg2://dorm:<pw>@postgres-dorm:5432/dorm_db

# ── OAuth Client credentials (ได้จากขั้นตอน 6) ──
DORM_CLIENT_ID=cli_xxxxxxxxxxxxxxxx
DORM_CLIENT_SECRET=<retrieve ครั้งเดียวจาก one-time link>

# ── Hub URLs ──
HUB_INTERNAL_URL=https://hub.example.ac.th     # prod: internal = public (คนละ host)
HUB_PUBLIC_URL=https://hub.example.ac.th       # URL ที่ browser redirect ไป
DORM_CALLBACK_URL=https://dorm.example.ac.th/oauth/callback   # ต้อง register ตรงนี้

# ── Webhook (back-channel จาก Hub) ──
HUB_WEBHOOK_SHARED_KEY=<ตรงกับ Hub WEBHOOK_SHARED_KEY เป๊ะ>
# ── Session ──
SESSION_COOKIE_NAME=dorm_session
SESSION_MAX_AGE_SECONDS=3600
```

**ต่างกันตามระบบย่อย:**
- **library** — prefix `LIB_*` แทน `DORM_*`
- **grade** — ใช้ SQLite (`DB_PATH=/app/data/grade.db`) + มี `GRADE_ROSTER_API_KEY`
  เพิ่ม (X-Api-Key สำหรับ Roster Sync) + `HUB_ISSUER=https://hub.example.ac.th`

> **URL ที่ได้ถ้าไม่ตั้ง custom domain** — Coolify/Dokploy สร้าง hostname ให้อัตโนมัติ
> ในรูป `<service>-<random>-<ip-คั่นด้วยขีด>.sslip.io` (sslip.io resolve กลับเป็น IP นั้น)
>
> ```text
> https://centralhub-<SERVER_IP_DASHED>.sslip.io          # Hub backend
> https://central-admin-<SERVER_IP_DASHED>.sslip.io       # Admin console
> https://<prefix>-dorm-<random>-<SERVER_IP_DASHED>.sslip.io
> https://<prefix>-library-<random>-<SERVER_IP_DASHED>.sslip.io
> ```
>
> `<SERVER_IP_DASHED>` = IP ของเซิร์ฟเวอร์โดยเปลี่ยน `.` เป็น `-` (เช่น `10.0.0.1` → `10-0-0-1`)
> **ไม่ระบุ IP จริงในเอกสารนี้โดยตั้งใจ** — repo เป็นสาธารณะ การเขียน host จริงลงไป
> เท่ากับประกาศเป้าให้สแกน · ค่าจริงดูได้ใน Coolify UI → resource → Domains

> **ห้ามใส่ secret ลง git** — `.env*` ถูก gitignore + pre-commit `block-env-files` block.
> บน Coolify ใส่ผ่าน **Environment Variables** ของ resource (เก็บ encrypted) ไม่ใช่ commit ไฟล์
>
> ⚠️ prod Hub รัน `config.validate_production()` — ถ้า `APP_ENV=production` แต่ยังใช้ default
> `SECRET_KEY`/`SECRET_ENCRYPTION_KEY` จะ **fail-fast ไม่ยอม start** (ฝั่ง Hub)

## 4. เตรียม Database + Migration

| ระบบย่อย | DB | Migration |
|----------|-----|-----------|
| dorm / library | PostgreSQL 15 (แยก container ต่อระบบ) | SQLAlchemy `create_all` ตอน start + seed script |
| grade | SQLite (self-contained, volume `/app/data`) | table สร้างตอน start |

- Postgres healthcheck ต้องมี `-d <db>`: `pg_isready -U dorm -d dorm_db` (B: ไม่งั้น FATAL spam)
- Seed ครั้งเดียวหลัง deploy:
  ```bash
  # ใน Coolify → Terminal ของ container (หรือ exec)
  python -m scripts.seed_rooms      # dorm: 24 ห้อง
  python -m scripts.seed_books      # library: 30 เล่ม
  # grade: ไม่มี seed — sync roster ผ่านหน้าเว็บ /manage
  ```
- **Backup:** ดู §18

## 5. เตรียม Domain + DNS

ตั้ง A/AAAA record ชี้มาที่ Coolify server:

```
dorm.example.ac.th      →  <Coolify server IP>
library.example.ac.th   →  <Coolify server IP>
grade.example.ac.th     →  <Coolify server IP>
```

domain นี้ต้องตรงกับ `*_CALLBACK_URL` และ redirect_uri ที่ register กับ Hub (ขั้นตอน 6-7)

## 6. ลงทะเบียนระบบย่อยกับ Central IAM

ทีมเจ้าของระบบย่อยต้องมีบัญชี role **teacher/staff/admin** (developer) ที่ Hub

**dorm / library** — ผ่าน console:
1. login `https://hub.example.ac.th` (หรือ admin console) → **Developer Portal**
2. `POST /developer/subsystems` — กรอก name, **redirect_uris** (`https://dorm.example.ac.th/oauth/callback`),
   scope (เช่น `["email","name"]`)
3. ระบบคืน **one-time secret link** (อายุ 15 นาที, ใช้ครั้งเดียว) → เปิดเพื่อ copy
   `client_secret` (เก็บเป็น HMAC ใน DB — retrieve ได้ครั้งเดียว)
4. เอา `client_id` + `client_secret` ไปกรอกใน `.env.production` (ขั้นตอน 3)
5. รอ admin **อนุมัติ** (`/admin/subsystems/{id}/approve`) → status `pending → active`

**grade** — ผ่าน script (ต้องออก Roster API key ด้วย):
```bash
docker compose exec hub-backend python -m scripts.register_grade_subsystem
# print: GRADE_CLIENT_ID / GRADE_CLIENT_SECRET / GRADE_ROSTER_API_KEY
```

**ตั้ง Access Policy** ตอนลงทะเบียน (โหมดใดโหมดหนึ่ง):
- `explicit` — เฉพาะ user ใน whitelist (upload CSV / เพิ่มทีละคน)
- `all` — ทุก user ที่ login Hub ได้
- `role` — ตาม user_type (เช่น student เท่านั้น)
- `attribute` — ตาม faculty/major/year
- \+ **deny-list** ทับได้ทุกโหมด

## 7. ตั้งค่า OAuth

Flow ที่ระบบย่อยใช้ (`services/hub_client.py`):

```
/login → สร้าง PKCE (verifier+challenge) → redirect
  → HUB_PUBLIC_URL/oauth/authorize?client_id&redirect_uri&state&code_challenge
  → (Hub: Google login + access_list check + RBA scoring)
  → redirect กลับ DORM_CALLBACK_URL?code&state
  → POST HUB_INTERNAL_URL/oauth/token (client_secret + code_verifier)  [server-to-server]
  → ได้ JWT (RS256, aud=client_id) → verify ผ่าน JWKS (cache 10 นาที)
```

**Redirect URI validation** (ฝั่ง Hub) — ต้อง match กับที่ register **เป๊ะ** และปฏิเสธ
scheme อันตราย (`javascript:`, `ftp:`, non-HTTPS ใน prod) → ดู B ใน `docs/bugs-encountered.md`

**PKCE บังคับ** ทุก flow (RFC 7636) + เทียบ challenge ด้วย `hmac.compare_digest` (B3)

## 8. HTTPS / TLS

- **Coolify ออก Let's Encrypt cert อัตโนมัติ** เมื่อผูก domain (ไม่ต้องตั้ง nginx เอง)
- ต้อง `SESSION_COOKIE_SECURE=true` (ไม่งั้น cookie ไม่ถูกส่งบน HTTPS หรือ leak บน HTTP) — B55
- ห้าม mixed content: `HUB_PUBLIC_URL` ต้องเป็น `https://`
- Coolify ตั้ง `X-Forwarded-Proto`/`X-Forwarded-For` ให้ — backend รันด้วย
  `--proxy-headers --forwarded-allow-ips='*'` เพื่อให้ `get_client_ip()` อ่าน IP จริง

## 9. Deploy ผ่าน Coolify

1. **New Resource** → เลือก **Git repository** (public/private + deploy key)
2. **Build Pack:**
   - *Dockerfile* → ชี้ `hub/subsystem-dorm/Dockerfile`, Base Directory `hub/subsystem-dorm`
   - หรือ *Docker Compose* → ชี้ `docker-compose.dorm.prod.yml`
3. **Environment Variables** → วางค่าจาก §3 (Coolify เก็บ encrypted)
4. **Domain** → `https://dorm.example.ac.th` (Coolify ออก TLS ให้)
5. **Port** → container ฟัง `8000` (uvicorn) → Coolify map 443 → 8000
6. กด **Deploy** → Coolify pull → build → run
7. (ทางเลือก) เปิด **Auto Deploy on push** ผูก webhook GitHub

## 10. ตรวจ Container ทำงาน

- Coolify → resource → **Deployments** = สถานะ Running (เขียว)
- **Logs** ไม่มี traceback / ไม่มี "fail-fast" (config error)
- ถ้าใช้ compose: `postgres-*` ต้อง healthy ก่อน subsystem (depends_on)

## 11. Health Check

```bash
curl https://dorm.example.ac.th/health
```

ควรได้:
```json
{"status": "healthy", "service": "subsystem-dorm", "version": "0.1.0"}
```
(grade คืน `{"status":"healthy", ...db.stats()}`) — **`status == "healthy"`** ตรงกับ
contract ของ guide → ตั้ง healthcheck/monitoring ให้ยึด `"healthy"`

Coolify healthcheck: ตั้ง path `/health`, expected status `200`.

## 12. ทดสอบเชื่อมต่อ Central IAM (OAuth end-to-end)

เปิด `https://dorm.example.ac.th` → กด login → ควรได้ครบ:
1. redirect ไป Hub → Google consent → กลับมาที่ callback
2. Hub เช็ค access_list + รัน RBA scoring
3. `/oauth/token` แลก JWT สำเร็จ → subsystem สร้าง session cookie ของตัวเอง
4. เข้าหน้าใช้งานได้ (เห็นชื่อ/email จาก JWT claim)
5. logout → session subsystem หาย + (ถ้า config) แจ้ง Hub back-channel

> E2E test ครอบ flow นี้แล้ว: `hub/backend/tests/test_e2e_oauth_flow.py` (7 เคส
> positive+negative: secret ผิด / PKCE ไม่ตรง / code ใช้ซ้ำ / aud confusion)

## 13. ทดสอบ Access Policy

| เคส | คาดหวัง |
|-----|---------|
| user ใน whitelist (explicit) | เข้าได้ |
| user นอก whitelist | Hub ปฏิเสธที่ `/oauth/callback` (ไม่ออก code) |
| user status = suspended/graduated | ปฏิเสธ (บล็อกที่ Hub) |
| user ใน deny-list | ปฏิเสธแม้ policy = all |
| admin force-logout / revoke | Hub ยิง **webhook** ตัด session subsystem (B52) |

## 14. ทดสอบ Data Scope

decode JWT ที่ได้ → ตรวจว่ามี **เฉพาะ** field ตาม scope ที่ register:
- scope `["email","name"]` → claim มี `email`, `full_name` เท่านั้น (ไม่มี phone/address)
- ทุก JWT มี `aud=client_id ของเรา` — เอาไป verify ที่ระบบอื่นไม่ได้ (B4)

## 15. ทดสอบ Webhook (back-channel)

Hub push webhook เมื่อมี action ที่ต้องตัดสิทธิ์ทันที (revoke / force-logout / ban):
- endpoint ฝั่ง subsystem verify ด้วย `HUB_WEBHOOK_SHARED_KEY` (HMAC) → ลบ session
- **fail-safe (B21/B52):** ยิงไม่สำเร็จ Hub log ไม่ raise (ไม่ล้ม flow หลัก)

ทดสอบ: login subsystem ค้างไว้ → admin กด force-logout ที่ Hub → session subsystem
ควรถูกตัด (ครั้งถัดไปที่ request)

## 16. ทดสอบ Logging

- **ฝั่ง Hub:** ทุก login/oauth/failure ลง `audit_logs` + `request_logs` (มี IP จริงผ่าน
  `get_client_ip`) — ตรวจใน admin console → Audit Log
- **ฝั่ง subsystem:** `services/audit.py` → `*_audit_logs` ของ DB ตัวเอง
- login ที่ล้มเหลวต้องมี log ด้วย (`oauth_login_failed_*`) — B7

## 17. Monitoring

- **Coolify:** health check + resource metrics (CPU/RAM) + log stream
- **Hub SOC Dashboard:** login sessions + anomaly_score + decision distribution +
  IP blacklist + API alerts (admin console)
- ตั้ง alert ถ้า `/health` != 200 หรือ failed_login เกิน threshold

## 18. Backup

- **Postgres (dorm/library):** `scripts/backup.sh` → `pg_dump` + sync (cron รายวัน)
- **SQLite (grade):** copy volume `/app/data/grade.db` (Coolify → Persistent Storage → snapshot)
- ทดสอบ restore อย่างน้อย 1 ครั้งก่อนเปิด production จริง

## 19. Security Checklist

| ข้อ | สถานะ | ที่มา |
|-----|-------|-------|
| HTTPS ทุก endpoint | ✅ | Coolify TLS + `SESSION_COOKIE_SECURE=true` |
| JWT validation (RS256 + aud + JWKS) | ✅ | `hub_client.py` verify + cache 10 นาที |
| PKCE ทุก OAuth flow | ✅ | `services/pkce.py` + `hmac.compare_digest` |
| Secret ไม่อยู่ใน source | ✅ | `.env` gitignore + pre-commit block + Coolify encrypted |
| DB ไม่ expose public | ✅ | prod compose ไม่ map host port (internal network) |
| Rate limiting | ✅ | Hub `rate_limiter.py` (per IP / client_id) |
| CORS | ⚙️ | ตั้ง allowed origins = domain ของตัวเอง |
| CSP / X-Frame-Options / HSTS | ⚙️ | Coolify proxy headers หรือ middleware |
| Token revocation (jti blacklist) | ✅ | Hub Redis + `verify_token` เช็คทุกครั้ง |
| Audit ทุก state-change + failure | ✅ | `log_action()` → commit → raise (B6/B7) |

⚙️ = ตั้งเพิ่มตอน deploy (per-environment header)

## 20. เปิด Production

1. ตั้ง `APP_ENV=production` ทุก service (subsystem + Hub)
2. ยืนยัน `SESSION_COOKIE_SECURE=true`, secret ทุกตัวไม่ใช่ default
3. **ML: Shadow → Enforce** (ฝั่ง Hub) — เริ่ม `ML_SHADOW_MODE=true` (log `would_*`
   ไม่บล็อก) เก็บสถิติ 1-2 สัปดาห์ → ค่อยตั้ง `false` เพื่อ enforce จริง (ดู DEPLOYMENT.md §5)
4. ตรวจ checklist §19 ครบ → เปิดให้ผู้ใช้จริง

---

## หมายเหตุสำคัญ

- **ไม่ใช่ SSO** — login Hub ไม่ carry เข้า subsystem อัตโนมัติ; แต่ละระบบมี session แยก
  (Hub เอื้อมไปลบ session subsystem ไม่ได้ → ต้องใช้ webhook §15)
- **แต่ละระบบย่อยคือ OAuth client อิสระ** — production ทีมต่างกัน host คนละที่ได้
  (Coolify คนละ instance) ขอแค่ `HUB_*_URL` ชี้มา Central IAM เดียวกัน
- **redirect_uri / callback / domain ต้องตรงกัน 3 ที่:** DNS (§5) = `.env` (§3) =
  ที่ register กับ Hub (§6) — ไม่ตรง = OAuth ปฏิเสธ
- ดูข้อจำกัด/บั๊กที่เคยเจอใน [`docs/subsystem-integration-constraints.md`](../subsystem-integration-constraints.md)
  และ [`docs/bugs-encountered.md`](../bugs-encountered.md)
