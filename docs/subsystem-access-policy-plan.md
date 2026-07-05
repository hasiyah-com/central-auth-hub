# Plan — Subsystem Access Policy + Roster Sync + role_in_sub → user_type

> เอกสารแผนงาน (ยังไม่ลงมือ) อ้างอิงแนวคิดจาก `D:\แนวคิดการจัดการสิทธิ์ของระบบย่อย.md`
> ปรับตาม decision ล่าสุด แล้ว map ลงโค้ดจริง (Hub + subsystem-dorm + subsystem-library)

## 0. Decisions (ยืนยันแล้ว)

| หัวข้อ | สรุป |
|---|---|
| Access Policy | ทำ 4 แบบ: **Explicit (เดิม)** · **All Users** · **Role-based** · **Attribute-based** |
| Campus / Department(แยก) | ❌ ไม่ทำ (ไม่มี column) — Attribute ใช้ **faculty / major** ที่มี |
| CSV by hub_user_id (เลข) | ❌ ไม่ทำ — Explicit ใช้ **email** ใน CSV เหมือนเดิม |
| **role_in_sub** | ❌ **ตัดออกทั้งหมด** → ใช้ **`user_type`** (student/teacher/staff/admin) แทนทุกที่ · ทุกคนบทบาทเดียวก่อน ปรับทีหลัง |
| **Library data** | 🗑️ **ลบเก่าทั้งหมด** (drop volume + reseed) → library: บรรณารักษ์ = staff/teacher, สมาชิก = student · ไม่มี migration column |
| Sync model | **Roster sync** หลังลงทะเบียน: ให้ **API key** → ส่ง `user_id, email, user_type` (3 field) · ข้อมูลเต็มไหลตอน **login** ตาม scope (ข้อ 7 + 6 ของเอกสาร) |
| Scope | คงเดิม (`student_id/employee_id/faculty/major/year/position/phone/address`) |
| Match key | **`user_id` (UUID)** ตลอด — ไม่ใช่ email |

**Naming (กันชนกับของเดิม):**
- **Login Method Policy** = (มีแล้ว) เลือก Google/Passkey — `app_settings.auth_policy`
- **Subsystem Access Policy** = (อันใหม่) ใครเข้า subsystem ได้ — `subsystems.access_policy`

---

## 1. สถาปัตยกรรมเป้าหมาย

```
ลงทะเบียน subsystem
  → client_id + client_secret (OAuth)  +  API key (roster, read-only)   ← ใหม่
  → เลือก Access Policy (explicit/all/role/attribute)                    ← ใหม่

[Roster sync — ก่อน login]
  subsystem --X-Api-Key--> GET /api/v1/roster
     Hub: evaluate access_policy → [{user_id, email, user_type}]         ← 3 field
  subsystem สร้าง record ของตัวเอง (เช่น grade) ผูกด้วย user_id

[Login — OAuth]
  user → subsystem → Hub → Google/Passkey → RBA
     → evaluate_access_policy(user, subsystem)  ← ชั้นเดียวกับ roster
        allowed? → JWT (sub=user_id, user_type, + scope fields) : 403
  subsystem: match JWT.sub กับ record ที่ sync ไว้ → แสดง UI ตาม user_type
```

**หลักการคู่ (สำคัญ):** Access Policy = ตัวกรอง **ตอน authorize** (login-time) — ใช้เกณฑ์เดียวกันทั้ง roster และ login (single source of truth). JIT provisioning เดิม **เก็บไว้เป็น safety net** (เผื่อ user เข้า policy หลัง sync ล่าสุด).

---

## 2. Hub — Data model

### 2.1 `subsystems` (ALTER TABLE, non-destructive)
```sql
ALTER TABLE subsystems ADD COLUMN access_policy VARCHAR(20) DEFAULT 'explicit';
   -- explicit | all | role | attribute
ALTER TABLE subsystems ADD COLUMN access_policy_config JSON;
   -- role:      {"roles": ["teacher","staff"]}              ← ค่าจาก user_type
   -- attribute: {"faculty": ["วิศวกรรมศาสตร์"], "major": [...]}
   -- explicit/all: null
ALTER TABLE subsystems ADD COLUMN api_key_hash VARCHAR(128);  -- Argon2/HMAC (เหมือน client_secret)
ALTER TABLE subsystems ADD COLUMN api_key_prefix VARCHAR(12); -- โชว์ 8 ตัวแรกใน UI (ระบุ key)
```
- `allowed_roles` เดิม → **deprecate** (เลิกใช้เป็น "role ที่ subsystem assign") — migrate ค่าไปเป็น `access_policy_config.roles` ถ้าจะใช้ Role-based; ไม่งั้นปล่อยทิ้ง
- subsystem เดิมทุกตัว → `access_policy='explicit'` อัตโนมัติ (default) → **พฤติกรรมเดิมไม่เปลี่ยน**

### 2.2 `access_list` (คงไว้ — 2 บทบาท)
- **Explicit policy** → คือ whitelist หลัก (เหมือนเดิม)
- **All/Role/Attribute policy** → ใช้เป็น **deny-list** (มี row + `revoked_at IS NULL` + flag `deny`) เพื่อ ban รายคน + เก็บ audit
- เพิ่ม column: `ALTER TABLE access_list ADD COLUMN entry_type VARCHAR(10) DEFAULT 'allow';` (allow | deny)
- **`role_in_sub` column → deprecate** (คง nullable ไว้ก่อน กัน migration พัง แต่เลิก populate/อ่าน)

### 2.3 `users`
- ไม่เปลี่ยน — `user_type`, `faculty`, `major`, `status` มีครบ

---

## 3. Hub — Access Policy engine

ไฟล์ใหม่: `app/services/access_policy.py`
```python
def evaluate_access_policy(db, user, subsystem) -> tuple[bool, str]:
    # 0) deny-list ทับทุก policy
    if _has_deny_entry(db, subsystem.id, user.id): return (False, "denied")
    p = subsystem.access_policy or "explicit"
    if p == "all":
        return (user.status == "active", "all_users")
    if p == "role":
        roles = (subsystem.access_policy_config or {}).get("roles", [])
        return (user.user_type in roles, f"role:{user.user_type}")
    if p == "attribute":
        cfg = subsystem.access_policy_config or {}
        ok = _match_attr(user.faculty, cfg.get("faculty")) and \
             _match_attr(user.major,   cfg.get("major"))
        return (ok, "attribute")
    # explicit (default)
    return (_in_access_list(db, subsystem.id, user.id), "explicit")
```
- เรียกใน **`oauth.py::_finalize_subsystem_login`** แทน access_list check ตรง ๆ (จุดที่ตอนนี้ตัดสิน 403 / ออก JWT)
- log เหตุผล (`reason`) ลง audit + login_session (debug ว่าทำไม allow/deny)

---

## 4. Hub — Roster Sync API

### 4.1 API key
- ออกตอนลงทะเบียน (`developer.py::register_subsystem`) — คู่กับ secret retrieval
- เก็บ `api_key_hash` (hash) + `api_key_prefix` (โชว์); plaintext แสดงครั้งเดียว
- **rotate** ได้ (เหมือน rotate-secret) — endpoint `POST /developer/subsystems/{id}/rotate-api-key`

### 4.2 Endpoint: `GET /api/v1/roster`
ไฟล์ใหม่: `app/routers/roster.py`
```
Header: X-Api-Key: <plaintext>
Query:  ?updated_since=<ISO>   (incremental, optional)
        ?limit=&offset=        (paginate)
Auth:   hash(X-Api-Key) → หา subsystem (ถ้าไม่เจอ → 401, opaque)
Logic:  ดึง users ที่ผ่าน evaluate_access_policy(subsystem) + status=active
Return: { "subsystem": "...", "count": N,
          "users": [{"user_id": "<uuid>", "email": "...", "user_type": "..."}] }
```
- **ส่งแค่ 3 field**: `user_id, email, user_type` (ข้อ 7) — ไม่ส่ง faculty/major/phone (เต็มตอน login)
- rate-limit + audit (`roster_pulled`, subsystem_id, count)
- เกณฑ์เดียวกับ login-time `evaluate_access_policy` (consistency)

### 4.3 Keep-fresh (มี infra แล้ว)
- webhook `access_revoked/updated/restored` (ทำแล้ว) → subsystem mark/ลบ
- subsystem re-pull roster เป็นระยะ (cron ฝั่ง subsystem)

---

## 5. Hub — role_in_sub → user_type (91 จุด)

| ไฟล์ | เปลี่ยนอะไร |
|---|---|
| `services/jwt_service.py` | JWT subsystem: claim `role_in_subsystem` → **populate ด้วย `user.user_type`** (คง claim name ช่วง transition เพื่อลดงาน subsystem) หรือเพิ่ม claim `user_type` ตรง ๆ |
| `routers/oauth.py` | `_finalize_subsystem_login`: เลิกอ่าน/ส่ง role_in_sub → ใช้ user_type; เปลี่ยน access check เป็น `evaluate_access_policy` |
| `routers/developer.py` | whitelist add/CSV/bulk-role: ตัด field `role` (role_in_sub) ออก — CSV เหลือ `email,note`; bulk-role endpoint → deprecate |
| `routers/users.py` | ตัด role_in_sub ออกจาก response/logic |
| `routers/admin.py` | active-sessions / audit: เลิกโชว์ role_in_sub → user_type |
| `routers/oidc.py`, `passkey.py` | claim mapping → user_type |
| `services/change_request_service.py` | ลบ `change_whitelist_role` / `bulk_change_whitelist_roles` (ไม่มี role ให้เปลี่ยนแล้ว) |
| `services/email_service.py` | ตัด role_in_sub ออกจาก template |
| `models.py` | `access_list.role_in_sub` → deprecate (nullable, เลิกใช้) + เพิ่ม `entry_type` |

> หมายเหตุ: ตั้ง `role_in_subsystem = user_type` ใน JWT ช่วง transition = subsystem ที่อ่าน claim เดิม **ยังทำงานได้** (แค่ค่ากลายเป็น user_type) → ลดความเสี่ยง big-bang

---

## 6. Subsystem-dorm (50 จุด) — เปลี่ยนอะไร

ปัจจุบัน role = resident/teacher/staff (resident ≈ student) → map ตรงกับ user_type ได้

| ไฟล์ | เปลี่ยน |
|---|---|
| `app/deps.py` | `CurrentUser.role_in_sub` → `user_type` (อ่านจาก claim `user_type`/`role_in_subsystem`) · `require_role(*roles)` → เช็ค `user.user_type` · `get_or_create_resident`: เก็บ `user_type` (reuse column `role_in_sub` เก็บค่า user_type ไปก่อน เลี่ยง migration หรือเพิ่ม column `user_type`) |
| `app/routers/auth.py` | อ่าน `claims["user_type"]` แทน `role_in_subsystem`; provided_scope เดิม |
| `app/routers/staff.py` | guard `require_role("staff")` → `require_user_type("staff","admin")`; teacher → "teacher" |
| `app/routers/pages.py` | logic ที่ดู role → user_type |
| `app/static/app.js` | menu switch: `role === "staff"/"teacher"/"student"` (เดิมมี resident) → ใช้ user_type 4 ค่า; **resident → student** |
| `app/models.py` | `residents.role_in_sub` → เก็บ user_type (rename ภายหลัง) |
| `templates/*` (base/home/me/room_detail/staff/residents) | badge/condition `role_in_sub` → `user_type` |
| **(ใหม่ optional)** | roster receiver — endpoint รับ/ดึง roster + pre-create (dorm เป็น JIT ไม่บังคับ; ทำเป็น demo ได้) |

**Mapping ค่า:** `resident → student` · `teacher → teacher` · `staff → staff` (staff menu ครอบ admin ด้วย)

---

## 7. Subsystem-library (25 จุด) — เปลี่ยนอะไร

ปัจจุบัน role = member/librarian (member ≈ student, librarian ≈ staff/teacher)

| ไฟล์ | เปลี่ยน |
|---|---|
| `app/deps.py` | `role_in_sub` → `user_type` · `require_role("librarian")` → `require_user_type("staff","teacher","admin")` · `get_or_create_member` เก็บ user_type |
| `app/routers/auth.py` | อ่าน `claims["user_type"]` |
| `app/routers/librarian.py` | guard librarian → user_type in (staff/teacher/admin) |
| `app/models.py` | **rename `members.role_in_sub` → `user_type`** (ลบ data เก่า drop+recreate ได้เลย — ดูด้านล่าง) |
| `templates/*` (base/home/me/book_detail/librarian/members) | badge `role_in_sub` (member/librarian) → แสดงตาม user_type |

**Mapping ค่า:** `member → student` · `librarian → staff/teacher`

> ✅ **DECISION (ยืนยันแล้ว):** บรรณารักษ์ = **ทุก staff/teacher** (ตัดสินจาก `user_type`), สมาชิก = student.
> ไม่มี assign รายคนแล้ว (เคส "เฉพาะ staff บางคน" รอ role_in_sub อนาคต)

> 🗑️ **DECISION (ยืนยันแล้ว): ลบข้อมูล library เก่าทั้งหมด** — ไม่ต้อง migrate column เดิม:
> `docker compose -f docker-compose.library.yml down -v` (ลบ volume postgres-library)
> แล้ว recreate (members/borrowings ใหม่ด้วย schema ที่ใช้ `user_type`) + `seed_books.py`.
> → library migration กลายเป็น **drop + reseed สะอาด** ไม่มี risk migration column.
> (ผลข้างเคียง: ประวัติยืม-คืน + สมาชิกเดิมหายหมด — ยอมรับแล้ว)

---

## 8. Phasing (incremental, แต่ละ phase test ได้ deploy ได้)

| Phase | งาน | behavior change | risk |
|---|---|---|---|
| **P0** | ALTER TABLE (access_policy default explicit, api_key cols, entry_type) + naming docs | ไม่มี | ต่ำ |
| **P1** | **role_in_sub → user_type** (Hub JWT=user_type + dorm + library) | เทียบเท่าเดิม (resident=student) | **กลาง-สูง** (cross-cutting 166 จุด) |
| **P2** | Access Policy engine + login-time check + **All + Role** (Attribute ทีหลัง) + admin/dev UI selector | explicit ยัง default → ของเก่าไม่พัง | กลาง |
| **P3** | **Roster API** (api key + `/api/v1/roster` + rotate) + webhook keep-fresh | feature ใหม่ | กลาง |
| **P4** | Attribute-based (faculty/major) | feature ใหม่ | ต่ำ |
| **P5** | (option) subsystem "ระบบเกรด" + roster receiver = demo sync เต็มรูป | feature ใหม่ | กลาง |

> แนะนำเริ่ม **P0 → P1** ก่อน (P1 คือฐานของทุกอย่าง) แล้วค่อย P2/P3

---

## 9. Testing plan (ตาม TDD)

| Phase | test |
|---|---|
| P1 | JWT carries user_type · dorm/library require_user_type gate ถูก · login flow ยัง allow คนเดิม (resident=student เข้าได้) · provided_scope ไม่พัง |
| P2 | `evaluate_access_policy`: explicit/all/role + deny-list ทับ · login 403 เมื่อ policy ไม่ผ่าน · เปลี่ยน policy แคบลง → kick คนที่หลุด |
| P3 | roster: API key ผิด → 401 · roster กรองตาม policy ตรงกับ login-time · ส่งแค่ 3 field · rotate key · rate-limit |
| P4 | attribute match faculty/major (รวม/ไม่รวม) |

เก็บ `.py` ที่ `tests/` + report `.md` ที่ `tests/reports/` (ตาม convention)

---

## 10. Risks & open questions

1. **P1 เป็น big refactor (166 จุด)** — ลดเสี่ยงด้วย: ตั้ง JWT `role_in_subsystem=user_type` ช่วง transition → subsystem code เดิมยังรันได้ แล้วค่อยเปลี่ยนชื่อ field ทีหลัง
2. ~~**library "บรรณารักษ์"**~~ — ✅ **ตัดสินแล้ว:** บรรณารักษ์ = ทุก staff/teacher + **ลบ data library เก่าทั้งหมด** (drop volume + reseed) → ไม่มี migration risk
3. **Roster `user_type` ของ admin** — admin ควรอยู่ใน roster ของระบบเกรดไหม? (น่าจะไม่ — กรอง user_type ที่ policy ระบุเท่านั้น)
4. **Email ใน roster = PII** — ส่งได้เพราะใช้ map legacy data; แต่ log การ pull + จำกัดด้วย API key + rate-limit
5. **subsystem-dorm/library reseed** — ถ้าเปลี่ยน column residents/members ต้อง migrate; แนะนำ reuse column เดิม (เก็บ user_type) เลี่ยง drop

---

## 11. สรุปไฟล์ที่จะแตะ (เช็คลิสต์)

**Hub:** `models.py` · `services/{access_policy(new),roster(new via router),jwt_service,change_request_service,email_service}` · `routers/{oauth,developer,users,admin,oidc,passkey,roster(new)}` · migration SQL
**Dorm:** `deps.py` · `models.py` · `routers/{auth,pages,staff}` · `static/app.js` · `templates/*` (6)
**Library:** `deps.py` · `models.py` · `routers/{auth,librarian}` · `templates/*` (5)
**Frontend (admin/dev):** subsystem register + detail — เพิ่ม Access Policy selector + config + แสดง API key (one-time) + rotate

---

> **ขั้นถัดไป:** อนุมัติ plan นี้ → เริ่ม **P0 (ALTER + naming)** แล้ว **P1 (role_in_sub → user_type)**
> เป็นฐาน. ระบบเกรด/roster ทำเป็น phase หลังได้ตามสะดวก
