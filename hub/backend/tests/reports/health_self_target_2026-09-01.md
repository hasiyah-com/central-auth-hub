# B60 — Health check รายงาน "online" หลอก เมื่อ redirect_uri ชี้กลับมาที่ Hub เอง

**วันที่:** 2026-09-01
**อาการ:** Dashboard แสดง `SERVICE HEALTH MATRIX` = **1 / 6 healthy** โดยระบบย่อยจริง
(หอพัก/ห้องสมุด/เกรด) ขึ้น `down` ทั้งหมด latency 6,000–15,000 ms — แต่ตัวที่ขึ้น **healthy
ตัวเดียวกลับเป็น subsystem ทดสอบที่ไม่มีอยู่จริง**

---

## 1. สาเหตุ (3 ชั้น — ไม่ใช่บั๊ก UI)

UI ต่อกับ backend ถูกต้องอยู่แล้ว ตัวเลขที่เห็นคือ backend **รายงานตามจริง** ของ dev env ที่ข้อมูลรก

| # | สาเหตุ | ประเภท |
|---|---|---|
| 1 | subsystem container ทั้ง 3 ตัว `Exited (255)` ตอน Docker restart | environment |
| 2 | มี subsystem "ขยะ" 3 ตัวใน DB ที่ status=active แต่ไม่มีวัน healthy | ข้อมูล |
| 3 | **subsystem ที่ตั้ง `redirect_uri` ชี้มาที่ Hub เอง → ขึ้น `online` หลอก** | **บั๊กจริง** |

### บั๊กข้อ 3 (B60) — false positive
`ระบบเทสสส` ตั้ง `redirect_uri = http://localhost:3000/developer/subsystems/new`
(= หน้าคอนโซลของ Hub เอง) → health check ยิง `http://localhost:3000/health`
→ **Next.js rewrite ส่งต่อเข้า `hub-backend`** ตาม single-domain mode (passthrough มี `/health`)
→ ได้ HTTP 200 กลับมาจาก **ตัว Hub เอง** → บันทึกเป็น `online 584ms`

ผลเสีย: subsystem ที่ตั้งค่าผิด/ไม่มีอยู่จริง แสดงเป็น "ปกติ" บน SOC dashboard —
กลบสัญญาณจริง และทำให้ KPI healthy เชื่อถือไม่ได้

---

## 2. การแก้

### A. ข้อมูล (ทำแล้ว — ผู้ใช้อนุมัติ)
- เปิด `docker-compose.{dorm,library,grade}.yml` ทั้ง 3 stack
- `UPDATE subsystems SET status='suspended'` กับ 3 ตัวขยะ:
  `e2e-db-f4cc38` (โดเมนปลอม `e2e.example.com`), `ระบบเทส1` (XAMPP ไม่ได้เปิด),
  `ระบบเทสสส` (ชี้มาที่ frontend เอง) → active เหลือ 3 ตัวจริง

### B. โค้ด — self-target guard (`app/services/subsystem_health.py`)
- เพิ่ม `_origin_key(url)` — normalize `(host, port)` เติม default port ตาม scheme
- เพิ่ม `_self_origin_keys()` — เซตของ origin ที่เป็น "Hub เอง": `hub_base_url`,
  `admin_frontend_url`, `hub-backend:8000`, `hub-frontend:3000` — เก็บทั้งรูปแบบดิบ
  **และหลัง `_translate_for_docker`** (dev แปลง `localhost:3000` → `host.docker.internal:3000`)
- `_ping()` เช็คก่อนยิงจริง: ถ้า origin (หรือ raw redirect_uri) ตรงกับ Hub เอง →
  คืน `status="unknown"` + `self_target=True` + ข้อความบอกให้แก้ `redirect_uri`

**ทำไม `unknown` ไม่ใช่ `down`:** ระบบย่อยจริงอาจปกติดี — เราแค่ *เช็คไม่ได้*
(ใช้ vocabulary เดียวกับเคส `no redirect_uri` / SSRF blocked ที่มีอยู่เดิม)

**fail-safe (B21):** เทียบ origin พลาด → `log.warning` แล้วเช็คต่อตามปกติ health loop ไม่ล้ม

---

## 3. Test

ไฟล์: `tests/test_health_self_target.py` (9 tests)

| กลุ่ม | test | ยืนยัน |
|---|---|---|
| `_origin_key` | default port ตาม scheme · case-insensitive host · garbage → None | normalize ถูก |
| `_self_origin_keys` | ครอบ `hub_base_url` + `admin_frontend_url` · docker service names | เซต self ครบ |
| ป้องกัน over-block | `localhost:8001/8002/8003` + โดเมนภายนอก **ไม่** ถูกนับเป็น self | ระบบย่อยจริงยังเช็คได้ |
| `_ping` | console origin → `unknown` + `self_target` · hub_base_url → เช่นกัน | บั๊กหาย |
| `_ping` | ระบบย่อยจริง → **ไม่** ติด guard | ไม่ regression |

**ผลรัน (reproducible):**
```bash
docker compose exec -T hub-backend pytest \
  tests/test_health.py tests/test_health_history.py \
  tests/test_subsystem_health_ssrf.py tests/test_health_self_target.py -q
```
```
tests/test_health.py .....                    [ 18%]
tests/test_health_history.py .......          [ 44%]
tests/test_subsystem_health_ssrf.py ......    [ 66%]
tests/test_health_self_target.py .........    [100%]
=== 27 passed in 9.78s ===
```

> หมายเหตุ: `pytest -k health` ทั้งชุดจะ INTERNALERROR เพราะ `tests/test_e2e_full_stack.py`
> เรียก `sys.exit(0)` ตอน import (ปัญหาเดิม ไม่เกี่ยวกับการแก้นี้) → ระบุไฟล์ตรง ๆ แทน

---

## 4. ผลลัพธ์จริงหลังแก้

| ระบบย่อย | ก่อน | หลัง |
|---|---|---|
| ระบบหอพัก | down · 6,344 ms | **online · 76 ms** |
| ระบบห้องสมุด | down · 15,214 ms | **online · 35 ms** |
| ระบบเกรดนักศึกษา | down | **online · 52 ms** |
| `e2e-db-f4cc38` / `ระบบเทส1` / `ระบบเทสสส` | active (1 ตัว online หลอก) | suspended — ไม่นับใน matrix |

**SERVICE HEALTH MATRIX: 1 / 6 healthy → 3 / 3 healthy**

> `uptime %` จะยังต่ำอยู่ช่วงแรกเพราะคำนวณจาก history ที่มีช่วง down ปนอยู่ —
> จะไต่ขึ้นเองเมื่อ health loop (ทุก 5 นาที) สะสมจุดใหม่

**ไม่ได้แก้ UI แม้แต่บรรทัดเดียว** — กราฟ/การ์ด/เลย์เอาต์เหมือนเดิมทุกอย่าง
