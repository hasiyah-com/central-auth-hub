# Security fixes — Batch 2 (#5 SSRF health checker + #9 open redirect)

**วันที่:** 2026-08-19
**ต่อจาก:** batch 1 (#2 Starlette CVE + #1 token-in-URL)
**สถานะ:** ✅ เสร็จ · full suite 688 passed

---

## #5 — SSRF ผ่าน subsystem health checker 🟠 กลาง

### ปัญหา
`subsystem_health.py` เป็น background task ยิง `GET {origin ของ redirect_uris[0]}/health`
ทุก 5 นาที · `redirect_uris` มาจาก **developer ตอนลงทะเบียน subsystem** → หลอก Hub
ยิงเข้า internal host ได้ (cloud metadata `169.254.169.254`, RFC1918, docker service ภายใน)
— blind SSRF (เก็บผลแค่ status/latency)

### แก้ — reuse SSRF guard เดียวกับ webhook
`_ping()` เรียก `webhook_dispatcher._is_safe_webhook_url(origin)` ก่อน fetch loop:
- **prod:** บังคับ https + block private/loopback/link-local/reserved/multicast/unspecified
- **dev:** localhost / docker-service เป็น target ตั้งใจ → ผ่าน
- unsafe → คืน `status=unknown, error="ถูกบล็อกโดย SSRF guard"` **ก่อน network I/O**
- ทุก candidate (`/health`, `/health.php`, `/`) ใช้ origin เดียวกัน → เช็คจุดเดียวครอบคลุม

### เทส — `tests/test_subsystem_health_ssrf.py` (6 tests)
```
test_ping_blocks_unsafe_target_in_prod[169.254.169.254] PASSED   ← cloud metadata
test_ping_blocks_unsafe_target_in_prod[127.0.0.1] ...... PASSED   ← loopback
test_ping_blocks_unsafe_target_in_prod[10.0.0.5] ....... PASSED   ← RFC1918
test_ping_blocks_unsafe_target_in_prod[192.168.1.10] ... PASSED   ← RFC1918
test_ping_blocks_unsafe_target_in_prod[http://public] .. PASSED   ← non-https
test_ping_does_not_block_public_https_in_prod .......... PASSED   ← public https ผ่าน
```
- fixture `no_network` = ถ้าเผลอยิง httpx ตอนควรบล็อก → AssertionError (พิสูจน์บล็อกก่อน I/O)

---

## #9 — Open redirect ผ่าน return_to 🟡 ต่ำ-กลาง

### ปัญหา
`_safe_return_to()` เดิมกัน `javascript:`/`data:`/`//` แต่ **ปล่อย `https://` ทุกโดเมน**
(docstring ยอมรับ "ไม่ผูก allowlist") → `?/passkey/recover?return_to=https://evil.com/phish`
ใช้โดเมน Hub เป็นจุดเด้ง phishing ได้

### แก้ — allowlist เป็น origin ของ subsystem ที่ลงทะเบียน
- เพิ่ม `_allowed_subsystem_origins(db)` — origin (scheme://netloc) ของ `redirect_uris`
  ทุก subsystem ที่ `status=active` (login page ของ subsystem อยู่ origin เดียวกับ redirect_uri)
- `_safe_return_to(raw, allowed_origins)`:
  - relative `/...` (ไม่ใช่ `//`) → อนุญาต
  - absolute http(s) → เฉพาะ origin ที่อยู่ใน allowlist → นอกนั้นทิ้ง
- `passkey_recover_page` เพิ่ม `db` dependency + ส่ง allowlist

### เทส — `tests/test_return_to_open_redirect.py` (8 tests)
```
test_allows_registered_subsystem_origin ......... PASSED
test_allows_relative_path ....................... PASSED
test_blocks_external_domain ..................... PASSED   ← evil.com → ""
test_blocks_lookalike_host ...................... PASSED   ← dorm...duckdns.org.evil.com → ""
test_blocks_protocol_relative ................... PASSED   ← //evil.com → ""
test_blocks_dangerous_schemes ................... PASSED   ← javascript:/data: → ""
test_empty_returns_empty ........................ PASSED
test_scheme_downgrade_not_in_allowlist_blocked .. PASSED
```

### 🐛 bug ที่เทสจับได้ระหว่างทำ
โค้ดใหม่ใช้ `urlparse` แต่ **oauth.py ไม่เคย import** (โค้ดเดิมไม่ใช้) → `NameError`
โดน `except Exception` กลืน → `_safe_return_to` คืน `""` **ทุกกรณีแม้ subsystem จริง**
(back button หาย). แก้: `from urllib.parse import urlparse` — เทส `test_allows_registered_
subsystem_origin` จับได้ก่อน deploy

---

## Regression — full suite

```
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py

================= 688 passed, 41 skipped in 195.82s =================
```
(674 batch-1 baseline + 6 health SSRF + 8 return_to = 688)

---

## สรุป audit 10 ข้อ — สถานะหลัง batch 1+2

| # | ประเด็น | สถานะ |
|---|---------|-------|
| 1 | token ใน URL | ✅ แก้ (code exchange) |
| 2 | Starlette CVE | ✅ แก้ (bump 0.49.3) |
| 3 | PG/Redis host port | ⏳ dev-only (prod ใช้ expose) — ปรับ dev compose bind 127.0.0.1 ได้ |
| 4 | ML ไม่มี auth/rate limit | ⏳ dev-only (prod expose ภายใน) |
| 5 | SSRF health checker | ✅ แก้ (guard) |
| 6 | frontend JWT ไม่ verify sig | ℹ️ by design (backend verify) — ผลกระทบต่ำ |
| 7 | XFF trust | ℹ️ กัน spoof แล้วบางส่วน (single-proxy topology) |
| 8 | secret token ใน URL | ℹ️ กันดีแล้ว (HMAC + one-time + replaceState) |
| 9 | open redirect return_to | ✅ แก้ (allowlist) |
| 10 | CSV ไม่จำกัดขนาด | ⏳ ต่ำ (developer เท่านั้น) |

**เหลือพิจารณา:** #3/#4 (harden dev compose), #10 (จำกัดขนาด CSV) — ความเสี่ยงต่ำ/dev-only

## ต้องทำเอง
Redeploy Dokploy → เอา batch 1+2 ขึ้น prod
