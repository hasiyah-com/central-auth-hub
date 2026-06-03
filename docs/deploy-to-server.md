# Deploy Central Auth Hub — มี server ของมหาวิทยาลัยให้

## Context

โปรเจคจบ Central Auth Hub ปัจจุบันรันบน `localhost` เท่านั้น (Hub :8000, Frontend :3000, Dorm :8001, Library :8002, ML :9000) ทำให้ทดสอบจากเครื่อง dev ได้เครื่องเดียว — อาจารย์/เพื่อนเข้าไม่ได้ มือถือทดสอบไม่ได้ Google OAuth ไม่ยอม IP

มี **server ของมหาวิทยาลัย** ให้ใช้ แต่ยังไม่รู้รายละเอียด (OS, network, domain) → ต้องคุยกับ IT ก่อน แล้วเลือก deploy mode ที่เหมาะ

ปลายทาง: ระบบทั้งหมดเข้าถึงได้ผ่าน URL HTTPS จากที่ไหนก็ได้ที่อาจารย์/grading committee ใช้

---

## STEP 0 — ถาม IT มหาวิทยาลัยก่อน (ต้องตอบให้ครบ 8 ข้อ)

ก่อนทำอะไร ส่งคำถาม 8 ข้อนี้ให้ IT ของมหาวิทยาลัย (อีเมล/Line):

### Checklist ถาม IT

| # | คำถาม | ทำไมต้องรู้ |
|---|-------|------------|
| 1 | **Server เป็น OS อะไร?** (Ubuntu/Debian/CentOS/Windows Server/อื่น ๆ) | Docker install steps ต่างกัน |
| 2 | **มี Docker ติดตั้งแล้วไหม?** ถ้าไม่ ติดตั้งเองได้หรือต้องขอ IT? | กำหนด deploy method |
| 3 | **Public IP หรือ Private IP?** ถ้า private → ต้องใช้ VPN ของมหาวิทยาลัยไหม? | กำหนดว่าใช้ tunnel หรือ direct |
| 4 | **มี domain/subdomain ให้ใช้ไหม?** เช่น `<ชื่อโปรเจค>.ac.th` หรือต้องซื้อเอง? | จำเป็นสำหรับ HTTPS + Google OAuth |
| 5 | **Firewall เปิด port ไหนได้บ้าง?** ปกติต้องได้ 80, 443 (HTTPS), 22 (SSH) | ต้องเปิดอย่างน้อย 80+443 |
| 6 | **SSH access?** username/key หรือ password? | สำหรับ deploy/manage |
| 7 | **RAM/Disk ขนาดเท่าไร?** | Docker stack กิน RAM ~2GB, Disk ~10GB เริ่มต้น |
| 8 | **ระบบ backup?** หรือต้องทำเอง? | สำคัญถ้ามีข้อมูล user จริง |

### Scenarios ที่เจอบ่อยในมหาวิทยาลัยไทย

| Scenario | ลักษณะ | Deploy mode |
|----------|--------|-------------|
| **S1. VM + public IP + subdomain `.ac.th`** | ดีที่สุด — IT จัด domain ให้ | **Mode C (Caddy direct)** |
| **S2. VM + public IP แต่ไม่มี domain** | มี IP แต่ต้อง improvise domain | **Mode C + sslip.io** (wildcard DNS ฟรี) |
| **S3. VM + private IP + VPN** | ต้องเปิด VPN ก่อน | **Mode C + VPN** (อาจารย์/ผู้ทดสอบต้องเปิด VPN ด้วย) |
| **S4. VM + private IP + ไม่มี VPN เปิดให้ outside** | เข้าจาก outside ไม่ได้เลย | **Mode B (Cloudflare Tunnel)** บน server ทะลุ NAT |
| **S5. ยังไม่ได้ provision / ช้ามาก** | ใช้ไม่ทันส่ง | **Mode A (Quick Tunnel)** จากเครื่อง dev เป็น fallback |

---

## Architecture overview

| Mode | สถานการณ์ | URL ที่ได้ | TLS | URL คงที่ | ค่าใช้จ่าย |
|------|-----------|-----------|-----|---------|----------|
| **A. Quick Tunnel** | Demo สั้น / dev เครื่องตัวเอง | `<random>.trycloudflare.com` | ✅ auto | ❌ | ฟรี |
| **B. Named Tunnel** | server มี NAT/firewall ปิด | `hub.<your-cf-domain>` | ✅ auto | ✅ | ฟรี (CF account) |
| **C. Direct + Caddy** | server มี public IP + port 80/443 | `hub.<domain>` | ✅ Let's Encrypt | ✅ | ฟรี (ถ้ามี domain มหาวิทยาลัย) |

ทั้ง 3 mode share **code base + docker-compose เดียวกัน** — ต่างแค่ overlay file + env

---

## Code changes (apply ครั้งเดียว ใช้ได้ทุก mode)

### 1. Hub backend CORS เป็น env-driven

**ไฟล์**: `hub/backend/app/config.py` + `hub/backend/app/main.py` (line 53-60)

```python
# config.py — เพิ่ม
cors_allow_origins: str = "http://localhost:3000"

# main.py — เปลี่ยน hardcoded list
allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
```

### 2. uvicorn ยอมรับ proxy headers

**ทุก uvicorn service** ใน `docker-compose.yml` (hub-backend, subsystem-dorm, subsystem-library):
```yaml
command: >
  uvicorn app.main:app
  --host 0.0.0.0 --port 8000 --reload
  --proxy-headers --forwarded-allow-ips="*"
```
→ FastAPI จะอ่าน `X-Forwarded-Proto` (https/http) + `X-Forwarded-For` (real IP) ถูกต้องเมื่อมี proxy ข้างหน้า

### 3. Frontend env-driven

`docker-compose.yml` service `hub-frontend`:
```yaml
environment:
  NEXT_PUBLIC_HUB_URL: ${NEXT_PUBLIC_HUB_URL:-http://localhost:8000}
  HUB_INTERNAL_URL: http://hub-backend:8000
  NODE_ENV: ${NODE_ENV:-development}
```

### 4. Subsystem URLs (มี pattern แล้ว — แค่เปลี่ยนค่า)

`hub/subsystem-dorm/.env`, `hub/subsystem-library/.env`:
- `HUB_INTERNAL_URL=http://hub-backend:8000` (คงเดิม)
- `HUB_PUBLIC_URL=https://hub.<domain>` (← ค่าจริง)
- `DORM_CALLBACK_URL=https://dorm.<domain>/oauth/callback`
- `SESSION_COOKIE_SECURE=true` (เมื่อ HTTPS)

### 5. Production hardening (เมื่อ deploy จริง)

`.env`:
```
APP_ENV=production
SECRET_KEY=<openssl rand -hex 32>
SECRET_ENCRYPTION_KEY=<openssl rand -hex 32>
ENABLE_DOCS=false
ML_SHADOW_MODE=false
CORS_ALLOW_ORIGINS=https://admin.<domain>,https://dorm.<domain>,https://library.<domain>
```

→ `config.validate_production()` fail-fast ถ้า SECRET ยัง default — กันเซ้นด์อย่างไม่ปลอดภัย

---

## Deploy paths — 3 modes

### Mode A — Quick Tunnel (fallback ถ้า server ยังไม่พร้อม)

รันบน **เครื่อง dev ตัวเอง** ทันที — ไม่ต้องรอ IT

**ไฟล์ใหม่**: `docker-compose.tunnel.yml`
```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: hub-tunnel
    command: tunnel --no-autoupdate --url http://hub-backend:8000
    depends_on: [hub-backend]
    restart: unless-stopped
```

**ไฟล์ใหม่**: `scripts/expose/quick-tunnel.sh`
- รัน docker compose + overlay
- `docker logs hub-tunnel` ดึง URL `https://*.trycloudflare.com`
- echo URL + คำสั่ง Google Console

**ขั้นตอน**:
1. `bash scripts/expose/quick-tunnel.sh`
2. copy URL → Google Console เพิ่ม `<URL>/auth/google/callback`
3. แก้ `.env` (4 ค่า: GOOGLE_REDIRECT_URI, OAUTH_CALLBACK_URI, HUB_BASE_URL, ADMIN_FRONTEND_URL ใช้ URL ของ frontend tunnel)
4. `docker compose restart hub-backend`

### Mode B — Named Tunnel (server มี NAT/firewall ปิด)

ติดตั้ง cloudflared **บน server** แทน เปิด tunnel จาก server ออกมา CF — ไม่ต้องเปิด port 80/443 บน server เลย

**Prereq** (one-time, ทำบน laptop):
1. สมัคร Cloudflare (ฟรี)
2. มี domain ใน CF (หรือใช้ workers.dev subdomain ฟรี)
3. `cloudflared tunnel login` (browser auth)
4. `cloudflared tunnel create central-auth-hub` → ได้ tunnel UUID + creds JSON

**ไฟล์ใหม่**: `cloudflared/config.yml`
```yaml
tunnel: <UUID>
credentials-file: /etc/cloudflared/<UUID>.json
ingress:
  - hostname: hub.<your-domain>
    service: http://hub-backend:8000
  - hostname: admin.<your-domain>
    service: http://hub-frontend:3000
  - hostname: dorm.<your-domain>
    service: http://subsystem-dorm:8000
  - hostname: library.<your-domain>
    service: http://subsystem-library:8000
  - service: http_status:404
```

**DNS** (รันบน laptop):
```bash
cloudflared tunnel route dns central-auth-hub hub.<your-domain>
# ... ทุก hostname
```

**Deploy ขึ้น server**:
```bash
rsync -avz ./central-auth-starter/ user@server:/srv/auth-hub/
ssh user@server "cd /srv/auth-hub && docker compose -f docker-compose.yml -f docker-compose.tunnel.yml up -d --build"
```

### Mode C — Direct Caddy (server มี public IP + open ports 80/443)

Best for: server มี subdomain `.ac.th` ของมหาวิทยาลัย

**ไฟล์ใหม่**: `Caddyfile`
```
hub.<domain> {
    reverse_proxy hub-backend:8000
    encode gzip
}
admin.<domain> {
    reverse_proxy hub-frontend:3000
    encode gzip
}
dorm.<domain> {
    reverse_proxy subsystem-dorm:8000
}
library.<domain> {
    reverse_proxy subsystem-library:8000
}
```

**ไฟล์ใหม่**: `docker-compose.caddy.yml`
```yaml
services:
  caddy:
    image: caddy:2-alpine
    container_name: hub-caddy
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    depends_on: [hub-backend, hub-frontend, subsystem-dorm, subsystem-library]
    restart: unless-stopped
volumes:
  caddy_data:
  caddy_config:
```

**ถ้าไม่มี domain เลย → ใช้ sslip.io** (fallback):
```
hub.<server-ip>.sslip.io {
    reverse_proxy hub-backend:8000
}
```
→ `hub.192-168-1-50.sslip.io` resolve เป็น 192.168.1.50 อัตโนมัติ + Caddy ขอ cert ได้ปกติ

**Deploy steps**:
```bash
# (1) ติดตั้ง Docker บน server (Ubuntu)
ssh user@server
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# (2) Upload code
exit
rsync -avz --exclude='.env' --exclude='node_modules' --exclude='.next' \
  ./central-auth-starter/ user@server:/srv/auth-hub/

# (3) สร้าง .env บน server (จาก .env.example + ค่าจริง)
ssh user@server "cd /srv/auth-hub && cp .env.example .env && nano .env"
# แก้ค่า APP_ENV, SECRET_KEY, GOOGLE_*, HUB_BASE_URL ฯลฯ ตาม checklist ด้านบน

# (4) DNS — ชี้ A record ของทุก subdomain → server public IP
#     ทำผ่าน DNS provider ของมหาวิทยาลัย หรือ DNS panel ที่ IT ให้

# (5) Start
ssh user@server "cd /srv/auth-hub && docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d --build"

# (6) รอ Caddy obtain cert (~30 วินาที — ครั้งแรกอาจช้า)
ssh user@server "docker logs hub-caddy --follow"

# (7) Seed users + JWT keys (เหมือน dev)
ssh user@server "cd /srv/auth-hub && docker compose exec hub-backend python -m scripts.generate_jwt_keys"
ssh user@server "cd /srv/auth-hub && docker compose exec hub-backend python -m app.seeds.seed_users"
```

---

## Critical files — modify / create

**Code changes (universal — apply ทั้ง 3 mode)**:
- `hub/backend/app/config.py` — เพิ่ม `cors_allow_origins`
- `hub/backend/app/main.py` — CORS อ่านจาก settings
- `docker-compose.yml` — เพิ่ม `--proxy-headers` ทุก uvicorn + `${NEXT_PUBLIC_HUB_URL:-...}` ใน hub-frontend
- `.env.example` — เพิ่ม doc `CORS_ALLOW_ORIGINS`, `NEXT_PUBLIC_HUB_URL`

**Mode-specific overlays**:
- `docker-compose.tunnel.yml` (Mode A + B)
- `docker-compose.caddy.yml` (Mode C)
- `cloudflared/config.yml` (Mode B)
- `Caddyfile` (Mode C)

**Scripts**:
- `scripts/expose/quick-tunnel.sh` (Mode A helper)
- `scripts/expose/deploy-vps.sh` (Mode C automation: rsync + ssh + docker up)
- `scripts/expose/README.md` (3 modes guide)

**Gitignore (อย่าลืม)**:
- `cloudflared/*.json` — credentials
- `Caddyfile.local` — local overrides ถ้าใช้

---

## Security checklist ก่อน deploy production

1. **Rotate secrets** — ถ้า `.env` ใน git history มี `GOOGLE_CLIENT_SECRET` ให้ regen ใหม่ที่ Google Console
2. **`APP_ENV=production`** + `ENABLE_DOCS=false` (ปิด Swagger)
3. **`SECRET_KEY` + `SECRET_ENCRYPTION_KEY`** สุ่มใหม่: `openssl rand -hex 32`
4. **`CORS_ALLOW_ORIGINS`** ตัด `localhost` ออก
5. **`SESSION_COOKIE_SECURE=true`** ใน subsystems
6. **JWT key** — `hub/backend/keys/jwt_private.pem` ห้าม commit / leak (ตรวจ `.gitignore`)
7. **Postgres password** — ไม่ใช้ `devpassword` ใน production
8. **Firewall** — เปิดเฉพาะ 80, 443, 22 (SSH); ปิด 5432, 6379, 8000-8002, 9000, 3000 จาก outside
9. **Backup** — `pg_dump` cron + เก็บ off-server

---

## Verification (end-to-end ทุก mode)

```bash
# (1) Health checks
curl https://hub.<domain>/health                      # → 200
curl https://hub.<domain>/.well-known/jwks.json       # → JSON keys
curl -I https://admin.<domain>                         # → HTTP/2 200

# (2) OAuth flow
# เปิด https://admin.<domain> จาก browser อาจารย์/มือถือ
# → กดล็อกอิน → Google → กลับมาที่ /dashboard
# → เห็น KPI cards (Identities/Subsystems/Login Forensics)

# (3) Subsystem flow
# เปิด https://dorm.<domain> → /login → กดล็อกอินผ่าน Hub
# → เห็น dashboard หอพัก (เป็น role student/staff)

# (4) Audit log — ตรวจว่า IP จริงถูกบันทึก (ไม่ใช่ Docker 172.x)
docker compose exec hub-backend python -c "
from app.database import SessionLocal
from app.models import AuditLog
db = SessionLocal()
for r in db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(5):
    print(r.action, r.ip, r.created_at)
"
# → IP ต้องเป็น public IP ของ test device ไม่ใช่ 172.18.x.x
```

---

## Recommendation — แนะนำลำดับงาน

**ทำตามนี้:**

1. **STEP 0** — ส่ง 8 คำถามให้ IT มหาวิทยาลัย (โดยเฉพาะข้อ 3 = public/private IP + ข้อ 4 = domain)
2. **ระหว่างรอ IT ตอบ** — implement "Code changes (universal)" + Mode A overlay
3. **ทดสอบ Mode A** บนเครื่อง dev ทันที — ยืนยันว่า OAuth ผ่าน + อาจารย์เข้าได้จากมือถือ
4. **เมื่อ IT ตอบ** → ดู scenario table แล้วเลือก mode:
   - S1/S2 → Mode C
   - S3/S4 → Mode B
   - S5 → คง Mode A ไว้ก่อน
5. **Deploy + production hardening** ตาม security checklist
6. **เพิ่ม redirect URI ใน Google Console** ของ URL ใหม่ + ลบ URL ของ Mode A
7. **End-to-end test** ตาม Verification section
