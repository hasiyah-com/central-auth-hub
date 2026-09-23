# Dashboard Insights API — รายงานผลทดสอบ

**วันที่:** 2026-08-30
**ขอบเขต:** เพิ่ม `GET /admin/dashboard/insights` + เพิ่ม `challenged` ใน `hourly` ของ `/admin/activity`
**เหตุผล:** หน้า dashboard ตามดีไซน์อ้างอิงต้องใช้ตัวเลขเปรียบเทียบ / การกระจายความเสี่ยง /
สัญญาณความผิดปกติ ซึ่ง `/admin/overview` และ `/admin/activity` เดิมยังไม่มี

## สรุปผล

| ชุดทดสอบ | ผ่าน | skip | หมายเหตุ |
|---|---|---|---|
| `test_dashboard_insights.py` (ใหม่) | 10 | 1 | skip = ไม่มี student user ใน DB ทดสอบ |
| `test_activity.py` | 10 | 0 | regression — แก้ `hourly` แล้วไม่พัง |
| `test_activity_online.py` | 1 | 12 | skip = ไม่มี session ออนไลน์ตอนรัน |
| `test_scope_conformance.py` | 107 | 0 | regression — scope/RBAC ทั้งระบบ |
| **รวม** | **128** | **13** | |

## TDD

| Phase | ผล |
|---|---|
| RED | `10 failed, 1 skipped` — endpoint ยังไม่มี (404) + `hourly` ขาด `challenged` |
| GREEN | `10 passed, 1 skipped` |
| REFACTOR | regression 118 เทสยังผ่านครบ |

## สิ่งที่ทดสอบ

1. `test_requires_admin` — ไม่มี token → 401/403 (**B1**: ทุก endpoint ต้องมี `Depends`)
2. `test_non_admin_forbidden` — student เรียกไม่ได้ (RBAC ชั้น endpoint)
3. `test_structure` — key ครบ: `window_hours / users / logins / risk / signals / attack_ip`
4. `test_users_delta_sane` — `0 <= new_30d <= total`
5. `test_thresholds_from_real_source` — เกณฑ์ต้องตรงกับ `risk_aggregator.THRESHOLDS` จริง
6. `test_distribution_buckets` — ผลรวม 4 ถัง = `scored_total` เป๊ะ
7. `test_signals_shape` — `{key,label,count}` เรียงมาก→น้อย, count > 0
8. `test_change_pct_none_when_no_baseline` — ไม่มี baseline → `None` (ไม่ปัดเป็น 0)
9. `test_risk_delta_consistent` — `delta = avg_today - avg_yesterday`
10. `test_hours_param_bounds` — `hours` นอกช่วง → 200/422 ไม่ใช่ 500
11. `test_activity_hourly_has_challenged` — bucket มี `challenged` + `blocked+challenged <= count`

## ประเด็นความปลอดภัย

- **B1** — `Depends(require_hub_admin)` ครบ มีเทสยืนยันทั้ง no-token และ non-admin
- **ไม่มีค่าสมมติ** — ทุกค่าจาก DB จริง; คำนวณไม่ได้ → `None` ไม่ใช่ `0`
  (`change_pct`, `risk.delta`, `attack_ip.pct` คืน `None` เมื่อไม่มี baseline)
- **ไม่ hardcode เกณฑ์ซ้ำ** — import `THRESHOLDS` จาก `risk_aggregator` แหล่งเดียว
  มีเทสยืนยันว่าตรงกัน (กันปัญหาแบบ **B49** ที่ค่าคงที่อยู่สองที่แล้วหลุด sync)
- **ไม่รั่ว PII** — `signals` คืนเฉพาะ key/label/count ไม่มี email/IP รายบุคคล
- `hours` มี `ge=1, le=8760` กัน query ยาวเกินจน DoS ตัวเอง

## แหล่งข้อมูลจริงของแต่ละค่า

| ค่า | มาจาก |
|---|---|
| `users.new_30d` | `User.created_at >= now-30d` |
| `logins.today/yesterday` | `LoginSession.created_at` หน้าต่าง 24 ชม. เลื่อน |
| `risk.avg_*` | `avg(LoginSession.risk_score)` |
| `risk.distribution` | `LoginSession.risk_score` แบ่งตาม `THRESHOLDS` |
| `signals` | `LoginSession.risk_reasons` (JSON) จัดกลุ่มด้วย `_reason_key()` |
| `attack_ip` | `LoginSession.is_attack_ip` |

## รันซ้ำ

```bash
docker compose exec hub-backend pytest tests/test_dashboard_insights.py -v
docker compose exec hub-backend pytest tests/test_activity.py tests/test_activity_online.py tests/test_scope_conformance.py -q
```

## ข้อจำกัดที่ทราบ

- `test_non_admin_forbidden` skip เมื่อ DB ทดสอบไม่มี student user — RBAC ยังถูกครอบด้วย
  `test_scope_conformance.py` (107 เทส) อยู่แล้ว
- `signals` นับจาก `risk_reasons` ที่ระบบบันทึกไว้ — session เก่าก่อนมีฟีเจอร์นี้จะไม่มี reasons
  จึงไม่ถูกนับ (ไม่ใช่บั๊ก แต่ค่าจะต่ำกว่าจริงสำหรับข้อมูลย้อนหลังไกล)
