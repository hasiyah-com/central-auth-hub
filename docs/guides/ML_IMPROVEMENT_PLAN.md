# ML Improvement Plan — Central Auth Hub (Hybrid RBA)

**แผนยกระดับประสิทธิภาพโมเดล** — ต่อยอดจาก `ML_FEATURE_ENGINEERING_AND_RISK_MODELING_PLAN.md`
Version 1.0 · 2026-06-15 · สถานะ: Design / รออนุมัติเริ่ม

---

## 0. บริบท + หลักคิด

**สถานะปัจจุบัน:** 21 features · 4-Layer RBA (rule+behavior+IForest+aggregation) · SHAP · Shadow Mode
**ปัญหารากเหง้า:** เทรน + วัดผลบน **synthetic data ล้วน** → AUC 0.99 เป็น circular วัดประสิทธิภาพจริงไม่ได้

> **หลักคิดของแผนนี้:** ระบบ**ไม่ได้ขาด feature** — ขาด **(1) ข้อมูลจริงไว้วัดผล (2) การปิด feedback loop จาก label ที่มีอยู่ (3) calibration + การป้องกัน regression**.
> เพิ่ม feature โดยไม่มี 3 อย่างนี้ = ปรับจูนบนพื้นที่ที่วัดไม่ได้ → แผนนี้จัดลำดับ "รากฐานก่อน feature"

**เกณฑ์จัดลำดับ:** ผลกระทบต่อความน่าเชื่อถือของผล × ความเป็นไปได้ในเวลาที่เหลือ (Week 11–16)

---

## Phase 1 — รากฐาน: วัดผลได้ + กัน regression  ⭐ ทำก่อน (thesis-critical)

> เป้าหมาย: เปลี่ยนจาก "เดาว่าดี" → "วัดได้ว่าดีแค่ไหนบนข้อมูลจริง"

### 1.1 Real labeled evaluation set
- **ทำอะไร:** สร้างชุดประเมินจาก `login_sessions` จริง + label ที่ admin ยืนยัน (`is_account_takeover`, `is_attack_ip`) + `MLFeedback`
- **ไฟล์:** สคริปต์ใหม่ `ml-service/scripts/build_eval_set.py` (export จาก hub DB → CSV held-out), `ml-service/scripts/evaluate_on_real.py`
- **Acceptance:** มี report FP/FN/precision/recall บน **ข้อมูลจริง** (แยกจาก synthetic) เก็บที่ `tests/reports/ml_real_eval_<date>.md`
- **Effort:** M · **ขึ้นกับ:** ต้องมี labeled session พอ (ถ้าไม่พอ → ใช้ admin label สะสม + เตือนใน report ว่า n น้อย)

### 1.2 Feature contract test (กันบั๊ก FEAT ซ้ำ)
- **ทำอะไร:** single source of truth ของ feature order + test ที่ fail ถ้า 4 ไฟล์ไม่ตรง (features.py / generate_data headers / feature_extraction / rule_engine.FEAT)
- **ไฟล์:** `hub/backend/tests/test_feature_contract.py` + (option) shared `feature_names.py`
- **Acceptance:** test fail ทันทีถ้ามีคนตัด/เพิ่ม/สลับ feature แล้วลืม sync — รันใน CI
- **Effort:** S · **อ้างอิงบั๊ก:** ML-BUG-1 (FEAT misalign, 2026-06-15)

### 1.3 Feature drift / distribution monitor
- **ทำอะไร:** บันทึก distribution ของ feature ที่ extract จริง เทียบกับ train set → เตือนเมื่อ skew (จับ train/serve skew อัตโนมัติ)
- **ไฟล์:** `ml-service/scripts/check_drift.py` (เทียบ sessions.csv vs feature จริงจาก hub DB)
- **Acceptance:** รายงาน feature ที่ค่าจริงหลุดช่วง train (เช่น perm_age=9999) — ML-BUG-2 ควรถูกจับได้
- **Effort:** S–M

---

## Phase 2 — คุณภาพโมเดล: ใช้ label + calibrate

### 2.1 Threshold + score calibration
- **ทำอะไร:** เปลี่ยน block 0.7/mfa 0.4 (hardcode) → calibrate จากข้อมูลจริง (cost-based / Youden's J) + ทบทวน IF→risk step function
- **ไฟล์:** `ml-service/app/main.py` (THRESHOLDS), `iforest_scorer.py:map_score`
- **Acceptance:** normal baseline ไม่ติด threshold (ตอนนี้ ~0.39–0.45 ชน mfa 0.4) — false-MFA rate ลดบน eval set
- **Effort:** S · **ขึ้นกับ:** 1.1 (ต้องมี eval set ก่อน calibrate)

### 2.2 ปิด feedback loop (retrain จาก label จริง)
- **ทำอะไร:** pipeline retrain ที่รวม labeled feedback (`MLFeedback` + confirmed incident) เข้า train set — ไม่ใช่ synthetic อย่างเดียว
- **ไฟล์:** `ml-service/scripts/train_model.py` (เพิ่ม source = real labeled), เอกสาร schedule retrain
- **Acceptance:** โมเดลใหม่เทรนด้วย synthetic + real labeled, วัดบน real held-out ดีขึ้นหรือเท่าเดิม
- **Effort:** M · **ขึ้นกับ:** 1.1

### 2.3 ใช้ label ที่มี (semi-supervised / hybrid) — *optional ถ้าเวลาเหลือ*
- **ทำอะไร:** เพิ่ม supervised layer (เช่น gradient boosting) บน labeled subset คู่กับ IForest (anomaly + classifier)
- **Acceptance:** เทียบ AUC hybrid vs IForest เดี่ยว บน real eval set
- **Effort:** L · **หมายเหตุ:** ทำเป็น "งานวิจัยเสริม" ดี แต่ต้องมี label พอ

### 2.4 Per-segment baseline (user_type)
- **ทำอะไร:** นักศึกษา/staff/admin pattern ต่างกัน → threshold หรือ baseline แยกต่อ user_type
- **ไฟล์:** `risk_aggregator.py` / `main.py` (threshold ต่อ segment)
- **Effort:** S–M

---

## Phase 3 — Infra/Feature ที่แผนเดิมตั้งเป็น Must-Have แต่ติด data gap

### 3.1 GeoIP2-City + lat/lon → impossible_travel
- **ทำอะไร:** เปลี่ยน GeoLite2-Country → City, เก็บ `geo_lat`/`geo_lon` ใน login_sessions, เพิ่ม feature geo_distance/velocity/impossible_travel
- **ไฟล์:** `geoip.py`, `models.py` (+2 column), `feature_extraction.py`, `features.py`, `generate_data.py`
- **Effort:** L · **บล็อก:** Must-Have ในแผนเดิมทำไม่ได้จนกว่าจะมีอันนี้

### 3.2 ฟื้น ipsum threat feed → ip_reputation
- **ทำอะไร:** แก้ fetch ที่ fail (no internet ใน container) — cache offline / mirror / mount ไฟล์
- **ไฟล์:** `ipsum_refresh.py`
- **Effort:** S

### 3.3 Device fingerprint (แทน user_agent proxy) — *optional*
- **ทำอะไร:** เพิ่ม device identity จริง (fingerprint/cookie) → device_trust แข็งขึ้น
- **Effort:** L · **หมายเหตุ:** scope ใหญ่ พิจารณาเป็น future work

---

## ลำดับการทำ (dependency)

```
Phase 1.2 (contract test)  ──┐  ทำได้ทันที ไม่ต้องรอใคร
Phase 1.3 (drift)          ──┤
Phase 1.1 (real eval set)  ──┴─▶ 2.1 (calibrate) ─▶ 2.2 (feedback retrain) ─▶ 2.3 (hybrid)
                                  2.4 (segment) ทำคู่ขนานได้
Phase 3.* ทำเมื่อ Phase 1–2 นิ่ง (เป็น feature expansion)
```

**แนะนำเริ่ม:** 1.2 + 1.3 (เล็ก ป้องกัน regression ทันที) → 1.1 (รากฐานวัดผล) → 2.1

---

## สิ่งที่ "ยังไม่ทำ" (defer — กัน scope creep)

- เพิ่ม feature ใหม่จำนวนมากตามแผนเดิม (28 ตัว) — **รอ Phase 1 วัดผลได้ก่อน** ไม่งั้นเพิ่มแล้ววัดไม่ได้
- Device fingerprint (3.3), hybrid model (2.3) — optional ถ้าเวลาเหลือ
- known_proxy/tor feed — ต้องแหล่งข้อมูลภายนอก (อาจเสียเงิน)

---

## ความเสี่ยง / ข้อควรระวัง

1. **Label จริงอาจมีน้อย** → eval set เล็ก → รายงานต้องระบุ n + confidence ตามตรง (อย่าเคลม AUC สูงจาก n น้อย)
2. **เพิ่ม feature = แก้ 4 ไฟล์ + retrain** (ML-BUG-1) → ต้องมี 1.2 contract test ก่อนแตะ feature อีก
3. **train/serve skew** (ML-BUG-2) → ทุก feature ใหม่ต้องเช็ค distribution จริง vs synthetic (1.3)
4. **Synthetic limitation** ยังอยู่จนกว่าจะมี real data (Phase 1.1) — เป็นข้อจำกัดที่ต้องเขียนใน thesis ตามตรง

---

## สรุป thesis framing

> "ระบบมี feature engineering ครบ (21 + แผนขยาย) — งานที่เพิ่มคุณค่าวิจัยจริงคือ **methodology**:
> สร้าง real labeled evaluation, ปิด feedback loop, calibrate threshold, และ engineering ที่กัน regression (contract + drift).
> นี่คือสิ่งที่แยกระบบ 'demo ได้' ออกจาก 'production-grade IAM'"
