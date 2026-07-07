# Incident Summary — Test Report (2026-07-06)

> **อัปเดต (รอบ 2):** ขยาย Incident Detail เป็น full modal 8 ส่วนตาม mockup +
> Take Action ที่ทำงานจริง (revoke session / block IP / reset passkey / notify) ผ่าน
> step-up. ดูหัวข้อ "Expansion (รอบ 2)" ท้ายรายงาน. Test รวมเป็น **32 tests**,
> full regression **319 passed** (5 fail เดิมไม่เกี่ยว).

## สรุป

เพิ่มหน้า **Incidents (เหตุการณ์เสี่ยง)** — เมื่อ 4-Layer RBA จับ login ว่าเสี่ยง
admin เห็นรายงานที่เฟรมเป็น narrative triage 4 ส่วน เพื่อจัดการได้เร็ว:

  ① **เข้าทางไหน (Entry)** — `login_method` → ช่องทาง + endpoint + เป้าหมาย (Hub/subsystem ไหน)
  ② **ตรวจเจออะไร (Detected)** — risk_score / breakdown 3 layer / reasons + IP/geo/device
  ③ **ระบบทำอะไรต่อ (Impact)** — decision + session ยังเปิด/ถูกตัด + timeline จาก audit_logs
  ④ **ต้องปิดช่องโหว่ตรงไหน (Actions)** — แนะนำ action อัตโนมัติ + link ไปหน้าจัดการ

**การตัดสินใจที่ยืนยันกับ user:** หน้า Incidents ใหม่เฉพาะ (ไม่ยัดใน ML/Activity)
+ ระบบแนะนำ action อัตโนมัติ (ไม่ใช่แค่แสดงข้อมูลเฉยๆ)

**ไม่แตะ DB** — derive จาก `login_sessions` + `audit_logs` ที่มีอยู่แล้ว
(single source of truth ไม่ต้อง sync ตารางใหม่)

## Test count: 310 passed (23 ใหม่ + 287 เดิม, no regression จากงานนี้)

```
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py \
  --ignore=tests/test_l1_oidc.py \
  --ignore=tests/test_l1_oidc_authlib.py
======================== 5 failed, 310 passed in 53.77s ========================
```

(5 failed = บั๊กเดิม `test_passkey_security.py::test_account_endpoints_reject_non_admin`
ก่อนงานนี้ — ยืนยันด้วย git stash ใน report ก่อนหน้า ไม่เกี่ยวกับ incident)

## Sections (`tests/test_incidents.py` — 23 tests)

**1. Entry channel mapping** — `_entry_channel(login_method, subsystem_name)`:
- google + Hub → "Google OAuth (Hub Console)" · `GET /auth/google/callback`
- google + subsystem → "Google OAuth (ระบบย่อย)" · `GET /oauth/callback` · target = ชื่อ subsystem
- passkey / discoverable → endpoint ถูก
- login_method แปลกๆ → endpoint "—" (ไม่ crash)

**2. Session status** — `_session_status`: ended (logout_at set) / active (ยังเปิด +
อยู่ใน JWT window) / expired (JWT หมดแต่ไม่ถูกตัด)

**3. Recommendations (auto-suggest)** — `build_recommendations` ยิง action ถูกตาม signal:
- attack_ip → critical + link `/ip-blacklist`
- impossible_travel / is_new_country → critical/warning "login ผิดปกติ"
- failed_logins_24h → warning brute force
- is_account_takeover → critical "incident response เต็มรูปแบบ"
- session active + risk ≥ 0.5 → critical "เร่ง force-revoke"
- subsystem เป็นเป้า + block/challenge → info "review Access Policy" + link `/subsystems/{id}`
- ไม่มี signal → fallback "ตรวจสอบด้วยตนเอง"
- **เรียง critical → warning → info เสมอ** (ด่วนสุดขึ้นก่อน)

**4. list_incidents** — คืนเฉพาะ session flagged (`decision ∈ INCIDENT_DECISIONS`
หรือ `is_attack_ip`) — ยืนยัน `"allow" not in INCIDENT_DECISIONS` + ทุก item ที่คืน
มาต้อง flagged จริง + KPIs (total/blocked/challenged/attack_ip)

**5. get_incident_detail** — โครงสร้างครบ 4 ส่วน (entry/detected/impact/
recommendations/user) + timeline ใน impact + คืน None ถ้าไม่พบ (→ 404)

**6. HTTP auth** — `/admin/incidents` + `/admin/incidents/{id}`:
- ไม่มี token → 401/403
- admin → 200
- teacher (non-admin) → 403
- detail id มั่ว → 404

## Manual E2E verification (ผ่าน frontend proxy จริง — localhost:3000 + 8000)

mint admin token → set cookie → ยิงผ่าน `/api/proxy`:

| # | Test | Result |
|---|------|--------|
| 1 | `GET /admin/incidents?hours=2160` — คืน 91 incidents จริงจาก historical sessions | ✅ |
| 2 | list row มี channel_label / target / decision / status / top_reason ครบ | ✅ |
| 3 | `GET /admin/incidents/{id}` — entry/detected/impact/recommendations ครบ | ✅ |
| 4 | recommendations ยิงถูกตาม reasons จริง (new_country → warning + link `/users?q=...`) | ✅ |
| 5 | timeline cap ที่ 20 events (admin ที่ active มากเคยได้ 37 → cap แล้ว) | ✅ |
| 6 | `GET /incidents` (หน้า Next.js) → 200 + heading "เหตุการณ์เสี่ยง" render | ✅ |
| 7 | `hours` เกิน 2160 (90 วัน) → 422 validation (กัน query กว้างเกิน) | ✅ |

## Files

**Backend:**
- `app/services/incident_service.py` (ใหม่) — entry channel map, session status,
  recommendations engine, list/detail
- `app/routers/admin.py` — `GET /admin/incidents` + `GET /admin/incidents/{id}`

**Frontend:**
- `app/(console)/incidents/page.tsx` (ใหม่) — triage list + KPIs + filter + drawer
- `app/(console)/incidents/_components/IncidentSummary.tsx` (ใหม่) — narrative 4 ส่วน
- `app/(console)/incidents/_types.ts` (ใหม่)
- `components/Sidebar.tsx` — nav entry "🚨 เหตุการณ์เสี่ยง"

## Compliance / conventions

- Endpoint ใหม่มี `Depends(require_hub_admin)` (B1) ✅ — read-only ไม่ต้อง step-up
- ไม่แตะ schema — reuse `login_sessions` + `audit_logs`
- Timeline query cap 20 rows (กัน N+1 / payload ใหญ่จาก user active มาก)
- `hours` มี upper bound 2160 (90 วัน) กัน full-table scan
