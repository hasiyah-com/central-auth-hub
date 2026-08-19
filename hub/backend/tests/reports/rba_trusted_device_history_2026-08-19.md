# B57/B58 — Trusted-device history + `would_challenge` ที่หายไป — Fix + Test Report

**วันที่:** 2026-08-19
**ต่อเนื่องจาก:** `is_new_device_signature_2026-08-19.md` (B56 — Fix A+B)

**อาการที่ผู้ใช้สังเกต (prod):**
login ครั้งแรกจาก Linux/Firefox → `0.900 WOULD_BLOCK` · ครั้งที่สอง 11 นาทีถัดมา → `0.100 MFA_PASSED`
คำถาม: ทำไมร่วงจาก 0.9 เหลือ 0.1 ทั้งที่ประวัติก่อนหน้าคือ 0.9

---

## 1. Root cause

risk score คำนวณใหม่ทุก login แบบ **memoryless** — คะแนนเก่าไม่ carry (ถูกต้องตามหลัก RBA)
แต่กลไก "เครื่องนี้เคยเห็นไหม" มีช่องโหว่:

`feature_extraction.py` query หา seen-device / seen-country **ไม่กรอง `decision` เลย** →
session ที่เพิ่งถูก flag (`would_block`) ถูกนับเป็น "เคยเห็นเครื่องนี้แล้ว" → **เครื่องที่ระบบ
เพิ่งเตือน whitelist ตัวเองในครั้งถัดไป** → `is_new_device` 1→0 → score ร่วง 0.9→0.1

เห็นชัดที่สุดใน **shadow mode** เพราะ `would_block` ไม่ block จริง → row ยังถูกบันทึก
(โหมด enforce จริง การ block จะไม่สร้าง row ที่ไว้ใจได้ตั้งแต่แรก)

**บั๊กที่ 2 (เจอระหว่างตรวจ):** `auth.py` refresh gate เช็ค `would_mfa` ซึ่ง **ไม่มีใครผลิตแล้ว**
(aggregator emit `challenge` แล้วเติม prefix → `would_challenge`) → shadow mode ไม่เคย log
`risk_refresh_would_stepup` เลย เงียบสนิท พบรูปแบบเดียวกันอีก 3 จุดใน `incident_service.py`

---

## 2. การแก้

### Fix C — `app/services/feature_extraction.py`

เพิ่ม `TRUSTED_DECISIONS = ("allow", "mfa_passed", "pass")` แล้วใช้กรอง **เฉพาะ trust signal**

| decision | trusted? | เหตุผล |
|---|---|---|
| `allow` | ✅ | ผ่านปกติ |
| `mfa_passed` | ✅ | ถูก challenge แล้ว **ยืนยันตัวตนผ่านจริง** (passkey.py เขียนทับ row เดิม) |
| `pass` | ✅ | legacy alias ของ allow (ยุคก่อน 4-layer) — ไม่เก็บไว้ = ประวัติเดิมทุกคนถูกล้าง |
| `warn` / `would_warn` | ❌ | สำเร็จแต่ไม่ได้ยืนยันตัวตนเพิ่ม (เลือกเข้มไว้ก่อน) |
| `challenge` / `would_challenge` / `mfa` / `would_mfa` / `mfa_required` | ❌ | ยังไม่พิสูจน์ — ถ้าผ่านจริง row จะกลายเป็น `mfa_passed` เอง |
| `block` / `would_block` / NULL | ❌ | ถูก flag |

**ขอบเขตการกรอง — สำคัญมาก:**

| query | กรอง? | เหตุผล |
|---|---|---|
| `seen_ua` → `is_new_device`, `is_new_user_agent_family` | ✅ | trust signal |
| `country_rows` → `is_new_country` | ✅ | trust signal |
| `country_change_count_30d` | ❌ | attacker login 5 ประเทศ โดน would_block ทุกครั้ง → กรองแล้วนับได้ 0 = **ดูปลอดภัยขึ้น** (ผิดทาง) |
| `impossible_travel` (prev country) | ❌ | "ล่าสุดอยู่ไหน" ต้องเห็น session ที่ถูก flag |
| `login_count_24h`, `failed_logins_24h`, `concurrent` | ❌ | volume signal |

**หลัก:** signal แบบ *"เคยเห็นไหม (trust)"* → กรอง · แบบ *"มีกิจกรรมน่าสงสัยแค่ไหน (volume)"* → ห้ามกรอง

**Cold-start guard แยกจาก trusted set** (กันช่องใหม่): ดึง `(value, decision)` แบบไม่กรองใน query
เดียว แล้วแยกใน Python เป็น `has_*_history` (มีประวัติไหม) + `seen_*` (ที่ไว้ใจได้)
→ user ที่มีประวัติแต่ **ไม่มี login ที่พิสูจน์แล้วเลย** จะได้ `is_new_device=1` ทุกเครื่อง
(ไม่ตกไปเป็น cold-start neutral=0 ซึ่งจะกลายเป็นให้คะแนน attacker ต่ำลง)
แยก `has_country_history` ต่างหากเพราะ `geo_country` เป็น NULL บ่อยมากใน deployment นี้
(private/NAT IP — CLAUDE.md gotcha #4) — ถ้าใช้ guard ร่วมจะกลายเป็น "ประเทศใหม่" ผิดๆ

### Fix D — `app/routers/auth.py:1400` (refresh gate)
`("block","challenge","would_block","would_mfa")` → `…,"would_challenge")`

### Fix E — `app/services/incident_service.py` (3 จุด, บั๊กคลาสเดียวกัน)
- `:295` subsystem-target recommendation → เติม `would_challenge`
- `:808` verdict statement → เติม `would_challenge`
- `:840` `challenged` ใน attack path → เติม `would_challenge`

ตรวจแล้ว: ทุก site ที่มี `would_mfa` ตอนนี้มี `would_challenge` คู่ครบ

---

## 3. Test

ไฟล์: `tests/test_feature_extraction.py` (เพิ่ม 6 test — รวมกับ B56 เป็น 8 test ใหม่)

| test | ยืนยัน |
|---|---|
| `test_flagged_session_does_not_trust_its_own_device` | `would_block` ครั้งแรก → ครั้งที่สองเครื่องเดิมยัง `is_new_device=1` |
| `test_mfa_passed_makes_device_trusted` | ยืนยันตัวตนผ่านจริง → เครื่องนั้น trusted (`0`) |
| `test_warn_is_not_trusted` | `warn` ยังไม่นับเป็น trusted (`1`) |
| `test_legacy_pass_decision_still_trusted` | legacy `pass` ยังไว้ใจได้ (กันประวัติเดิมถูกล้าง) |
| `test_no_trusted_history_treats_every_device_as_new` | มีประวัติแต่ไม่มี trusted เลย → ทุกเครื่องใหม่ (ไม่ตกเป็น neutral) |
| `test_true_cold_start_still_neutral` | user ใหม่จริง (0 session) → ยัง neutral |

**ผลรัน (reproducible):**
```bash
# ล้าง rate-limit budget ที่ค้างใน Redis ก่อน (ดูหัวข้อ 4)
docker compose exec -T redis sh -c \
  'redis-cli --scan --pattern "LIMITS:LIMITER/testclient/*" | xargs -r redis-cli DEL'

docker compose exec -T hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
```
```
tests/test_feature_extraction.py .................(17)   ← 8 test ใหม่ (B56+B57)
...
=== 697 passed, 41 skipped, 2 failed in 188.83s ===
```

---

## 4. 2 failure ที่เหลือ — ยืนยันแล้วว่าไม่ได้เกิดจากการแก้นี้

| test | สาเหตุ | หลักฐาน |
|---|---|---|
| `test_scope_conformance::test_scope1_student_blocked_hub_direct` | **429 rate limit** | log: `ratelimit 10 per 1 minute (testclient) exceeded at /auth/google/login` |
| `test_incidents::test_incident_timeline_two_strands` | **cross-test DB pollution** | ผ่าน 45/45 เมื่อรันเดี่ยว · test ใช้ `decision="would_block"` ซึ่งเข้า branch `shadow` **ก่อน** ถึงบรรทัดที่ Fix E แก้ (808/840) และ `subsystem_id=None` ทำให้ branch 295 ไม่ถูกเรียก → Fix E แตะไม่ถึง |

**หมายเหตุ rate limiter:** `app/rate_limiter.py` ใช้ `storage_uri=settings.redis_url` → budget
(เช่น `change-google/start` 10/hour, `recovery/request` 5/hour) **ค้างข้ามรอบรันและข้าม process**
การรัน pytest ซ้ำหลายรอบจะทำให้ test ที่ยิง endpoint เหล่านี้ fail แบบสุ่ม
พิสูจน์: ล้าง key `LIMITS:LIMITER/testclient/*` แล้วรันไฟล์กลุ่มเดิม → **139 passed** (จากเดิม 8 failed)

**ไฟล์ที่ต้อง `--ignore`:** `test_e2e_full_stack.py`, `test_l1_oidc.py` เป็น **สคริปต์** (มี `sys.exit()`
ระดับ module ต้องการ service จริง) ไม่ใช่ pytest module — collect แล้วทำให้ทั้ง session INTERNALERROR

---

## 5. ผลคาดหวังหลัง deploy

- เครื่องที่เพิ่งโดน `would_block` **จะไม่ whitelist ตัวเอง** — ยัง `is_new_device=1` จนกว่าจะมี
  login ที่เป็น `allow`/`mfa_passed` จริงจากเครื่องนั้น
- shadow mode + user ที่ไม่ได้เปิด Always-2FA → เครื่องที่โดน flag จะค้างคะแนนสูง
  (**ยอมรับตามที่ตัดสินใจไว้** — `mfa_policy.is_second_factor_required` มี `enforcing and …`
  ทำให้ risk step-up ไม่ทำงานใน shadow → ไม่มีทางได้ `mfa_passed` จาก risk flow;
  shadow คือโหมดวัดผล คะแนนสูงค้างสะท้อนความจริงว่าเปิด enforce แล้วจะโดน block)
- shadow mode จะเริ่ม log `risk_refresh_would_stepup` (Fix D) และหน้า Incidents จะนับ
  `would_challenge` ได้ถูกต้อง (Fix E)

## 6. ยังไม่ได้ตรวจ — ควรทำก่อน deploy

รัน query นี้บน **prod DB** เพื่อยืนยันว่า whitelist ครอบคลุมค่าที่มีจริง
(ถ้าเจอค่าอื่นนอกจาก allow/mfa_passed/pass/warn/challenge/block/would_* ต้องทบทวน `TRUSTED_DECISIONS`):
```sql
SELECT decision, count(*) FROM login_sessions GROUP BY decision ORDER BY count DESC;
```
สนใจเป็นพิเศษ: มี row ที่ `decision IS NULL` เยอะไหม (NULL = untrusted → ประวัติเครื่องหาย)
