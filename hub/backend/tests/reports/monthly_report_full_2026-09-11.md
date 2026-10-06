# Monthly Report ฉบับเต็ม — ขยาย `GET /admin/reports/monthly`

**วันที่:** 2026-09-11
**ต่อจาก:** `monthly_report_2026-09-10.md` (ฉบับแรก 16 tests)
**ไฟล์เทสต์:** `tests/test_monthly_report.py` (34 tests)
**รัน:** `docker compose exec hub-backend pytest tests/test_monthly_report.py -v`

---

## 1. ที่มา

ผู้ใช้ส่งแม่แบบ `Monthly_Report_May_2026.docx` ขอให้รายงานละเอียดขึ้นแบบนั้น

ตัวเลขในแม่แบบเป็นตัวอย่าง (48,291 logins, ระบบจัดการการลา ฯลฯ) ไม่ใช่ข้อมูลของระบบนี้ —
ใช้เฉพาะ **โครง** ของรายงาน ตัวเลขทุกตัวดึงจาก DB จริง และไม่ใช้ emoji ตามแม่แบบ

ผู้ใช้เลือก (AskUserQuestion):

| คำถาม | คำตอบ |
|---|---|
| ข้อความสรุป / ข้อเสนอแนะ / บทสรุป | ร่างอัตโนมัติจากกฎ + แก้ได้บนหน้าเว็บก่อนพิมพ์ (ไม่บันทึก) |
| Uptime และ CPU/Memory/Disk | ใช้ผลสุ่มตรวจสุขภาพ + ตัด CPU ออก |
| รูปแบบ | หน้าเว็บแบบเอกสาร A4 + PDF |
| ภาคผนวกประสิทธิภาพ API | ใส่ |

## 2. หมวดในแม่แบบ → แหล่งข้อมูลจริง

| หมวดในแม่แบบ | ฟิลด์ใหม่ | แหล่งข้อมูล |
|---|---|---|
| สรุปผู้บริหาร + ข้อสังเกต | `narrative.summary`, `findings[]` | กฎบนตัวเลขในรายงาน |
| ตัวชี้วัดหลัก (8 ใบ) | `logins`, `risk`, `availability`, `api_overall`, `subsystem_status` | login_sessions, audit_logs, request_logs, subsystems |
| การใช้งานแต่ละระบบ | `by_subsystem[]` (+users, blocked, challenged, block_rate) | login_sessions |
| Uptime ต่อระบบ | `availability.units[]` | audit `subsystem_health_summary` (3 ครั้ง/วัน) — **ผลสุ่มตรวจ ไม่ใช่ uptime** |
| เหตุการณ์ความปลอดภัย | `security_events[]`, `security_summary` | audit_logs (19 action), api_alerts, ip_blacklist |
| ข้อเสนอแนะ | `recommendations[]` | กฎจาก findings + คำขอระบบย่อยค้าง |
| แนวโน้ม 6 เดือน | `trend[]` | login_sessions (คอลัมน์ uptime ตัดออก) |
| บทสรุป | `narrative.conclusion` | findings ระดับ critical / warn |
| ภาคผนวก API | `api_performance[]`, `api_overall` | request_logs — avg / P95 / P99 (`percentile_cont`) / 5xx |
| False positive rate | `ml_feedback` | ml_feedback — **ไม่คำนวณถ้า label < 30** (ตอนนี้มี 8 ทั้งระบบ) |
| CPU / Memory / Disk | — | **ไม่มีการเก็บที่ไหนเลย** → `unavailable: ["resource_usage"]` |
| วิธียืนยันตัวตน / ประเทศ | `login_methods[]`, `geo[]` | login_sessions (country ว่าง = None ไม่เดาว่าไทย) |

## 3. กฎ findings / recommendations

pure function (`build_findings`, `build_recommendations`, `build_narrative`) ทดสอบได้โดยไม่ต้องใช้ DB
ทุกข้อมี `basis` เก็บตัวเลขที่ใช้ตัดสิน · เกณฑ์ตั้งให้ไม่ตัดสินจากตัวอย่างน้อยเกินไป

| code | เงื่อนไข | ระดับ | ข้อเสนอแนะ |
|---|---|---|---|
| `availability_low` | ระบบใดปกติ < 99% ของการตรวจ | < 90% critical · อื่น warn | high |
| `api_alert_critical` | api alert ระดับ critical > 0 | critical | high |
| `server_error_rate` | กลุ่ม API ≥ 50 request และ 5xx ≥ 1% | warn | medium |
| `subsystem_block_rate_high` | ระบบย่อย ≥ 10 login, block ≥ 2% และ ≥ 2 เท่าของภาพรวม | warn | medium |
| `block_rate_up` | block rate เพิ่ม ≥ 1 จุด % จากเดือนก่อน | warn | medium |
| `logins_change` | login เปลี่ยน ≥ 20% | info | — |
| `ml_labels_insufficient` | label < 30 | info | low |
| `no_health_samples` | ไม่มีผลตรวจสุขภาพในเดือน | info | low |
| `foreign_logins` | มี login จากประเทศอื่นที่ไม่ใช่ TH | info | — |
| `no_logins` | ไม่มี login | info | — |
| `pending_subsystems` | (recommendation) มีคำขอระบบย่อยค้าง | — | medium |

## 4. Test cases ที่เพิ่ม (18 → รวม 34)

ข้อมูลเสริมใน ก.พ. 2001 + ตัวหลอกนอกเดือน (1 มี.ค. / 2 มี.ค.) ลบทิ้งท้ายเทสต์

| Test | ตรวจอะไร |
|---|---|
| `test_uptime_declared_unavailable` (แก้) | ประกาศ `subsystem_uptime` + `resource_usage` · ห้ามมีฟิลด์ `uptime` |
| `test_full_structure` | key ใหม่ครบ 13 ตัว |
| `test_by_subsystem_detail` | users 2 · blocked 1 · challenged 1 · block_rate 25.0 |
| `test_login_methods_and_geo` | google 4 · country None (ไม่เดา) |
| `test_trend_six_months` | 2000-09 → 2001-02 เรียงเก่า→ใหม่ · เดือนว่าง block_rate None |
| `test_availability_from_health_snapshots` | 2 snapshot ในเดือน (ตัว 1 มี.ค. ไม่นับ) · hub 100% · sub-x 50% |
| `test_api_performance` | oauth 4 req · avg 250 · P95 385 · P99 397 · 5xx 25% · ไม่นับนอกเดือน · ไม่แสดงกลุ่มว่าง |
| `test_security_events_and_summary` | รวม action เดียวกันวันเดียวกัน (count 2) · ไม่มี hub_login_success · api alert critical/warning/unresolved · blacklist 1 · force logout 1 |
| `test_subsystem_status_and_ml_feedback` | label 1 → fp_rate None · min_labels ≥ 30 |
| `test_findings_and_recommendations_from_real_data` | availability_low critical (SubX) · api_alert_critical · ไม่มี block_rate_up (50%→25%) · เรียง high→low |
| `test_narrative_uses_real_numbers` | มี "กุมภาพันธ์" และ "4 ครั้ง" |
| `test_empty_month_full_report_is_honest` | เดือนว่าง: availability/api/events ว่าง · avg_ms None · no_logins + no_health_samples |
| `test_rule_subsystem_block_rate_high` | B 10% เทียบภาพรวม 2% → เจอ |
| `test_rule_subsystem_block_rate_ignores_tiny_samples` | 3 login → ไม่ตัดสิน |
| `test_rule_server_error_rate` | 2% ของ 200 req → warn + medium |
| `test_rule_block_rate_up` | 2% → 5% · basis ตรง |
| `test_rule_pending_subsystems_recommendation` | pending 2 → มีข้อเสนอแนะ |
| `test_narrative_no_urgent_issue` | ไม่มี finding → "ไม่พบประเด็นเร่งด่วน" |
| `test_conclusion_groups_repeated_findings` | ชนิดเดียวกัน 3 รายการ → "เร่งด่วน 1 เรื่อง … (และอีก 2 รายการ)" |

## 5. RED → GREEN → REFACTOR

### RED (ใส่ stub `NotImplementedError` ให้ import ผ่าน เพื่อเห็น fail รายเทสต์ ไม่ใช่ collection error)
```
18 failed, 15 passed in 9.89s        (15 = ของเดิม · 0 skipped)
```

### GREEN
```
33 passed in 12.53s
```

### ข้อค้นพบจากข้อมูลจริง → RED/GREEN รอบย่อย
ดึงรายงาน 2026-08 จริง: dev ไม่ได้รันระบบย่อย + Hub degraded (ML ConnectTimeout) →
`availability_low` 7 รายการ บทสรุปไล่ครบ 7 ข้อความยาวเกินสำหรับผู้บริหาร
เพิ่ม `test_conclusion_groups_repeated_findings` ก่อน:
```
RED    1 failed, 33 passed   ("เร่งด่วน 3 เรื่อง: S0 …; S1 …; S2 …")
GREEN  34 passed in 7.75s
```

### REFACTOR — ruff
```
ruff check    All checks passed!
ruff format   2 files reformatted → 1 file reformatted (รอบย่อย)
pytest        34 passed
```
ลบ helper `_api_stats` ที่เขียนค้างไว้และไม่มีใครเรียก

### ความสะอาดของข้อมูลทดสอบ
หลังรัน นับแถวก่อนปี 2002 ในทุกตารางที่เทสต์เขียน (login_sessions, audit_logs, api_alerts,
request_logs, ip_blacklist, ml_feedback) = **0 ทุกตาราง**

## 6. Regression — full suite
```
docker compose exec hub-backend pytest . -q --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
1 failed, 1108 passed, 62 skipped in 193.53s
FAILED tests/test_expert_review_db.py::test_round1_locked_after_unblind  (assert 401 == 200)
```
สองไฟล์ที่ ignore เป็นสคริปต์ที่เรียก `sys.exit` ตอน import ทำให้ pytest หยุด collect ทั้งชุด

**เทสต์ที่ fail ไม่เกี่ยวกับงานนี้:**
- รันเดี่ยว → `1 passed in 2.22s` → ขึ้นกับลำดับการรัน (token ของผู้ใช้ในเทสต์ถูกทำให้ใช้ไม่ได้โดยเทสต์อื่นก่อนหน้า)
- ไฟล์ expert review มาจาก commit `08e789a` (2026-09-11 01:23) ของงานอื่น ไม่มีการแก้ค้างในรอบนี้
- endpoint รายงานเป็น read-only ไม่แตะ user / token / ตาราง expert review
- ยังไม่แก้ในรอบนี้ — แจ้งผู้ใช้แยก

## 7. ข้อมูลจริง เดือน 2026-08 (endpoint ที่รันอยู่)

```
logins 607 · users 2 · blocked 45 (7.4%) · challenged 90
trend        2026-03 … 2026-08 (มี.ค./เม.ย. = 0 เพราะข้อมูลเริ่ม 18 พ.ค.)
availability 10 snapshot · ปกติรวม 4.3% (ระบบย่อยไม่ได้รันใน dev · Hub degraded จาก ML timeout)
api_overall  15,184 req · avg 138.1 ms · P95 156 ms · P99 3,625 ms · 5xx 0.4%
security     13 แถว · api alert 2 (warning) · IP เข้า blacklist 3,407 (ส่วนใหญ่จากฟีด ipsum)
ml_feedback  label 1 → fp_rate None
findings 10 · recommendations 3
conclusion   "พบประเด็นที่ควรดำเนินการเร่งด่วน 1 เรื่อง: Hub (Central Auth) อยู่ในสถานะปกติ 0 จาก 10 ครั้งที่ตรวจ (0.0%) (และอีก 6 รายการ)"
```

## 8. Frontend

แยกเนื้อหาเอกสารเป็น `reports/monthly/_components/ReportDocument.tsx` (render จาก data อย่างเดียว)
+ `_types.ts` · `page.tsx` เหลือ state / fetch / แถบคำสั่ง

หมวดในเอกสาร: 01 สรุปผู้บริหาร · 02 ตัวชี้วัดหลัก · 03 การใช้งานแต่ละระบบ + ผลตรวจสุขภาพ ·
04 ภาพรวมการเข้าสู่ระบบ · 05 เหตุการณ์ความปลอดภัย · 06 ข้อเสนอแนะ (แก้ / ลบ / เพิ่ม / เปลี่ยนความสำคัญ) ·
07 แนวโน้ม 6 เดือน · 08 บทสรุป · ภาคผนวก ก API · ภาคผนวก ข ข้อจำกัดของข้อมูล

**ตรวจด้วย component จริง** — ไม่เขียน harness เลียนแบบ markup: transpile `ReportDocument.tsx`
ด้วย sucrase ในคอนเทนเนอร์ frontend แล้ว `renderToStaticMarkup` ด้วย JSON เดือน 2026-08 จริง

| จุดตรวจ | ผล |
|---|---|
| `tsc --noEmit` | exit 0 |
| dev server compile `/reports/monthly` | ไม่มี error (ไม่มี token → 307 ไป login ตาม middleware) |
| desktop 1280px | 10 หมวด · KPI 4 คอลัมน์ · ไม่มีตาราง/ช่องล้น · ไม่มี scroll แนวนอน |
| กฎดีไซน์ | หัวหมวด 700 · หัวย่อย 500 · เนื้อหาตาราง 400 · มุมเหลี่ยม 0px · Sarabun · ไม่มี emoji |
| print (A4 703px) | แถบคำสั่ง + ปุ่มลบ/เพิ่มถูกซ่อน · ไม่มีตารางล้น · KPI 4 คอลัมน์ · หัวหมวดไม่ค้างท้ายหน้า · แถวตารางไม่ถูกตัด · ≈ 5 หน้า A4 |

## 9. Security checks

| กฎ | สถานะ |
|---|---|
| B1 — endpoint ยังมี `Depends(require_hub_admin)` | ผ่าน (`test_requires_auth`, `test_non_admin_forbidden`) |
| read-only — ไม่เปลี่ยนสถานะ ไม่ต้อง `log_action` | ข้อความที่แก้บนหน้าไม่ถูกส่งกลับ backend |
| ไม่มีค่าสมมติ | fp_rate / avg_ms / block_rate เป็น None เมื่อข้อมูลไม่พอ · uptime ไม่ถูกตั้งชื่อเกินหลักฐาน |
| ไม่ใส่ข้อมูลส่วนบุคคลในรายงาน | timeline รวมเป็นจำนวนต่อวัน ไม่แสดง IP / อีเมล |
| Scoring freeze | ไม่แตะ rule_engine / risk_engine |
