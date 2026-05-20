---
name: central-auth-hub
description: Project guide for the Central Auth Hub senior project — invoke when working on the Hub (OAuth, JWT, RBAC, audit, ML scoring), Subsystem A (dorm, port 8001), Subsystem B (library, port 8002), or the ML Verifier (Isolation Forest). Covers conventions, the 32 known-bug rules, security defense-in-depth, and common task recipes. Skip for pure Next.js frontend work (Week 8+, not built yet) or non-project chatter.
---

# Central Auth Hub — Project Skill

ระบบ centralized identity & permission management สำหรับมหาวิทยาลัย (senior project) ประกอบด้วย Hub + 2 subsystems (dorm, library) + ML Verifier — **ไม่ใช่ SSO** แต่ละ subsystem มี session แยก Hub แค่ authenticate + authorize

Stack: Python 3.11 + FastAPI + Postgres 15 + Redis 7 + OAuth 2.0 + PKCE + JWT RS256 + Isolation Forest (Shadow Mode) + Docker Compose

> Source of truth ละเอียด: `CLAUDE.md` ที่ root — skill นี้เป็น distilled view สำหรับใช้ตอนทำงานจริง

---

## 🔒 Security non-negotiables (กฎห้ามผิดซ้ำ จาก bug B1–B32)

ก่อน commit/PR ทุกครั้ง ตรวจ checklist นี้:

1. **ทุก endpoint ต้องมี `Depends`** — `get_current_user` / `require_developer` / `require_hub_admin`; ถ้าเป็น public จริง comment ให้ชัด (B1)
2. **JWT decode ต้อง `verify_aud=True`** + ระบุ `audience=...` — Hub-direct = `hub.internal`, subsystem token = `client_id` (B4)
3. **Order ตอน error**: `log_action(db, ...)` → `db.commit()` → `raise HTTPException(...)` — ห้ามสลับ ไม่งั้น rollback กิน audit (B6)
4. **ทุก failure path ต้อง log** — login fail, whitelist miss, PKCE mismatch (B7)
5. **`hmac.compare_digest`** สำหรับเทียบ secret/token/PKCE — ห้ามใช้ `==` (B3)
6. **`get_client_ip(request)`** จาก `app/deps.py` — ห้ามใช้ `request.client.host` (คืน Docker IP `172.x`) (B20)
7. **One-time token เก็บ HMAC-SHA256** ไม่ใช่ plaintext + URL ห้ามมี token (HTML response + `history.replaceState()`) (B2, B5)
8. **Atomic ops ใช้ Redis `getdel`** — `/oauth/token` ต้อง atomic ไม่งั้น race condition (B9)
9. **Production fail-fast** — `config.validate_production()` reject ถ้า `APP_ENV=production` + secret ยัง default (B8)
10. **`/docs` ปิด production** — `ENABLE_DOCS=false` + recreate container ไม่ใช่ restart (B10, B22)
11. **ML fail-safe to pass** — `ml_client.py` try/except ทุกชนิด → `{score: 0.0, decision: pass}` (B21)
12. **Student blocked ที่ Hub-direct** — ใน `/auth/google/callback` ก่อนออก JWT + `require_developer` ที่ endpoint (Defense in Depth 2 ชั้น) (B19)

---

## 👥 RBAC matrix

| Route                                  | student | teacher | staff | admin |
|----------------------------------------|---------|---------|-------|-------|
| `/auth/google/*` (Hub direct)          | ❌      | ✅      | ✅    | ✅    |
| `/developer/*` (subsystem registration)| ❌      | ✅      | ✅    | ✅    |
| `/admin/*`                             | ❌      | ❌      | ❌    | ✅    |
| `/oauth/*` (subsystem flow)            | ✅*     | ✅      | ✅    | ✅    |

*if whitelisted in `access_list`

Dependencies: `get_current_user`, `require_developer`, `require_hub_admin`

---

## 📋 Convention quick-ref

- **UTC ทุก timestamp** — แปลงตอน display: `created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Bangkok'` (B29, B32)
- **`metadata_json`** Python attr + `Column("metadata", JSON)` alias — `metadata` reserved บน DeclarativeBase (B14)
- **UUID PK** — ห้ามใช้ auto-increment INT
- **`NUMERIC(3,2)`** สำหรับ anomaly_score — ห้าม FLOAT
- **Soft delete** — `revoked_at = NOW()` ไม่ใช่ `DELETE` (preserve history)
- **Email pattern** — student `<id>@uni.ac.th`, teacher/staff `<name><3digits>@uni.ac.th`, admin `<name>@hub.local`
- **Commit prefix** — `feat:` `fix:` `docs:` `refactor:` `security:` `test:`

---

## 🛠️ Common task recipes

### Add new endpoint
1. Function ใน `app/routers/<router>.py`
2. ใส่ `Depends(...)` ทุกครั้ง (B1)
3. ถ้าเปลี่ยน state → `log_action()` → `commit()` → `raise/return`
4. ถ้าเป็น file ใหม่ register router ใน `main.py`
5. `docker compose restart hub-backend` (uvicorn auto-reload ส่วนใหญ่)

### Add user field
1. Update `app/models.py` User class
2. Dev: drop & recreate / Prod: Alembic migration
3. Update `seed_users.py` ถ้าจำเป็น
4. Re-seed ตามลำดับ child→parent (ดูข้างล่าง)

### Add ML feature
1. เพิ่มใน `ml-service/app/features.py` ทั้ง `FEATURE_NAMES` และ `FEATURE_RANGES`
2. Update `ml-service/scripts/generate_data.py`
3. Update `hub/backend/app/services/feature_extraction.py`
4. Regenerate + retrain: `docker compose exec ml-service python -m scripts.generate_data && python -m scripts.train_model`
5. Restart hub-backend — feature-count mismatch crash ถ้าลืม (B27)

### Re-seed (preserves Gmail admin)
```bash
docker compose exec hub-backend python -m app.seeds.seed_users
```
ลำดับลบ children ก่อน: `secret_retrieval_tokens` → `access_list` → `login_sessions` → `audit_logs` → `request_logs` → `subsystems` → `users` (B11)

### Nuke & fresh
```bash
docker compose down -v
docker compose up -d --build
docker compose exec hub-backend python -m app.seeds.seed_users
docker compose exec hub-backend python -m scripts.generate_jwt_keys
docker compose exec ml-service python -m scripts.generate_data
docker compose exec ml-service python -m scripts.train_model
```

---

## 🗄️ Database snapshot

- **hub_db** (port 5432) — 7 tables: `users`, `subsystems`, `access_list`, `login_sessions`, `audit_logs`, `request_logs`, `secret_retrieval_tokens`
- **dorm_db** (port 5433) — 4 tables: `rooms`, `residents`, `reservations`, `dorm_audit_logs`
- **library_db** (port 5434) — 4 tables: `books`, `members`, `borrowings`, `library_audit_logs`

Subsystems ไม่มี FK ไป Hub — เก็บ `hub_user_id` เป็น UUID อิสระจาก JWT.sub

Postgres healthcheck ต้องระบุ `-d <db>`: `pg_isready -U hub -d hub_db` ไม่งั้น log spam (B12)

---

## 🐛 Bug index (อ้างอิงเต็มที่ CLAUDE.md → "Bugs Encountered")

| Group | Bug IDs |
|-------|---------|
| 🔒 Security | B1–B10 |
| 🗄️ Database | B11–B14 |
| 🌐 Auth/OAuth | B15–B19 |
| 🐳 Docker/Infra | B20–B22 |
| 📦 Git/Repo | B23–B25 |
| 🧠 ML | B26–B28 |
| 🔧 Config/Misc | B29–B32 |

เจอ bug ใหม่ → เพิ่มใน CLAUDE.md section "Bugs Encountered" ทุกครั้ง พร้อม "กฎ" ป้องกันซ้ำ

---

## 🚫 When NOT to invoke this skill

- งาน frontend Next.js admin dashboard (Week 8+ ยังไม่มีโค้ด)
- ML research ล้วน (อ่าน paper, ทฤษฎี) ที่ไม่แตะ feature pipeline
- คำถามทั่วไปไม่เกี่ยวโปรเจค
