# PHP SDK — Security Audit (injection / code-execution focus)

| | |
|---|---|
| **วันที่** | 2026-06-15 |
| **ขอบเขต** | `hub/sdk/php-client/` ทั้งหมด (src 9 ไฟล์ + examples + RevocationStore + webhook) |
| **โฟกัส** | code injection, การยิงโค้ด (RCE/XSS/header injection/open redirect/SSRF/cache poisoning) |
| **ผลรวม** | ไม่พบ RCE/SQLi/code-injection · พบ hardening 3 จุด (1 medium, 2 low) |

---

## 1. สรุปผล — ปลอดภัยในแกนหลัก

| Vector | ผล |
|---|---|
| Code injection (eval/system/exec/shell) | ไม่มี (grep ยืนยัน — curl_exec เป็น false-positive) |
| Object injection (unserialize) | ไม่มี — ใช้ json_decode ล้วน |
| SQL injection | N/A — SDK ไม่มี DB (RevocationStore = JSON file) |
| dynamic include / extract / variable-variable | ไม่มี |
| XSS (examples) | ใช้ htmlspecialchars ทุกจุดแสดง claim (dashboard/profile/callback) |
| CSRF (state) | random_bytes + hash_equals + consume-before-compare |
| PKCE | random_bytes (CSPRNG) + SHA256 + S256 |
| Webhook spoof/replay | HMAC-SHA256 + timestamp tolerance + hash_equals |
| JWT forgery | verify signature + aud + iss + exp |
| Token theft (secret) | client_secret ส่ง server-side (POST form) เท่านั้น |

---

## 2. Findings (hardening)

### F1 [MEDIUM] Open redirect via return_path
**ที่:** Client::startLogin(returnPath) -> เก็บใน session -> callback.php ทำ
header('Location: ' . result['return_path'])

**ปัญหา:** SDK ไม่ validate return_path — ถ้า dev ดึงจาก user input
(เช่น startLogin(GET['next'])) ผู้โจมตีใส่ absolute URL -> open redirect
ไปเว็บฟิชชิ่ง (PHP header() บล็อก CRLF ตั้งแต่ 5.1.2 -> header injection ส่วนใหญ่กันได้
แต่ open redirect ยังเกิดได้)

**แก้:** validate ใน SDK — รับเฉพาะ relative path (reject ถ้ามี scheme / // / netloc / CRLF)

### F2 [LOW-MED] curl ไม่ตั้ง SSL verify ชัดเจน
**ที่:** TokenExchange, Discovery, JwtVerifier — curl ไม่ set SSL_VERIFYPEER/VERIFYHOST

**ปัญหา:** ช่องนี้รับส่ง client_secret + JWT — ถ้า php.ini ถูกตั้งปิด verify -> MITM
อ่าน secret ได้ ปัจจุบันพึ่ง default (ON) เฉยๆ

**แก้:** ตั้ง explicit (prod https): CURLOPT_SSL_VERIFYPEER=true, CURLOPT_SSL_VERIFYHOST=2

### F3 [LOW] JWKS/Discovery cache ใน sys_get_temp_dir() (shared /tmp)
**ที่:** JwtVerifier::jwksCacheFile, Discovery::cacheFile -> /tmp/cah_jwks_*.json

**ปัญหา:** บน shared hosting /tmp ใช้ร่วมกันหลาย tenant -> co-tenant เขียนทับ
ไฟล์ JWKS cache ด้วย key ของตัวเอง -> ปลอม JWT ผ่าน verify ได้ (cache poisoning)

**แก้:** เก็บ cache ใน app-private dir + perms 0600 ; dedicated server = ความเสี่ยงต่ำ

---

## 3. Info (ไม่ใช่ช่องโหว่ — บันทึกไว้)

- TokenExchange: ตัวแปร code ใช้ซ้ำ (auth code -> HTTP status) — ไม่ใช่บั๊ก
  (payload สร้างก่อน overwrite) แต่เป็น code smell
- JwtVerifier error msg ใส่ค่า aud/iss ของ token — แต่เป็นค่าจาก signed token
  (Hub คุม) ไม่ใช่ข้อมูลผู้โจมตี + examples escape ตอนแสดง -> low
- RevocationStore ใช้ hub_user_id เป็น JSON key — มาจาก webhook ที่ verify HMAC
  แล้ว (trusted) + json_encode escape -> ไม่มี injection

---

## 4. สรุป + สถานะแก้ (แก้แล้วทั้ง 3 — 2026-06-15)

| # | Severity | แก้ | สถานะ |
|---|---|---|---|
| F1 open redirect | MEDIUM | `Client::sanitizeReturnPath` — reject scheme/`//`/CRLF/backslash (relative-only) | ✅ |
| F2 SSL verify | LOW-MED | `CURLOPT_SSL_VERIFYPEER=true` + `VERIFYHOST=2` ทั้ง 3 curl | ✅ |
| F3 cache /tmp | LOW | `Config::cacheDir()` per-client subdir (0700) + ไฟล์ chmod 0600 + config `cache_dir` override | ✅ |

**Test:** `tests/HardeningTest_manual.php` → 14/14 (F1 10 cases + F3 4 cases)
**Lint:** php -l ผ่านทุกไฟล์ · copy ไป xampp แล้ว

แกน auth (PKCE/state/JWT/HMAC/secret-handling) ปลอดภัยดี — ไม่มีช่องฝัง/ยิงโค้ด
ที่เหลือเป็น defense-in-depth hardening

---

*ตรวจด้วย: อ่าน source ทุกไฟล์ + grep dangerous functions -> ไม่พบ eval/exec/unserialize/extract/include-var*
