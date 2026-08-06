# Redirect URI Validation — ปิด Zero-Tolerance Security Gap (REQ-SUB-02) 2026-07-26

## บริบท

`test-design-document.md §3.6.3` ระบุ Redirect URI validation (TC-SUB-04) เป็น
**Critical / zero-tolerance** — *"บล็อก release ถ้าไม่ผ่าน"* (open redirect เป็น OWASP risk).

ตรวจโค้ดจริงพบว่า `SubsystemCreate.redirect_uris: list[str]` **ไม่มี validator** — รับ
string อะไรก็ได้เข้า DB: `javascript:alert(...)`, `data:...`, ไม่มี scheme, ว่างเปล่า.

**ความเสี่ยง:**
- `javascript:`/`data:` scheme → XSS ถ้ามีจุดใน UI render redirect_uri เป็นลิงก์คลิกได้
- `http://` host จริง → auth code ส่งผ่าน query string plaintext (ดักฟังได้)
- string เสีย → พัง parse ที่อื่น (health-check/webhook ต้อง try/except กันไว้)

> หมายเหตุ: `/oauth/authorize` มี exact-match check อยู่แล้ว (กันปลอม redirect_uri
> ตอน flow) แต่**ตอนลงทะเบียนไม่มีการกรอง** — ค่าอันตรายเข้า DB ได้ตั้งแต่แรก

## วิธีแก้

เพิ่ม `_validate_redirect_uris()` + `@field_validator("redirect_uris")` บน **ทั้ง**
`SubsystemCreate` และ `SubsystemUpdate` (`hub/backend/app/routers/developer.py`):

```python
def _validate_redirect_uris(uris):
    if not uris: raise ValueError("ต้องมี redirect_uri อย่างน้อย 1 รายการ")
    for raw in uris:
        uri = (raw or "").strip()
        if not uri: raise ValueError("redirect_uri ห้ามว่าง")
        p = urlparse(uri)
        if p.scheme not in ("http", "https"):     # กัน javascript:/data:/ftp:
            raise ValueError(...)
        if not p.hostname:                          # ต้องมี host
            raise ValueError(...)
        if p.scheme == "http" and p.hostname not in {localhost,127.0.0.1,::1}:
            raise ValueError(...)                   # host จริงบังคับ https
```

**กฎ:** http/https เท่านั้น · มี host · http เฉพาะ localhost (dev) · reject ทั้ง request
ถ้ามีตัวใดเสีย (ไม่บันทึกครึ่ง ๆ) · trim whitespace ก่อนตรวจ

**Defense in depth 2 ชั้น:** (1) validator ตอนลงทะเบียน/แก้ (ใหม่) + (2) exact-match
ตอน `/oauth/authorize` (เดิม)

## ผลกระทบกับข้อมูลเดิม
Validator ทำงานที่ **input boundary เท่านั้น** — subsystem เดิมที่ redirect_uri เสีย
(เช่น `ttp://localhost:4000/`, status=suspended) ยังอ่านได้ปกติ ไม่พัง. active subsystem
ทั้งหมดใช้ `http://localhost:...` ซึ่ง valid (dev). จะโดนตรวจก็ต่อเมื่อมีการแก้ redirect_uri ใหม่

## ผลการทดสอบ (TDD RED → GREEN)

**RED** (ก่อน validator):
```
12 failed, 5 passed — ทุก URL อันตราย (javascript:/data:/ftp:/empty/http-real) ผ่านหมด
```

**GREEN** (หลัง validator):
```
tests/test_developer_redirect_uri.py .................  17 passed
```

| กลุ่ม | Test | ยืนยัน |
|---|---|---|
| Positive (TC-SUB-03) | https / localhost-http / multiple | URL ถูกต้องผ่าน |
| Negative (TC-SUB-04) | javascript:/data:/ftp://evil/no-scheme/no-host/empty/whitespace | reject (ValidationError) |
| Negative | http host จริง (ไม่ใช่ localhost) | reject (บังคับ https) |
| Negative | list ว่าง / มี URL เสียปน 1 ตัว | reject ทั้ง request |
| Update | valid ผ่าน · bad reject · None (ไม่แก้) ผ่าน | Update ก็ validate |

**Regression:**
```
test_developer_redirect_uri (17) · test_oauth_policy_integration (2) · test_access_policy (14)
test_roster (6) · test_critical_action_policy (7)
======================== 40 passed, 6 skipped ========================
```

## ไฟล์ที่แก้
- `hub/backend/app/routers/developer.py` — `_validate_redirect_uris()` + field_validator (Create+Update) + import field_validator
- `hub/backend/tests/test_developer_redirect_uri.py` — ใหม่ (17 tests)
- `docs/test-design-document.md` — RTM REQ-SUB-02 ❌→✅

## สถานะ RTM หลังปิด gap นี้
Zero-tolerance security item **ปิดครบแล้ว** — ไม่มี Critical gap เหลือ. RTM ✅ 32/45 (71%)
ช่องว่างที่เหลือเป็น Medium/Low (Developer Portal full flow, bulk CSV, subsystem business logic)
