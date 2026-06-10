# รายงานความคืบหน้าการพัฒนาระบบ Central Auth Hub
**วันที่จัดทำ:** 8 มิถุนายน 2569  
**ผู้พัฒนา:** hasiyahdama5@gmail.com  
**ประเภทโปรเจค:** โปรเจคจบปริญญาตรี — ระบบจัดการสิทธิ์ผู้ใช้แบบศูนย์กลางสำหรับมหาวิทยาลัย

---

## ภาพรวมระบบ

Central Auth Hub คือแพลตฟอร์มกลางสำหรับจัดการ Identity และ Permission ของผู้ใช้ในมหาวิทยาลัย ออกแบบให้ระบบย่อยต่าง ๆ (หอพัก, ห้องสมุด ฯลฯ) เชื่อมต่อผ่าน OAuth 2.0 + PKCE แทนที่จะดูแล authentication เอง

**สถาปัตยกรรม:** ไม่ใช่ SSO แบบ traditional — แต่ละ subsystem มี session ของตัวเอง Hub ทำหน้าที่ authenticate + authorize + ตรวจสอบความผิดปกติ (ML) เท่านั้น

---

## สรุปความคืบหน้าตาม Roadmap

| สัปดาห์ | งานหลัก | สถานะ |
|---------|---------|-------|
| 1 | ตั้งค่าระบบ + PostgreSQL + seed ผู้ใช้ 100 คน | ✅ เสร็จ |
| 2 | Google OAuth + JWT (Hub direct login) | ✅ เสร็จ |
| 3 | ลงทะเบียน Subsystem + Whitelist (CSV / รายคน) | ✅ เสร็จ |
| 4 | OAuth flow เต็มรูปแบบ + PKCE + ตรวจสิทธิ์ | ✅ เสร็จ |
| 5 | ML Verifier (Isolation Forest, 12 features) + แก้บั๊กความปลอดภัย 17 จุด | ✅ เสร็จ |
| 6 | Subsystem A — ระบบหอพัก (จองห้อง, อนุมัติ, check-in) | ✅ เสร็จ |
| 7 | Subsystem B — ระบบห้องสมุด (ยืม/คืนหนังสือ) | ✅ เสร็จ |
| 8 | Admin Dashboard (Next.js 14) | ✅ เสร็จ |
| 9–12 | Hybrid RBA, MFA, Hardening, Threat Intel | ✅ เสร็จบางส่วน (ล่วงหน้า) |
| 13–14 | Test suite + documentation | 🔄 อยู่ระหว่างดำเนินการ |
| 15–16 | Buffer + เขียนวิทยานิพนธ์ + สอบ | ⏳ ยังไม่ถึง |

##การทดสอบทุกขั้นตอน
***ยังไม่เริ่มทำ

**รวม commits ทั้งหมด: 56 commits**

---

## รายละเอียดสิ่งที่พัฒนาแล้ว

### 1. Hub Backend — ระบบแกนกลาง (FastAPI + Python)

**ฐานข้อมูล (PostgreSQL) — 12 ตาราง:**

| ตาราง | ใช้ทำอะไร |
|-------|----------|
| users | ผู้ใช้ 100 คน (student 70 / teacher 15 / staff 10 / admin 5) |
| subsystems | ระบบย่อยที่จดทะเบียน (client_id, secret hash) |
| access_list | whitelist ว่าใครเข้า subsystem ไหนได้ |
| login_sessions | ประวัติการ login ทุกครั้ง + คะแนน ML |
| audit_logs | บันทึกการกระทำทุกอย่าง (append-only) |
| request_logs | log HTTP ทุก request |
| secret_retrieval_tokens | ลิงก์ดึง client_secret แบบ one-time |
| SubsystemChangeRequest | workflow ขออนุมัติเปลี่ยนแปลง subsystem |
| MLFeedback | feedback จาก admin ให้ ML model |
| MFAChallenge | OTP challenge สำหรับ MFA flow |
| ApiAlert | แจ้งเตือนเมื่อ API ผิดปกติ |
| IpBlacklist | บัญชีดำ IP อันตราย |

**Services ที่พัฒนา:**
- `jwt_service.py` — ออก JWT (RS256) แยก audience Hub vs Subsystem
- `secret_service.py` — Argon2id hash + Fernet encryption
- `mfa_service.py` — Email OTP challenge (flow: ML บอก mfa → ส่ง OTP → verify → ออก JWT)
- `geoip.py` — ระบุประเทศจาก IP (MaxMind GeoIP2)
- `ip_blacklist.py` + `ipsum_refresh.py` — ดึง threat feed + บล็อก IP อันตราย
- `webhook_dispatcher.py` — ส่ง event ไปยัง subsystem เมื่อมีการเปลี่ยนแปลง
- `email_service.py` — ส่งอีเมล OTP + แจ้งเตือน
- `structured_logger.py` — JSON log format สำหรับ production
- `alert_service.py` + `api_guard.py` — ตรวจจับและแจ้งเตือน API ผิดปกติ
- `hooks.py` (Event Bus) — pluggable extension points (EVT_LOGIN_SUCCESS, EVT_ML_SCORED ฯลฯ)

### 2. ระบบ ML — Anomaly Detection

**อัลกอริทึม:** Isolation Forest (Liu, Ting, Zhou 2008)  
**Features:** 12 ตัว ครอบคลุม 4 มิติ

| มิติ | Features |
|-----|---------|
| เวลา (Temporal) | hour_of_day, day_of_week, is_weekend, hours_from_typical_login_time |
| ภูมิศาสตร์ (Geographic) | is_thailand, is_new_country, country_change_count_30d |
| อุปกรณ์ (Device) | is_new_device, is_new_user_agent_family |
| ความเร็ว (Velocity) | log_minutes_since_last_login, login_count_24h, failed_logins_24h |

**Hybrid RBA — การตัดสินใจ 4 ชั้น:**
1. **Rule Engine** — กฎแน่นอน (IP blacklist, failed login เกิน threshold)
2. **Behavior Profiling** — เปรียบเทียบกับพฤติกรรมปกติของผู้ใช้คนนี้
3. **Isolation Forest Scorer** — ML score (พร้อม SHAP อธิบาย feature ที่มีผล)
4. **Risk Aggregator** — รวม 3 ชั้น → ตัดสิน: `pass / mfa / block`

**SHAP Integration:** ระบุได้ว่า feature ไหนทำให้ score สูง (ใช้สำหรับอธิบายต่อ admin)

**Shadow Mode:** `ML_SHADOW_MODE=true` → ML score แต่ไม่บล็อกจริง บันทึกเป็น `would_mfa` / `would_block`

### 3. Subsystem A — ระบบหอพัก (port 8001)

- ห้องพัก 24 ห้อง (ตึก A/B × 3 ชั้น × 4 ห้อง)
- นักศึกษาจองห้อง → เจ้าหน้าที่อนุมัติ/ปฏิเสธ → check-in
- OAuth 2.0 + PKCE เชื่อมต่อกับ Hub
- UI: Jinja2 + Tailwind CSS (theme: Indigo)
- ฐานข้อมูลแยก (postgres-dorm): rooms, residents, reservations, dorm_audit_logs
- แก้บั๊ก 11 จุด (security + race condition + UX)

### 4. Subsystem B — ระบบห้องสมุด (port 8002)

- หนังสือ 30 เล่ม × 6 หมวด
- สมาชิกขอยืม → บรรณารักษ์อนุมัติ/ปฏิเสธ/รับคืน
- OAuth 2.0 + PKCE เชื่อมต่อกับ Hub
- UI: Jinja2 + Tailwind CSS (theme: Emerald)
- ฐานข้อมูลแยก (postgres-library): books, members, borrowings, library_audit_logs
- แก้บั๊ก 10 จุด

### 5. Admin Dashboard Frontend (Next.js 14, port 3000)

หน้าหลักที่พัฒนาแล้ว:
- **Dashboard** — ภาพรวม KPI (users, subsystems, login stats)
- **ML Dashboard** — กราฟ anomaly score, decision distribution, timeline
- **Audit Log Viewer** — ค้นหา/กรองบันทึกการกระทำ
- **Subsystem Triage** — อนุมัติ/ปฏิเสธ subsystem ที่รอการตรวจสอบ
- **API Alerts** — แจ้งเตือน API ผิดปกติ
- **IP Blacklist** — จัดการ IP อันตราย

### 6. Infrastructure & DevOps

**Migration B — แยก Docker Compose เป็น 3 stack อิสระ:**
- `docker-compose.yml` → Hub + ML + Frontend
- `docker-compose.dorm.yml` → Subsystem A
- `docker-compose.library.yml` → Subsystem B
- เชื่อมกันผ่าน external network `cah-net`

**เหตุผล:** สะท้อน production จริงที่แต่ละทีมดูแล subsystem ของตัวเอง — deploy แยกกันได้

**เพิ่มเติม:**
- Caddy reverse proxy (`docker-compose.caddy.yml`) — HTTPS + auto TLS
- Cloudflare Tunnel (`docker-compose.tunnel.yml`) — expose ออก internet
- Backup script (`scripts/backup.sh`) — pg_dump 3 ฐานข้อมูล + sync ไป OneDrive
- Worktree workflow — ทำงานคู่ขนานหลาย feature โดย Docker port ไม่ชนกัน
- Pre-commit hooks — ป้องกัน commit ไฟล์ลับ + lint + syntax check

### 7. Security Hardening — 10 ชั้น

| ชั้น | มาตรการ |
|-----|--------|
| Data at Rest | Argon2id hash secret, pgcrypto สำหรับ PII |
| Data in Transit | HTTPS/TLS ผ่าน Caddy |
| Auth Flow | OAuth 2.0 + PKCE (RFC 7636) |
| Token Security | JWT RS256 + jti claim |
| Subsystem Key | One-time link (15 นาที) + AES Fernet encryption |
| Session | HttpOnly + SameSite cookie |
| Audit Log | Append-only + hash chain |
| Rate Limiting | Per IP / per client_id |
| ML Detection | Isolation Forest + Hybrid RBA 4-layer |
| Secret Management | `.env` แยกจาก git, รองรับ key rotation |

**บั๊กที่แก้สะสมทั้งหมด: 32+ จุด** (ครอบคลุม security, database, auth/OAuth, Docker, git, ML, config)

### 8. Tests

Test ที่มีแล้ว (pytest):
- `test_health.py` — healthcheck endpoints
- `test_jwt_service.py` — JWT create/verify/audience
- `test_pkce.py` — PKCE generation + verification + timing-safe compare
- `test_rate_limit.py` — rate limiter behavior
- `test_rbac.py` — role-based access control
- `test_secret_service.py` — Argon2id + Fernet

---

## สิ่งที่ยังเหลือ (สัปดาห์ 13–16)

1. **Test suite ครบ** — เพิ่ม integration test สำหรับ OAuth flow เต็มรูปแบบ (pytest + httpx)
2. **MFA flow สมบูรณ์** — ทดสอบ end-to-end + frontend MFA page ใน Next.js
3. **Token revocation** — jti + Redis blacklist + admin `/sessions` endpoint
4. **Documentation** — API docs, deployment guide, thesis writing
5. **Security penetration test** — ทดสอบตาม OWASP Top 10

---

## สถิติโปรเจค

| รายการ | จำนวน |
|-------|------|
| Total commits | 56 |
| Python files (Hub) | ~60 ไฟล์ |
| Database tables | 12 (Hub) + 4 (Dorm) + 4 (Library) |
| API endpoints | 30+ |
| ML features | 12 |
| บั๊กที่แก้และบันทึก | 32+ |
| Test files | 6 |
| Docker services | 8 (3 stacks) |

---

*รายงานนี้สร้างจาก codebase จริง — git log 56 commits, โครงสร้างไฟล์, และ daily logs*
