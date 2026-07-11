# รายงาน: ทดสอบ 4-Layer RBA เต็ม (รวม Layer 2 Behavior) บน Simulated Data

- **วันที่:** 2026-06-15
- **ที่มา:** การทดสอบก่อนหน้าใช้แค่ Layer 1 (Rule) + Layer 3 (IForest) — **ยังไม่ได้ใช้ Layer 2 (Behavior)**
- **Script:** `four_layer_eval.py` (จำลอง logic จริงจาก `hub/backend/app/security/`)

---

## 1. 4 Layer ที่ทดสอบ (ตรงระบบจริง)
| Layer | ที่มา | logic |
|---|---|---|
| L1 Rule | `rule_engine.py` | hard block (ip_attack/impossible_travel/failed≥10/login≥50/cc30≥8) + score (new_device .3, new_country .3, new_uafam .2, failed≥3 .2, not_th .1) |
| **L2 Behavior** | `behavior_profiling.py` | cold-start .2 \| hours_diff≥10 .4 (≥6 .2) \| new_country .3 \| new_device .2 \| weekend_mismatch .1 |
| L3 IForest | `iforest_scorer.py` | raw≥.7→.4, ≥.5→.2, ≥.3→.1 |
| L4 Aggregate | `risk_aggregator.py` | total=L1+L2+L3 (cap 1) ; block≥.85 challenge≥.7 warn≥.5 ; hard block ชนะ |

decision distribution: allow 8287 · warn 817 · challenge 87 · block 482

---

## 2. ผล (actionable = challenge+block ≥0.7 = step-up/block จริง)
| | level-2 | level-3 | level-1 | Precision | Recall | F1 | FP/9373 |
|---|---|---|---|---|---|---|---|
| **4-layer เต็ม (มี L2)** | **44/47** | 253/253 | 0/35 | 0.522 | **0.990** | 0.684 | 272 |
| ตัด Layer 2 (L1+L3) | 34/47 | 253/253 | 0/35 | 0.615 | 0.957 | 0.748 | 180 |
| รวม warn (≥0.5, monitor) | 46/47 | 253/253 | 4/35 | 0.216 | 0.997 | 0.355 | 1087 |

---

## 3. Layer 2 เพิ่มอะไร (ablation)
- **เพิ่ม recall:** level-2 34 → 44 (+10 attack เนียน), recall 0.957 → 0.990
- **ลด precision:** FP 180 → 272 (+92 false positive)
- เคสที่ flag เพิ่มเพราะ L2 = **102 แถว (จริง 10 + ปลอม 92)**

## 4. ข้อสรุป
1. **Layer 2 มีประโยชน์จริงด้าน recall** — จับ attack เนียน (single-column behavioral) ที่ L1+L3 พลาด
2. **ปัจจุบัน over-flag (FP สูง)** — น้ำหนัก L2 (cold-start 0.2, weekend 0.1, hours_diff 0.4) ดัน normal ข้าม threshold;
   ตรงกับคอมเมนต์ใน `risk_aggregator.py` ว่า FPR เป็นปัญหาที่ต้อง calibrate
3. **warn (≥0.5) = monitor เฉยๆ ไม่ block** → นับเป็น detection ไม่แฟร์ (FP 1087)
4. **Layer 2 = ปุ่มปรับ recall↔precision** — calibrate น้ำหนัก L2 + threshold คือ tuning ที่ต้องทำต่อ

## 5. หมายเหตุ feature order
ระบบจริง (`rule_engine.py:FEAT`) ใช้ลำดับ 23 feature ต่างจาก Experiment C (มี `ever_changed_permission`,
`impossible_travel_score` แทน `is_attack_ip`, `active_session_count`) — การทดสอบนี้ apply logic ตามชื่อ
feature ไม่ใช่ index จึงเทียบเชิงพฤติกรรมได้ แต่ถ้าจะรันโค้ดจริงตรงๆ ต้อง map ลำดับให้ตรง (B27)

## 6. งานต่อ
- calibrate น้ำหนัก Layer 2 + threshold เพื่อลด FP (เป้า: คง recall level-2 สูง + precision ดีขึ้น)
- รัน `scripts/calibrate_thresholds.py` ของระบบจริงบน dataset นี้
