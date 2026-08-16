# Incident Summary — 3 การ์ดต้องสอดคล้องกับระดับความเสี่ยง

**วันที่:** 2026-08-16
**ขอบเขต:** แก้การ์ด WHAT TO DO ในหน้ารายละเอียดเหตุการณ์เสี่ยง ให้เล่าเรื่องตรงกับ WHY/WHAT
**ไฟล์ที่แก้:** `app/services/incident_service.py` (`_build_summary` + `_summary_todo` ใหม่)
**ไฟล์เทส:** `tests/test_incidents.py` (+5 tests)
**วิธีทำ:** TDD — RED → GREEN → regression

---

## 1. ปัญหาที่พบ

หน้า Incident Detail แสดงสรุป 3 การ์ดที่**ขัดกันเอง**:

| การ์ด | ค่าที่แสดง |
|-------|-----------|
| WHY · ทำไมเสี่ยง | login จากอุปกรณ์ใหม่ |
| WHAT · เกิดอะไรขึ้น | **อนุญาต** |
| WHAT TO DO · ควรทำอะไร | **บล็อกการเข้าถึงทันที** ❌ |

**สาเหตุ:** `_build_summary` หยิบ **action แรกสุด**ที่ `executable && enabled` จาก playbook
มาแสดงเสมอ โดย**ไม่ดูระดับความเสี่ยงเลย**:

```python
todo = "ตรวจสอบด้วยตนเอง"
for a in actions:
    if a.get("executable") and a.get("enabled"):
        todo = a["title"]      # ← "บล็อกการเข้าถึงทันที" แม้ risk = 0.1
        break
```

ผลคือ login ปกติที่ระบบอนุญาต (risk ต่ำ) ก็ถูกแนะนำให้บล็อก → แอดมินตกใจเกินเหตุ
และลดความน่าเชื่อถือของหน้า triage

---

## 2. การแก้ไข

เพิ่ม `_summary_todo(ls, actions)` ที่เลือกคำแนะนำตามความรุนแรงจริง
(ใช้ `_risk_level()` = threshold เดียวกับ `risk_aggregator`)

| เงื่อนไข | คำแนะนำ |
|----------|---------|
| attack IP / account takeover / `block`,`would_block` / risk ≥ 0.7 | action เชิงรุกจาก playbook (เหมือนเดิม) |
| `mfa_passed` (และไม่เข้าเกณฑ์ข้างบน) | "ยืนยันตัวตนผ่านแล้ว — ไม่ต้องดำเนินการเพิ่ม" |
| `challenge`/`mfa`/`mfa_required`/`would_mfa`/`would_challenge` | "ระบบบังคับยืนยันตัวตนแล้ว — ติดตามผล ยังไม่ต้องระงับ" |
| risk 0.5–0.7 (medium/warn) | "ตรวจสอบเมื่อสะดวก — ยังไม่ถึงเกณฑ์ต้องระงับ" |
| ที่เหลือ (risk ต่ำ + อนุญาต) | "ไม่ต้องดำเนินการ — เฝ้าดูตามปกติ" |

WHY และ WHAT ไม่เปลี่ยน (ยึดข้อมูลจริงจาก RBA + `system_response.action_taken`)

---

## 3. ผลการทดสอบ

### 3.1 RED — เทสก่อนแก้ (ต้อง fail)

```
docker compose exec hub-backend pytest tests/test_incidents.py -k summary -q
```

```
FAILED tests/test_incidents.py::test_summary_low_risk_allow_does_not_recommend_block
FAILED tests/test_incidents.py::test_summary_mfa_passed_does_not_recommend_block
FAILED tests/test_incidents.py::test_summary_medium_risk_is_review_not_block
================== 3 failed, 2 passed, 40 deselected in 2.95s ==================
```

ข้อความ assert ยืนยันบั๊กตรงจุด:
```
AssertionError: assert 'บล็อก' not in 'บล็อกการเข้าถึงทันที'
```
(2 เคสเชิงรุก — high risk / attack IP — ผ่านอยู่แล้วตั้งแต่ RED ตามที่ควรเป็น)

### 3.2 GREEN — หลังแก้

```
docker compose exec hub-backend pytest tests/test_incidents.py -k summary -v
```

```
tests/test_incidents.py::test_summary_low_risk_allow_does_not_recommend_block PASSED [ 20%]
tests/test_incidents.py::test_summary_mfa_passed_does_not_recommend_block PASSED [ 40%]
tests/test_incidents.py::test_summary_high_risk_keeps_aggressive_action PASSED [ 60%]
tests/test_incidents.py::test_summary_attack_ip_keeps_aggressive_action PASSED [ 80%]
tests/test_incidents.py::test_summary_medium_risk_is_review_not_block PASSED [100%]

======================= 5 passed, 40 deselected in 2.02s =======================
```

### 3.3 Regression — ทั้งไฟล์ + ทั้ง suite

```
docker compose exec hub-backend pytest tests/test_incidents.py -q
============================== 45 passed in 3.99s ==============================
```

```
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
================= 668 passed, 41 skipped in 199.55s (0:03:19) ==================
```

**ไม่มี fail** (รอบนี้ไม่เจอ rate-limit flake ของ `test_scope1` ด้วย)

---

## 4. เทสที่เพิ่ม (5)

| Test | ตรวจอะไร |
|------|----------|
| `test_summary_low_risk_allow_does_not_recommend_block` | allow + risk 0.1 → ห้ามมีคำว่า "บล็อก" |
| `test_summary_mfa_passed_does_not_recommend_block` | mfa_passed + risk 0.3 → ไม่บล็อก |
| `test_summary_high_risk_keeps_aggressive_action` | would_block + risk 0.92 → ยังเสนอ "บล็อกการเข้าถึงทันที" |
| `test_summary_attack_ip_keeps_aggressive_action` | attack IP แม้ decision=allow → เชิงรุก |
| `test_summary_medium_risk_is_review_not_block` | would_warn + risk 0.6 → ให้ตรวจสอบ ไม่บล็อก |

---

## 5. Security check

| ประเด็น | สถานะ |
|---------|-------|
| ไม่ลดทอนการแจ้งเตือนของภัยจริง | ✅ attack IP / ATO / block / risk≥0.7 ยังเสนอ action เชิงรุกครบ (2 เทสคุม) |
| ไม่แตะ playbook `actions[]` | ✅ ปุ่มลงมือจริงยังมีครบทุกตัว เปลี่ยนแค่ "ประโยคสรุป" |
| ไม่แตะ RBAC / step-up | ✅ `require_hub_admin` + step-up gate เหมือนเดิม |
| ยึดความจริง (ไม่กลบ shadow mode) | ✅ WHAT ยังมาจาก `action_taken` ตรงๆ |

---

## 6. Reproduce

```bash
docker compose up -d postgres redis hub-backend
docker compose exec hub-backend pytest tests/test_incidents.py -k summary -v
```
