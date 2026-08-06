# ML Real-Traffic Evaluation — หลังแก้ Data Leakage

**วันที่:** 2026-07-22
**โมเดล:** 23-feature Isolation Forest + 4-Layer RBA (retrain ใหม่)
**เงื่อนไขสำคัญ:** รันหลังแก้ point-in-time data leakage (ดู `feature_leakage_fix_2026-07-22.md`)
**แทนที่:** `ml_real_eval_2026-06-18.md` (ตัวเลขเดิมได้จาก feature ที่รั่ว — ใช้ไม่ได้)

---

## 1. ขั้นตอนที่รัน (ตามลำดับ)

```bash
# 1. re-export labeled data ด้วย feature ที่แก้ leakage แล้ว
docker compose exec hub-backend python -m scripts.export_labeled_data
#    → 7 rows (normal=7, anomaly=0)

# 2. ย้าย CSV → ml-service แล้ว retrain
docker cp hub-backend:/app/tests/reports/real_labeled.csv <host> ; docker cp <host> hub-ml:/app/data/
docker compose exec ml-service python -m scripts.train_model

# 3. restart ml-service ให้โหลดโมเดลใหม่
docker compose restart ml-service

# 4. calibrate threshold บนข้อมูลจริง
docker compose exec hub-backend python -m scripts.calibrate_thresholds

# 5. วัดผลบน real traffic
docker compose exec hub-backend python -m scripts.evaluate_real_logins
```

> 💾 **Backup ก่อน retrain:** `iforest_v1.pkl.bak_20260723_040440`, `sessions.csv.bak_20260723_040440`

---

## 2. ผลการ retrain

| Metric | Train | **Test (held-out, 2,102 samples)** |
|---|---|---|
| AUC-ROC | 0.9927 | **0.9953** |
| Precision (anomaly) | — | **0.77** |
| Recall (anomaly) | — | **0.93** |
| F1 (anomaly) | — | **0.84** |
| Accuracy | — | **0.98** |

**Confusion Matrix (test):**
| | pred_normal | pred_anomaly |
|---|---|---|
| **true_normal** | 1,974 | 28 |
| **true_anomaly** | 7 | 93 |

> ⚠️ **ตัวเลขชุดนี้อยู่บน synthetic data** (10,000 normal + 500 anomaly) — ไม่ใช่ traffic จริง
> ต้องอ่านคู่กับ §4 เสมอ ห้ามอ้างเดี่ยว ๆ ในเล่มว่า "ระบบแม่นยำ 99%"

**Threshold suggestion (Youden's J):** raw = −0.0080 · TPR 0.96 · FPR 0.0195

---

## 3. ผล Calibration บนข้อมูลจริง ⭐

**ตัวอย่าง:** real normal 634 (ML-driven) + 66 hard-block

### การกระจายคะแนน (ML-driven normal)
| percentile | score |
|---|---|
| p50 | 0.300 |
| p75 | 0.400 |
| p90 | 0.600 |
| p95 | 0.600 |
| p99 | 1.000 |
| mean | 0.323 |

### FPR ที่แต่ละ threshold
| threshold | flagged | FPR (ML) |
|---|---|---|
| 0.3 | 360 | 56.8% |
| 0.4 | 247 | 39.0% |
| 0.5 | 149 | 23.5% |
| 0.6 | 70 | 11.0% |
| **0.7** | **31** | **4.9%** ← ค่าที่ใช้จริง |
| 0.8 | 20 | 3.2% |
| 0.9 | 18 | 2.8% |

### ✅ ข้อสรุปสำคัญ
สคริปต์แนะนำ **challenge ≈ 0.70** (FPR ≤ 10% ตามเป้า) · block = challenge + 0.15–0.2 · warn = challenge − 0.2

**ตรงกับค่าที่ระบบใช้อยู่แล้วเป๊ะ** (`risk_aggregator.py`):
```python
THRESHOLDS = {"block": 0.85, "challenge": 0.7, "warn": 0.5}
```
→ **ไม่ต้องแก้ threshold** — และตอนนี้มีหลักฐานยืนยันบนข้อมูลที่ไม่รั่วแล้ว
(เดิม threshold ชุดนี้ตั้งจากข้อมูลที่มี leakage จึงยังพิสูจน์ไม่ได้)

---

## 4. ผลวัด False-Positive บน Real Traffic ⭐

**Sessions scored:** 700 (normal 700, attack label 0) · shadow_mode = True

### Decision distribution
| decision | count | % |
|---|---|---|
| allow | 485 | **69.3%** |
| would_warn | 118 | 16.9% |
| would_block | 84 | 12.0% |
| would_challenge | 13 | 1.9% |

### False-Positive rate
| Metric | ค่า |
|---|---|
| **FP friction (mfa+)** | **97/700 = 13.9%** |
| FP block-level | 84/700 = 12.0% |
| mean risk (normal) | 0.386 |

### เหตุผลที่ normal โดน flag (diagnostic)
| reason | count |
|---|---|
| `login_count_24h` | 49 |
| `is_new_device` | 35 |
| `failed_logins_24h` | 23 |
| `weekend_mismatch` | 19 |
| `hours_diff` | 18 |
| `is_new_country` | 8 |
| `is_new_user_agent_family` | 7 |
| `impossible_travel_score` | 6 |

---

## 5. เปรียบเทียบก่อน/หลังแก้ leakage ⭐

| Metric | ก่อนแก้ (2026-06-18) | **หลังแก้ (2026-07-22)** | เปลี่ยนแปลง |
|---|---|---|---|
| Sessions scored | 244 | 700 | +456 |
| **FP friction (mfa+)** | **47.1%** | **13.9%** | **↓ 33.2 จุด** |
| FP block-level | 44.7% | 12.0% | ↓ 32.7 จุด |
| allow | 41.0% | **69.3%** | ↑ 28.3 จุด |
| mean risk (normal) | 0.659 | **0.386** | ↓ 0.273 |
| `login_count_24h` เป็นสาเหตุ FP | 106 (92% ของ FP) | 49 (51% ของ FP) | ↓ 57 |

> 🎯 **FP ลดลงจาก 47.1% → 13.9%** โดยไม่ได้แก้ threshold หรือ rule ใด ๆ
> — มาจากการแก้ data leakage อย่างเดียว

### การกระจายของสาเหตุ FP ดีขึ้น
เดิม `login_count_24h` ครอง 92% ของ FP (สัญญาณเดียวครอบงำ) → ตอนนี้ 51%
และสาเหตุอื่นกระจายตัวสมเหตุสมผล (device, failed logins, เวลา) = โมเดลใช้หลายสัญญาณจริง

---

## 6. ข้อจำกัดที่ยังเหลือ (ต้องเขียนในเล่ม)

| ข้อจำกัด | รายละเอียด |
|---|---|
| ❌ **Recall วัดไม่ได้** | `attack label = 0` — ไม่มี session ที่ยืนยันว่าเป็นการโจมตีจริง → precision/recall/AUC บนข้อมูลจริงทำไม่ได้ |
| ⚠️ **Real labeled data น้อยมาก** | export ได้เพียง **7 แถว** (normal 7, attack 0) → training ยังพึ่ง synthetic เป็นหลัก |
| ⚠️ **Test traffic ปนใน dataset** | ยังมี user ทดสอบที่ login 70+ ครั้ง/24 ชม. จาก `127.0.0.1` → 66 session ติด hard-block (`login_count_24h >= 50`) ซึ่ง**ไม่ใช่ traffic จริง** |
| ⚠️ **AUC 0.9953 มาจาก synthetic** | ห้ามอ้างเป็นความแม่นยำของระบบบนข้อมูลจริง |

---

## 7. สิ่งที่ต้องทำต่อ

1. **เก็บ attack label จริง** — ให้ admin ใช้ `toggle-attack-ip` / `MLFeedback = true_positive`
   → ปลดล็อกการวัด recall (bottleneck หลักที่เหลือ)
2. **สร้าง attack set จาก attacker model** — ตาม Wiefling et al. 2023 (4 ระดับ) +
   MITRE ATT&CK → `build_attack_set.py` (ดู `docs/references.md` §3)
3. **แยก/ลบ test traffic** — ล้าง session จาก `127.0.0.1` หรือ mark เป็น dev
   เพื่อวัด FP ที่สะอาดกว่านี้

---

## สรุปสำหรับ thesis

> "จากการตรวจสอบพบว่ากระบวนการสกัดคุณลักษณะมีปัญหา data leakage — การ re-score ข้อมูล
> ย้อนหลังดึงประวัติที่เกิดขึ้น *หลัง* เวลาที่ประเมิน (11 จุด) หลังแก้ไขให้เป็น point-in-time
> อย่างถูกต้อง อัตรา false positive บน traffic จริงลดลงจาก **47.1% เหลือ 13.9%**
> โดยไม่ได้เปลี่ยนแปลงค่าขีดแบ่งหรือกฎใด ๆ นอกจากนี้การ calibrate ค่าขีดแบ่งบนข้อมูลที่
> ไม่มี leakage ยืนยันว่าค่าที่ระบบใช้อยู่ (challenge = 0.70) ให้ FPR เพียง 4.9%
> ซึ่งอยู่ในเกณฑ์เป้าหมาย ≤ 10%
>
> ข้อจำกัดที่ยังคงอยู่คือไม่มีชุดข้อมูลการโจมตีที่มีป้ายกำกับจริง ทำให้ยังวัด recall
> บนข้อมูลจริงไม่ได้ ซึ่งเป็นข้อจำกัดร่วมของงานวิจัยด้าน RBA โดยทั่วไป และแก้ไขได้ด้วย
> การจำลองการโจมตีตามโมเดลผู้โจมตีที่อ้างอิงงานวิจัย (attacker modeling)"
