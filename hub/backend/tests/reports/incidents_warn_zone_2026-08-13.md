# Incidents — ครอบคลุมทุกบัญชีที่เข้าเงื่อนไข (warn zone)

**วันที่:** 2026-08-13
**ขอบเขต:** ขยายเกณฑ์หน้า "เหตุการณ์เสี่ยง" (Incidents) ให้จับ *ทุก* session ที่ RBA flag
**ไฟล์ที่แก้:** `app/services/incident_service.py`, `app/routers/admin.py` (docstring)
**ไฟล์เทส:** `tests/test_incidents.py` (+2 tests)

---

## 1. ปัญหาที่พบ

เคสจริงจากหน้า ML/anomaly: session `U08@example.invalid` → `risk_score = 0.600`,
`decision = WOULD_WARN` **ไม่ปรากฏ**ในหน้า Incidents

**สาเหตุ (2 ชั้นพร้อมกัน):**

| ตัวกรอง | ค่าเดิม | ผลกับเคสนี้ |
|---------|--------|-------------|
| `INCIDENT_DECISIONS` | ไม่มี `warn` / `would_warn` | ❌ ตกหล่น |
| `INCIDENT_RISK_SCORE_MIN` | `0.7` (challenge threshold) | ❌ 0.600 < 0.7 |

RBA threshold จริง (`app/security/risk_aggregator.py:THRESHOLDS`):
`warn 0.5` · `challenge 0.7` · `block 0.85`
→ โซน **warn (0.5–0.7)** ถูก flag โดย RBA แต่หลุดจากหน้า triage ทั้งหมด

---

## 2. การแก้ไข

```python
# app/services/incident_service.py
INCIDENT_DECISIONS = (
    "block", "would_block", "challenge", "would_challenge",
    "would_mfa", "mfa", "mfa_required", "mfa_passed",
    "warn", "would_warn",          # ← เพิ่ม
)

INCIDENT_RISK_SCORE_MIN = 0.5      # ← เดิม 0.7 (ผูกกับ THRESHOLDS["warn"])
```

เงื่อนไขเข้า Incidents (OR gate — ไม่มี dedup/limit ต่อบัญชี):
1. `decision ∈ INCIDENT_DECISIONS` (warn ขึ้นไป)
2. `is_attack_ip = True`
3. `risk_score >= 0.5`

`allow` ที่คะแนนต่ำยังไม่เข้า (หน้านี้ไม่ใช่ log ทุก login)

---

## 3. ผลการทดสอบ

### 3.1 test_incidents.py (ไฟล์ที่เกี่ยวข้องโดยตรง)

```
docker compose exec hub-backend pytest tests/test_incidents.py -v
```

```
collected 40 items
...
tests/test_incidents.py::test_list_incidents_shape PASSED                [ 40%]
tests/test_incidents.py::test_incident_decisions_excludes_allow PASSED   [ 42%]
tests/test_incidents.py::test_list_incidents_includes_high_risk_score_even_if_decision_allow PASSED [ 45%]
tests/test_incidents.py::test_incident_timeline_two_strands PASSED       [ 50%]
...
tests/test_incidents.py::test_list_incidents_includes_warn_zone_sessions PASSED [ 97%]
tests/test_incidents.py::test_incident_threshold_matches_rba_warn_threshold PASSED [100%]

============================== 40 passed in 3.29s ==============================
```

**เทสใหม่ 2 ตัว:**

| Test | ตรวจอะไร |
|------|----------|
| `test_list_incidents_includes_warn_zone_sessions` | สร้าง session `risk_score=0.6 / would_warn` → ต้องปรากฏใน `list_incidents()` |
| `test_incident_threshold_matches_rba_warn_threshold` | `INCIDENT_RISK_SCORE_MIN == THRESHOLDS["warn"]` (กันค่า drift) + `allow` ยังไม่เข้า |

### 3.2 Full suite (regression)

```
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
```

```
============ 1 failed, 662 passed, 41 skipped in 145.88s (0:02:25) =============
FAILED tests/test_scope_conformance.py::test_scope1_student_blocked_hub_direct
```

**ตัวที่ fail — ไม่เกี่ยวกับการแก้ครั้งนี้:**
```
assert 429 in (302, 307, 400, 401)
WARNING slowapi: ratelimit 10 per 1 minute (testclient) exceeded at endpoint: /auth/google/login
```
เป็น **rate-limit flake** (เทสก่อนหน้ายิง `/auth/google/login` จนเกิน 10/นาที)
ยืนยันโดยรันเดี่ยวหลังพ้น window:

```
docker compose exec hub-backend pytest tests/test_scope_conformance.py::test_scope1_student_blocked_hub_direct -q
```
```
tests/test_scope_conformance.py .                                        [100%]
============================== 1 passed in 1.33s ===============================
```

---

## 4. Security check

| ประเด็น | สถานะ |
|---------|-------|
| RBAC — `/admin/incidents` ต้องเป็น hub admin | ✅ ไม่แตะ `Depends(require_hub_admin)` · `test_http_incidents_rejects_non_admin` ผ่าน |
| Step-up ยังบังคับกับ action อันตราย | ✅ `test_http_action_requires_stepup` ผ่าน |
| ไม่เปิดเผยข้อมูลเกินสิทธิ์ | ✅ เปลี่ยนแค่ "เกณฑ์คัดกรองแถว" ไม่แตะ field ที่คืน |
| ไม่กลายเป็น log ทุก login | ✅ `allow` คะแนนต่ำยังไม่เข้า (`test_incident_decisions_excludes_allow`) |

---

## 5. ผลกระทบที่ต้องรู้

- **จำนวนแถวในหน้า Incidents จะเพิ่มขึ้น** — โซน warn (0.5–0.7) เข้ามาด้วย
  ตามเจตนา "ทุกบัญชีที่เข้าเงื่อนไข ต้องไม่ตกหล่น"
- KPI `total` เพิ่มตาม · `blocked` / `challenged` นับเท่าเดิม (แยกตามความรุนแรง)
- ถ้าภายหลังอยากลดเสียงรบกวน: กรองที่ UI (filter decision) ดีกว่าย้อนกลับไปตัดที่ backend
  เพราะการตัดที่ backend = admin ไม่มีทางรู้ว่ามีอะไรถูกซ่อน

---

## 6. Reproduce

```bash
docker compose up -d postgres redis hub-backend
docker compose exec hub-backend pytest tests/test_incidents.py -v
```
