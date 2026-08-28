# (1) L3 threshold sweep + (2) วินิจฉัยจุดอ่อน L1/L2 ต่อ campaign

**วันที่:** 26 ส.ค. 2026 · seeds [42, 43, 44] · size 5000 · final attack (holdout)


## (1) threshold sweep — หาจุดที่ L3 FPR ≤ 1%

| quantile | L3 FPR | L3 unique | ผ่านเกณฑ์ FPR≤1% |
|---|---|---|---|
| 0.99 | 2.14±0.32% | 5.31±0.71% | ❌ |
| 0.993 | 1.76±0.24% | 4.39±0.79% | ❌ |
| 0.995 | 1.52±0.19% | 3.66±0.56% | ❌ |
| 0.997 | 1.19±0.06% | 3.35±0.71% | ❌ |
| 0.999 | 0.79±0.10% | 2.43±0.66% | ✅ |

> **เลือก quantile 0.999** — FPR 0.79% · unique 2.43%


## (2) campaign family ที่ L1/L2 พลาด (final holdout)

| family | พลาด/ทั้งหมด | อัตราพลาด |
|---|---|---|
| `u_intermittent` | 78/180 | 43% |
| `u_mixed_direction` | 53/180 | 29% |
| `u_off_f_axis` | 81/180 | 45% |
| `u_scope_only` | 93/180 | 52% |
| `u_subsystem_shuffle` | 105/180 | 58% |

### เหตุผลที่พลาด

| family | สัญญาณที่ได้ | ครั้ง |
|---|---|---|
| `u_intermittent` | weekend_mismatch (+0.10) | 61 |
| `u_intermittent` | ไม่มีสัญญาณเลย | 4 |
| `u_mixed_direction` | weekend_mismatch (+0.10) | 25 |
| `u_mixed_direction` | ไม่มีสัญญาณเลย | 15 |
| `u_off_f_axis` | weekend_mismatch (+0.10) | 68 |
| `u_off_f_axis` | ไม่มีสัญญาณเลย | 4 |
| `u_scope_only` | weekend_mismatch (+0.10) | 64 |
| `u_scope_only` | ไม่มีสัญญาณเลย | 7 |
| `u_subsystem_shuffle` | weekend_mismatch (+0.10) | 72 |
| `u_subsystem_shuffle` | hour_rarity=1.00 (hour 11 ไม่เคยเข้า, +0.30) | 4 |
