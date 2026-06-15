# Backlog — Traceability & Logging

รายการงานที่ยังไม่ทำ (เก็บไว้ก่อน) เกี่ยวกับการเก็บ log + รู้ต้นทางการเข้าถึง

อัปเดต: 2026-06-14

---

## ✅ ทำไปแล้ว (อ้างอิง)

- **Failure-path audit logging** — whitelist add/remove/role log ทุก attempt (รวม 404/400) + ip + user_agent (commit หลัง 506b405)
- **Rate limit** — whitelist mutations + user CRUD = 30/min → 429
- **Audit page UI** — คอลัมน์ "ต้นทาง (IP · อุปกรณ์)" + detail panel (parse user_agent)
- **Proxy forward IP** — `req.ip` fallback ใน `/api/proxy` route
- **2-layer logging มีอยู่แล้ว** — `request_logs` (ทุก HTTP request: method/path/status/ip/UA/user/duration) + `audit_logs` (business action)

---

## ⏳ BACKLOG #1 — Alert เมื่อ failed mutation ซ้ำเกิน threshold

**โจทย์:** ยิง whitelist add / mutation ที่ fail ซ้ำๆ ควร fire alert (เหมือน failed login + probing)

**แนวทาง:** reuse `security_listener` pattern
- track `whitelist_add_failed` / `*_failed` ต่อ (actor_id, ip) ใน window (เช่น 5 นาที)
- เกิน threshold → fire alert (severity warning/critical) เข้าหน้า API Alerts
- คล้าย `unauthorized_probing` / `high_error_rate` ที่มีอยู่

**ไฟล์ที่เกี่ยว:** `app/hooks/security_listener.py`, `app/services/alert_service.py`

**สถานะ:** ยังไม่ทำ (task #21)

---

## ⏳ BACKLOG #2 — เห็น IP จริงของ client ใน dev (Docker Desktop NAT)

**ปัญหา:** บน Windows Docker Desktop — published-port NAT rewrite source เป็น gateway (172.18.0.1) ตั้งแต่ hop แรก → ทั้ง Next.js + backend เห็น 172.x ไม่ใช่ IP เครื่องจริง

**ยืนยันแล้ว:**
- code ถูกต้อง: backend `get_client_ip` อ่าน XFF → client จริง (พิสูจน์ด้วย XFF=203.0.113.99 → เก็บได้)
- container-to-container เก็บ IP จริง (frontend 172.18.0.6 → backend เห็น 172.18.0.6)
- ปัญหาอยู่ที่ Docker Desktop NAT เท่านั้น (prod ไม่มีปัญหา)

**3 วิธีทดสอบ/แก้ (เก็บไว้):**

### วิธี A — รัน backend บน host ตรงๆ (เร็วสุด)
```powershell
cd E:\hub\central-auth-starter\hub\backend
# venv + DATABASE_URL ชี้ localhost:5432
uvicorn app.main:app --host 0.0.0.0 --port 8000
# → browser → backend เห็น 127.0.0.1 / LAN IP จริง (ไม่ผ่าน NAT)
```
- ✅ เห็น IP จริงใน dev
- เหมาะกับ: ทดสอบเร็ว

### วิธี B — nginx reverse proxy (จำลอง prod)
```nginx
# nginx ตั้ง header ให้ backend
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Real-IP $remote_addr;
proxy_pass http://hub-backend:8000;
```
- ⚠️ nginx ใน container บน Docker Desktop ก็เห็น gateway → ต้องรัน nginx/backend บน host ถึงเห็น IP เครื่องจริงใน dev
- ✅ ใกล้ prod สุด (โครงสร้างเหมือน production)
- เหมาะกับ: เทสสถาปัตยกรรม prod

### วิธี C — deploy บน Linux server จริง + nginx/cloudflare
- ✅ เห็น IP client จริงทั่วโลก (Linux iptables DNAT preserve source; reverse proxy ตั้ง XFF)
- เหมาะกับ: production จริง
- อ้างอิง: `docs/deploy-to-server.md`

**วิธีทดสอบว่า pipeline ทำงาน (ใช้ได้เลยใน dev):**
```powershell
# จำลอง reverse proxy ตั้ง XFF
curl.exe -s -o NUL -H "X-Forwarded-For: 1.1.1.1" -H "User-Agent: Test/1" "http://localhost:8000/auth/me"
docker exec -i hub-postgres psql -U hub -d hub_db -c "SELECT path,status_code,ip,user_agent FROM request_logs WHERE ip='1.1.1.1' ORDER BY created_at DESC LIMIT 1;"
# → เก็บ 1.1.1.1 ครบ = pipeline พร้อมสำหรับ prod
```

**สถานะ:** ยังไม่ทำ (เลือกวิธีตอน deploy)

---

## ⏳ BACKLOG #3 — failure logging เพิ่มเติม (endpoint อื่น)

ตอนนี้ทำเฉพาะ whitelist add/remove/role — ยังเหลือ failure paths ที่ควร log เพิ่ม:
- `_get_owned_subsystem` (subsystem not found / not owned) — helper ที่หลาย endpoint ใช้
- subsystem register / update / transfer failure paths
- user CRUD failure paths (404 user not found)
- bulk-update failure paths

**แนวทาง:** ใส่ `log_action(... action="*_failed")` ก่อน raise ทุก HTTPException (B7)

**สถานะ:** ยังไม่ทำ (whitelist 3 ตัวทำแล้วเป็น pattern)
