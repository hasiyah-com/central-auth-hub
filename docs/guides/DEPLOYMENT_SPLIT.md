# Deployment แบบแยกเครื่อง — Hub บน VM, Subsystem บน Local

แผน setup ตั้งแต่ศูนย์: **Hub อยู่บน VM (VMware), Subsystem (หอพัก/ห้องสมุด) เป็น Docker บนเครื่อง local**
เพื่อพิสูจน์ว่า Hub กับ subsystem **แยกกันจริง** (คนละเครื่อง คนละ IP) — ตอบโจทย์ที่อาจารย์ทักว่า
"Docker บนเครื่องเดียวมันก็ IP เดียวกัน เหมือนอยู่ที่เดียวกัน"

> ต่างจาก `DEPLOYMENT.md` (วางทุก stack บน VM เดียว). ไฟล์นี้เน้น topology แยกเครื่อง + เพิ่มขั้น
> provision VM/OS/Docker ที่ runbook เดิมข้ามไป

---

## ภาพรวม

```
┌─ VM บน server (VMware bridged) ──────────────┐      ┌─ เครื่อง local ────────────┐
│  Ubuntu Server                               │      │  Docker (dev compose):     │
│   Nginx 443 → Frontend (admin.<host>)        │◄────►│   subsystem-dorm  :8001    │
│            → Backend  (auth.<host>)          │HTTPS │   subsystem-library :8002  │
│            → PostgreSQL + Redis + ML         │      │   postgres-dorm/library    │
│  Cert (mkcert หรือ Let's Encrypt)            │      │   HUB_BASE_URL=auth.<host>  │
└───────────────────────────────────────────────┘      └────────────────────────────┘
        IP ของ VM                                            IP ของ local
              └──────── คนละ IP คนละเครื่อง ────────┘
```

**ทำไม subsystem อยู่ local ได้:** subsystem เป็น OAuth **client** — แค่ต้อง "ต่อออก" ไป Hub ได้
(token exchange + JWKS = outbound จาก local → ได้เสมอ). ขั้น redirect ใช้ **browser** เป็นตัวพา
(browser อยู่ local เปิด localhost:8001 ได้). → **ขอ subdomain แค่ 2 ตัว** (`admin.` + `auth.`) ไม่ใช่ 4

---

## 2 Tracks — เลือกตามทรัพยากร

| | Track A — Demo ภายใน | Track B — Public จริง |
|---|---|---|
| เครือข่าย | network มหาลัยเดียวกัน | public IP |
| Cert | **mkcert / self-signed** | **Let's Encrypt** |
| Domain | hostname ปลอมใน `/etc/hosts` | domain จริงจาก IT + DNS A record |
| พึ่ง IT | ไม่ต้อง (แค่ต่อ network มหาลัย) | ต้องขอ domain + เปิด port 80/443 |
| เหมาะกับ | สาธิตในห้องสอบ | ใช้งานจริง/เข้าจากนอก |

> ⚠️ **WebAuthn/Passkey ใช้ IP เป็น rp_id ไม่ได้** — ต้องเป็น hostname เสมอ (ทั้ง 2 track)
> Track A จึงต้อง map hostname ใน `/etc/hosts` ไม่ใช่ใช้ IP ดิบ

---

## Phase 0 — เตรียมของ

| ของ | จากไหน | หมายเหตุ |
|---|---|---|
| Ubuntu Server 24.04 LTS (ISO) | ubuntu.com/download/server | OS ของ VM |
| VMware | (มีแล้ว) | Network = **Bridged** |
| GeoLite2-Country.mmdb | maxmind.com (สมัครฟรี) | GeoIP feature ของ ML |
| mkcert (Track A) | github.com/FiloSottile/mkcert | สร้าง local CA |
| Google OAuth | console.cloud.google.com | มีแล้ว — เพิ่ม redirect URI ทีหลัง |

---

## Phase 1 — สร้าง VM + ลง Ubuntu

**สเปก VM (Hub มี ML/SHAP + Next.js build → กิน RAM):**

| | ขั้นต่ำ | แนะนำ |
|---|---|---|
| vCPU | 2 | 4 |
| RAM | 4 GB | **8 GB** (กัน OOM ตอน next build + SHAP) |
| Disk | 25 GB | 40 GB |
| Network | Bridged | **Bridged** (VM ได้ IP จาก network ที่ host ต่ออยู่) |

1. VMware → New VM → ISO Ubuntu Server 24.04 → ตั้งสเปก → Network **Bridged**
2. ลง Ubuntu: เลือก **OpenSSH server** · ตั้ง user/password
3. จด IP: `ip a`
   - host ต่อ **network มหาลัย** → ได้ IP campus (เข้าถึงได้ในรั้ว) ← Track A/B
   - host ต่อ **เน็ตบ้าน** → ได้ IP บ้าน (เฉพาะ LAN บ้าน)

---

## Phase 2 — ติดตั้ง Docker บน VM

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates

# Docker Engine + Compose plugin (official repo)
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker

# firewall
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable

docker --version && docker compose version
```

---

## Phase 3 — Hostname / DNS

### Track A (Demo ภายใน) — /etc/hosts
ที่ **ทุกเครื่องที่ใช้ demo** (เครื่อง local + เครื่องอาจารย์) เพิ่มใน hosts file:
```
<vm-ip>   admin.cah.local  auth.cah.local
```
- Windows: `C:\Windows\System32\drivers\etc\hosts`
- Linux/Mac: `/etc/hosts`

### Track B (Public) — DNS A record
ให้ IT ตั้ง: `admin.<domain>` + `auth.<domain>` → public IP ของ VM
ตรวจ: `nslookup auth.<domain>`

---

## Phase 4 — TLS Cert

### Track A — mkcert (แนะนำ, ไม่มี browser warning)
```bash
# บนเครื่องที่มี mkcert
mkcert -install                                   # สร้าง + ลง local CA
mkcert -cert-file cah.crt -key-file cah.key \
  admin.cah.local auth.cah.local                  # ออก cert
# คัดลอก cah.crt + cah.key ขึ้น VM → deploy/nginx/certs/
# ลง rootCA ที่เครื่อง demo อื่น: คัดลอก "$(mkcert -CAROOT)/rootCA.pem" ไปลง trusted store
```
ชี้ nginx ใช้ `cah.crt` / `cah.key` (แก้ path cert ใน nginx template เป็นไฟล์นี้)

### Track A (ทางเลือก) — self-signed ล้วน
ใช้ dummy cert ที่ `init-letsencrypt.sh` สร้างให้อยู่แล้ว แล้ว **ไม่ต้องรันสเตปขอ cert จริง**
(browser จะ warning — กด proceed; passkey อาจงอแงบางเบราว์เซอร์ → mkcert ดีกว่า)

### Track B — Let's Encrypt
```bash
STAGING=1 bash deploy/init-letsencrypt.sh    # ลองก่อนกัน rate-limit
bash deploy/init-letsencrypt.sh              # ของจริง
```

---

## Phase 5 — Deploy Hub stack บน VM

```bash
git clone https://github.com/hasiyah-com/central-auth-hub.git
cd central-auth-hub
cp prod.env.template .env.prod
nano .env.prod
```

แก้ `.env.prod` (ค่าสำคัญ):
```
DOMAIN=cah.local                 # Track A | <domain จริง> Track B
SECRET_KEY=<openssl rand -hex 32>
SECRET_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
POSTGRES_PASSWORD=<openssl rand -hex 32>
GOOGLE_CLIENT_ID=...  GOOGLE_CLIENT_SECRET=...
WEBHOOK_SHARED_KEY=<openssl rand -hex 32>     # ต้องตรงกับ subsystem
WEBAUTHN_RP_ID=cah.local                       # apex (ห้ามเป็น IP)
WEBAUTHN_ORIGINS=https://admin.cah.local,https://auth.cah.local
ML_SHADOW_MODE=true
```

```bash
# GeoIP
mkdir -p hub/backend/data    # scp GeoLite2-Country.mmdb → ที่นี่

# JWT keys (ก่อน backend start)
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm hub-backend python -m scripts.generate_jwt_keys

# start Hub
bash deploy/up.sh hub

# seed + train (ครั้งเดียว)
docker compose --env-file .env.prod -f docker-compose.prod.yml exec hub-backend python -m app.seeds.seed_users
docker compose --env-file .env.prod -f docker-compose.prod.yml exec ml-service python -m scripts.generate_data
docker compose --env-file .env.prod -f docker-compose.prod.yml exec ml-service python -m scripts.train_model
```
ตรวจ: `curl -kI https://auth.cah.local/health` → 200 (`-k` ข้าม cert check ตอนทดสอบ)

---

## Phase 6 — Google OAuth

เพิ่ม Authorized redirect URIs:
- `https://auth.cah.local/auth/google/callback`
- `https://auth.cah.local/oauth/callback`

> Track A: Google ยอมรับ redirect_uri ที่เป็น hostname `.local` ได้ถ้าเป็น https. ถ้า Google ไม่ยอม
> ออก cert/hostname บางแบบ → ใช้ domain จริงสำหรับ auth. (Track B) เฉพาะส่วน Google OAuth

---

## Phase 7 — Subsystem Docker บน Local

1. ลงทะเบียน subsystem ที่ `https://admin.cah.local` → ได้ `client_id` + `client_secret`
   - redirect_uri ตอน register = `http://localhost:8001/oauth/callback` (dorm), `http://localhost:8002/oauth/callback` (library)
2. แก้ `.env` subsystem local:
   ```
   HUB_BASE_URL=https://auth.cah.local
   HUB_ISSUER=https://auth.cah.local
   DORM_CLIENT_ID=...  DORM_CLIENT_SECRET=...
   HUB_WEBHOOK_SHARED_KEY=<ตรงกับ Hub>
   SESSION_COOKIE_SECURE=false        # local เป็น http
   ```
   > local ต้อง map `auth.cah.local` → VM IP ใน /etc/hosts ด้วย (ขั้น Phase 3)
   > ถ้า cert เป็น self-signed/mkcert ต้อง trust CA ที่เครื่อง local ไม่งั้น token exchange (httpx) จะ verify ไม่ผ่าน
3. start:
   ```bash
   bash scripts/stack/up.sh dorm
   bash scripts/stack/up.sh library
   docker compose -f docker-compose.dorm.yml exec subsystem-dorm python -m scripts.seed_rooms
   docker compose -f docker-compose.library.yml exec subsystem-library python -m scripts.seed_books
   ```

---

## Phase 8 — Verify "แยกจริง"

| ตรวจ | คาดหวัง |
|---|---|
| `https://auth.cah.local/health` | 200 จาก VM |
| login ที่ `localhost:8001` | redirect ไป `auth.cah.local` (คนละ IP) แล้วกลับ |
| ML session detail | `ip` + `geo_country` = IP จริงของ local ไม่ใช่ 172.x |
| postgres/redis บน VM | ต่อจากนอกไม่ได้ (เปิดแค่ 443) |
| `ip a` ทั้ง 2 เครื่อง | IP ต่างกัน — หลักฐานต่อ thesis |

---

## Phase 9 — Maintenance

| งาน | คำสั่ง |
|---|---|
| Backup DB | `bash scripts/backup.sh` + cron |
| แก้ env | `up -d --force-recreate <svc>` (ห้าม `restart` — B36) |
| Redeploy code | `git pull` → `bash deploy/up.sh hub` |
| Cert renew (Track B) | อัตโนมัติ (certbot container) |

⚠️ **ห้าม regenerate JWT keys** ตอน redeploy — volume `hub_jwt_keys` persist (regenerate = token ทุกใบใช้ไม่ได้)

---

## ต้องปรับใน config ก่อน deploy

- `prod.env.template` ตั้ง `dorm.`/`library.` เป็น subdomain (กรณี subsystem บน VM) — แผนนี้ subsystem
  อยู่ local → register redirect_uri เป็น `http://localhost:8001|8002/oauth/callback` แทน
- Track A: แก้ path cert ใน `deploy/nginx/templates/*.conf.template` ให้ชี้ mkcert/self-signed cert
  (แทน path Let's Encrypt) — หรือทำ nginx template variant สำหรับ demo

---

## หมายเหตุข้อจำกัด

- single VM = single point of failure — รับได้สำหรับ demo/senior project
- self-signed/mkcert = ใช้ภายในเท่านั้น (เครื่องนอกที่ไม่ได้ trust CA จะ warning)
- ไม่มี Alembic — schema สร้างด้วย `create_all` ตอน start
