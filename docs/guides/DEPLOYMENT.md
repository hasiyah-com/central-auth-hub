# Production Deployment Runbook — Central Auth Hub

Deploy ระบบจริงขึ้น Internet อย่างปลอดภัย: **VM เดียว + Let's Encrypt + nginx + 4 subdomains**
(อ้างอิง plan: `C:\Users\hasiy\.claude\plans\mellow-wobbling-fiddle.md`)

> งานนี้เป็น **config/infra ล้วน — ไม่แตะ logic แอป**. แอปรองรับ production ผ่าน env อยู่แล้ว
> (`config.validate_production()`, `--proxy-headers`, security headers, ENABLE_DOCS).

---

## 1. Topology

| Subdomain | → service (internal) | บทบาท |
|---|---|---|
| `admin.<domain>` | hub-frontend:3000 | Next.js console (UI ผู้ดูแล) |
| `auth.<domain>`  | hub-backend:8000  | OAuth, Passkey API, JWKS, OIDC, Hub-served HTML |
| `dorm.<domain>`  | subsystem-dorm:8000 | ระบบหอพัก |
| `library.<domain>` | subsystem-library:8000 | ระบบห้องสมุด |

เปิด public แค่ **nginx 80/443**. ทุก service อื่น (backend, frontend, ml, postgres×3, redis)
อยู่ใน network `cah-net` เท่านั้น — prod compose ไม่ publish port ใด ๆ

> **ทำไม `admin.` แยกจาก `auth.`:** console กับ backend ใช้ route ชนกัน (`/auth/*`, `/developer/subsystems`)
> บน subdomain เดียว split ด้วย path ไม่ได้ → แยก subdomain. ผลพลอยได้: passkey ใช้ `rp_id = apex domain`
> ครอบทั้ง admin. (หน้า register) และ auth. (ceremony)

ไฟล์ที่เกี่ยวข้อง: `docker-compose.prod.yml`, `docker-compose.dorm.prod.yml`,
`docker-compose.library.prod.yml`, `deploy/nginx/`, `deploy/init-letsencrypt.sh`, `deploy/up.sh`,
`prod.env.template` (×3), `hub/frontend/Dockerfile.prod`

---

## 2. Prerequisites

- VM Linux (Ubuntu 22.04+), public IP, **80 + 443 เปิด** (firewall/security group)
- Docker + Docker Compose plugin
- โดเมนจริง + **DNS A record** 4 ตัวชี้มาที่ VM:
  `admin` · `auth` · `dorm` · `library` → `<public-ip>`
- ไฟล์ GeoIP `GeoLite2-Country.mmdb` (ฟรีจาก MaxMind) — วางที่ `hub/backend/data/`
- เพิ่ม redirect URI ใน Google Console — ดู §6

---

## 3. ขั้นตอน Deploy (ครั้งแรก)

```bash
# 3.1 clone
git clone <repo> && cd central-auth-starter

# 3.2 เตรียม env (กรอก secret จริง — ดูคำสั่ง generate ใน comment ของแต่ละไฟล์)
cp prod.env.template .env.prod
cp hub/subsystem-dorm/prod.env.template    hub/subsystem-dorm/.env.prod
cp hub/subsystem-library/prod.env.template hub/subsystem-library/.env.prod
#   แก้ DOMAIN, SECRET_KEY, SECRET_ENCRYPTION_KEY, POSTGRES_PASSWORD,
#   GOOGLE_*, WEBHOOK_SHARED_KEY (ให้ตรงกันทั้ง Hub + subsystem) ฯลฯ

# 3.3 วาง GeoIP DB
#   คัดลอกไฟล์ GeoLite2-Country.mmdb → hub/backend/data/

# 3.4 ออก TLS cert (สร้าง network + dummy cert + start nginx + ขอ cert จริง)
#   ทดสอบก่อนด้วย staging กัน rate limit:  STAGING=1 bash deploy/init-letsencrypt.sh
bash deploy/init-letsencrypt.sh

# 3.5 generate JWT keys ลง volume (ต้องมีก่อน backend start — ไม่งั้น fail-fast)
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm hub-backend python -m scripts.generate_jwt_keys

# 3.6 start Hub stack
bash deploy/up.sh hub

# 3.7 seed users + train ML (ครั้งเดียว)
docker compose --env-file .env.prod -f docker-compose.prod.yml exec hub-backend python -m app.seeds.seed_users
docker compose --env-file .env.prod -f docker-compose.prod.yml exec ml-service python -m scripts.generate_data
docker compose --env-file .env.prod -f docker-compose.prod.yml exec ml-service python -m scripts.train_model

# 3.8 ลงทะเบียน subsystem ผ่าน console (admin.<domain>) → ได้ client_id + secret
#     กรอกลง hub/subsystem-dorm/.env.prod และ hub/subsystem-library/.env.prod
#     (redirect_uri ที่ register = https://dorm.<domain>/oauth/callback ฯลฯ)

# 3.9 start subsystem
bash deploy/up.sh dorm
bash deploy/up.sh library

# 3.10 seed ข้อมูล subsystem (ครั้งเดียว)
docker compose --env-file hub/subsystem-dorm/.env.prod -f docker-compose.dorm.prod.yml exec subsystem-dorm python -m scripts.seed_rooms
docker compose --env-file hub/subsystem-library/.env.prod -f docker-compose.library.prod.yml exec subsystem-library python -m scripts.seed_books
```

---

## 4. OAuth provider config (นอก codebase)

- **Google Console** → Authorized redirect URIs เพิ่ม:
  - `https://auth.<domain>/auth/google/callback`
  - `https://auth.<domain>/oauth/callback`
  - ย้าย OAuth app: Testing → **Production** (หรือเพิ่ม test users)

> ใช้แค่ Google + Passkey — ไม่ตั้งค่า LINE (โค้ดยังอยู่ในระบบแต่ไม่ใช้)

---

## 5. ML: Shadow → Enforce (2 เฟส ตามที่ตกลง)

- **เฟส 1 (deploy แรก):** `ML_SHADOW_MODE=true` — ML ให้คะแนน + log แต่ **ไม่บล็อก**
  (decision = `would_mfa`/`would_block`). มอนิเตอร์บน dashboard + alert ว่า would_* ไปโดน user ปกติแค่ไหน
- **เฟส 2:** เมื่อ false-positive ต่ำพอ → แก้ `ML_SHADOW_MODE=false` ใน `.env.prod` แล้ว
  **recreate** (ไม่ใช่ restart — B36):
  ```bash
  docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate hub-backend
  ```
  คง `RISK_BLOCK_HARD_THRESHOLD=0.85` (สูง กัน hard-block พลาด)

---

## 6. Verification (หลัง deploy)

```bash
curl -I https://auth.<domain>/health         # 200 + TLS valid
curl -I https://auth.<domain>/docs           # 404 (ENABLE_DOCS=false)
```
ตรวจด้วยมือ:
1. login Google ที่ console (`admin.<domain>`) → เข้า dashboard ได้
2. **Passkey:** register ที่ `admin.<domain>/account/security` → logout → login passkey สำเร็จ (rp_id=apex ถูก)
3. Subsystem: เข้า `dorm.<domain>` → redirect chooser (auth.) → login → กลับ dorm มี session
4. ML session detail: `geo_country` ขึ้นจาก **IP จริง** (ไม่ใช่ 172.x) → X-Forwarded-For ทำงาน
5. logout → token เดิมใช้ไม่ได้ (revocation)
6. postgres/redis/ml ไม่ตอบจาก public IP (เปิดแค่ 443)

---

## 7. Maintenance

| งาน | คำสั่ง |
|---|---|
| Logs | `docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f hub-backend` |
| Backup DB | `bash scripts/backup.sh` (pg_dump 3 DB) — ตั้ง cron + offsite |
| Cert renew | อัตโนมัติ (certbot container renew 12 ชม. + nginx reload 6 ชม.) |
| แก้ env แล้ว apply | `... up -d --force-recreate <service>` **ห้าม `restart`** (B36) |
| Redeploy โค้ดใหม่ | `git pull` → `bash deploy/up.sh hub` (build ใหม่) |

**ห้าม regenerate JWT keys** ตอน redeploy — `hub_jwt_keys` volume persist ไว้ (regenerate = token ทุกใบใช้ไม่ได้)

---

## 8. Troubleshooting

- **nginx start ไม่ขึ้น (no cert):** ยังไม่รัน `init-letsencrypt.sh` หรือ DNS ยังไม่ propagate
- **backend fail-fast "ไม่พบ JWT key":** ข้ามขั้น 3.5 → รัน generate_jwt_keys เข้า volume ก่อน
- **passkey ใช้ไม่ได้:** `WEBAUTHN_RP_ID` ต้อง = apex domain, `WEBAUTHN_ORIGINS` ต้องมีทั้ง admin. + auth. (https)
- **subsystem verify JWT ไม่ผ่าน:** `HUB_ISSUER` ใน subsystem ต้องตรงกับ Hub เป๊ะ
- **ML score 0 ตลอด:** ยังไม่ train (ขั้น 3.7) — ml_client fail-safe เป็น pass จึงไม่ crash แต่ไม่ detect

---

## 9. ข้อจำกัด

- **ไม่มี Alembic** — schema สร้างด้วย `create_all` ตอน start (เหมาะ deploy ใหม่); schema change ภายหลังต้องระวัง
- **single VM = single point of failure** — รับได้สำหรับ demo/senior project; prod จริงค่อยแยก subsystem เป็นคนละเครื่อง + HA
- **Redis ไม่มี auth** — ปลอดภัยเพราะไม่ expose ออก public (internal cah-net เท่านั้น)
