# Examples — Roster Receiver (ระบบเกรด pattern)

`roster_receiver_demo.py` — reference implementation ของการ sync roster
สำหรับระบบย่อยที่ **ข้อมูลถูกสร้างก่อน user login** (เกรด / HR / ลงทะเบียนเรียน).

## แนวคิด (ตามเอกสาร ข้อ 7 + ที่อาจารย์เสนอ)

```
1. ลงทะเบียน subsystem → ได้ client_secret + API key + เลือก Access Policy
2. subsystem ดึง roster:  GET /api/v1/roster  (header X-Api-Key)
   → Hub คืนเฉพาะคนที่ผ่าน policy: [{user_id, email, user_type}]   (3 field)
3. subsystem pre-create record ของตัวเอง (grade_records) ผูกด้วย user_id
4. user login จริง (OAuth) → JWT.sub = user_id → match record → แสดง UI ตาม user_type
```

## รัน demo

```bash
# 1. ออก API key + ตั้ง policy ที่หน้า admin subsystem detail (การ์ด Access Policy)
#    หรือผ่าน API: POST /developer/subsystems/{id}/rotate-api-key
# 2. รัน
python docs/examples/roster_receiver_demo.py --hub http://localhost:8000 --api-key rsk_xxxxx
```

ผลลัพธ์ตัวอย่าง:
```
[1] ดึง roster ... subsystem='ระบบเกรด' policy='role' count=72
[2] sync → สร้าง 72 grade records
[login] JWT.sub=<uuid> → UI นักศึกษา: ...@... เกรดเฉลี่ย = ยังไม่มี
[login] JWT.sub=<นอก roster> → 403 / สร้าง JIT
```

## นำไปใช้จริง

- เปลี่ยน `:memory:` sqlite เป็น postgres ของ subsystem
- เรียก `fetch_roster` + `sync_roster` เป็น cron (เช่นทุกชั่วโมง) + รับ webhook
  `access_updated/access_revoked` จาก Hub เพื่อ keep-fresh
- **match ด้วย `user_id` (UUID) เท่านั้น** — email/user_type ใช้แสดงผล/ตัดสิน UI
- ขอข้อมูลเต็ม (faculty/major/...) ตอน login ผ่าน OAuth scope — ไม่ดึงผ่าน roster

## ความปลอดภัย
- API key = read-only, เก็บ Argon2 hash ที่ Hub, rotate ได้
- roster ส่งแค่ 3 field (least privilege) — ข้อมูลเต็มไหลตอน login ตาม scope
- subsystem ไม่ active → roster 403 (เกณฑ์เดียวกับ login)
