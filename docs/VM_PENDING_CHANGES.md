# VM Pending Changes — รอ apply ขึ้น VM ครั้งเดียวตอนจบ

บันทึกทุกครั้งที่เพิ่ม/แก้ไขสำเร็จบน local — เพื่อ apply ขึ้น VM รวดเดียวตอนพัฒนาเสร็จ
ไม่ต้องไล่ทำทีละอย่างระหว่างทาง

**หลักการ:**
- **Code** = มากับ `git pull` อัตโนมัติ → เขียนแค่ชื่อสั้นๆ พอ (รายละเอียดอยู่ใน git)
- **Manual steps** (env / migration / data / firewall) = `git pull` ทำให้ไม่ได้ → เขียนคำสั่งเต็ม
- แก้เรื่องเดิมซ้ำ → **อัปเดตบรรทัดเดิม** ไม่เพิ่มใหม่

> ⚠️ **ก่อน `git pull` บน VM ได้ผล — ต้อง push commit ที่ยังค้างอยู่ local ขึ้น origin ก่อน**
> (ดู `git log origin/main..HEAD` เช็คว่ามี commit ค้าง push อยู่ไหม)

---

## 1. Env (`.env.prod`) — ต้องแก้มือ + force-recreate

| ตัวแปร | ค่า | เหตุผล |
|---|---|---|
| `PASSKEY_REQUIRED_AFTER_DAYS` | `7` | เปิด nudge เตือนตั้ง passkey หลังใช้งาน 7 วัน |

**คำสั่ง apply (บน VM):**
```bash
cd ~/central-auth-hub
grep -q '^PASSKEY_REQUIRED_AFTER_DAYS=' .env.prod \
  && sed -i 's/^PASSKEY_REQUIRED_AFTER_DAYS=.*/PASSKEY_REQUIRED_AFTER_DAYS=7/' .env.prod \
  || echo 'PASSKEY_REQUIRED_AFTER_DAYS=7' >> .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate hub-backend
```

---

## 2. Database migration (Alembic)

ทุกครั้งที่ pull โค้ดที่แก้ `models.py` → รัน migration:
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec hub-backend alembic upgrade head
```

**Pending migrations รอ apply:**
- `5e31bcaf0cf4` add refresh_id to login_sessions (refresh token feature)

_(ยังไม่มี migration ใหม่เพิ่มจาก session ล่าสุด — graduated/resigned status + deny-list ใช้ column/type เดิม)_

---

## 3. Code (มากับ git pull — build ใหม่)

| commit | build service ไหน |
|---|---|
| `6cf07d2` feat(passkey): dev จัดการ passkey ตัวเองได้ + nudge banner 7 วัน | hub-backend + hub-frontend |
| `18fff8f` feat(hub): refresh token + re-validate risk ทุกครั้งที่ renew — **แก้บั๊ก logout ค้าง "ออนไลน์"** (ปุ่ม logout เดิมไม่เคยเรียก `/auth/logout` เลย แค่ลบ cookie ฝั่ง client) | hub-backend + hub-frontend |
| `7e61080` fix(frontend): admin passkey step-up prompts เป็น inline popup ทั้งหมด | hub-frontend |
| `7e19247` fix(oauth): เช็คสิทธิ์เข้าระบบย่อยก่อนโชว์หน้าตั้ง passkey (เดิมเช็ค passkey ก่อน — เสียเวลาตั้งก่อนมาเจอ "ไม่มีสิทธิ์") | hub-backend |
| `1a3c60e` feat(admin): User 360-degree detail view (access list + revoke + login history) | hub-backend + hub-frontend |
| `b708f2a` feat(admin): incident triage view with attack path + one-click remediation | hub-backend + hub-frontend |
| `2273992` feat(users): graduated/resigned lifecycle statuses with cascade revoke | hub-backend + hub-frontend |
| `75842c6` feat(frontend): User 360-degree view — full page + audit scope filter | hub-frontend |
| `4ff64d4` feat(subsystem-grade): add Subsystem C — ระบบเกรด (Roster Sync + API key demo) | **ต้อง setup ใหม่ทั้งสาย — ดู §4.1** |
| `3b6fde6` feat(admin): revoke user access under any policy via deny-list + status + time fix | hub-backend + hub-frontend |
| `4ac3050` docs: update subsystem integration guide | (docs เท่านั้น — ไม่ต้อง rebuild) |
| `7f8caaf` feat(dashboard): SOC security-monitor dashboard + amCharts globe — เพิ่ม npm dep ใหม่ (`@amcharts/amcharts5`, `@amcharts/amcharts5-geodata`) + **fix falsy-zero KPI bug** | hub-frontend (**ต้อง `--build` ไม่ใช่แค่ restart — npm dep ใหม่**) |
| `19a78ae` docs: admin UI guide, thesis diagrams, TOR + reports | (docs เท่านั้น — ไม่ต้อง rebuild) |
| `7c4fcb1` / `03a79a5` test(ml): 4-layer RBA benchmark reports + eval scripts | (scripts/reports เท่านั้น — ไม่ต้อง rebuild) |

**คำสั่ง apply (บน VM):**
```bash
cd ~/central-auth-hub
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build hub-backend hub-frontend
```

---

## 4. One-off / Data / Firewall

### 4.1 Subsystem C (ระบบเกรด) — deploy ครั้งแรกทั้งสาย (ยังไม่เคยขึ้น VM)

Subsystem C เป็น service ใหม่ที่ยังไม่เคย deploy — ต้องทำครบทุกขั้นก่อนใช้งานได้จริง
(ไฟล์ infra สร้างไว้แล้วใน commit ล่าสุด: `docker-compose.grade.prod.yml`,
`hub/subsystem-grade/prod.env.template`, `deploy/nginx/templates/grade.conf.template`,
`deploy/up.sh` มี `up_grade()`, `deploy/init-letsencrypt.sh` มี `grade.$DOMAIN` แล้ว)

**ก) DNS** — เพิ่ม A record ตัวที่ 5 ชี้มาที่ VM (นอกเหนือ admin/auth/dorm/library เดิม):
```
grade.<domain>  →  <public-ip>
```
ตรวจ propagate: `nslookup grade.<domain>`

**ข) Hub `.env.prod` — เพิ่ม grade เข้า CORS allowlist:**
```bash
cd ~/central-auth-hub
DOMAIN="$(grep -E '^DOMAIN=' .env.prod | cut -d= -f2-)"
sed -i "s|^CORS_ALLOW_ORIGINS=.*|CORS_ALLOW_ORIGINS=https://admin.$DOMAIN,https://dorm.$DOMAIN,https://library.$DOMAIN,https://grade.$DOMAIN|" .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate hub-backend
```

**ค) TLS cert** — ออก cert เฉพาะ subdomain ใหม่ (ห้ามรัน `init-letsencrypt.sh` ทั้งไฟล์ซ้ำ
เพราะจะไป re-issue cert ของ admin/auth/dorm/library เดิมด้วย เสี่ยงโดน Let's Encrypt rate limit):
```bash
cd ~/central-auth-hub
DOMAIN="$(grep -E '^DOMAIN=' .env.prod | cut -d= -f2-)"
COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"

# dummy cert ก่อน (ให้ nginx โหลด template ใหม่ได้โดยไม่ error หา cert ไม่เจอ)
$COMPOSE run --rm --entrypoint "/bin/sh -c '\
  mkdir -p /etc/letsencrypt/live/grade.$DOMAIN && \
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout /etc/letsencrypt/live/grade.$DOMAIN/privkey.pem \
    -out /etc/letsencrypt/live/grade.$DOMAIN/fullchain.pem \
    -subj \"/CN=grade.$DOMAIN\"'" certbot

# recreate nginx (ไม่ใช่ reload) — ให้ entrypoint รัน envsubst จับ template ใหม่ (grade.conf.template)
$COMPOSE up -d --force-recreate nginx
sleep 5

# ขอ cert จริง (webroot — ต้อง DNS propagate แล้ว)
$COMPOSE run --rm --entrypoint "/bin/sh -c '\
  rm -rf /etc/letsencrypt/live/grade.$DOMAIN /etc/letsencrypt/archive/grade.$DOMAIN /etc/letsencrypt/renewal/grade.$DOMAIN.conf'" certbot || true
$COMPOSE run --rm certbot certonly --webroot -w /var/www/certbot \
  --agree-tos --no-eff-email -d "grade.$DOMAIN"

$COMPOSE exec nginx nginx -s reload
```

**ง) Env file:**
```bash
cd ~/central-auth-hub
cp hub/subsystem-grade/prod.env.template hub/subsystem-grade/.env.prod
nano hub/subsystem-grade/.env.prod
# ตั้ง: SESSION_SECRET_KEY (openssl rand -hex 32), HUB_PUBLIC_URL, GRADE_PUBLIC_URL,
#      GRADE_CALLBACK_URL, HUB_ISSUER (ทั้งหมดใช้ domain จริง), HUB_WEBHOOK_SHARED_KEY
#      (ต้องตรงกับ WEBHOOK_SHARED_KEY ใน .env.prod ของ Hub)
```

**จ) ลงทะเบียน subsystem กับ Hub** (ผ่าน script — ไม่ใช่ console เพราะต้องออก Roster API key ด้วย):
```bash
GRADE_REDIRECT_URI=https://grade.<domain>/oauth/callback \
  docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec hub-backend python -m scripts.register_grade_subsystem
```
copy `GRADE_CLIENT_ID` / `GRADE_CLIENT_SECRET` / `GRADE_ROSTER_API_KEY` ที่ print ออกมา
ไปใส่ใน `hub/subsystem-grade/.env.prod` (ค่าที่เว้นว่างไว้ในขั้น ง)

**ฉ) Start:**
```bash
bash deploy/up.sh grade
```

**ช) Sync roster ครั้งแรก** — login ที่ `https://grade.<domain>` ด้วยบัญชี teacher/staff
→ หน้า `/manage` → กด "Sync ตอนนี้" (pre-create ตารางเกรดของนักศึกษาทั้งหมด)

**ซ) Verify:**
```bash
curl -kI https://grade.<domain>/health   # 200
```
login ด้วย student → เห็นเกรดตัวเอง / login ด้วย teacher → เห็นหน้า `/teacher` รายชื่อนักศึกษา

### 4.2 อื่นๆ

_(ยังไม่มีเพิ่ม — เช่น seed, ALTER มือ, เปิด port ให้จดที่นี่)_

---

## ลำดับ apply สุดท้าย (รวบทุกอย่าง)

```bash
cd ~/central-auth-hub
git pull                                    # ← code (ต้อง push จาก local ก่อน — ดูคำเตือนบนสุด)

# ── env เดิม (ข้อ 1) ──
# (รันคำสั่ง sed/force-recreate จากข้อ 1)

# ── build Hub + migration ──
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build hub-backend hub-frontend
docker compose --env-file .env.prod -f docker-compose.prod.yml exec hub-backend alembic upgrade head

# ── Subsystem C ใหม่ทั้งสาย (ข้อ 4.1 ก-ซ — DNS ต้อง propagate ก่อนเริ่ม) ──
```
