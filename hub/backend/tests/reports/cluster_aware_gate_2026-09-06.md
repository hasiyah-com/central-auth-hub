# Cluster-aware FPR + three-way gate verdict

วันที่ 6 ก.ย. 2569 · ขั้นที่ 1–2 ของแผนแก้ปัญหา cold-start FPR
สถานะ: **ไม่เปลี่ยน scoring** — ไม่มีไฟล์ใน `hub/backend/app/security/` ถูกแก้

## 1. ปัญหาที่แก้

จาก [cold_start_fpr_rootcause_2026-09-06.md](cold_start_fpr_rootcause_2026-09-06.md):
`_final_gate()` เทียบ **ค่าประมาณจุด** ของ FPR กับงบแล้วประกาศ passed/failed
ทั้งที่หน่วยอิสระของการทดลองมีเพียง **12 ผู้ใช้** และ U01 ครองสัดส่วน FPR เกิน 60%
ในบาง seed → verdict "ไม่ผ่านงบ 1.0%" จากค่า 1.18% สรุปเกินหลักฐาน (แบบเดียวกับ B69)

## 2. สิ่งที่เพิ่ม

| ไฟล์ | สิ่งที่เพิ่ม |
|---|---|
| `hybrid_experiment/bootstrap.py` | `cluster_rate_ci()` · `rate_verdict()` |
| `hybrid_experiment/gate.py` (ใหม่) | `rate_tree()` · `config_gate()` |
| `hybrid_experiment/tune.py` | `CellStat.per_user_normal_counts` |
| `exp_hybrid_gate.py` | `_final_gate()` รับ `cells_by_config` · เพิ่ม `gate.py` ใน `SCORING_FILES` |

### `cluster_rate_ci` — สุ่มใหม่ระดับ ผู้ใช้ → seed

ไม่สุ่มระดับเหตุการณ์โดยตั้งใจ: binomial sd ที่ n=6,000, p=0.01 คือ **0.13 pp**
ขณะที่การกระจายระหว่างผู้ใช้ที่วัดได้จริงเกิน **10 pp** — ชั้นในสุดไม่เปลี่ยนผล
แต่ทำให้ช้ามาก · ประกาศไว้ใน `levels_resampled` ให้ผู้อ่านตรวจได้

### `rate_verdict` — สามทาง

```
passed        ขอบบน <= งบ   -> มั่นใจว่าอยู่ในงบ
failed        ขอบล่าง > งบ  -> มั่นใจว่าเกินงบ
inconclusive  CI คร่อมงบ    -> ข้อมูลไม่พอตัดสิน
```

`deployable` เป็นจริงเฉพาะ `passed` — **inconclusive = ไม่ deploy (fail-closed)**
ความซื่อตรงในการรายงานต้องไม่ถูกใช้เป็นช่องผ่อนเกณฑ์ความปลอดภัย

### `gate.py` แยกโมดูล (stdlib ล้วน)

ตรรกะการตัดสินต้องทดสอบได้โดยไม่ต้องมี numpy/sklearn/แอป Hub — บทเรียน B61
(โค้ดที่ import ไม่ได้ในสภาพแวดล้อมจริง คือโค้ดที่ไม่เคยถูกพิสูจน์)

## 3. การตัดสินใจเชิงออกแบบที่เทสบังคับไว้

### k=0 ทุก cell -> Wilson **ระดับเหตุการณ์** ไม่ใช่ระดับผู้ใช้

ครั้งแรกใช้ Wilson ระดับผู้ใช้ตามแบบ `hierarchical_proportion` → n=12 ให้ขอบบน
~26% → ระดับ `warn` ที่ **ไม่เคยยิงเลยใน 12,000 เหตุการณ์** ถูกตัดสินเป็น
`inconclusive` เทียบงบ 5% ซึ่งไร้ประโยชน์เชิงการตัดสิน

เหตุผลที่ต่างกัน: `hierarchical_proportion` นับหน่วยเป็น**แคมเปญ** (ไม่กี่หน่วยต่อคน)
แต่ที่นี่นับเป็น**เหตุการณ์ปกติ** (1,000 ต่อคน)

**ข้อจำกัดที่ประกาศไว้ใน `caveat`:** ขอบบนกรณี k=0 ครอบคลุมเฉพาะผู้ใช้ที่อยู่ใน
ตัวอย่าง ไม่เผื่อผู้ใช้ประเภทที่ยังไม่เคยเห็น

### เก็บผลแบบค่าจุดไว้คู่กัน

`passed_point_estimate` / `point_estimate_violations` ยังคงอยู่ เพื่อเทียบกับ
Round 1/2/2b/2c ได้ · `passed` เปลี่ยนไปอ้างอิง cluster CI แทน

## 4. ผลการทดสอบ

### RED

```
$ python -m pytest tests/test_cluster_aware_gate.py -q --noconftest
FAILED tests/test_cluster_aware_gate.py::test_point_estimate_equals_pooled_ratio
FAILED tests/test_cluster_aware_gate.py::test_dominant_cluster_widens_ci_far_beyond_wilson
... (12 failed — AttributeError: module has no attribute 'cluster_rate_ci')
======================== 12 failed, 1 warning in 2.51s ========================

# รอบสอง หลังเพิ่มเทสระดับ gate
E   ImportError: cannot import name 'gate' from 'hybrid_experiment'
```

### GREEN

```
$ cd hub/backend && python -m pytest tests/test_cluster_aware_gate.py \
      tests/test_round2_statistics.py -q --noconftest
======================== 43 passed, 1 warning in 3.74s ========================
```

18 เทสใหม่ + 25 เทสเดิมของ Round 2 ยังผ่านครบ

### ตรวจในคอนเทนเนอร์ (B61 — fail-safe ต้องพิสูจน์เส้นทางจริง)

```
$ docker compose exec hub-backend python -m pytest \
      tests/test_cluster_aware_gate.py tests/test_round2_statistics.py -q
collected 0 items / 2 skipped
============================== 2 skipped in 4.96s ==============================
```

skip อย่างถูกต้อง (harness ของ ml-service ไม่อยู่ใน path ของคอนเทนเนอร์)

## 5. ตรวจ adapter ทั้งสองเส้นทาง

ใช้ผลที่เก็บไว้ของ Round 2c + cells จำลองที่มีรูปแบบ U01 ครองสัดส่วนตามที่วัดได้จริง:

```
legacy path  : per_size_point_estimate | passed = False
cluster path : per_size_cluster_ci     | passed = False
summary      : inconclusive ที่ challenge@50 — CI คร่อมงบ ข้อมูลแยกไม่ออก
               จึงไม่ deploy (fail-closed)
  size    50 ch  1.13% [ 0.50%,  2.40%] -> inconclusive
  size   100 ch  0.62% [ 0.50%,  0.88%] -> passed
  size   500 ch  0.62% [ 0.50%,  0.88%] -> passed
  size  1000 ch  0.62% [ 0.50%,  0.88%] -> passed
  size  5000 ch  0.62% [ 0.50%,  0.88%] -> passed
point-estimate passed : False ['challenge@50=1.18%']
```

## 6. สิ่งที่ **ไม่** ทำในขั้นนี้

- **ไม่คำนวณ verdict ใหม่ย้อนหลังให้ Round 2b/2c** — `final_result.json` ที่เก็บไว้
  ไม่มีสถิติระดับผู้ใช้ (`per_user_normal_counts` เพิ่งเพิ่มในรอบนี้) การได้มาต้อง
  เปิด holdout ซ้ำ ซึ่งขัด B68 · Round 2b/2c คงสถานะ `failed_gate` ตามเดิม
- **ไม่แตะ scoring** — `git diff --name-only -- hub/backend/app/security/` = ว่างเปล่า

## 7. ผลต่อ fingerprint

`exp_hybrid_gate.py`, `tune.py` และไฟล์ใหม่ `gate.py` อยู่ใน `SCORING_FILES` →
`check_frozen_intact()` เทียบกับ `frozen_config.json` ของ Round 2c จะไม่ผ่านตั้งแต่นี้
ซึ่ง **ถูกต้องตามที่ควรเป็น** (Round 2c ปิดไปแล้วด้วยสถานะ failed_gate)
รอบถัดไปต้อง freeze ใหม่ตามขั้นที่ 6–7 ของแผน

## 8. ขั้นถัดไป (ตามแผนที่ตกลงไว้)

3. ออกแบบ subsystem novelty เป็น evidence family เดียว
4. ทดลองสูตร confidence บน validation
5. เลือก candidate ตาม recall@challenge + cluster-aware FPR
6. เปลี่ยน scoring fingerprint + re-prepare ทุก config
7. Freeze แล้วเปิด holdout ใหม่ครั้งเดียว
8. เพิ่มโปรไฟล์ 40+ เป็น external synthetic validation
