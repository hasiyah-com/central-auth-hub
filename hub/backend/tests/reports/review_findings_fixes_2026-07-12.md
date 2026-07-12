# Verification Report — แก้ 3 PLAUSIBLE findings (SOC dashboard + grade subsystem)

**วันที่:** 2026-07-12
**ขอบเขต:** ปิด 3 PLAUSIBLE findings ที่ค้างจาก code review ต้น session (จาก 6 findings เดิม —
2 CONFIRMED + 1 security แก้ไปแล้วก่อนหน้า, เหลือ 3 ข้อนี้)
**วิธีทดสอบ:** manual verification (curl / inline SQL / tsc) — fix เล็ก + บางส่วนเป็น visual/flow
ที่ไม่เหมาะเขียน pytest (frontend globe, OAuth redirect). บันทึกคำสั่ง reproducible ไว้ครบ

---

## Finding 1 — `_oauth_flows` in-memory dict โตไม่จำกัด (subsystem-grade)

**ไฟล์:** `hub/subsystem-grade/app/main.py`

**ปัญหา:** `_oauth_flows: dict[str, str] = {}` เก็บ `state → code_verifier` ใน memory ไม่มี TTL/
cleanup — user ที่เริ่ม OAuth แล้วไม่จบ (ปิด tab) ทิ้ง entry ค้างตลอด → memory leak ช้า ๆ +
หายหมดตอน restart

**แก้:** เปลี่ยนเป็น **signed cookie** (`grade_oauth_flow`) ตาม pattern dorm/library —
`URLSafeTimedSerializer` salt แยก (`grade-oauth`) เก็บ `{state, verifier}` TTL 600s +
เพิ่ม **CSRF state validation** (เทียบ `flow.state == query.state` — เดิม dict key = state
validate โดยปริยาย, cookie ต้องเทียบเอง = ชัดเจนขึ้น) + `secure` flag ตาม `session_cookie_secure`

**ผลทดสอบ:**

| เคส | คำสั่ง | ผลที่คาด | ผลจริง |
|---|---|---|---|
| happy path | `GET /login/start` | 307 → Hub, Set-Cookie signed (HttpOnly, Max-Age=600, SameSite=lax), state ใน cookie = state ใน redirect | ✅ 307, cookie payload decode = `{state, verifier}` ตรง state ใน URL |
| no cookie | `GET /oauth/callback?code=x&state=fake` | 307 `/login?error=oauth_state` + ลบ cookie | ✅ 307 + `Max-Age=0` |
| CSRF (state mismatch) | valid cookie + `state=WRONG_STATE` | 307 `/login?error=oauth_state` + ลบ cookie | ✅ 307 + `Max-Age=0` |

```bash
# reproducible
curl -s -i http://localhost:8003/login/start | grep -iE '^HTTP|^location|^set-cookie'
curl -s -i "http://localhost:8003/oauth/callback?code=x&state=fake" | grep -iE '^HTTP|^location|^set-cookie'
```

---

## Finding 2 — Dashboard globe ไม่ update ตาม poll 30s

**ไฟล์:** `hub/frontend/app/(console)/dashboard/_components/AuthTopologyMap.tsx`

**ปัญหา:** `useEffect(..., [])` สร้าง globe ครั้งเดียวตอน mount แต่ `dashboard/page.tsx` poll
`/admin/dashboard/map` ใหม่ทุก 30s — prop `geo`/`subsystems` เปลี่ยนแต่ globe ไม่วาดใหม่ →
จุด/เส้นบนแผนที่ค้างเป็นข้อมูลตอน mount ตลอด (KPI ข้าง ๆ update ปกติ = ดูขัดกัน)

**แก้:** เพิ่ม `sig = JSON.stringify({...})` เป็น signature ของ data → ใช้เป็น effect dep
(`[sig]`). aggregate 30 วันเปลี่ยนช้า → ปกติ sig เดิม = **ไม่ rebuild = ไม่กระพริบ**; มี login/
health ใหม่ → sig เปลี่ยน → วาดใหม่รอบเดียว (ไม่ blind-rebuild ทุก 30s ที่จะทำ globe flash +
เสีย rotation state)

**ผลทดสอบ:** `docker compose exec hub-frontend npx tsc --noEmit` → **exit 0** (ไม่มี type error).
Visual live-refresh ต้อง login เข้า dashboard (Google OAuth) ตรวจด้วยตา — logic: dep เปลี่ยน
เมื่อ data เปลี่ยนเท่านั้น (verified โดย inspection + tsc)

---

## Finding 3 — `risk_score = NULL` ถูกจัดเป็น "green" (ปลอดภัย) บนแผนที่

**ไฟล์:** `hub/backend/app/routers/admin.py` (`/admin/dashboard/map`) +
`AuthTopologyMap.tsx` (สี + legend)

**ปัญหา:** `case((>=0.5,red),(>=0.4,yellow),else_=green)` — `risk_score` NULL (ML ล่ม →
fail-safe ไม่ให้คะแนน) ไม่ตรงเงื่อนไขไหน → ตก `else_=green` → login ที่ **ไม่ถูกประเมินความเสี่ยงเลย**
โผล่เป็นจุดเขียว "ปลอดภัย" (เข้าใจผิดได้)

**แก้:** เพิ่ม `(risk_score.is_(None), "unknown")` เป็นเงื่อนไขแรกใน `case()` + frontend เพิ่ม
`RISK_HEX.unknown = 0x64748b` (slate/เทา) + riskLines/moverFor/legend รองรับ "unknown"

**ผลทดสอบ (inline SQL กับ DB จริง):**
```
bucket distribution: {'red': 153, 'green': 260, 'unknown': 84, 'yellow': 16}
actual NULL risk_score rows: 84
```
→ 84 row ที่ risk_score = NULL ถูกแยกเป็น **"unknown" ตรงเป๊ะ** (ก่อนแก้: 84 นี้จะรวมใน green
= 344) — ยืนยันบั๊กจริง + impact จริง (84 session ที่ไม่เคยประเมิน เคยโชว์เป็น "ปลอดภัย")

```bash
# reproducible (inline)
docker compose exec hub-backend python -c "
from sqlalchemy import case, func
from app.database import SessionLocal
from app.models import LoginSession
db = SessionLocal()
rb = case((LoginSession.risk_score.is_(None),'unknown'),(LoginSession.risk_score>=0.5,'red'),(LoginSession.risk_score>=0.4,'yellow'),else_='green')
print(dict(db.query(rb, func.count(LoginSession.id)).group_by(rb).all()))
print('NULL rows:', db.query(func.count(LoginSession.id)).filter(LoginSession.risk_score.is_(None)).scalar())
"
```

---

## สรุป

| # | Finding | สถานะ | หลักฐาน |
|---|---|---|---|
| 1 | grade `_oauth_flows` memory leak | ✅ แก้ + verified | curl 3 เคส (happy/no-cookie/CSRF) ผ่านหมด |
| 2 | dashboard globe ไม่ live-refresh | ✅ แก้ + tsc ผ่าน | sig-based rebuild dep, tsc exit 0 |
| 3 | NULL risk → green (safe) | ✅ แก้ + verified | 84 NULL → "unknown" ตรงเป๊ะกับ actual NULL count |

**ผลข้างเคียง:** ไม่มี — backend `py_compile` ผ่าน, frontend `tsc --noEmit` exit 0,
container (grade + hub-backend) reload สะอาด ไม่มี import/runtime error

**Bug ที่บันทึกเพิ่ม:** ทั้ง 3 เป็น PLAUSIBLE จาก review เดิม — ไม่ได้เพิ่มใน bugs-encountered.md
(เป็น hardening ไม่ใช่ regression ที่เจอตอน dev) ยกเว้นถ้าต้องการให้ track
