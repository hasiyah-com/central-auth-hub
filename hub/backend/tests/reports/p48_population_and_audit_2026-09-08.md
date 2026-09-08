# ประชากรโปรไฟล์ P48 + ตรวจ shortcut/leakage ของ generator

วันที่ 8 ก.ย. 2569 · ขั้นที่ 4–5 ของแผน
**ยังไม่มีการวัดประสิทธิภาพใด ๆ · โปรไฟล์ holdout 16 คนไม่ถูกแตะ**

## 1. เหตุผล

`build_profiles_v2.SPEC` มีโปรไฟล์ 12 คนที่ตายตัวและใช้ชุดเดิมทุก seed — การเปลี่ยน
seed เปลี่ยนเพียงการสุ่มของ RNG ไม่ได้เพิ่มหน่วยทดลอง · ผลคือผู้ใช้คนเดียว (U01)
ครองสัดส่วน challenge FPR ได้ถึง 62% ในบาง seed
(ดู [cold_start_fpr_rootcause_2026-09-06.md](cold_start_fpr_rootcause_2026-09-06.md))

## 2. สิ่งที่สร้าง

| ไฟล์ | หน้าที่ |
|---|---|
| `ml-service/scripts/population_p48.py` | generator + split + roster + summary + CLI |
| `hub/backend/tests/test_population_p48.py` | 20 เทสบังคับให้ตรงกับ pre-registration |
| `ml-service/scripts/audit_p48_generator.py` | ตรวจ shortcut/leakage (ขั้นที่ 5) |
| `gen_v3.build_seed(spec=, roster=)` | ฉีดประชากรอื่นได้ · `None` = พฤติกรรมเดิมทุกประการ |

เอกสารผูกพัน: `docs/design/USER_POPULATION_P48_PREREG.md` (commit ก่อนเขียน generator)

## 3. ประชากรที่ได้ (`POP_SEED = 480906`)

```
n_profiles      48
rows            41 – 157  (median 101)
n_subsystems    1 ระบบ 14 คน · 2 ระบบ 24 คน · 3 ระบบ 10 คน
โหมดรอง         min 0.030 · median 0.177 · max 0.471 · ที่ <= 0.15 มี 14 คน
n_devices       1 เครื่อง 13 · 2 เครื่อง 24 · 3 เครื่อง 11
n_hour_peaks    1 จุด 19 · 2 จุด 25 · 3 จุด 4
passkey_users   35 / 48
scope           0.3 -> 12 · 0.5 -> 14 · 0.8 -> 15 · 1.0 -> 7
```

**14 คนมีโหมดรอง ≤ 0.15** — เคสแบบ U01 (โหมดชอบธรรมที่หายจากชุดฝึกเล็ก) ยังอยู่ใน
ประชากรจริง ไม่ได้ถูกออกแบบให้หายไปเพื่อให้ตัวเลขสวย

### การแบ่ง (ล็อกก่อนวัดผลใด ๆ)

```
validation 32: P34 P14 P35 P08 P20 P25 P01 P03 P48 P41 P11 P19 P44 P24 P07 P32
               P21 P12 P37 P02 P10 P31 P29 P15 P06 P16 P33 P38 P40 P17 P22 P09
holdout    16: P46 P13 P36 P39 P45 P04 P43 P05 P23 P47 P28 P26 P42 P30 P27 P18
```

## 4. เติม pre-registration §2b — seed ของข้อมูล

เอกสารฉบับแรกประกาศเฉพาะ **ประชากรโปรไฟล์** แต่ลืมประกาศ **seed ของการสุ่มข้อมูล**
ซึ่งเป็นคนละแกน (โปรไฟล์ = ใคร · seed = การสุ่มเหตุการณ์ของคนนั้น)

```
SEEDS_P48 = [301, 302, 303, 304, 305]
```

เติมไว้ **ก่อนมีการวัดใด ๆ** และบันทึกในเอกสารว่าเป็นการเติมภายหลัง ·
`[101-115]` ถูกใช้ไปแล้ว · `[201-205]` จองไว้ให้ Round 3 (conditional L3)

## 5. ผลตรวจ shortcut / leakage (ขั้นที่ 5)

เปิดเฉพาะ **P48-validation** และเฉพาะ split `tune` · สคริปต์ assert ว่าถ้าหลุดไป
สร้างโปรไฟล์ holdout ให้หยุดทันที

```
runs 25 (5 seeds x 5 sizes) · features 23 · flagged 0
leakage: {'overlapping_rows': 0, 'holdout_rows': 843475, 'clean': True}
```

เกณฑ์เดิมทุกประการเพื่อให้เทียบรอบก่อนได้: `AUC > 0.99` หรือ `coverage < 0.05`
(Mann-Whitney แบบ mid-rank จัดการค่าเสมอ)

ฟีเจอร์ที่แยกได้ดีที่สุด 5 อันดับ:

| feature | auc_max | auc_mean | coverage_min |
|---|---|---|---|
| `log_minutes_since_last_login` | 0.9103 | 0.8921 | 1.0000 |
| `login_count_24h` | 0.9013 | 0.8807 | 0.7401 |
| `day_of_week` | 0.6720 | 0.6683 | 1.0000 |
| `passkey_last_used_days` | 0.6658 | 0.6626 | 1.0000 |
| `hours_from_typical_login_time` | 0.6325 | 0.6180 | 1.0000 |

ตัวสูงสุด 0.9103 ยังห่างจากเกณฑ์ 0.99 พอสมควร และ `coverage = 1.0` แปลว่าค่าของ
attack อยู่ในช่วงของ normal ทั้งหมด — ไม่ใช่การแยกด้วยค่าที่ normal ไม่มีทางได้

**สรุป: ไม่พบ single-feature shortcut และไม่พบ leakage บน P48-validation**

## 6. จุดที่ต้องแก้ระหว่างทาง

RED รอบแรกใช้ `pytest.importorskip("population_p48")` ทำให้เทสทั้งไฟล์ **skip แทนที่
จะ fail** ตอนที่โมดูลยังไม่มี — กลืนเฟส RED ไปทั้งชุดโดยไม่มีใครเห็น

แก้ให้ skip เฉพาะเมื่อ **ไม่มี harness ของ ml-service เลย** (กรณีรันในคอนเทนเนอร์)
ส่วนกรณีมี harness แต่โมดูลหาย ต้อง fail — อาการเดียวกับ B61 (fail-safe ที่ทำงาน
"ถูกต้อง" จนไม่มีใครรู้ว่าเส้นทางจริงไม่เคยทำงาน)

## 7. ขั้นถัดไป

6. รัน Config B + baseline บน **P48-validation** เท่านั้น
7. รายงานด้วย cluster-aware CI + per-user distribution ตามเกณฑ์ §4 ของ pre-registration
8. เปิด **P48-holdout** ครั้งเดียว เฉพาะเมื่อ validation ผ่าน
9. ถ้าไม่ผ่าน — หยุดที่ Shadow ห้ามปรับ threshold ต่อ
