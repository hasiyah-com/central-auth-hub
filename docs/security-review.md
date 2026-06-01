# Security Review — Central Auth Hub

> Capstone security audit using OWASP Top 10 + ZAP baseline scan
> สำหรับ thesis Chapter 4 (Results) Section "Security Validation"

---

## 1. Threat Model

ระบบมี 3 attacker classes:
1. **External attacker** — ไม่มี credential ใด ๆ; พยายาม brute-force / SQL injection / XSS
2. **Compromised user** — credential หลุด; พยายาม privilege escalation / persistence
3. **Malicious developer** — มี Developer Portal access; พยายามใช้ subsystem registration ขโมยข้อมูลคนอื่น

**Crown jewels:**
- JWT private key (`hub/backend/keys/jwt_private.pem`) — leak = ปลอม token ทุกคนได้
- DB `users` table — PII (email, phone, address)
- ML model — leak = หาช่อง bypass anomaly detection

---

## 2. OWASP Top 10 (2021) Coverage

| # | Risk | Mitigation in Hub | Status |
|---|------|-------------------|--------|
| A01 | Broken Access Control | `require_hub_admin`, `require_developer`, JWT `aud` check, access_list whitelist | ✅ |
| A02 | Cryptographic Failures | RS256 (asymmetric), Argon2id hash, Fernet AES, HMAC-SHA256 token | ✅ |
| A03 | Injection (SQL/XSS) | SQLAlchemy ORM (parameterized), Jinja2 auto-escape, Pydantic validation | ✅ |
| A04 | Insecure Design | Threat modeling done; PKCE + state token; one-time secret link | ✅ |
| A05 | Security Misconfiguration | `ENABLE_DOCS=false` ใน prod; `config.validate_production()` fail-fast | ✅ |
| A06 | Vulnerable Components | `pip-audit` — 28→5 vulns; pinned versions; auto-scan ใน CI (future) | 🟡 (5 transitive ค้าง) |
| A07 | Identification & Auth Failures | OAuth 2.0 + PKCE, JWT short TTL (60min), MFA (Email OTP) | ✅ |
| A08 | Software/Data Integrity | JWT signed; client_secret hash + encrypted; audit log append-only with hash chain | ✅ |
| A09 | Security Logging/Monitoring | `request_logs`, `audit_logs`, `api_alerts` (NIST SP 800-228), `login_sessions` with ML score | ✅ |
| A10 | SSRF | redirect_uri whitelist match (`subsystem.redirect_uris` array); no user-controlled HTTP fetch | ✅ |

---

## 3. Hardening Layers (Defense-in-Depth)

| Layer | Implementation | File |
|-------|---------------|------|
| 1. Data at Rest | Argon2id (client_secret), Fernet AES (retrieval secret), HMAC-SHA256 (tokens) | `secret_service.py` |
| 2. Data in Transit | HTTPS via Caddy + Let's Encrypt (production); HSTS header | `Caddyfile`, `main.py` |
| 3. Auth Flow | OAuth 2.0 + PKCE (RFC 7636); state token in Redis | `oauth.py`, `pkce.py` |
| 4. Token Security | JWT RS256 + `aud` claim enforced + 60min TTL | `jwt_service.py` |
| 5. Subsystem Secret | One-time URL (15min, HMAC stored, sent via email) | `developer.py`, `email_service.py` |
| 6. Session Security | httpOnly cookie + SameSite=Lax + Secure in prod | `main.py` |
| 7. Audit Log | Append-only `audit_logs`, IP via X-Forwarded-For (Docker-aware) | `audit_service.py`, `deps.py` |
| 8. Rate Limiting | slowapi per-IP — login 10/min, OAuth 20/min, register 5/min | `rate_limiter.py` |
| 9. ML Anomaly Detection | Isolation Forest (12 features, RBA dataset), Shadow + Enforce modes | `ml-service/`, `feature_extraction.py` |
| 10. Secret Management | `.env` gitignored; production `SECRET_KEY` rotation policy | `.env.example` |
| 11. MFA (when score ≥ 0.40) | Email OTP, HMAC stored, 5min TTL, max 5 attempts | `mfa_service.py`, `mfa.py` router |
| 12. Security Headers | CSP, HSTS, X-Frame-Options=DENY, X-Content-Type-Options=nosniff, Permissions-Policy | `main.py` SecurityHeadersMiddleware |
| 13. IP Blacklist | Auto-add on attack pattern; manual mark by admin | `ip_blacklist.py`, `api_guard.py` |

---

## 4. CSRF Analysis

**Conclusion: traditional CSRF token NOT needed**

| Attack vector | Why mitigated |
|--------------|---------------|
| Cookie-based admin actions | Admin Console ใช้ **Bearer JWT** ใน `Authorization` header (httpOnly cookie → `/api/proxy/*` แนบเป็น Bearer) — ไม่ใช่ session cookie แบบ traditional |
| OAuth login attack | PKCE (`code_challenge` + `code_verifier`) + state token ใน Redis — กัน CSRF per RFC 6749 + 7636 |
| Subsystem mutation | ทุก mutation ต้องผ่าน `/oauth/*` flow ที่มี state + code_verifier |
| Cookie session middleware | ใช้เฉพาะ Authlib state ระหว่าง OAuth redirect — ไม่ใช่ mutation auth |

อ้างอิง: OWASP Cheat Sheet "CSRF Prevention" — ระบุว่า OAuth + PKCE เป็น valid CSRF defense

---

## 5. Pentest Results — OWASP ZAP Baseline

Run command:
```bash
bash scripts/pentest/zap-baseline.sh http://host.docker.internal:8000 hub-backend
```

Report files:
- `zap/baseline-report-hub-backend.html`
- `zap/baseline-report-hub-backend.md`

### Findings (expected pattern)
| Severity | Finding | Status | Mitigation |
|----------|---------|--------|------------|
| Medium | Missing Anti-CSRF Token | ❌ False positive — Bearer JWT ใช้แทน (CSRF analysis ด้านบน) |
| Low | X-Content-Type-Options not set (some endpoints) | ✅ Fixed — SecurityHeadersMiddleware sets globally |
| Low | Content-Security-Policy not set | ✅ Fixed — CSP added in middleware |
| Info | Modern Web Application (suspected SPA) | ✅ Expected — Next.js frontend |

Run scans across all 4 services for complete coverage.

---

## 6. Dependency Audit (pip-audit)

Initial: **28 vulnerabilities** in 8 packages
After hardening: **5 vulnerabilities** (-82%)

Remaining (all transitive, low risk):
- `pytest 8.3.3` — dev-only, not deployed
- `pyasn1 0.4.8` — via python-jose pin (planned: migrate to PyJWT → removes ecdsa+pyasn1)
- `starlette 0.48.0` — via fastapi pin (awaiting fastapi 0.120+)
- `ecdsa 0.19.2` — no upstream fix; **not exercised** (we use RS256 only, not ECDSA)
- `python-jose` — superseded by PyJWT migration planned

See `docs/deploy-to-server.md` Security Checklist section.

---

## 7. Pending Items (Week 11-12)

- [ ] PyJWT migration (removes ecdsa + pyasn1 + python-jose CVEs)
- [ ] Token revocation endpoint (`/auth/logout` → blacklist `jti` in Redis)
- [ ] Active ZAP scan (post-baseline) — fuzz `/admin/*` + `/developer/*` with admin token
- [ ] Penetration test report write-up (Chapter 4 thesis)
- [ ] CI dependency scan (Dependabot / `pip-audit` GitHub Action)

---

## 8. References

- **OWASP Top 10 2021** — https://owasp.org/Top10/
- **OWASP API Security Top 10 2023** — https://owasp.org/API-Security/
- **NIST SP 800-63B-4** — Digital Identity Guidelines (Authentication)
- **NIST SP 800-228** — API Protection
- **RFC 6749** — OAuth 2.0 Authorization Framework
- **RFC 7636** — PKCE for OAuth Public Clients
- **RFC 7519** — JWT
- **Wiefling et al. (2022)** — *Risk-Based Authentication: A Survey* (ACM TOPS)
- **Liu, Ting, Zhou (2008)** — *Isolation Forest* (ICDM)
