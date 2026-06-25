# HYBRID_RBA_ML_VALIDATION.md

# Central Auth Hub

## Hybrid Risk-Based Authentication Validation

Version: 1.0

---

# 1. Purpose

ประเมินประสิทธิภาพของ Hybrid RBA

ประกอบด้วย

* Rule Engine
* Behavior Profiling
* Isolation Forest
* Risk Aggregator

---

# 2. Evaluation Dataset

Normal Logins

Suspicious Logins

Attack Simulations

Passkey Step-Up Events

---

# 3. Metrics

## Precision

วัดความแม่นยำของการแจ้งเตือน

Formula

TP / (TP + FP)

---

## Recall

วัดความสามารถในการจับเหตุการณ์ผิดปกติ

Formula

TP / (TP + FN)

---

## F1 Score

วัดสมดุลระหว่าง Precision และ Recall

---

## ROC-AUC

วัดคุณภาพการจำแนก

---

## False Positive Rate

เป้าหมาย

< 5%

---

## False Negative Rate

เป้าหมาย

< 2%

---

# 4. Model Validation

## New Device

Expected

MFA

---

## New Country

Expected

MFA

---

## Impossible Travel

Expected

Block

---

## Credential Stuffing

Expected

Block

---

## Trusted Device

Expected

Pass

---

# 5. SHAP Explainability

Example

* new_country +0.32
* new_device +0.21
* passkey_age_days -0.18
* device_trust_score -0.15

---

# 6. Adversarial Testing

## Device Spoofing

Expected

Detected

---

## VPN Usage

Expected

Low Risk Increase

---

## Session Hijacking

Expected

Step-Up Authentication

---

# 7. Drift Monitoring

Monitor

* Precision
* Recall
* FPR
* FNR

Frequency

Monthly

---

# 8. Acceptance Criteria

Precision > 95%

Recall > 90%

F1 > 92%

False Positive < 5%

False Negative < 2%

---

# 9. Conclusion

Hybrid RBA สามารถลดความเสี่ยงจาก Account Takeover
และลด False Positive เมื่อเทียบกับ Rule-Based Authentication เพียงอย่างเดียว
