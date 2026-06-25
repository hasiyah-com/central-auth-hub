# Central Auth Hub
# Security Verification and Testing Master Plan

Version: 1.0

Status: Approved

Authors: Project Team

---

# 1. Purpose

เอกสารฉบับนี้กำหนดแนวทางการทดสอบและการตรวจสอบความปลอดภัย
(Security Verification and Validation)

เพื่อพิสูจน์ว่า Central Auth Hub

- ทำงานได้ถูกต้อง
- มีความปลอดภัย
- ทนต่อการโจมตีที่พบบ่อย
- สอดคล้องกับ OAuth 2.0 Security Best Practices
- สอดคล้องกับ OWASP Top 10
- สอดคล้องกับ OWASP ASVS
- สามารถใช้งานจริงในสภาพแวดล้อม Production

---

# 2. Testing Pyramid

โครงสร้างการทดสอบแบ่งออกเป็น

Level 1
Unit Testing

Level 2
Integration Testing

Level 3
End-to-End Testing

Level 4
Security Testing

Level 5
Threat Modeling

Level 6
Security Validation

---

# 3. Unit Testing

## Objective

ตรวจสอบ Logic ของแต่ละ Component
โดยไม่พึ่งพาระบบภายนอก

---

## Coverage Target

80-90%

---

# 3.1 JWT Service

### Test Case

Generate JWT

วัตถุประสงค์

ตรวจสอบว่าสามารถสร้าง JWT ได้ถูกต้อง

Expected Result

Token ถูกสร้างสำเร็จ

---

### Test Case

Verify JWT Signature

วัตถุประสงค์

ตรวจสอบลายเซ็นดิจิทัล

Expected Result

Token ผ่านการตรวจสอบ

---

### Test Case

Expired Token

วัตถุประสงค์

ตรวจสอบการหมดอายุ

Expected Result

401 Unauthorized

---

### Test Case

Invalid Signature

วัตถุประสงค์

ป้องกัน Token Tampering

Expected Result

Reject

---

### Test Case

Invalid Audience

วัตถุประสงค์

ป้องกัน Token Reuse ข้าม Subsystem

Expected Result

Reject

---

# 3.2 OAuth Service

### Authorization Code Generation

วัตถุประสงค์

ตรวจสอบการสร้าง Authorization Code

---

### Authorization Code Validation

วัตถุประสงค์

ตรวจสอบการแลก Token

---

### Authorization Code Replay

วัตถุประสงค์

ตรวจสอบว่า Code ใช้ซ้ำไม่ได้

Expected

Reject

---

### PKCE Verification

วัตถุประสงค์

ตรวจสอบ code_verifier

Expected

Reject เมื่อ verifier ไม่ถูกต้อง

---

### Redirect URI Validation

วัตถุประสงค์

ป้องกัน Open Redirect

Expected

Reject

---

# 3.3 Passkey Service

### Registration Success

วัตถุประสงค์

ตรวจสอบการลงทะเบียน Passkey

---

### Registration Failure

วัตถุประสงค์

ตรวจสอบ Error Handling

---

### Authentication Success

วัตถุประสงค์

ตรวจสอบ Signature Verification

---

### Authentication Failure

วัตถุประสงค์

ตรวจสอบ Signature Invalid

---

### Challenge Replay

วัตถุประสงค์

ป้องกัน Replay Attack

Expected

Reject

---

# 3.4 RBAC Service

### Permission Allow

วัตถุประสงค์

ตรวจสอบการอนุญาต

---

### Permission Deny

วัตถุประสงค์

ตรวจสอบการปฏิเสธสิทธิ์

---

### Role Inheritance

วัตถุประสงค์

ตรวจสอบการสืบทอด Role

---

# 4. Integration Testing

## Objective

ตรวจสอบการทำงานร่วมกันของหลาย Service

---

# 4.1 OAuth Login Flow

User

↓

Google OAuth

↓

Central Auth Hub

↓

JWT

Expected

Success

---

# 4.2 Risk-Based Authentication Flow

Login

↓

Behavior Profiling

↓

Isolation Forest

↓

Risk Aggregator

Expected

Risk Score Generated

---

# 4.3 Passkey Step-Up Flow

High Risk Login

↓

Passkey Challenge

↓

JWT

Expected

Success

---

# 5. End-to-End Testing

## Objective

จำลองการใช้งานจริง

---

# Scenario 1

Login ผ่าน Google

Expected

Success

---

# Scenario 2

Register Passkey

Expected

Success

---

# Scenario 3

Login ด้วย Passkey

Expected

Success

---

# Scenario 4

Admin Management

Expected

Permission Enforcement

---

# 6. Security Testing

## Objective

ทดสอบการโจมตีที่พบบ่อย

---

# 6.1 Authentication Security

## Authorization Code Replay

Attack

ใช้ Code ซ้ำ

Purpose

ป้องกัน Replay Attack

Expected

Reject

---

## PKCE Bypass

Attack

ใช้ Verifier ปลอม

Purpose

ป้องกัน OAuth Interception

Expected

Reject

---

## JWT Tampering

Attack

แก้ไข Payload

Purpose

ตรวจสอบ Signature Validation

Expected

Reject

---

## Expired JWT

Attack

ใช้ Token หมดอายุ

Expected

Reject

---

# 6.2 Passkey Security

## Challenge Replay

Attack

ใช้ Challenge เดิม

Purpose

ป้องกัน Replay

Expected

Reject

---

## Origin Validation

Attack

evil.com

Purpose

ป้องกัน Phishing

Expected

Reject

---

## RP ID Validation

Attack

RP ID ปลอม

Expected

Reject

---

## Counter Regression

Attack

Credential Cloning

Expected

Audit Alert

---

# 6.3 Session Security

## Session Fixation

Purpose

ป้องกัน Session Reuse

Expected

Session Rotation

---

## Session Hijacking

Purpose

ป้องกัน Cookie Theft

Expected

Step-Up Authentication

---

## Concurrent Session Abuse

Purpose

ตรวจจับ Session Sharing

Expected

Risk Increase

---

# 6.4 Access Control Security

## Broken Access Control

Attack

Student เรียก Admin API

Expected

403

---

## IDOR

Attack

เปลี่ยน Resource ID

Expected

403

---

## Privilege Escalation

Attack

เปลี่ยน Role เป็น Admin

Expected

Reject

---

# 6.5 API Security

## Rate Limiting

Attack

100 Requests/Second

Expected

429

---

## Mass Assignment

Attack

ส่ง role=admin

Expected

Ignored

---

## JSON Injection

Purpose

Input Validation

Expected

Reject

---

# 7. Threat Modeling

## Methodology

STRIDE

---

# S - Spoofing

Threat

Credential Theft

Mitigation

OAuth + Passkey

---

Threat

Session Hijacking

Mitigation

Step-Up Authentication

---

# T - Tampering

Threat

JWT Modification

Mitigation

RS256 Signature

---

Threat

OAuth Parameter Manipulation

Mitigation

PKCE

---

# R - Repudiation

Threat

User Denies Action

Mitigation

Audit Logs

---

# I - Information Disclosure

Threat

PII Leakage

Mitigation

Encryption

---

# D - Denial of Service

Threat

Login Flood

Mitigation

Rate Limiting

---

Threat

OTP Flood

Mitigation

Throttle

---

# E - Elevation of Privilege

Threat

Role Escalation

Mitigation

RBAC

---

# 8. OWASP Top 10 Mapping

A01 Broken Access Control

Tests

- IDOR
- Privilege Escalation
- Permission Bypass

---

A02 Cryptographic Failures

Tests

- JWT Signature
- TLS
- Encryption

---

A03 Injection

Tests

- SQL Injection
- JSON Injection

---

A04 Insecure Design

Tests

- Threat Modeling
- Architecture Review

---

A05 Security Misconfiguration

Tests

- Header Validation
- TLS Configuration

---

A07 Authentication Failures

Tests

- Replay Attack
- PKCE
- Passkey

---

A09 Logging and Monitoring

Tests

- Audit Logging
- Alert Generation

---

# 9. Security Automation

## SAST

Tools

- Bandit
- Semgrep

Purpose

ตรวจสอบ Source Code

---

## Dependency Scanning

Tools

- Trivy
- Safety

Purpose

ตรวจสอบ Library Vulnerability

---

## Container Scanning

Tools

- Trivy

Purpose

ตรวจสอบ Docker Image

---

## Secret Scanning

Tools

- Gitleaks

Purpose

ตรวจสอบ Secret Leak

---

# 10. Coverage Matrix

Unit Tests

Target > 85%

Integration Tests

Target > 80%

Security Tests

Target > 90%

Critical Security Paths

Target 100%

---

# 11. Acceptance Criteria

ระบบจะถือว่าผ่าน Security Verification เมื่อ

- Unit Test Coverage ≥ 85%
- Integration Test Coverage ≥ 80%
- Security Test Pass ≥ 90%
- ไม่มี Critical Vulnerability
- ไม่มี High Vulnerability ที่ยังไม่แก้ไข
- ผ่าน Threat Modeling Review
- ผ่าน OWASP Top 10 Validation
- ผ่าน OAuth Security Verification
- ผ่าน Passkey Security Verification

---

# 12. Conclusion

Central Auth Hub จะถือว่าพร้อมสำหรับ Production Deployment
เมื่อผ่าน Security Verification และ Validation ทุกระดับ
ตั้งแต่ Unit Test ไปจนถึง Threat Modeling และ Security Assessment
ตามเอกสารฉบับนี้
