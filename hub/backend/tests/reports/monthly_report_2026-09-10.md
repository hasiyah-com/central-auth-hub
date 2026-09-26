# Monthly Executive Report — `GET /admin/reports/monthly`

**วันที่:** 2026-09-10
**ไฟล์เทสต์:** `tests/test_monthly_report.py` (16 tests)
**รัน:** `docker compose exec hub-backend pytest tests/test_monthly_report.py -v`

---

## 1. ที่มา

ผู้ใช้ขอรายงานผลรายเดือนสำหรับผู้บริหาร โดยเลือก **เดือนตามปฏิทิน** และเทียบเดือนก่อน

ตรวจ endpoint เดิมแล้ว **ไม่มีตัวไหนรับช่วงวันที่หรือเดือนได้** — ทุกตัวเป็น "ย้อนหลัง N ชม. จากตอนนี้"

| endpoint | พารามิเตอร์เวลา |
|---|---|
| `/admin/activity` | `hours` ≤ 720 |
| `/admin/incidents` | `hours` ≤ 2160 |
| `/admin/dashboard/insights` | `hours` ≤ 8760 (เทียบวันนี้กับเมื่อวานเท่านั้น) |
| `/admin/audit` | ไม่มี |
| `/admin/overview` | ไม่มี (ยอดสะสมทั้งหมด) |

จึงเพิ่ม endpoint ใหม่ `GET /admin/reports/monthly?month=YYYY-MM`

## 2. ไฟล์ที่เพิ่ม/แก้

| ไฟล์ | สิ่งที่ทำ |
|---|---|
| `app/services/monthly_report.py` | ตรรกะรวมข้อมูล (ใหม่) |
| `app/routers/reports.py` | endpoint + ตรวจรูปแบบเดือน (ใหม่) |
| `app/main.py` | ลงทะเบียน router ที่ `/admin/reports` |
| `tests/test_monthly_report.py` | 16 tests (ใหม่) |

## 3. การออกแบบที่ต้องระวัง

**ขอบเดือนตามเวลาไทย** — DB เก็บ naive UTC ถ้าตัดเดือนตาม UTC session ช่วง 00:00–06:59 น.
ของวันที่ 1 จะหลุดไปอยู่เดือนก่อน จึงตัดตาม Asia/Bangkok (UTC+7, ไม่มี DST) แล้วแปลงเป็น UTC

**นิยามเดียวกับหน้าอื่นในคอนโซล** — ใช้ค่าคงที่ร่วม ไม่เขียนซ้ำ
- blocked / challenged → `_BLOCKED_DECISIONS`, `_CHALLENGED_DECISIONS` (ชุดเดียวกับ Activity/Dashboard)
- incident → `INCIDENT_DECISIONS` + `is_attack_ip` + `risk_score >= INCIDENT_RISK_SCORE_MIN` (ชุดเดียวกับหน้า Incidents)

**ไม่มีข้อมูล = 0 / None ห้ามค่าสมมติ**
- `success_rate`, `risk.avg` เป็น `None` เมื่อไม่มี session
- `change_pct` เป็น `None` เมื่อเดือนก่อนเป็น 0 (หารศูนย์ไม่ได้ ไม่คืน 0 หรือ 100)

**metric ที่ไม่มีข้อมูลรองรับ → ประกาศ ไม่เดา**
uptime ระบบย่อย: health history อยู่ใน Redis `subsystem:health:history:*` แค่ 288 จุด
(≈ 24 ชม., TTL 48 ชม.) ไม่มีตารางใน DB → ใส่ `"subsystem_uptime"` ใน `unavailable`
และเทสต์บังคับว่า**ห้ามมีฟิลด์ `uptime`**

## 4. Test cases (16)

| # | Test | ตรวจอะไร |
|---|---|---|
| 1 | `test_requires_auth` | ไม่มี token → 401/403 (B1) |
| 2 | `test_non_admin_forbidden` | teacher (ไม่ใช่ hub admin) → 401/403 |
| 3–8 | `test_invalid_month_rejected[×6]` | `2001-13`, `2001-00`, `abc`, `2001-2`, `01-2001`, `""` → 422 ไม่ใช่ 500 |
| 9 | `test_structure` | key ครบ + timezone = Asia/Bangkok |
| 10 | `test_login_counts_exact` | total 4 · unique 2 · blocked 1 · challenged 1 · allowed 2 · success 75.0% |
| 11 | `test_bangkok_month_boundaries` | UTC 31 ม.ค. 17:00 นับเป็น 1 ก.พ. · UTC 28 ก.พ. 17:00 ไม่นับ · 28 วันครบ |
| 12 | `test_risk_and_incidents` | avg 0.54 (ตัด None) · incidents 2 · attack IP 1 |
| 13 | `test_month_over_month` | ม.ค. 2 logins → ก.พ. 4 = +100.0% · blocked 1→1 = 0.0% |
| 14 | `test_by_subsystem_sums_to_total` | ผลรวมแยกระบบ = total |
| 15 | `test_empty_month_is_honest` | เดือนว่าง → 0 / None · MoM = None · 31 วันครบ |
| 16 | `test_uptime_declared_unavailable` | มี `subsystem_uptime` ใน unavailable · ไม่มีฟิลด์ uptime |

ข้อมูลทดสอบสร้างในเดือน ม.ค./ก.พ. 2001 (ไม่มีข้อมูลจริงปน) และลบทิ้งท้ายเทสต์ด้วย fixture `cleanup_sessions`

## 5. RED → GREEN

### RED รอบแรก — เจอปัญหาเทสต์ถูก skip เงียบๆ
```
9 failed, 7 skipped
SKIPPED ... ไม่พบ student user ใน DB — รัน seed_users ก่อน   (×7)
```
7 เทสต์ที่ถูกข้ามคือเทสต์ตัวเลขทั้งหมด — dev DB ไม่เหลือ student สถานะ `active`
(27 graduated · 29 resigned · 16 suspended · 1 deleted) และ `conftest._find_user` กรอง `status == "active"`

ถ้าปล่อยไว้ ตอน GREEN เทสต์เหล่านี้จะ "ข้าม" ต่อ ดูเหมือนผ่านทั้งที่ไม่เคยตรวจตัวเลขเลย (อาการเดียวกับ B61)
**แก้:** ใช้ `teacher_user` / `teacher_token` แทน — เทสต์ต้องการแค่ผู้ใช้ 2 คนที่ต่างกันและ token ที่ไม่ใช่ admin
ยืนยันแล้วว่า teacher ที่ fixture หยิบ (`risk-demo@uni.ac.th`) มี `is_hub_admin = False` · ไม่แก้ `conftest.py`

### RED รอบสอง
```
16 failed in 4.82s        (0 skipped — ทุกเทสต์ถูกรันจริง)
```

### GREEN
```
16 passed in 3.86s
```
ระหว่างเขียนแก้บั๊กในโค้ดตัวเองก่อนรัน: `func.cast(cond, Integer)` SQLAlchemy แปลงเป็นฟังก์ชัน `cast(a, b)`
ที่ Postgres ไม่มี → เปลี่ยนเป็น `case((cond, 1), else_=0)` แบบเดียวกับ `admin.py`

### REFACTOR — ruff
```
ruff check          All checks passed!
ruff format         2 files reformatted → 3 files already formatted
pytest (หลังจัดรูปแบบ)  16 passed in 4.09s
```

## 6. Regression — full suite
```
docker compose exec hub-backend pytest . -q --ignore=<สคริปต์ที่มี sys.exit ระดับ module>
1029 passed, 53 skipped in 182.56s
```
0 failed · `test_scoring_freeze.py` ผ่าน (service อ่านอย่างเดียว ไม่แตะตรรกะการให้คะแนน)
skip 53 เป็นของเดิม (เช่น `test_user_lifecycle` ที่ต้องใช้ student active)

## 7. ทดสอบกับเซิร์ฟเวอร์จริง (หลัง restart hub-backend)

```
2026-08 → HTTP 200 · logins 607 · users 2 · challenged 90 · blocked 45 · incidents 307 · days 31 · vs 2026-07 +56.8%
2026-09 → HTTP 200 · logins 408 · users 2 · challenged 73 · blocked 53 · incidents 231 · days 30 · vs 2026-08 -32.8%
ไม่มี token → 403
เดือนผิด   → 422
```
ตัวเลขมาจากข้อมูล dev (ส่วนใหญ่เป็น session ทดสอบ risk-demo) — incident สูงราว 50% ของ login
เพราะนิยาม incident ครอบคลุม warn / mfa_passed / risk ≥ 0.5 ตามหน้า Incidents

## 8. Security checks

| กฎ | สถานะ |
|---|---|
| B1 — endpoint มี `Depends(require_hub_admin)` | ผ่าน (tests 1–2) |
| input validation — เดือนผิดรูปแบบไม่หลุดเป็น 500 | ผ่าน (tests 3–8, `Query(pattern=...)`) |
| read-only — ไม่เปลี่ยนสถานะระบบ จึงไม่ต้อง `log_action` | ตามข้อกำหนด CLAUDE.md |
| UTC ใน DB / แสดงเวลาไทย | ผ่าน (test 11) |
| ไม่มีค่าสมมติ | ผ่าน (tests 15–16) |

## 9. Frontend

- หน้า `/reports/monthly` — เลือกเดือน (`<input type="month">` ค่าเริ่มต้น = เดือนที่แล้ว), KPI 5 ใบพร้อม % เทียบเดือนก่อน,
  สรุป, กราฟรายวัน, ตารางแยกระบบ, หมายเหตุ uptime
- ปุ่ม "พิมพ์ / บันทึก PDF" + print CSS (A4, ซ่อน sidebar/topbar/ปุ่ม)
- `middleware.ts` เพิ่ม `/reports` ใน `ADMIN_PATHS` · Sidebar เพิ่มเมนู Monthly Report
- `tsc --noEmit` exit 0

### ตรวจหน้าจริงด้วย harness (ข้อมูลจริงเดือน 2026-08 จาก endpoint)

| จุดตรวจ | ผล |
|---|---|
| desktop 1280px — KPI 5 คอลัมน์สูงเท่ากัน, ไม่มี scroll แนวนอน | ผ่าน |
| legend กราฟรายวัน | **เจอบั๊ก** กล่องสีซ้อนบนข้อความ — `.cx-panel > header span {display:block}` ของหัวแผงกินไปด้วย → เพิ่ม selector เจาะจงกว่า · หลังแก้สูง 13px บรรทัดเดียว |
| print (เปิด `@media print` บนจอ) กว้าง A4 703px | **เจอบั๊ก** KPI ถูก media query ≤1120px ตัดเป็น 3+2 เหลือช่องว่าง → บังคับ 5 คอลัมน์ตอนพิมพ์ + กราฟ 130px |
| print หลังแก้ | สูง 919px ≤ 1017px (พื้นที่ A4 หลังหักขอบ) → **จบใน 1 หน้า** · KPI ไม่ล้น · sidebar/ปุ่มถูกซ่อน |
