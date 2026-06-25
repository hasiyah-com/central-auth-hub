# THREAT_MODEL_STRIDE.md

# Central Auth Hub

## STRIDE Threat Modeling

Version: 1.0

---

# 1. Purpose

เอกสารฉบับนี้ใช้วิเคราะห์ภัยคุกคามของระบบ Central Auth Hub
ตามกรอบ STRIDE Methodology

ประกอบด้วย

* Spoofing
* Tampering
* Repudiation
* Information Disclosure
* Denial of Service
* Elevation of Privilege

---

# 2. System Scope

Assets ที่ต้องปกป้อง

* User Accounts
* OAuth Authorization Codes
* JWT Access Tokens
* Refresh Tokens
* Passkeys
* User Profiles
* Audit Logs
* RBAC Policies
* OAuth Clients

---

# 3. Data Flow Diagram

User
↓
Google OAuth
↓
Central Auth Hub
↓
Risk Engine
↓
JWT Issuer
↓
Subsystem

---

# 4. STRIDE Analysis

## S - Spoofing Identity

Threat

* Credential Theft
* Session Hijacking
* Passkey Impersonation
* OAuth Client Spoofing

Mitigation

* PKCE
* Passkey
* JWT Signature
* Device Trust
* Step-Up Authentication

Residual Risk

Low

---

## T - Tampering

Threat

* JWT Modification
* OAuth Parameter Manipulation
* Request Payload Manipulation

Mitigation

* RS256
* Input Validation
* HMAC Verification

Residual Risk

Low

---

## R - Repudiation

Threat

User ปฏิเสธว่าไม่ได้ Login

Mitigation

* Audit Log
* Correlation ID
* Security Event Logging

Residual Risk

Medium

---

## I - Information Disclosure

Threat

* JWT Leak
* PII Leak
* Database Dump

Mitigation

* TLS 1.3
* Encryption at Rest
* Argon2id
* Access Control

Residual Risk

Low

---

## D - Denial of Service

Threat

* Login Flood
* OTP Flood
* Passkey Challenge Flood

Mitigation

* Rate Limiting
* CAPTCHA
* Request Throttling

Residual Risk

Medium

---

## E - Elevation of Privilege

Threat

Student → Admin

Mitigation

* RBAC
* Permission Checks
* Admin Step-Up Authentication

Residual Risk

Low

---

# 5. Risk Matrix

Likelihood × Impact

* Critical
* High
* Medium
* Low

---

# 6. Security Requirements

SR-01 ผ่าน PKCE ทุก Flow

SR-02 JWT ต้อง Signed

SR-03 Passkey ต้อง Verify Origin

SR-04 Audit ทุก Security Event

SR-05 MFA เมื่อ Risk สูง

---

# 7. Conclusion

Central Auth Hub ลดความเสี่ยงตาม STRIDE ได้ครบทุกหมวด
และมี Mitigation Controls รองรับทุก Threat หลัก
