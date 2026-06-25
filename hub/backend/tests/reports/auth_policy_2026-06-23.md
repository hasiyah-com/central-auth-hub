# Test Report — Global Auth Policy (เลือกวิธี Login: Google / Passkey)

- **วันที่:** 2026-06-23
- **ไฟล์ test:** `hub/backend/tests/test_auth_policy.py`
- **ผลรวม:** ✅ **18/18 passed** (3.14s) + regression **51/51 passed** (3.49s)
- **รันด้วย:**
  ```bash
  docker compose exec hub-backend pytest tests/test_auth_policy.py -v
  # regression:
  docker compose exec hub-backend pytest tests/test_critical_action_policy.py \
      tests/test_oauth_passkey.py tests/test_passkey_login.py tests/test_rbac.py -q
  ```

## ฟีเจอร์ที่ทดสอบ

Admin เลือกที่หน้าภาพรวม (dashboard) ว่าระบบยอมให้ login ผ่าน Google / Passkey / ทั้งคู่ →
บันทึก (step-up) → ตัดทุก session ทุก subsystem → user login ใหม่เห็นเฉพาะวิธีที่เปิด

## ผลลัพธ์รายข้อ (18 tests)

### Service layer (3)
| Test | ผล | ตรวจอะไร |
|---|---|---|
| `test_get_policy_returns_dict` | ✅ | `get_auth_policy` คืน `{google, passkey}` (bool) |
| `test_set_and_get_roundtrip` | ✅ | set→get persist ถูกต้องทั้ง 2 combo |
| `test_set_both_false_raises` | ✅ | **Invariant:** ปิดทั้งคู่ → `ValueError` (กัน lockout) |

### HTTP — read (3)
| Test | ผล | ตรวจอะไร |
|---|---|---|
| `test_public_policy_endpoint` | ✅ | `GET /auth/policy` public (ไม่ auth) → 200 |
| `test_admin_get_requires_auth` | ✅ | `GET /admin/auth-policy` ไม่มี token → 401/403 |
| `test_admin_get_with_admin` | ✅ | admin → 200 + คืน policy |

### HTTP — PUT + step-up (4)
| Test | ผล | ตรวจอะไร |
|---|---|---|
| `test_put_without_stepup_returns_403` | ✅ | critical action — ไม่มี step-up → 403 `stepup_required` |
| `test_put_both_false_rejected` | ✅ | ปิดทั้งคู่ → 400 (ไม่บันทึก) |
| `test_put_noop_no_kick` | ✅ | ตั้งค่าเท่าเดิม → `changed=False`, `sessions_closed=0` (ไม่ตัด session) |
| `test_put_real_change_persists` | ✅ | เปลี่ยนจริง → `changed=True` + persist + webhook loop หลัง commit ไม่ crash |

### Enforcement ที่ login endpoint (4)
| Test | ผล | ตรวจอะไร |
|---|---|---|
| `test_enforce_google_disabled` | ✅ | ปิด google → `/auth/google/login` = **403** |
| `test_enforce_passkey_disabled` | ✅ | ปิด passkey → `/auth/passkey/login/start` = **403** |
| `test_enforce_passkey_discoverable_disabled` | ✅ | ปิด passkey → `discoverable/start` = **403** |
| `test_google_login_works_when_enabled` | ✅ | เปิด google → redirect (302/307) ปกติ |

### Subsystem login chooser render (4)
| Test | ผล | ตรวจอะไร |
|---|---|---|
| `test_chooser_both_enabled` | ✅ | เปิดทั้งคู่ → ปุ่ม passkey + google + divider + recover ครบ |
| `test_chooser_google_only` | ✅ | ปิด passkey → ซ่อนปุ่ม passkey + divider + recover |
| `test_chooser_passkey_only` | ✅ | ปิด google → ซ่อนปุ่ม google + divider |
| `test_chooser_js_guarded_when_passkey_off` | ✅ | JS มี `if (toggle)` guard กัน null crash |

## Manual / integration checks (นอก pytest)

| ตรวจ | ผล |
|---|---|
| table `app_settings` auto-create ตอน startup | ✅ |
| kick-all จริง: สร้าง active session → `close_subsystem_login_sessions` → `logout_at` set + jti revoked | ✅ `{closed:1, jti_revoked:1}` |
| frontend `tsc --noEmit` (LoginMethodsCard / dashboard / login page) | ✅ ไม่มี error |
| dashboard + `/auth/login` render | ✅ 200 |
| regression (critical_action_policy / oauth_passkey / passkey_login / rbac) | ✅ 51/51 |

## Security checks

- **Defense in depth (3 ชั้น):** UI ซ่อนปุ่ม → endpoint reject 403 → invariant ≥1 วิธี
- **Step-up gate:** เปลี่ยน policy = critical action (`auth_policy_update` ∈ CRITICAL_ACTIONS) — PUT ต้องมี passkey/OTP grant
- **Anti-lockout:** ปิดทั้งคู่ถูก reject ทั้ง service (ValueError) + HTTP (400)
- **Audit:** `auth_policy_updated` + `auth_policy_update_failed` log พร้อม old/new + kick count
- **Fail-safe read:** `get_auth_policy` error → default เปิดทั้งคู่ (ไม่ทำ login พัง)

## หมายเหตุ / ข้อสังเกต

- ทุก test ที่แก้ policy ใช้ fixture `policy_guard` restore → `{google:true, passkey:true}` หลังจบ → suite idempotent, สถานะสุดท้ายปลอดภัย (ยืนยัน `GET /auth/policy` = both true)
- การกด PUT จริงบน production มีคนใช้งานเยอะ = ตัดทุก session ทันที — ใช้ระวัง
- ระหว่างพัฒนา Docker Desktop (เครื่อง dev) ล่ม 2 ครั้ง — ไม่เกี่ยวกับโค้ด ฟีเจอร์ทำงานปกติหลัง engine กลับมา

## ไม่พบบั๊ก

ตรวจจุดเสี่ยงที่ test ครอบคลุม: f-string KeyError ใน chooser (✅ render ครบ 3 โหมด), JS null crash เมื่อ passkey off (✅ guard), expired ORM หลัง commit ใน webhook loop (✅ ไม่ crash), lockout invariant (✅ reject 2 ชั้น) — **ไม่พบบั๊ก**
