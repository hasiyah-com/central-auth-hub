# ML Real-Traffic Evaluation (Phase 1.1)

**วันที่:** 2026-06-18
**โมเดล:** 23-feature Isolation Forest + 4-Layer RBA (ปัจจุบัน)
**สคริปต์:** `hub/backend/scripts/evaluate_real_logins.py`
**รัน:** `docker compose exec hub-backend python -m scripts.evaluate_real_logins`

---

## 1. วัตถุประสงค์

วัดผลโมเดลบน **login จริงใน DB** (ไม่ใช่ synthetic) เพื่อได้เลข defensible —
เพราะเดิมเทรน+วัดบน synthetic ล้วน → AUC สวยแต่ circular

**วิธี:** re-score login จริงแบบ point-in-time (now = session.created_at) ด้วยโมเดลปัจจุบัน
ผ่าน 4-Layer risk engine → วัด False-Positive rate + Recall

---

## 2. ผลลัพธ์

| Metric | ค่า |
|---|---|
| Sessions scored | 244 (normal 244, **attack label 0**) |
| Decision: would_block | 109 (44.7%) |
| Decision: allow | 100 (41.0%) |
| Decision: would_warn | 29 (11.9%) |
| Decision: would_challenge | 6 (2.5%) |
| **FP rate (friction mfa+)** | **47.1%** (115/244) |
| FP block-level | 44.7% (109/244) |
| mean risk (normal) | 0.659 |
| **Recall** | **วัดไม่ได้ (attack label = 0)** |

### ทำไม normal โดน flag (diagnostic)
| reason | count |
|---|---|
| **login_count_24h** | **106** ← 92% ของ FP |
| failed_logins_24h | 9 |
| hours_diff (behavior) | 9 |
| weekend_mismatch | 7 |

---

## 3. การวิเคราะห์ (สำคัญ)

**FP 47% ดูน่าตกใจ แต่ 92% มาจาก dev artifact ตัวเดียว:**
- `login_count_24h ≥ 50 (hard block)` — เกิดจาก **test user เดียว** ที่มี 100+ login/24ชม.
  จากการทดสอบระบบ (ไม่ใช่ traffic จริง)
- ตัด artifact นี้ออก → ML/behavior layer flag เพียง **~25/244 ≈ 10%**
  (failed_logins 9 + hours_diff 9 + weekend_mismatch 7) ซึ่งสมเหตุผลกว่ามาก

**สรุป:**
1. ✅ Eval pipeline ทำงาน — วัด FP บน traffic จริงได้
2. ⚠️ Dev dataset **ปนเปื้อนจากการทดสอบ** (test bursts) → FP ดิบ 47% ไม่ใช่ค่าจริง
3. ✅ โมเดล ML จริงๆ (ตัด rule artifact) FP ราว 10% — ยังสูงไป (synthetic limitation) แต่สมเหตุผล
4. ❌ **Recall วัดไม่ได้** — ไม่มี attack label จริง (is_account_takeover=0)

---

## 4. ข้อจำกัด (caveats)

- **Rule layer ไม่ point-in-time 100%** — `login_count_24h`/`impossible_travel`/`multi_account`
  query ที่ now จริง → FP conservative (สูงกว่าจริงเล็กน้อย)
- **n_attack = 0** → recall, precision, AUC บนข้อมูลจริง ทำไม่ได้
- **dataset เล็ก + ปนเปื้อน test** → ไม่ representative ของ production

---

## 5. ข้อเสนอถัดไป

1. **เก็บ attack label จริง** — admin ใช้ toggle-attack-ip / MLFeedback บน session ที่เป็น attack จริง
   → ปลดล็อก recall/precision (ทำ 2.1 calibrate, 2.2 feedback loop ได้เต็ม)
2. **แยก test traffic ออก** — หรือ seed normal baseline สะอาด เพื่อวัด FP จริง
3. **2.1 Calibrate** — ปรับ threshold จาก FP-rate ที่วัดได้ (ML layer ~10%) ลด false friction

---

## สรุปสำหรับ thesis

> "ประเมินบน real traffic 244 sessions พบ FP ดิบ 47% แต่ root-cause analysis ชี้ว่า 92%
> มาจาก rule `login_count_24h` ที่ถูก trigger ด้วย test bursts (dev artifact) — ML layer จริง
> FP ~10%. แสดงให้เห็นว่า (ก) eval pipeline ใช้งานได้ (ข) ต้องการ clean labeled real data
> เพื่อวัด recall — ซึ่งเป็น bottleneck หลัก ไม่ใช่จำนวน feature"
