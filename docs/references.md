# เอกสารอ้างอิง (References) — Central Auth Hub

> รายการอ้างอิงทั้งหมดสำหรับปริญญานิพนธ์ พร้อมระบุ **ชัดเจนว่าอ้างอิงส่วนไหนของระบบ**
> (ไฟล์จริง · ฟังก์ชัน · feature · ค่าพารามิเตอร์) และ **ใช้ในบทไหนของเล่ม**
>
> ตรวจสอบผู้แต่ง/ปี/วารสาร/DOI แล้วเมื่อ 2026-07-22
>
> ⚠️ **แก้ไขจากเดิม:** `CLAUDE.md` ระบุ "Wiefling et al. (2022) ACM TOPS" —
> ที่ถูกต้องคือ **2023** (Vol. 26, Issue 1, Article 6, Feb 2023); ปี 2022 คือ arXiv preprint

---

## สารบัญ

1. [Risk-Based Authentication (RBA)](#1-risk-based-authentication-rba)
2. [Machine Learning & Anomaly Detection](#2-machine-learning--anomaly-detection)
3. [Attack Taxonomy & Threat Model](#3-attack-taxonomy--threat-model)
4. [Device / Browser Fingerprinting](#4-device--browser-fingerprinting)
5. [Standards & Specifications](#5-standards--specifications)
6. [ตารางสรุป: Feature → อ้างอิง](#6-ตารางสรุป-feature--อ้างอิง)
7. [ตารางสรุป: ไฟล์ในระบบ → อ้างอิง](#7-ตารางสรุป-ไฟล์ในระบบ--อ้างอิง)
8. [รายการที่ต้องตรวจสอบเพิ่ม](#8-รายการที่ต้องตรวจสอบเพิ่ม)
9. [BibTeX](#9-bibtex)

---

## 1. Risk-Based Authentication (RBA)

### [1] Wiefling et al. (2023) — ⭐ **อ้างอิงหลักของงานนี้**
> Wiefling, S., Jørgensen, P. R., Thunem, S., & Lo Iacono, L. (2023).
> **Pump Up Password Security! Evaluating and Enhancing Risk-Based Authentication on a Real-World Large-Scale Online Service.**
> *ACM Transactions on Privacy and Security (TOPS)*, 26(1), Article 6, 36 pages.
> DOI: [10.1145/3546069](https://doi.org/10.1145/3546069)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ไฟล์/ตำแหน่งจริง | ใช้อ้างอิงว่าอะไร |
|---|---|---|
| **Attacker Model 5 ระดับ** | `ml-service/scripts/generate_data.py` (ส่วนสร้าง anomaly) | นิยาม attacker: very naive / naive / VPN / targeted / very targeted → ใช้สร้าง attack dataset แบบ *labeled by construction* |
| **Feature ที่ RBA ควรเก็บ** | `app/services/feature_extraction.py` | IP, geolocation, user agent, device, timing เป็น feature มาตรฐานของ RBA |
| **Temporal features** | `hour_of_day` (idx 0), `day_of_week` (idx 1), `hours_from_typical_login_time` (idx 2) | ช่วงเวลา login เป็นสัญญาณความเสี่ยง |
| **Geographic features** | `is_thailand` (idx 3), `is_new_country` (idx 4), `country_change_count_30d` (idx 5) | ประเทศที่ผิดปกติเป็นสัญญาณ account takeover |
| **Threshold-based decision** | `app/security/risk_aggregator.py:20-22` (`block=0.85`, `challenge=0.7`, `warn=0.5`) | แนวคิดแบ่งช่วงคะแนน → allow / challenge / block |

**ประโยคตัวอย่างที่ใช้ในเล่ม:**
> "ระบบกำหนดโมเดลผู้โจมตี 4 ระดับตามระดับความรู้เกี่ยวกับเหยื่อ (naive, VPN, targeted) ตามแนวทางของ Wiefling et al. [1] เพื่อประเมินอัตราการตรวจจับในสถานการณ์ที่ผู้โจมตีมีข้อมูลต่างกัน"

**ใช้ในบท:** บทที่ 2 (ทฤษฎี), บทที่ 3 (ออกแบบระบบประเมินความเสี่ยง), บทที่ 4 (การประเมินผล)

---

### [2] Wiefling, Lo Iacono, & Dürmuth (2019)
> Wiefling, S., Lo Iacono, L., & Dürmuth, M. (2019).
> **Is This Really You? An Empirical Study on Risk-Based Authentication Applied in the Wild.**
> In *ICT Systems Security and Privacy Protection (IFIP SEC 2019)*, IFIP AICT vol. 562, pp. 134–148. Springer.
> DOI: [10.1007/978-3-030-22312-0_10](https://doi.org/10.1007/978-3-030-22312-0_10)

**อ้างอิงส่วนไหนของระบบ:**
- **การเลือก feature** (`feature_extraction.py`) — ยืนยันว่า IP + user agent + เวลา คือ feature ที่บริการออนไลน์ขนาดใหญ่ (Google, Amazon, LinkedIn) ใช้จริง
- **เหตุผลที่ไม่ใช้ feature ที่ล้ำเกินไป** — งานวิจัยพบว่าบริการจริงใช้ feature ไม่กี่ตัว
- **ที่มาของ `is_new_device`** (idx 6) — device เป็นสัญญาณที่บริการจริงใช้แพร่หลาย

**ประโยคตัวอย่าง:**
> "การศึกษาเชิงประจักษ์ของ Wiefling et al. [2] พบว่าบริการออนไลน์ขนาดใหญ่ใช้คุณลักษณะ IP address, user agent และเวลา login เป็นหลักในการประเมินความเสี่ยง ซึ่งสอดคล้องกับคุณลักษณะที่ระบบนี้เลือกใช้"

**ใช้ในบท:** บทที่ 2

---

### [3] Wiefling, Patil, Dürmuth, & Lo Iacono (2020)
> Wiefling, S., Patil, T., Dürmuth, M., & Lo Iacono, L. (2020).
> **Evaluation of Risk-based Re-Authentication Methods.**
> In *ICT Systems Security and Privacy Protection (IFIP SEC 2020)*, IFIP AICT vol. 580, pp. 280–294. Springer.
> DOI: [10.1007/978-3-030-58201-2_19](https://doi.org/10.1007/978-3-030-58201-2_19)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ไฟล์จริง | อ้างอิงว่าอะไร |
|---|---|---|
| **Risk-Triggered MFA** | `app/routers/auth.py` (branch `is_mfa_required`) | เมื่อคะแนนถึงเกณฑ์ → ขอยืนยันซ้ำ ไม่ใช่บล็อกทันที |
| **การเลือกวิธียืนยันซ้ำ** | `app/routers/passkey.py` — `/auth/passkey/risk-stepup` | เปรียบเทียบวิธี re-auth (passkey vs OTP) ว่าแบบไหนเหมาะ |
| **รองรับหลาย factor** | `risk-stepup` รับทั้ง Passkey และ TOTP | ผู้ใช้ควรมีทางเลือกวิธียืนยัน |

**ประโยคตัวอย่าง:**
> "การเลือกวิธียืนยันตัวตนซ้ำเมื่อพบความเสี่ยงอ้างอิงผลการประเมินของ Wiefling et al. [3] ซึ่งเปรียบเทียบวิธี re-authentication แบบต่าง ๆ ระบบนี้จึงรองรับทั้ง Passkey (phishing-resistant) และ TOTP (ใช้ได้ทุกอุปกรณ์)"

**ใช้ในบท:** บทที่ 3 (ออกแบบ Risk-Triggered MFA)

---

### [4] Wiefling, Dürmuth, & Lo Iacono (2021) — Long-term study
> Wiefling, S., Dürmuth, M., & Lo Iacono, L. (2021).
> **What's in Score for Website Users: A Data-Driven Long-Term Study on Risk-Based Authentication Characteristics.**
> In *Financial Cryptography and Data Security (FC 2021)*, pp. 361–381. Springer.
> DOI: [10.1007/978-3-662-64331-0_19](https://doi.org/10.1007/978-3-662-64331-0_19)

**อ้างอิงส่วนไหนของระบบ:**
- **การตั้งค่า threshold** — `app/security/risk_aggregator.py:17-22`
  ```python
  # ML-driven normal score p90=0.6 p95=0.7 → challenge 0.7 ทำให้ FPR 24%→5.8%
  THRESHOLDS = {"block": 0.85, "challenge": 0.7, "warn": 0.5}
  ```
  ใช้อ้างว่าการเลือก threshold ควรอิงจากการกระจายตัวของคะแนน (percentile) ไม่ใช่ตั้งลอย ๆ
- **สคริปต์ calibrate** — `hub/backend/scripts/calibrate_thresholds.py`
- **การเฝ้าดูคะแนนระยะยาว** — `scripts/check_feature_drift.py`

**ประโยคตัวอย่าง:**
> "การกำหนดค่าขีดแบ่ง (threshold) อ้างอิงแนวทางของ Wiefling et al. [4] ที่ศึกษาการกระจายตัวของคะแนนความเสี่ยงในระยะยาว ระบบนี้จึงปรับ challenge threshold จาก 0.5 เป็น 0.7 ตามค่า p95 ของคะแนนผู้ใช้ปกติ ทำให้ FPR ลดจาก 24% เหลือ 5.8%"

**ใช้ในบท:** บทที่ 3 (การตั้ง threshold), บทที่ 4 (การประเมินผล)

---

### [5] Wiefling, Dürmuth, & Lo Iacono (2020) — Usability
> Wiefling, S., Dürmuth, M., & Lo Iacono, L. (2020).
> **More Than Just Good Passwords? A Study on Usability and Security Perceptions of Risk-based Authentication.**
> In *Proceedings of the 36th Annual Computer Security Applications Conference (ACSAC 2020)*, pp. 203–218. ACM.
> DOI: [10.1145/3427228.3427243](https://doi.org/10.1145/3427228.3427243)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ไฟล์จริง | อ้างอิงว่าอะไร |
|---|---|---|
| **เลือก adaptive แทนบังคับ 2FA ทุกคน** | `app/services/mfa_policy.py` — `is_second_factor_required()` | RBA รบกวนผู้ใช้น้อยกว่าการบังคับ MFA ตลอด |
| **Always-2FA เป็น opt-in ไม่บังคับ** | `User.mfa_always` + `SecurityCard.tsx` | ให้ผู้ใช้เลือกระดับความปลอดภัยเอง |
| **ไม่บังคับตั้ง factor (snooze ได้)** | `mfa_policy.should_prompt_setup()` + `snooze_onboarding()` | บังคับมากเกินไปกระทบ usability |

**ประโยคตัวอย่าง:**
> "งานวิจัยของ Wiefling et al. [5] แสดงว่า RBA ได้รับการยอมรับจากผู้ใช้ดีกว่าการบังคับใช้ 2FA ตลอดเวลา ระบบนี้จึงออกแบบให้ยืนยันซ้ำเฉพาะเมื่อพบความเสี่ยง และเปิดให้ผู้ใช้เลือกโหมด Always-2FA ได้เองตามความสมัครใจ"

**ใช้ในบท:** บทที่ 3 (เหตุผลการออกแบบ), บทที่ 5 (สรุปและอภิปราย)

---

### [6] Wiefling, Dürmuth, & Lo Iacono (2021) — User perception
> Wiefling, S., Dürmuth, M., & Lo Iacono, L. (2021).
> **Verify It's You: How Users Perceive Risk-based Authentication.**
> *IEEE Security & Privacy*, 19(6), 47–57.
> DOI: [10.1109/MSEC.2021.3077954](https://doi.org/10.1109/MSEC.2021.3077954)

**อ้างอิงส่วนไหนของระบบ:**
- **การแสดงเหตุผลให้ผู้ใช้เห็น** — `app/routers/passkey.py:_risk_stepup_html()` แสดง `risk_reasons` ("ปัจจัยเสี่ยงที่ตรวจพบ")
- **ข้อความที่ไม่ทำให้ผู้ใช้ตกใจ** — หน้า risk-stepup แสดง "ตรวจพบความเสี่ยง" เฉพาะเมื่อ *เกิดจาก risk จริง* ไม่แสดงเมื่อเป็น Always-2FA

**ประโยคตัวอย่าง:**
> "การอธิบายเหตุผลที่ต้องยืนยันซ้ำช่วยให้ผู้ใช้เข้าใจและยอมรับระบบมากขึ้น [6] ระบบนี้จึงแสดงปัจจัยเสี่ยงที่ตรวจพบบนหน้ายืนยันตัวตน"

**ใช้ในบท:** บทที่ 3 (ออกแบบ UI), บทที่ 5

---

### [7] Wiefling, Tolsdorf, & Lo Iacono (2021) — Privacy
> Wiefling, S., Tolsdorf, J., & Lo Iacono, L. (2021).
> **Privacy Considerations for Risk-Based Authentication Systems.**
> In *International Workshop on Privacy Engineering (IWPE 2021)*, pp. 320–327. IEEE.
> DOI: [10.1109/EuroSPW54576.2021.00040](https://doi.org/10.1109/EuroSPW54576.2021.00040)

**อ้างอิงส่วนไหนของระบบ:**
- **เก็บแค่ประเทศ ไม่เก็บพิกัด** — `app/services/geoip.py` `lookup_country()` คืนเฉพาะรหัสประเทศ (ไม่เก็บ lat/lon)
- **Impossible travel แบบไม่ใช้พิกัด** — `feature_extraction.py` คำนวณจาก *การเปลี่ยนประเทศ + เวลา* แทน lat/lon (data minimization)
- **การเก็บ log ที่จำเป็นเท่านั้น** — `login_sessions` เก็บ IP/UA เพื่อความปลอดภัย

**ประโยคตัวอย่าง:**
> "ตามข้อพิจารณาด้านความเป็นส่วนตัวของ RBA [7] ระบบนี้เก็บข้อมูลตำแหน่งเพียงระดับประเทศ และคำนวณ impossible travel จากการเปลี่ยนประเทศเทียบกับเวลา โดยไม่จัดเก็บพิกัดละติจูด/ลองจิจูด"

**ใช้ในบท:** บทที่ 3 (ความเป็นส่วนตัว), บทที่ 5 (ข้อจำกัด)

---

### [8] Unsel, Wiefling, Gruschka, & Lo Iacono (2023) — Implementation
> Unsel, V., Wiefling, S., Gruschka, N., & Lo Iacono, L. (2023).
> **Risk-Based Authentication for OpenStack: A Fully Functional Implementation and Guiding Example.**
> In *Proceedings of the 13th ACM Conference on Data and Application Security and Privacy (CODASPY 2023)*. ACM.
> DOI: [10.1145/3577923.3583634](https://doi.org/10.1145/3577923.3583634)

**อ้างอิงส่วนไหนของระบบ:**
- **สถาปัตยกรรมแยก ML service** — `ml-service/` แยก container จาก Hub (port 9000)
- **การผนวก RBA เข้ากับระบบ identity ที่มีอยู่** — เทียบกับการที่ Hub ผนวก RBA เข้ากับ OAuth flow เดิม
- **Fail-safe** — `app/services/ml_client.py` (ML ล่ม → คืนคะแนน 0.0 ไม่ทำให้ระบบล่ม)

**ประโยคตัวอย่าง:**
> "งานของ Unsel et al. [8] แสดงตัวอย่างการนำ RBA ไปใช้กับระบบ identity จริง (OpenStack) ระบบนี้ใช้แนวทางคล้ายกันโดยแยกบริการประเมินความเสี่ยงออกเป็น microservice"

**ใช้ในบท:** บทที่ 2 (งานที่เกี่ยวข้อง), บทที่ 3 (สถาปัตยกรรม)

---

### [9] Büttner, Pedersen, Wiefling, Gruschka, & Lo Iacono (2024) — ⭐ **Account Recovery**
> Büttner, A., Pedersen, A. T., Wiefling, S., Gruschka, N., & Lo Iacono, L. (2024).
> **Is It Really You Who Forgot the Password? When Account Recovery Meets Risk-Based Authentication.**
> In *Ubiquitous Security (UbiSec 2023)*. Springer.
> DOI: [10.1007/978-981-97-1274-8_26](https://doi.org/10.1007/978-981-97-1274-8_26)

**อ้างอิงส่วนไหนของระบบ:** ⭐ *ตรงกับระบบกู้บัญชีของงานนี้มากที่สุด*

| ส่วนของระบบ | ไฟล์จริง | อ้างอิงว่าอะไร |
|---|---|---|
| **Recovery ladder** | `app/routers/passkey.py` (`/recover/*`), `app/routers/recovery.py` | ลำดับการกู้บัญชี: Passkey → TOTP → Recovery Ticket |
| **กู้บัญชีคือจุดอ่อนของ MFA** | `app/services/credential_service.py` `recovery_ready()` | ถ้ากู้บัญชีอ่อนแอ MFA ที่แข็งแรงก็ไร้ความหมาย |
| **Recovery ต้องประเมินความเสี่ยงด้วย** | Recovery Ticket + four-eyes approval | การกู้บัญชีต้องมีการยืนยันหลายชั้น |
| **TOTP เป็น recovery factor** | `app/services/totp_service.py` | ปัจจัยสำรองสำหรับกรณีเข้าอีเมลเดิมไม่ได้ |

**ประโยคตัวอย่าง:**
> "Büttner et al. [9] ชี้ว่ากระบวนการกู้บัญชีมักเป็นจุดอ่อนที่สุดของระบบยืนยันตัวตนหลายปัจจัย ระบบนี้จึงออกแบบลำดับการกู้บัญชี (recovery ladder) ที่ยังคงต้องพิสูจน์การครอบครองปัจจัยยืนยันตัวตน และใช้กระบวนการอนุมัติสองคน (four-eyes) สำหรับกรณีที่ผู้ใช้ไม่มีปัจจัยใดเหลืออยู่"

**ใช้ในบท:** บทที่ 3 (ระบบกู้บัญชี) ⭐ สำคัญมาก

---

### [10] Freeman, Jain, Dürmuth, Biggio, & Giacinto (2016)
> Freeman, D., Jain, S., Dürmuth, M., Biggio, B., & Giacinto, G. (2016).
> **Who Are You? A Statistical Approach to Measuring User Authenticity.**
> In *Network and Distributed System Security Symposium (NDSS 2016)*.
> [PDF](https://theory.stanford.edu/~dfreeman/papers/ato-model.pdf)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ไฟล์/ตำแหน่ง | อ้างอิงว่าอะไร |
|---|---|---|
| **`is_new_country`** | `feature_extraction.py` (idx 4) | ประเทศที่ไม่เคยพบ = สัญญาณ account takeover |
| **การรวมคะแนนหลายสัญญาณ** | `app/security/risk_aggregator.py` `aggregate()` | แนวคิดรวมหลาย feature เป็นคะแนนเดียว |
| **Behavior profiling** | `app/security/behavior_profiling.py` `get_user_profile()` | เทียบพฤติกรรมกับ baseline ของผู้ใช้แต่ละคน |
| **แนวคิด account takeover detection** | `LoginSession.is_account_takeover` | นิยามของ ATO ที่ใช้เป็น label |

**ประโยคตัวอย่าง:**
> "Freeman et al. [10] เสนอวิธีเชิงสถิติสำหรับตรวจจับการยึดบัญชี (account takeover) ที่ LinkedIn โดยใช้คุณลักษณะ IP, ตำแหน่งภูมิศาสตร์, การตั้งค่าเบราว์เซอร์ และเวลาที่ login ระบบนี้นำแนวคิดการเทียบพฤติกรรมกับประวัติของผู้ใช้แต่ละคนมาใช้ในชั้น Behavior Profiling"

**ใช้ในบท:** บทที่ 2, บทที่ 3 (ชั้น Behavior Profiling)

---

## 2. Machine Learning & Anomaly Detection

### [11] Liu, Ting, & Zhou (2008) — ⭐ **Isolation Forest**
> Liu, F. T., Ting, K. M., & Zhou, Z.-H. (2008).
> **Isolation Forest.**
> In *Proceedings of the 8th IEEE International Conference on Data Mining (ICDM 2008)*, pp. 413–422. IEEE.
> DOI: [10.1109/ICDM.2008.17](https://doi.org/10.1109/ICDM.2008.17)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ไฟล์จริง | อ้างอิงว่าอะไร |
|---|---|---|
| **อัลกอริทึมหลักของ ML Verifier** | `ml-service/app/model.py` | Isolation Forest แยก anomaly ด้วยการสุ่มแบ่ง (path length สั้น = ผิดปกติ) |
| **ชั้นที่ 3 ของ 4-Layer RBA** | `app/security/iforest_scorer.py` | นำคะแนนจากโมเดลมาแปลงเป็น risk score |
| **การเทรน** | `ml-service/scripts/train_model.py:151-159` — `fit(X_train_normal)` | ⭐ **เทรนด้วย normal อย่างเดียว (unsupervised)** — เหตุผลสำคัญที่เลือกอัลกอริทึมนี้ เพราะไม่มี attack label จริง |
| **พารามิเตอร์** | `train_model.py:153-154` — `n_estimators=100`, `contamination=0.02` | ค่าพารามิเตอร์ตามทฤษฎีของ Isolation Forest |

**ประโยคตัวอย่าง:**
> "ระบบเลือกใช้ Isolation Forest [11] เป็นชั้นตรวจจับความผิดปกติ เนื่องจากเป็นวิธีแบบ unsupervised ที่เรียนรู้จากข้อมูลปกติเพียงอย่างเดียว จึงเหมาะกับบริบทที่ไม่มีชุดข้อมูลการโจมตีที่มีป้ายกำกับ (labeled attack data)"

**ใช้ในบท:** บทที่ 2 (ทฤษฎี ML), บทที่ 3 (ออกแบบ ML Verifier)

---

### [12] Liu, Ting, & Zhou (2012) — Isolation Forest ฉบับขยาย
> Liu, F. T., Ting, K. M., & Zhou, Z.-H. (2012).
> **Isolation-Based Anomaly Detection.**
> *ACM Transactions on Knowledge Discovery from Data (TKDD)*, 6(1), Article 3.
> DOI: [10.1145/2133360.2133363](https://doi.org/10.1145/2133360.2133363)

**อ้างอิงส่วนไหนของระบบ:**
- **ค่า `contamination=0.02`** — `train_model.py:154` (สัดส่วน anomaly ที่คาดว่ามีในข้อมูล)
- **การแปลง anomaly score** — `ml-service/app/model.py` (sigmoid mapping)
- **ทฤษฎี path length → anomaly score**

**ประโยคตัวอย่าง:**
> "การกำหนดค่า contamination และการแปลงคะแนนอ้างอิงทฤษฎี isolation-based anomaly detection [12]"

**ใช้ในบท:** บทที่ 3 (รายละเอียดโมเดล)

---

### [13] Lundberg & Lee (2017) — ⭐ **SHAP**
> Lundberg, S. M., & Lee, S.-I. (2017).
> **A Unified Approach to Interpreting Model Predictions.**
> In *Advances in Neural Information Processing Systems 30 (NIPS 2017)*, pp. 4765–4774.
> [Paper](https://papers.nips.cc/paper/7062-a-unified-approach-to-interpreting-model-predictions)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ไฟล์จริง | อ้างอิงว่าอะไร |
|---|---|---|
| **SHAP TreeExplainer** | `ml-service/app/` (ส่วน explanation) | คำนวณ contribution ของแต่ละ feature |
| **`iforest_explanation`** | `app/security/risk_engine.py:107` | ส่งค่าอธิบายกลับไปแสดงผล |
| **แสดงผลเป็น bar chart** | Frontend หน้า SOC / ML threshold preview | ผู้ดูแลระบบเห็นว่า feature ใดทำให้คะแนนสูง |

**ประโยคตัวอย่าง:**
> "เพื่อให้ผลการตัดสินใจของโมเดลอธิบายได้ (explainable) ระบบใช้ SHAP [13] คำนวณค่าการมีส่วนร่วมของแต่ละคุณลักษณะ ทำให้ผู้ดูแลระบบทราบว่าเหตุใดการเข้าสู่ระบบครั้งหนึ่งจึงถูกประเมินว่าเสี่ยง"

**ใช้ในบท:** บทที่ 3 (Explainability), บทที่ 4 (การแสดงผล)

---

### [14] (2025) — Neural Networks สำหรับ RBA
> **That's not you! Applying Neural Networks to Risk-Based Authentication to Detect Suspicious Logins.**
> In *Proceedings of the 18th ACM Workshop on Artificial Intelligence and Security (AISec 2025)*. ACM.
> DOI: [10.1145/3733799.3762970](https://dl.acm.org/doi/10.1145/3733799.3762970)

**อ้างอิงส่วนไหนของระบบ:**
- **ใช้เปรียบเทียบทางเลือก** — อธิบายว่าทำไมงานนี้เลือก Isolation Forest แทน neural network
  - NN ต้องการ **labeled data จำนวนมาก** ซึ่งงานนี้ไม่มี
  - Isolation Forest เทรนด้วย normal อย่างเดียวได้
  - Isolation Forest + SHAP อธิบายผลได้ง่ายกว่า

**ประโยคตัวอย่าง:**
> "แม้จะมีงานวิจัยที่นำโครงข่ายประสาทเทียมมาใช้กับ RBA [14] แต่วิธีดังกล่าวต้องอาศัยชุดข้อมูลที่มีป้ายกำกับจำนวนมาก งานนี้จึงเลือกใช้ Isolation Forest ซึ่งเป็นวิธี unsupervised ที่เหมาะกับข้อจำกัดด้านข้อมูลของระบบ"

**ใช้ในบท:** บทที่ 2 (งานที่เกี่ยวข้อง), บทที่ 5 (แนวทางพัฒนาต่อ)

---

### [14b] Fereidouni, Hafid, Makrakis, & Baseri (2024) — **F-RBA**
> Fereidouni, H., Hafid, A. S., Makrakis, D., & Baseri, Y. (2024).
> **F-RBA: A Federated Learning-based Framework for Risk-based Authentication.**
> arXiv preprint arXiv:2412.12324. Submitted 16 December 2024.
> [arXiv:2412.12324](https://arxiv.org/abs/2412.12324)

**สถานะ:** ✅ **เจอตัวจริงแล้ว** — นี่คือ "F-RBA 2024" ที่ `CLAUDE.md` อ้างถึง
> ⚠️ เป็น **arXiv preprint** ยังไม่ผ่าน peer review และยังไม่ตีพิมพ์ในวารสาร/การประชุม
> → ถ้าจะอ้างในเล่ม ต้องระบุว่าเป็น preprint (บางมหาวิทยาลัยไม่นับ preprint เป็นอ้างอิงหลัก)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ตำแหน่งจริง | อ้างอิงว่าอะไร |
|---|---|---|
| **Cold-start policy** | `feature_extraction.py:32` — `MIN_HISTORY_FOR_PERSONALIZATION = 5` · `behavior_profiling.py:19` — `COLD_START_SCORE = 0.20` | F-RBA เสนอวิธีรับมือผู้ใช้ใหม่ที่ยังไม่มีประวัติ (cold start) ด้วย global model — ระบบนี้ใช้วิธีให้ค่า neutral แทน |
| **Similarity-based feature engineering** | `feature_extraction.py` — feature เชิงเปรียบเทียบ เช่น `is_new_country`, `is_new_device`, `hours_from_typical_login_time` | แนวคิดสร้าง feature จาก "ความต่างจากประวัติเดิม" แทนค่าดิบ |
| **เปรียบเทียบสถาปัตยกรรม** | `ml-service/` (centralized) | F-RBA = federated (ประเมินบนเครื่องผู้ใช้); ระบบนี้ = centralized → ใช้อภิปรายข้อดี/ข้อเสีย |
| **ข้อจำกัดด้าน privacy ของ centralized RBA** | `login_sessions` เก็บ IP/UA ที่ server | F-RBA ชี้ว่า centralized RBA ต้องส่งข้อมูลดิบไปเก็บที่ server = ความเสี่ยงด้านความเป็นส่วนตัว |

**ประโยคตัวอย่าง:**
> "Fereidouni et al. [14b] เสนอกรอบงาน F-RBA ที่ใช้ federated learning ประเมินความเสี่ยงบนอุปกรณ์ของผู้ใช้
> เพื่อลดความเสี่ยงด้านความเป็นส่วนตัวจากการรวมศูนย์ข้อมูล พร้อมทั้งเสนอวิธีรับมือปัญหา cold start
> สำหรับผู้ใช้ใหม่ที่ยังไม่มีประวัติเพียงพอ ระบบในงานนี้ใช้สถาปัตยกรรมแบบรวมศูนย์
> และแก้ปัญหา cold start ด้วยการกำหนดค่ากลาง (neutral) เมื่อประวัติน้อยกว่า 5 ครั้ง"

**ใช้ในบท:** บทที่ 2 (งานที่เกี่ยวข้อง), บทที่ 3 (Cold-start policy), บทที่ 5 (แนวทางพัฒนาต่อ — federated learning)

---

### [14c] (2025) — Privacy-Preserving Federated RBA *(งานต่อยอด)*
> **Privacy-Preserving Federated Learning Framework for Risk-Based Adaptive Authentication.**
> arXiv preprint arXiv:2508.18453 (2025).
> [arXiv:2508.18453](https://arxiv.org/abs/2508.18453)

**อ้างอิงส่วนไหนของระบบ:** งานล่าสุดในทิศทาง federated RBA → ใช้ในบทที่ 5 (แนวทางพัฒนาต่อ)

---

## 3. Attack Taxonomy & Threat Model

> 📌 ใช้สำหรับ **สร้าง attack dataset (labeled by construction)** และหัวข้อ Threat Model
> เพื่อยืนยันว่ารูปแบบการโจมตีที่จำลองขึ้น **อ้างอิงจากมาตรฐานสากล ไม่ได้คิดขึ้นเอง**

### [15] MITRE ATT&CK — Valid Accounts (T1078)
> MITRE. **Valid Accounts (T1078).** MITRE ATT&CK Enterprise Matrix.
> [https://attack.mitre.org/techniques/T1078/](https://attack.mitre.org/techniques/T1078/)

**อ้างอิงส่วนไหนของระบบ:**
- **นิยามภัยหลักที่ระบบนี้รับมือ** — ผู้โจมตีมี credential ที่ถูกต้อง แต่พฤติกรรมผิดปกติ
- **เหตุผลที่ต้องมี RBA** — รหัสผ่านถูกต้องจึงผ่านการตรวจสอบแบบเดิมได้ ต้องดูพฤติกรรมประกอบ
- **`LoginSession.is_account_takeover`** — คอลัมน์ label สำหรับ ATO

**ประโยคตัวอย่าง:**
> "เทคนิค Valid Accounts (T1078) [15] คือการที่ผู้โจมตีใช้ข้อมูลรับรองที่ถูกต้องเข้าสู่ระบบ ทำให้กลไกตรวจสอบรหัสผ่านแบบดั้งเดิมไม่สามารถตรวจจับได้ จึงเป็นเหตุผลหลักที่ระบบนี้ใช้การยืนยันตัวตนตามความเสี่ยง"

**ใช้ในบท:** บทที่ 1 (ที่มาและความสำคัญ), บทที่ 3 (Threat Model)

---

### [16] MITRE ATT&CK — Credential Stuffing (T1110.004)
> MITRE. **Brute Force: Credential Stuffing (T1110.004).** MITRE ATT&CK Enterprise Matrix.
> [https://attack.mitre.org/techniques/T1110/004/](https://attack.mitre.org/techniques/T1110/004/)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ตำแหน่งจริง | อ้างอิงว่าอะไร |
|---|---|---|
| **`failed_logins_24h`** | `feature_extraction.py` (idx 10) | จำนวน login ล้มเหลวเป็นสัญญาณ credential stuffing |
| **Rule: `failed_logins_24h >= 3`** | `rule_engine.py:65` (น้ำหนัก **0.20**) | กฎตรวจจับโดยตรง |
| **scenario ใน validation doc** | `HYBRID_RBA_ML_VALIDATION.md §4` | Expected: Block |
| **Rate limiting** | `app/rate_limiter.py` | ป้องกันการลองรหัสจำนวนมาก |

**ประโยคตัวอย่าง:**
> "ระบบตรวจจับ credential stuffing (T1110.004) [16] ผ่านคุณลักษณะ `failed_logins_24h` โดยกำหนดกฎว่าหากมีการเข้าสู่ระบบล้มเหลวตั้งแต่ 3 ครั้งขึ้นไปภายใน 24 ชั่วโมง จะเพิ่มคะแนนความเสี่ยง 0.20"

**ใช้ในบท:** บทที่ 3 (Rule Engine), บทที่ 4 (การทดสอบ)

---

### [17] MITRE ATT&CK — Password Spraying (T1110.003)
> MITRE. **Brute Force: Password Spraying (T1110.003).** MITRE ATT&CK Enterprise Matrix.
> [https://attack.mitre.org/techniques/T1110/003/](https://attack.mitre.org/techniques/T1110/003/)

**อ้างอิงส่วนไหนของระบบ:**
- **`_check_multi_account_ip()`** — `rule_engine.py:249` (ตรวจ IP เดียวเข้าหลายบัญชี)
- **`MULTI_ACCOUNT_SCORE = 0.25`** — `rule_engine.py:74`
- **IP Blacklist** — `app/services/ip_blacklist.py`

**ประโยคตัวอย่าง:**
> "การโจมตีแบบ password spraying (T1110.003) [17] มีลักษณะเด่นคือ IP เดียวพยายามเข้าสู่ระบบหลายบัญชี ระบบจึงตรวจสอบจำนวนบัญชีที่ถูกเข้าถึงจาก IP เดียวกัน และเพิ่มคะแนนความเสี่ยง 0.25 เมื่อพบรูปแบบดังกล่าว"

**ใช้ในบท:** บทที่ 3 (Rule Engine)

---

### [18] MITRE ATT&CK — Steal Web Session Cookie (T1539)
> MITRE. **Steal Web Session Cookie (T1539).** MITRE ATT&CK Enterprise Matrix.
> [https://attack.mitre.org/techniques/T1539/](https://attack.mitre.org/techniques/T1539/)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ตำแหน่งจริง | อ้างอิงว่าอะไร |
|---|---|---|
| **HttpOnly + SameSite cookie** | `app/api/set-token/route.ts` (frontend), subsystem `services/session.py` | ป้องกัน cookie ถูกขโมยผ่าน JS |
| **Token Revocation** | `app/services/jwt_service.py` `revoke_jti()` | ยกเลิก token ที่ถูกขโมยได้ทันที |
| **`concurrent_session_count`** | `feature_extraction.py` (idx 15) | session พร้อมกันหลายที่ = สัญญาณ hijack |
| **scenario Adversarial Testing** | `HYBRID_RBA_ML_VALIDATION.md §6` | Session Hijacking |

**ประโยคตัวอย่าง:**
> "เพื่อรับมือกับการขโมย session cookie (T1539) [18] ระบบกำหนด cookie เป็น HttpOnly และ SameSite พร้อมทั้งรองรับการเพิกถอน token ผ่าน jti blacklist"

**ใช้ในบท:** บทที่ 3 (ความปลอดภัย session)

---

### [19] Adversary Models for Mobile Device Authentication
> **Adversary Models for Mobile Device Authentication.**
> arXiv preprint. [arXiv:2009.10150](https://arxiv.org/pdf/2009.10150)

**อ้างอิงส่วนไหนของระบบ:**
- **วิธีนิยาม adversary model อย่างเป็นระบบ** — รองรับการออกแบบ attacker model 4 ระดับ
- **การจัดระดับความสามารถของผู้โจมตี** — ใช้ประกอบ [1]

**ใช้ในบท:** บทที่ 3 (Threat Model)

---

## 4. Device / Browser Fingerprinting

### [20] Laperdrix, Bielova, Baudry, & Avoine (2020)
> Laperdrix, P., Bielova, N., Baudry, B., & Avoine, G. (2020).
> **Browser Fingerprinting: A Survey.**
> *ACM Transactions on the Web (TWEB)*, 14(2), Article 8.
> DOI: [10.1145/3386040](https://doi.org/10.1145/3386040) · [PDF](https://www-sop.inria.fr/members/Nataliia.Bielova/papers/Lape-etal-20-TWEB.pdf)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ตำแหน่งจริง | อ้างอิงว่าอะไร |
|---|---|---|
| **`is_new_device`** | `feature_extraction.py` (idx 6) | ใช้ user agent ระบุอุปกรณ์ |
| **`is_new_user_agent_family`** | `feature_extraction.py` (idx 7) | ตระกูลเบราว์เซอร์เป็นสัญญาณที่เสถียรกว่า UA string เต็ม |
| **`browser_family()`, `parse_os_name()`, `parse_device_type()`** | `feature_extraction.py:66-159` | การแยกส่วนประกอบของ fingerprint |
| **ข้อจำกัด** | — | ⚠️ user agent ปลอมแปลงได้ → เหตุผลที่ไม่ใช้เป็นสัญญาณเดี่ยว |

**ประโยคตัวอย่าง:**
> "ระบบใช้ user agent เป็นตัวแทน (proxy) ของลายนิ้วมืออุปกรณ์ตามแนวทางใน [20] อย่างไรก็ตาม งานวิจัยดังกล่าวชี้ว่า user agent สามารถปลอมแปลงได้ ระบบจึงไม่ใช้เป็นสัญญาณเดี่ยว แต่รวมกับคุณลักษณะอื่นในการประเมิน"

**ใช้ในบท:** บทที่ 2, บทที่ 3 (Device features), บทที่ 5 (ข้อจำกัด)

---

### [21b] Iqbal, Englehardt, & Shafiq (2021) — ⚠️ **ตรวจสอบแล้ว: ใช้ผิดบริบท**
> Iqbal, U., Englehardt, S., & Shafiq, Z. (2021).
> **Fingerprinting the Fingerprinters: Learning to Detect Browser Fingerprinting Behaviors.**
> In *2021 IEEE Symposium on Security and Privacy (S&P)*, pp. 1143–1161. IEEE.
> DOI: [10.1109/SP40001.2021.00017](https://doi.org/10.1109/SP40001.2021.00017) ·
> [Project page](https://uiowa-irl.github.io/FP-Inspector/)

**สถานะ:** ✅ เปเปอร์มีจริง (นี่คือ "Iqbal 2021" ที่ `CLAUDE.md` อ้างถึงแน่นอน)

**⚠️ แต่อ้างผิดวัตถุประสงค์:**
`CLAUDE.md` อ้างเปเปอร์นี้สนับสนุน feature `is_new_user_agent_family` (ใช้ fingerprint **เพื่อยืนยันตัวตน**)
แต่เนื้อหาจริงของเปเปอร์คือ **การตรวจจับและบล็อกสคริปต์ fingerprinting เพื่อความเป็นส่วนตัว** (FP-Inspector)
— เป็นงานฝั่ง *ต่อต้าน* การ fingerprint ไม่ใช่ฝั่ง *ใช้* fingerprint

| ประเด็น | เปเปอร์นี้ทำ | ที่ `CLAUDE.md` อ้าง |
|---|---|---|
| วัตถุประสงค์ | ตรวจจับ/บล็อกสคริปต์ fingerprinting | ใช้ fingerprint ระบุอุปกรณ์ |
| มุมมอง | Privacy / anti-tracking | Authentication |

**คำแนะนำ:**
- ❌ **อย่าใช้อ้าง `is_new_user_agent_family` โดยตรง** → ใช้ **[20] Laperdrix** และ **[21] Andriamilanto** แทน
- ✅ **ใช้ได้ในบทที่ 5 (ข้อจำกัด/จริยธรรม)** — อ้างว่า fingerprinting เป็นเทคนิคที่มีประเด็นด้านความเป็นส่วนตัว
  และมีเครื่องมือตรวจจับ/บล็อก → เป็นเหตุผลว่าทำไมระบบนี้ใช้เพียง user agent (ข้อมูลที่เบราว์เซอร์ส่งมาปกติ)
  แทนการทำ active fingerprinting

**ประโยคตัวอย่าง (ถ้าจะใช้):**
> "แม้ browser fingerprinting จะเพิ่มความแม่นยำในการระบุอุปกรณ์ แต่เป็นเทคนิคที่มีข้อกังวลด้านความเป็นส่วนตัว
> จนมีงานวิจัยพัฒนาเครื่องมือตรวจจับและบล็อกโดยเฉพาะ [21b] ระบบนี้จึงใช้เพียง user agent ที่เบราว์เซอร์ส่งมา
> ตามปกติ โดยไม่ดำเนินการ active fingerprinting"

**ใช้ในบท:** บทที่ 5 (ข้อจำกัดและจริยธรรม) — **ไม่ใช่** บทที่ 3

---

### [21] Andriamilanto, Allard, & Le Guelvouit (2021)
> **A Large-scale Empirical Analysis of Browser Fingerprints Properties for Web Authentication.**
> *ACM Transactions on the Web*, 2021.
> DOI: [10.1145/3478026](https://doi.org/10.1145/3478026) · [arXiv:2006.09511](https://arxiv.org/pdf/2006.09511)

**อ้างอิงส่วนไหนของระบบ:**
- **ความน่าเชื่อถือของ fingerprint ในการยืนยันตัวตน** — ประเมินว่าการใช้ UA เป็น proxy เพียงพอหรือไม่
- **แนวทางพัฒนาต่อ** — `ML_IMPROVEMENT_PLAN.md §3.3` (Device fingerprint แทน user_agent proxy)

**ใช้ในบท:** บทที่ 5 (ข้อเสนอแนะการพัฒนาต่อ)

---

## 5. Standards & Specifications

### [22] RFC 6749 — OAuth 2.0
> Hardt, D. (2012). **The OAuth 2.0 Authorization Framework.** RFC 6749, IETF.
> [https://datatracker.ietf.org/doc/html/rfc6749](https://datatracker.ietf.org/doc/html/rfc6749)

**อ้างอิงส่วนไหนของระบบ:**
- **`app/routers/oauth.py`** — `/oauth/authorize`, `/oauth/callback`, `/oauth/token`
- **Authorization Code Grant** — flow ที่ระบบใช้
- **`subsystems` table** — `client_id`, `client_secret_hash`, `redirect_uris`, `scope`

**ใช้ในบท:** บทที่ 2 (ทฤษฎี OAuth), บทที่ 3 (ระบบจัดการระบบย่อย)

---

### [23] RFC 7636 — PKCE
> Sakimura, N., Bradley, J., & Agarwal, N. (2015). **Proof Key for Code Exchange by OAuth Public Clients.** RFC 7636, IETF.
> [https://datatracker.ietf.org/doc/html/rfc7636](https://datatracker.ietf.org/doc/html/rfc7636)

**อ้างอิงส่วนไหนของระบบ:**
- **`app/services/pkce.py`** — `verify_pkce()`, `generate_pkce_pair()`
- **ใช้ `hmac.compare_digest`** — ป้องกัน timing attack (กฎ B3 ในโปรเจกต์)
- **บังคับทุก subsystem flow** — ป้องกัน authorization code interception

**ประโยคตัวอย่าง:**
> "ระบบบังคับใช้ PKCE (RFC 7636) [23] ในทุกกระบวนการ OAuth ของระบบย่อย เพื่อป้องกันการดักจับ authorization code"

**ใช้ในบท:** บทที่ 3 (ความปลอดภัย OAuth)

---

### [24] RFC 7519 — JWT
> Jones, M., Bradley, J., & Sakimura, N. (2015). **JSON Web Token (JWT).** RFC 7519, IETF.
> [https://datatracker.ietf.org/doc/html/rfc7519](https://datatracker.ietf.org/doc/html/rfc7519)

**อ้างอิงส่วนไหนของระบบ:**
- **`app/services/jwt_service.py`** — `create_access_token()`, `create_subsystem_token()`, `verify_token()`
- **`aud` claim** — Hub-direct = `hub.internal`, subsystem = `client_id` (ป้องกัน audience confusion)
- **`jti` claim** — ใช้กับ token revocation
- **RS256** — ลายเซ็นแบบ asymmetric + JWKS endpoint

**ใช้ในบท:** บทที่ 3 (ระบบ token)

---

### [25] RFC 6238 — TOTP
> M'Raihi, D., Machani, S., Pei, M., & Rydell, J. (2011). **TOTP: Time-Based One-Time Password Algorithm.** RFC 6238, IETF.
> [https://datatracker.ietf.org/doc/html/rfc6238](https://datatracker.ietf.org/doc/html/rfc6238)

**อ้างอิงส่วนไหนของระบบ:**
- **`app/services/totp_service.py`** — `generate_secret()`, `verify(secret, code, valid_window=1)`
- **`valid_window=1`** — ยอมรับรหัสในช่วง ±30 วินาที (ตามข้อกำหนด time-step)
- **`provisioning_uri()`** — สร้าง otpauth:// URI สำหรับ QR code
- **`user_totp_credentials` table** — เก็บ secret แบบ Fernet-encrypted

**ใช้ในบท:** บทที่ 3 (ระบบ TOTP)

---

### [26] NIST SP 800-63B — Digital Identity Guidelines
> National Institute of Standards and Technology (NIST).
> **Digital Identity Guidelines: Authentication and Lifecycle Management.** NIST Special Publication 800-63B.
> [https://pages.nist.gov/800-63-3/sp800-63b.html](https://pages.nist.gov/800-63-3/sp800-63b.html)

**อ้างอิงส่วนไหนของระบบ:**

| ส่วนของระบบ | ตำแหน่งจริง | อ้างอิงว่าอะไร |
|---|---|---|
| **`failed_logins_24h`** | `feature_extraction.py` (idx 10) | ข้อกำหนดการจำกัดจำนวนครั้งที่ล้มเหลว (rate limiting) |
| **Credential Lifecycle** | `models.py` — `REGISTERED/ACTIVE/SUSPENDED/REVOKED` | มาตรฐานการจัดการวงจรชีวิต authenticator |
| **การจัดประเภท authenticator** | Passkey (AAL3-capable), TOTP (AAL2) | ระดับความมั่นใจของแต่ละปัจจัย |
| **Account recovery** | `app/routers/recovery.py` | ข้อกำหนดการกู้บัญชีที่ปลอดภัย |
| **OTP** | `app/services/mfa_service.py` | ความยาว/อายุของ OTP |

**ประโยคตัวอย่าง:**
> "การออกแบบวงจรชีวิตของปัจจัยยืนยันตัวตน (REGISTERED → ACTIVE → SUSPENDED → REVOKED) อ้างอิงข้อกำหนดใน NIST SP 800-63B [26]"

**ใช้ในบท:** บทที่ 2 (มาตรฐาน), บทที่ 3 (Credential Management)

---

### [27] W3C — Web Authentication (WebAuthn)
> W3C. **Web Authentication: An API for accessing Public Key Credentials Level 2.** W3C Recommendation.
> [https://www.w3.org/TR/webauthn-2/](https://www.w3.org/TR/webauthn-2/)

**อ้างอิงส่วนไหนของระบบ:**
- **`app/services/webauthn_service.py`** — `register_begin/complete()`, `login_begin/complete()`, `stepup_begin/complete()`
- **`passkey_credentials` table** — `credential_id`, `public_key`, `sign_count`, `aaguid`
- **Sign counter** — ตรวจ counter regression (สัญญาณ credential ถูกโคลน)
- **`allowCredentials`** — ⚠️ ต้องไม่ว่างเสมอ (กัน user enumeration — กฎ B43)

**ประโยคตัวอย่าง:**
> "ระบบ Passkey พัฒนาตามมาตรฐาน WebAuthn [27] โดยเก็บเฉพาะกุญแจสาธารณะ (public key) ไว้ที่เซิร์ฟเวอร์ ทำให้แม้ฐานข้อมูลรั่วไหลก็ไม่สามารถปลอมการยืนยันตัวตนได้"

**ใช้ในบท:** บทที่ 3 (ระบบ Passkey)

---

### [28] OWASP Top 10
> OWASP Foundation. **OWASP Top 10 Web Application Security Risks.**
> [https://owasp.org/www-project-top-ten/](https://owasp.org/www-project-top-ten/)

**อ้างอิงส่วนไหนของระบบ:**
- **A01 Broken Access Control** → RBAC + `Depends(require_hub_admin/require_developer)` (กฎ B1)
- **A07 Identification and Authentication Failures** → RBA + MFA + rate limiting
- **A09 Security Logging and Monitoring Failures** → Audit log แบบ append-only + hash chain
- **Anti-enumeration** — ตอบ error เหมือนกันทุกกรณี (กฎในโปรเจกต์)

**ใช้ในบท:** บทที่ 3 (Defense in Depth 10 ชั้น), บทที่ 4 (การทดสอบความปลอดภัย)

---

### [29] OWASP — Credential Stuffing Prevention Cheat Sheet
> OWASP Foundation. **Credential Stuffing Prevention Cheat Sheet.**
> [https://cheatsheetseries.owasp.org/cheatsheets/Credential_Stuffing_Prevention_Cheat_Sheet.html](https://cheatsheetseries.owasp.org/cheatsheets/Credential_Stuffing_Prevention_Cheat_Sheet.html)

**อ้างอิงส่วนไหนของระบบ:**
- **แนวทางป้องกัน** — MFA, rate limiting, device fingerprinting, IP reputation
- **`app/rate_limiter.py`** — จำกัดอัตราต่อ IP / client_id
- **`app/services/ip_blacklist.py`** — IP reputation

**ใช้ในบท:** บทที่ 3 (มาตรการป้องกัน)

---

## 6. ตารางสรุป: Feature → อ้างอิง

| # | Feature (index) | หมวด | อ้างอิง |
|---|---|---|---|
| 0 | `hour_of_day` | Temporal | [1] |
| 1 | `day_of_week` | Temporal | [1], [3] |
| 2 | `hours_from_typical_login_time` | Temporal (personalized) | [1], [10] |
| 3 | `is_thailand` | Geographic | [1] |
| 4 | `is_new_country` | Geographic | [10], [1] |
| 5 | `country_change_count_30d` | Geographic | [1] |
| 6 | `is_new_device` | Device | [20], [2] |
| 7 | `is_new_user_agent_family` | Device | [20], [21] ~~[21b]~~ ⚠️ |
| 8 | `log_minutes_since_last_login` | Velocity | [10] |
| 9 | `login_count_24h` | Velocity | [10] |
| 10 | `failed_logins_24h` | Brute Force | [26], [16] |
| 11–14 | `passkey_*` | Credential | [27], [26] |
| 15 | `concurrent_session_count` | Session | [18] |
| 16 | `active_subsystem_count` | Scope | — (ออกแบบเอง) |
| 17 | `weekday_usage_score` | Temporal (personalized) | [1], [10] |
| 18 | `scope_sensitivity_score` | Scope | — (ออกแบบเอง) |
| 19–20 | `permission_change_*` | Permission | — (ออกแบบเอง) |
| 21 | `confirmed_incident_count` | History | [10] |
| 22 | `impossible_travel_score` | Geographic velocity | [1], [7] |

> 💡 **feature ที่ไม่มีอ้างอิง = ส่วนที่งานนี้ออกแบบเพิ่มเอง** — เป็นจุดที่เขียนเป็น *contribution* ของงานได้

---

## 7. ตารางสรุป: ไฟล์ในระบบ → อ้างอิง

| ไฟล์ / โมดูล | อ้างอิงที่เกี่ยวข้อง |
|---|---|
| `app/security/rule_engine.py` | [1], [10], [16], [17] |
| `app/security/behavior_profiling.py` | [10], [1] |
| `app/security/iforest_scorer.py` · `ml-service/app/model.py` | [11], [12] |
| `app/security/risk_aggregator.py` | [1], [4], [10] |
| `app/services/feature_extraction.py` | [1], [2], [10], [20], [26] |
| `app/services/jwt_service.py` | [24] |
| `app/services/pkce.py` | [23] |
| `app/services/webauthn_service.py` | [27], [26] |
| `app/services/totp_service.py` | [25], [26] |
| `app/services/mfa_policy.py` | [3], [5] |
| `app/services/geoip.py` | [7] |
| `app/routers/oauth.py` | [22], [23] |
| `app/routers/recovery.py` · `passkey_recovery.py` | [9], [26] |
| `app/services/audit_service.py` | [28] |
| `ml-service/scripts/train_model.py` | [11], [12] |
| `ml-service/scripts/generate_data.py` | [1], [15]–[19] |

---

## 8. ผลการตรวจสอบอ้างอิงที่ค้างไว้

> ค้นหาและยืนยันแล้วเมื่อ 2026-07-22

| อ้างอิงเดิมใน `CLAUDE.md` | ผลการค้นหา | สิ่งที่ต้องทำ |
|---|---|---|
| **F-RBA 2024** | ✅ **เจอแล้ว** → Fereidouni et al. (2024), *F-RBA: A Federated Learning-based Framework for Risk-based Authentication*, arXiv:2412.12324 (ดู **[14b]**) | ใช้ได้ แต่ **ระบุว่าเป็น preprint** · แก้บริบทการอ้าง: เดิมอ้างเป็นที่มาของ 4-Layer aggregation ซึ่ง**ไม่ตรง** — F-RBA เป็นเรื่อง federated learning + cold start |
| **Iqbal 2021** | ⚠️ **เจอแล้วแต่อ้างผิดบริบท** → Iqbal, Englehardt & Shafiq (2021), *Fingerprinting the Fingerprinters*, IEEE S&P (ดู **[21b]**) | **ย้ายไปบทที่ 5** (privacy/ข้อจำกัด) · แทนที่ด้วย **[20]** และ **[21]** สำหรับ `is_new_user_agent_family` |
| **Microsoft Entra** | เป็น product documentation ไม่ใช่งานวิจัย | อ้างเป็น *technical documentation* หรือใช้ **[10] Freeman** แทน |
| **Wiefling 2022** | ✅ แก้แล้ว → **2023** (ดู **[1]**) | อัปเดต `CLAUDE.md` |

### 📌 การแก้ไขที่ต้องทำใน `CLAUDE.md`

| จุด | เดิม | แก้เป็น |
|---|---|---|
| ตาราง External Standards | `Wiefling et al. (2022) ACM TOPS` | `Wiefling et al. (2023) ACM TOPS 26(1)` |
| ตาราง ML Features แถว `is_new_user_agent_family` | `Laperdrix 2020 / Iqbal 2021` | `Laperdrix 2020 / Andriamilanto 2021` |
| ตาราง Roadmap Week 8.5 (RBA) | `F-RBA 2024` (อ้างเป็นที่มา aggregation) | `Freeman 2016 / Wiefling 2023` — ส่วน F-RBA ใช้อ้าง cold start แทน |

---

## 9. BibTeX

```bibtex
@article{wiefling2023pump,
  author  = {Wiefling, Stephan and J{\o}rgensen, Paul Ren{\'e} and Thunem, Sigurd and Lo Iacono, Luigi},
  title   = {Pump Up Password Security! Evaluating and Enhancing Risk-Based Authentication on a Real-World Large-Scale Online Service},
  journal = {ACM Transactions on Privacy and Security},
  volume  = {26}, number = {1}, articleno = {6}, numpages = {36},
  year    = {2023}, doi = {10.1145/3546069}
}

@inproceedings{wiefling2019really,
  author    = {Wiefling, Stephan and Lo Iacono, Luigi and D{\"u}rmuth, Markus},
  title     = {Is This Really You? An Empirical Study on Risk-Based Authentication Applied in the Wild},
  booktitle = {ICT Systems Security and Privacy Protection (IFIP SEC)},
  volume    = {562}, pages = {134--148}, year = {2019},
  publisher = {Springer}, doi = {10.1007/978-3-030-22312-0_10}
}

@inproceedings{wiefling2020evaluation,
  author    = {Wiefling, Stephan and Patil, Tanvi and D{\"u}rmuth, Markus and Lo Iacono, Luigi},
  title     = {Evaluation of Risk-based Re-Authentication Methods},
  booktitle = {ICT Systems Security and Privacy Protection (IFIP SEC)},
  volume    = {580}, pages = {280--294}, year = {2020},
  publisher = {Springer}, doi = {10.1007/978-3-030-58201-2_19}
}

@inproceedings{wiefling2021score,
  author    = {Wiefling, Stephan and D{\"u}rmuth, Markus and Lo Iacono, Luigi},
  title     = {What's in Score for Website Users: A Data-Driven Long-Term Study on Risk-Based Authentication Characteristics},
  booktitle = {Financial Cryptography and Data Security (FC)},
  pages     = {361--381}, year = {2021},
  publisher = {Springer}, doi = {10.1007/978-3-662-64331-0_19}
}

@inproceedings{wiefling2020more,
  author    = {Wiefling, Stephan and D{\"u}rmuth, Markus and Lo Iacono, Luigi},
  title     = {More Than Just Good Passwords? A Study on Usability and Security Perceptions of Risk-based Authentication},
  booktitle = {Annual Computer Security Applications Conference (ACSAC)},
  pages     = {203--218}, year = {2020},
  publisher = {ACM}, doi = {10.1145/3427228.3427243}
}

@article{wiefling2021verify,
  author  = {Wiefling, Stephan and D{\"u}rmuth, Markus and Lo Iacono, Luigi},
  title   = {Verify It's You: How Users Perceive Risk-based Authentication},
  journal = {IEEE Security \& Privacy},
  volume  = {19}, number = {6}, pages = {47--57}, year = {2021},
  doi     = {10.1109/MSEC.2021.3077954}
}

@inproceedings{wiefling2021privacy,
  author    = {Wiefling, Stephan and Tolsdorf, Jan and Lo Iacono, Luigi},
  title     = {Privacy Considerations for Risk-Based Authentication Systems},
  booktitle = {International Workshop on Privacy Engineering (IWPE)},
  pages     = {320--327}, year = {2021},
  publisher = {IEEE}, doi = {10.1109/EuroSPW54576.2021.00040}
}

@inproceedings{unsel2023openstack,
  author    = {Unsel, Vincent and Wiefling, Stephan and Gruschka, Nils and Lo Iacono, Luigi},
  title     = {Risk-Based Authentication for OpenStack: A Fully Functional Implementation and Guiding Example},
  booktitle = {ACM Conference on Data and Application Security and Privacy (CODASPY)},
  year      = {2023}, publisher = {ACM}, doi = {10.1145/3577923.3583634}
}

@inproceedings{buettner2024recovery,
  author    = {B{\"u}ttner, Andre and Pedersen, Andreas Thue and Wiefling, Stephan and Gruschka, Nils and Lo Iacono, Luigi},
  title     = {Is It Really You Who Forgot the Password? When Account Recovery Meets Risk-Based Authentication},
  booktitle = {Ubiquitous Security (UbiSec)}, year = {2024},
  publisher = {Springer}, doi = {10.1007/978-981-97-1274-8_26}
}

@inproceedings{freeman2016who,
  author    = {Freeman, David and Jain, Sakshi and D{\"u}rmuth, Markus and Biggio, Battista and Giacinto, Giorgio},
  title     = {Who Are You? A Statistical Approach to Measuring User Authenticity},
  booktitle = {Network and Distributed System Security Symposium (NDSS)},
  year      = {2016}
}

@inproceedings{liu2008isolation,
  author    = {Liu, Fei Tony and Ting, Kai Ming and Zhou, Zhi-Hua},
  title     = {Isolation Forest},
  booktitle = {IEEE International Conference on Data Mining (ICDM)},
  pages     = {413--422}, year = {2008},
  publisher = {IEEE}, doi = {10.1109/ICDM.2008.17}
}

@article{liu2012isolation,
  author  = {Liu, Fei Tony and Ting, Kai Ming and Zhou, Zhi-Hua},
  title   = {Isolation-Based Anomaly Detection},
  journal = {ACM Transactions on Knowledge Discovery from Data},
  volume  = {6}, number = {1}, articleno = {3}, year = {2012},
  doi     = {10.1145/2133360.2133363}
}

@inproceedings{lundberg2017unified,
  author    = {Lundberg, Scott M. and Lee, Su-In},
  title     = {A Unified Approach to Interpreting Model Predictions},
  booktitle = {Advances in Neural Information Processing Systems 30 (NIPS)},
  pages     = {4765--4774}, year = {2017}
}

@misc{fereidouni2024frba,
  author = {Fereidouni, Hamidreza and Hafid, Abdelhakim Senhaji and Makrakis, Dimitrios and Baseri, Yaser},
  title  = {F-RBA: A Federated Learning-based Framework for Risk-based Authentication},
  year   = {2024}, eprint = {2412.12324},
  archivePrefix = {arXiv}, primaryClass = {cs.CR},
  note   = {arXiv preprint}
}

@inproceedings{iqbal2021fingerprinting,
  author    = {Iqbal, Umar and Englehardt, Steven and Shafiq, Zubair},
  title     = {Fingerprinting the Fingerprinters: Learning to Detect Browser Fingerprinting Behaviors},
  booktitle = {IEEE Symposium on Security and Privacy (S\&P)},
  pages     = {1143--1161}, year = {2021},
  publisher = {IEEE}, doi = {10.1109/SP40001.2021.00017}
}

@article{laperdrix2020browser,
  author  = {Laperdrix, Pierre and Bielova, Nataliia and Baudry, Benoit and Avoine, Gildas},
  title   = {Browser Fingerprinting: A Survey},
  journal = {ACM Transactions on the Web},
  volume  = {14}, number = {2}, articleno = {8}, year = {2020},
  doi     = {10.1145/3386040}
}

@misc{mitre_t1078,
  author = {{MITRE}}, title = {Valid Accounts (T1078)},
  howpublished = {MITRE ATT\&CK Enterprise Matrix},
  url = {https://attack.mitre.org/techniques/T1078/}
}

@misc{mitre_t1110_004,
  author = {{MITRE}}, title = {Brute Force: Credential Stuffing (T1110.004)},
  howpublished = {MITRE ATT\&CK Enterprise Matrix},
  url = {https://attack.mitre.org/techniques/T1110/004/}
}

@misc{mitre_t1110_003,
  author = {{MITRE}}, title = {Brute Force: Password Spraying (T1110.003)},
  howpublished = {MITRE ATT\&CK Enterprise Matrix},
  url = {https://attack.mitre.org/techniques/T1110/003/}
}

@misc{mitre_t1539,
  author = {{MITRE}}, title = {Steal Web Session Cookie (T1539)},
  howpublished = {MITRE ATT\&CK Enterprise Matrix},
  url = {https://attack.mitre.org/techniques/T1539/}
}

@techreport{rfc6749,
  author = {Hardt, Dick}, title = {The OAuth 2.0 Authorization Framework},
  institution = {IETF}, number = {RFC 6749}, year = {2012}
}

@techreport{rfc7636,
  author = {Sakimura, Nat and Bradley, John and Agarwal, Naveen},
  title = {Proof Key for Code Exchange by OAuth Public Clients},
  institution = {IETF}, number = {RFC 7636}, year = {2015}
}

@techreport{rfc7519,
  author = {Jones, Michael and Bradley, John and Sakimura, Nat},
  title = {JSON Web Token (JWT)},
  institution = {IETF}, number = {RFC 7519}, year = {2015}
}

@techreport{rfc6238,
  author = {M'Raihi, David and Machani, Salah and Pei, Mingliang and Rydell, Johan},
  title = {TOTP: Time-Based One-Time Password Algorithm},
  institution = {IETF}, number = {RFC 6238}, year = {2011}
}

@techreport{nist80063b,
  author = {{NIST}},
  title = {Digital Identity Guidelines: Authentication and Lifecycle Management},
  institution = {National Institute of Standards and Technology},
  number = {SP 800-63B}
}

@misc{w3c_webauthn,
  author = {{W3C}}, title = {Web Authentication: An API for accessing Public Key Credentials Level 2},
  howpublished = {W3C Recommendation}, url = {https://www.w3.org/TR/webauthn-2/}
}
```

---

## สรุปการใช้อ้างอิงตามบทของปริญญานิพนธ์

| บท | อ้างอิงที่ควรใช้ |
|---|---|
| **บทที่ 1 — บทนำ / ที่มาและความสำคัญ** | [15] (T1078 — ภัยจากการยึดบัญชี), [28] |
| **บทที่ 2 — ทฤษฎีและงานวิจัยที่เกี่ยวข้อง** | [1]–[14], [20], [21], [22]–[27] |
| **บทที่ 3 — ระบบยืนยันตัวตน** | [22]–[27], [9] |
| **บทที่ 3 — ระบบจัดการผู้ใช้และสิทธิ์** | [26], [28] |
| **บทที่ 3 — ระบบจัดการระบบย่อย** | [22], [23], [24] |
| **บทที่ 3 — ระบบประเมินความเสี่ยง** | [1], [2], [4], [10], [11], [12], [13] |
| **บทที่ 3 — Threat Model** | [1], [15]–[19], [29] |
| **บทที่ 3 — ระบบกู้บัญชี** | [9], [26] |
| **บทที่ 3 — ระบบติดตามและตรวจสอบ** | [28] |
| **บทที่ 4 — การทดสอบและประเมินผล** | [1], [3], [4], [10], [14], [16] |
| **บทที่ 5 — สรุป อภิปราย และข้อเสนอแนะ** | [5], [6], [7], [14], [20], [21] |
