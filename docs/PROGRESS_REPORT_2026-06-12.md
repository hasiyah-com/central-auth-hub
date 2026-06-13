# รายงานความคืบหน้าโครงการ — Central Auth Hub

**ระบบการจัดการสิทธิ์ผู้ใช้แบบศูนย์กลาง (Centralized Identity & Permission Management Platform)**

| | |
|---|---|
| **ประเภท** | โครงงานวิศวกรรม/วิทยาการคอมพิวเตอร์ ระดับปริญญาตรี (Senior Project) |
| **ระยะเวลา** | 16 สัปดาห์ |
| **วันที่รายงาน** | 2026-06-12 (สิ้นสุด Week 9–10, ช่วง Passkey) |
| **สถานะรวม** | 🟢 **เกินแผนเดิม** — Core platform + ML + Passkey ครบ |
| **Repository** | github.com/hasiyah-com/central-auth-hub (65 commits) |

---

## 1. บทสรุปผู้บริหาร (Executive Summary)

ระบบ Central Auth Hub เป็นแพลตฟอร์ม **authentication + authorization แบบรวมศูนย์** สำหรับมหาวิทยาลัย
ทำหน้าที่ยืนยันตัวตนและจัดการสิทธิ์ให้ระบบย่อย (subsystem) หลายระบบ โดย **ไม่ใช่ SSO** —
แต่ละ subsystem มี session ของตัวเอง Hub ทำหน้าที่ authenticate + authorize เท่านั้น

**ความคืบหน้า ณ ปัจจุบัน:**
- ✅ Core auth platform (OAuth 2.0 + PKCE + JWT RS256) — เสร็จสมบูรณ์
- ✅ ระบบย่อย 2 ระบบ (หอพัก + ห้องสมุด) — เป็น OAuth client เต็มรูปแบบ
- ✅ ML Risk-Based Authentication (4-Layer RBA + SHAP) — ทำงานใน Shadow Mode
- ✅ Admin Dashboard (Next.js) — dashboard, users, audit, ML preview
- ✅ **Passkey / WebAuthn (FIDO2)** — ครบ 8 phase (passwordless login) ← งานล่าสุด
- ✅ IdP รองรับ 2 ทาง: Google OAuth + LINE Login
- 🔄 กำลังทำ: MFA wire-up, Session Downgrade, Token Revocation

**ตัวเลขสำคัญ:**

| Metric | ค่า |
|---|---|
| API endpoints (Hub) | **105** endpoints / 14 routers |
| Backend tests | **167 passed** (unit + integration + ceremony) |
| Test reports เก็บถาวร | 19 ฉบับ |
| Git commits | 65 |
| Database tables | 7 (Hub) + 4 (Dorm) + 4 (Library) |
| ML features | 17 (12 RBA + 5 passkey), AUC 0.9946 |
| Security layers | 10 (Defense in Depth) |

---

## 2. สถาปัตยกรรมระบบ

ระบบแยกเป็น **3 docker-compose stacks** เชื่อมผ่าน external network `cah-net`
(จำลองสภาพจริงที่แต่ละ subsystem มีทีมเจ้าของต่างกัน)

```
┌─────────────────────────────────────────────────────────────┐
│  cah-hub stack (Auth Platform)                               │
│  ┌──────────┐ ┌─────────┐ ┌──────────────┐ ┌──────────────┐ │
│  │ hub-     │ │ hub-    │ │ ml-service   │ │ hub-frontend │ │
│  │ backend  │ │ postgres│ │ (IForest+SHAP)│ │ (Next.js 14) │ │
│  │ :8000    │ │ :5432   │ │ :9000        │ │ :3000        │ │
│  └──────────┘ └─────────┘ └──────────────┘ └──────────────┘ │
│       + hub-redis :6379                                      │
└─────────────────────────────────────────────────────────────┘
        ▲                              ▲
        │ OAuth + JWKS                 │ OAuth + JWKS
┌───────┴────────┐            ┌────────┴───────┐
│ cah-dorm stack │            │ cah-library    │
│ subsystem-dorm │            │ subsystem-     │
│ :8001 (หอพัก)  │            │ library :8002  │
│ + postgres-dorm│            │ (ห้องสมุด)     │
└────────────────┘            └────────────────┘
```

**IdP ภายนอก:** Google OAuth (OIDC) + LINE Login (OIDC) — ทั้งคู่ผ่าน discovery, swappable

---

## 3. ความคืบหน้าตาม Roadmap (16 สัปดาห์)

| Week | งาน | สถานะ |
|------|-----|-------|
| 1 | Setup + Postgres + 100 users | ✅ |
| 2 | Google OAuth + JWT (Hub direct) | ✅ |
| 3 | Subsystem Registration + Whitelist | ✅ |
| 4 | OAuth flow + PKCE + access_list check | ✅ |
| 5 | ML Verifier (IForest, 12 features, Shadow Mode) + security hardening | ✅ |
| 6 | Subsystem A — ระบบหอพัก | ✅ |
| 7 | Subsystem B — ระบบห้องสมุด | ✅ |
| 8 | Admin Dashboard (Next.js) + audit viewer + pending triage | ✅ |
| 8.5 | Migration B (3 stacks) + SHAP + LINE Login + 4-Layer RBA + secret rotation | ✅ |
| **9–10** | **Passkey/WebAuthn (8 phases)** ✅ · MFA wire-up 🔄 · Session Downgrade ⏳ · Token Revocation ⏳ | 🔄 |
| 11–12 | Security hardening (rate limit ✅, CSRF, CSP ✅, prod fail-fast ✅) + threat model + pentest | ⏳ |
| 13–14 | Test suite (pytest ✅ 167) + frontend tests + CI (✅ GitHub Actions) + docs | 🔄 |
| 15–16 | Buffer + thesis writing + defense | ⏳ |

**สรุป:** ทำเสร็จถึง Week 8.5 ครบ + Week 9–10 ส่วน Passkey เสร็จสมบูรณ์ (เกินแผน)
งานที่ scaffold ไว้แต่ยังไม่ wire: MFA OTP flow, Session Downgrade, Token Revocation

---

## 4. รายละเอียดแต่ละองค์ประกอบ

### 4.1 Hub (Central Auth Server) — ✅ Core สมบูรณ์
- **105 endpoints / 14 routers** — auth, oauth, developer, admin, users, secret, health, oidc,
  mfa, passkey (22), ml_admin, ip_blacklist, api_alerts
- OAuth 2.0 Authorization Code + PKCE (RFC 7636), JWT RS256 + JWKS discovery
- RBAC 4 ระดับ (student/teacher/staff/admin) + `Depends` ทุก protected endpoint
- Audit log แบบ append-only + hash chain, request logger middleware
- OIDC endpoints (L1): Discovery, UserInfo, Token Introspection

### 4.2 Subsystem A — ระบบหอพัก (port 8001) — ✅
- OAuth client เต็มรูปแบบ (PKCE + token exchange + JWKS verify cache 10 นาที)
- Business logic: จองห้อง, อนุมัติ, check-in (24 ห้อง: ตึก A/B × 3 ชั้น × 4 ห้อง)
- React SPA + Bauhaus theme · session แยกของตัวเอง (itsdangerous signed cookie)

### 4.3 Subsystem B — ระบบห้องสมุด (port 8002) — ✅
- OAuth client (รูปแบบเดียวกับ A) · business logic ยืม/คืนหนังสือ (30 เล่ม × 6 หมวด)
- Vintage UI + sidebar · librarian flow (อนุมัติ/คืน/สมาชิก)

### 4.4 ML Verifier (port 9000) — ✅ Shadow Mode
- **4-Layer RBA:** Rule Engine + Behavior Profiling + Isolation Forest + Aggregation
  (Freeman 2016, Wiefling 2022, F-RBA 2024)
- **SHAP TreeExplainer** — per-feature contribution + UI bars (Lundberg & Lee 2017)
- **17 features** (12 RBA + 5 passkey: has_passkey, passkey_count, passkey_age, new_recently_added, last_used) — retrain AUC **0.9946**
- Fail-safe: ML ล่ม → Hub คืน pass (ไม่ crash) · Shadow Mode: score แต่ไม่ block (would_mfa/would_block)

### 4.5 Admin Dashboard (Next.js 14, port 3000) — ✅
- Dashboard KPI, users (+ passkey overview), subsystems, pending triage
- Audit log viewer, ML threshold preview + SHAP, IP blacklist, API alerts
- Account security page (passkey management) — admin only

---

## 5. ความปลอดภัย — Defense in Depth (10 ชั้น)

| # | ชั้น | สถานะ |
|---|------|-------|
| 1 | Data at Rest — Argon2id (secret/backup codes), pgcrypto (PII) | ✅ |
| 2 | Data in Transit — HTTPS/TLS | ✅ (prod) |
| 3 | Auth Flow — OAuth 2.0 + PKCE (`hmac.compare_digest`) | ✅ |
| 4 | Token Security — JWT RS256 + jti + aud verification | ✅ |
| 5 | Subsystem Key Delivery — one-time link 15 นาที + HMAC + Fernet | ✅ |
| 6 | Session Security — HttpOnly + SameSite cookies | ✅ |
| 7 | Audit Log — append-only + hash chain | ✅ |
| 8 | Rate Limiting — per IP / per client_id | ✅ |
| 9 | ML Anomaly Detection — Isolation Forest (Shadow) | ✅ |
| 10 | Secret Management — `.env` แยก git + key rotation | ✅ |

**Hardening เพิ่มเติม:** CSP nonce-based (Hub-served pages), production fail-fast
(`validate_production()`), X-Forwarded-For handling + IP validation, anti-enumeration
(generic error + decoy descriptors), atomic auth code (Redis getdel)

---

## 6. Passkey / WebAuthn (FIDO2) — งานหลัก Week 9–10 ✅

ระบบ passwordless authentication ตามมาตรฐาน WebAuthn/FIDO2 — ครบ **8 phase**

| Phase | งาน |
|---|---|
| 0 | Foundation — config, step-up cache, critical-action gate |
| 1 | Register passkey (attestation) + mandatory backup codes (Argon2id) |
| 2 | Login (email-first assertion) + device parse + ML scoring |
| 3 | Lifecycle — list / rename / delete + last-passkey guard + admin overview |
| 4 | Recovery — backup code / email OTP / admin reset + auto-heal |
| 5 | Step-up re-auth (passkey + OTP fallback) + critical gate + ML 17 features |
| 6 | Full ceremony integration tests (soft-webauthn) + GitHub Actions CI |
| 7 | Discoverable login (userHandle) + force-adoption policy |
| B/A/E | Subsystem chooser + passkey OAuth path + enroll interstitial (รวมนักศึกษา) + Hub-served recover |

**จุดเด่นด้านความปลอดภัย:**
- Counter regression detection (clone detection) → lenient allow + risk boost
- Anti-enumeration ครบ: generic message + `allowCredentials` decoy (HMAC-based) — **B43**
- OTP purpose binding (recovery vs regenerate แยกกัน), lockout 5 ครั้ง
- ไม่ส่ง backup codes ทาง email — แสดงบนหน้าจอ + ack UX เท่านั้น

---

## 7. การทดสอบและคุณภาพ (Testing & Quality)

- **167 backend tests passed** — TDD (RED→GREEN→REFACTOR) ทุก feature
  - unit (service/router), integration (full WebAuthn ceremony 13 tests ด้วย soft-webauthn),
    security (SQLi, enumeration, RBAC, rate limit)
- **GitHub Actions CI** — postgres + redis services, seed, pytest (fail-safe ML/GeoIP)
- **Pre-commit hooks** — detect-secrets, block-env-files, ruff, pytest-collect
- **Claude Code hooks** — block write `.env`/`*.pem`/`keys/`, audit-order reminder
- Test reports เก็บถาวร **19 ฉบับ** ใน `tests/reports/`

---

## 8. ช่องว่างที่เหลือ (Known Gaps) และงานถัดไป

| งาน | สถานะ | หมายเหตุ |
|---|---|---|
| MFA OTP flow | ⚠️ scaffold แล้ว ยังไม่ wire | `routers/mfa.py` ยังไม่ trigger ใน oauth challenge branch |
| Session Downgrade (`restricted` JWT claim) | ⏳ design พร้อม | `docs/p2-session-downgrade-plan.md` |
| Token Revocation (jti + Redis blacklist) | ⏳ | ยังไม่มี blacklist |
| GeoIP lookup (`geo_country`) | ⚠️ partial | MaxMind GeoIP2 — private IP ยังขึ้น "—" |
| Threat model (STRIDE) + pentest checklist | ⏳ | Week 11–12 |
| Frontend tests (Jest/RTL) | ⏳ | Week 13–14 |
| Manual browser test Passkey Phase 0–7 | 🔄 | checklist พร้อม รอทดสอบด้วย Windows Hello |

**ลำดับความสำคัญถัดไป (Week 9–10 ที่เหลือ):**
1. Wire MFA OTP flow เข้า OAuth challenge branch
2. Token Revocation (jti + Redis blacklist) — ต่อยอดจาก step-up cache ที่มี
3. Session Downgrade — `restricted` claim + `require_write_access()` ใน subsystems

---

## 9. สรุป

ระบบ Central Auth Hub พัฒนา**เกินแผนเดิม** — นอกจาก core OAuth/JWT platform แล้ว
ยังเพิ่ม 4-Layer RBA + SHAP, LINE Login, และระบบ **Passkey/WebAuthn เต็มรูปแบบ**
(passwordless + recovery + step-up + ceremony tests) ซึ่งเป็น state-of-the-art ของ
authentication ปัจจุบัน

ความปลอดภัยครอบคลุม Defense-in-Depth 10 ชั้น พร้อม test 167 ตัวและ CI
งานที่เหลือเป็นส่วน wire-up (MFA, token revocation, session downgrade) +
documentation/thesis (Week 11–16) ซึ่งมี design รองรับไว้แล้ว

---

*รายงานนี้สร้างจากสถานะจริงของ codebase ณ 2026-06-12 — ดูบั๊กที่เจอทั้งหมดที่
`docs/bugs-encountered.md` (B1–B43) และ daily logs ที่ `docs/daily/`*
