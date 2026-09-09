# P48-T2 validation — Config B บนประชากรที่แก้ `weekend_rate` แล้ว

วันที่ 9 ก.ย. 2569 · รอบ validation แยกต่างหากจาก P48 รุ่นเดิม

---

## สถานะ: FROZEN — `p48t2-validation-inconclusive`

| รายการ | สถานะ |
|---|---|
| Warn FPR | **ผ่าน** |
| Block FPR | **ผ่าน** |
| Challenge FPR | **Inconclusive ทุกขนาด** |
| Final holdout | **ยังไม่เปิด** |
| Config B | ใช้ศึกษาต่อใน Shadow Mode |
| Enforcement | **ยังไม่อนุญาต** |
| P48 รุ่นเดิม | เก็บเป็นหลักฐาน ไม่เขียนทับ |
| P48-T2 | รอบ validation แยกต่างหาก |

โปรไฟล์ที่สงวนไว้ (ไม่เคยถูกเปิด):
`T05 T22 T43 T30 T33 T04 T18 T11 T09 T01 T42 T10 T17 T19 T23 T13`

---

## 1. วัตถุประสงค์ของ P48-T2

ตอบคำถามเดียว

> เมื่อประชากรจำลองสร้างพฤติกรรมวันหยุดได้ตามค่าที่ประกาศไว้จริง ผล FPR และ Recall
> ของ Config B ยังยืนอยู่หรือไม่

รอบนี้ **แก้เฉพาะ generator ด้านเวลา** ไม่แตะ scoring, threshold หรือ config ใด ๆ
เพื่อให้ความต่างที่พบไม่ปนกับการเปลี่ยนโมเดล

## 2. การแก้บั๊ก `weekend_rate` (B71)

`build_profiles_v2.spread_over_days()` เคยใส่ `weekend_rate` เป็น **น้ำหนักต่อวัน**
ทั้งที่ pre-registration ประกาศว่าเป็น **สัดส่วนของ login ที่เกิดวันหยุด**

```
สัดส่วนที่ได้ = (n_weekend x rate) / (n_weekday + n_weekend x rate)
```

ต่ำกว่าค่าที่ประกาศ 0.27–0.37 เท่าเสมอ และมีเพดานที่ **0.2667** แม้ตั้ง `rate = 1.0`

### การแก้ — แปลงสัดส่วนเป้าหมายเป็นน้ำหนักตามสูตรปิด

```
w_weekend = (p x n_weekday) / ((1 - p) x n_weekend)      # วันธรรมดา = 1.0
```

| กรณีขอบเขต | พฤติกรรม |
|---|---|
| `p = 0` | ไม่สร้าง login วันหยุดเลย |
| `0 < p < 1` | ใช้สูตรแปลงน้ำหนัก |
| `p = 1` | สร้างเฉพาะวันหยุด |
| ไม่มีวันหยุด / ไม่มีวันธรรมดาในช่วง | `ValueError` พร้อมข้อความชัดเจน |
| `p` นอก `[0, 1]` | `ValueError` |

ยืนยันด้วย `tests/test_generator_weekend_rate.py` — 3 เทสที่เคย RED กลายเป็น GREEN
พร้อมเทส boundary รวม **13 รายการผ่าน**

**ไม่มีการแก้อื่นใดใน generator นอกจากจุดนี้**

## 3. Pre-registration และ provenance

เอกสาร: `docs/design/USER_POPULATION_P48_T2_PREREG.md` — **commit ก่อนอ่านผลใด ๆ**

| รายการ | ค่า |
|---|---|
| `POP_SEED` | 490909 |
| aliases | `T01` – `T48` |
| validation | 32 โปรไฟล์ |
| holdout | 16 โปรไฟล์ |
| data seeds | `[401, 402, 403, 404, 405]` |
| history sizes | `[50, 100, 500, 1000, 5000]` |
| tolerance `weekend_rate` | `max(0.02, sampling_CI)` |
| งบ FPR | warn ≤ 5.0% · challenge ≤ 1.0% · block ≤ 0.2% |
| การตัดสิน | cluster-aware CI สามทาง · `inconclusive` = fail-closed · ต้องผ่านทุกขนาด |

`ml-service/data/hybrid_experiment/p48t2_provenance.json` บันทึกก่อนอ่านผล
(`recorded_before_reading_results: true`) ประกอบด้วย

```
git_commit      c4ac910f800a
source_sha256   20 ไฟล์ที่ผลิตข้อมูลและตัวเลข
scoring_freeze  fingerprint ครบ 10 ไฟล์
```

### สิ่งที่ provenance check จับได้และแก้แล้ว

`hybrid_experiment/metrics.py` อยู่ในชุดที่ผลิตตัวเลขแต่ยังไม่ถูก commit —
ถ้าไม่ตรวจ จะทำซ้ำจาก git ไม่ได้ · commit เข้าไปแล้ว (`c4ac910`) ตอนนี้ไม่มีไฟล์ใด
ในชุด source หรือใน scoring freeze ค้างอยู่นอก commit

## 4. Population integrity และ distribution fidelity

### 4.1 Population integrity

| ตรวจ | ผล |
|---|---|
| จำนวนโปรไฟล์ | 48 |
| alias ชนกับ P48 เดิม | **ไม่ชน** (`T01–T48` เทียบ `P01–P48`) |
| `POP_SEED` | ต่างจากเดิม (490909 เทียบ 480906) |
| data seeds | ต่างจากเดิม (`[401–405]` เทียบ `[301–305]`) |
| split 32/16 | ต่างจากเดิม และแยกขาดจากกัน |
| P48 เดิมถูกแตะหรือไม่ | **ไม่ถูกแตะ** — `population_p48.py` เพิ่มเพียงพารามิเตอร์ที่ค่าเริ่มต้นคงพฤติกรรมเดิม hash test ของ amendment #2 ยังผ่าน |

บังคับด้วย `tests/test_population_p48_t2.py` — **11 รายการผ่าน**

### 4.2 Distribution fidelity

seed 401 · 32 โปรไฟล์ validation

| alias | ประกาศ | ที่ได้จริง | ต่าง |
|---|---|---|---|
| T32 | 0.3776 | 0.3758 | 0.0018 |
| T16 | 0.3714 | 0.3756 | 0.0042 |
| T45 | 0.2779 | 0.2822 | 0.0043 |
| T02 | 0.2086 | 0.2172 | 0.0086 |
| T37 | 0.1996 | 0.2024 | 0.0028 |
| T07 | 0.1362 | 0.1364 | 0.0002 |

```
observed weekend_rate ทั้ง 32 คน: min 0.0000 · median 0.0872 · max 0.3758
เกิน tolerance 0.02: 0 คน
```

ค่าสูงสุดที่สร้างได้คือ **0.3758** ห่างจากค่าที่วัดได้จากผู้ใช้จริง (0.381) อยู่
**0.0052** ซึ่งอยู่ภายใน tolerance 0.02 ที่ประกาศไว้

## 5. Leakage และ shortcut audit

เปิดเฉพาะ P48-T2-validation และเฉพาะ split `tune` · มี assert กันไว้ว่าถ้าหลุดไป
สร้างโปรไฟล์ holdout ให้หยุดทันที

```
runs 25 (5 seeds x 5 sizes) · features 23 · flagged 0
leakage: {'overlapping_rows': 0, 'holdout_rows': 843620, 'clean': True}
```

ฟีเจอร์ที่แยกได้ดีที่สุด

| feature | auc_max | coverage_min |
|---|---|---|
| `login_count_24h` | 0.9230 | 0.5735 |
| `log_minutes_since_last_login` | 0.9194 | 1.0000 |
| `passkey_last_used_days` | 0.6834 | 1.0000 |

ตัวสูงสุด 0.9230 ยังห่างจากเกณฑ์ 0.99

## 6. ผล Config B แยกทุก history size

| size | mean | cluster CI | median | p90 | เกินงบ | verdict |
|---|---|---|---|---|---|---|
| 50 | 0.856% | [0.626, 1.131] | 0.720% | 2.040% | 8/32 | **inconclusive** |
| 100 | 0.893% | [0.607, 1.240] | 0.560% | 2.040% | 9/32 | **inconclusive** |
| 500 | 0.905% | [0.579, 1.312] | 0.560% | 2.080% | 7/32 | **inconclusive** |
| 1000 | 0.898% | [0.579, 1.295] | 0.560% | 2.080% | 7/32 | **inconclusive** |
| 5000 | 0.906% | [0.581, 1.315] | 0.560% | 2.080% | 7/32 | **inconclusive** |

### การกระจาย per-user FPR

| size | min | q25 | median | q75 | p90 | max |
|---|---|---|---|---|---|---|
| 50 | 0.08% | 0.36% | 0.72% | 1.24% | 2.04% | 2.40% |
| 5000 | 0.00% | 0.36% | 0.56% | 0.84% | 2.08% | 4.28% |

### outlier report — ผู้ใช้ที่เกินงบ 1% ที่ size 50

8 จาก 32 คน · **ไม่ใช้เป็นเกณฑ์ตัดสิน** ตามที่ประกาศไว้ แต่ต้องเห็น

```
T38 2.40%   T24 2.28%   T47 2.04%   T40 2.04%
T44 1.84%   T39 1.80%   T02 1.36%   T32 1.24%
```

### Baseline (Config A)

| size | mean | cluster CI | เกินงบ | verdict |
|---|---|---|---|---|
| 50 | 2.461% | [1.846, 3.190] | 28/32 | **failed** |
| 100 | 2.167% | [1.685, 2.724] | 27/32 | failed |
| 500 | 2.067% | [1.621, 2.590] | 28/32 | failed |
| 1000 | 2.091% | [1.628, 2.636] | 27/32 | failed |
| 5000 | 2.144% | [1.646, 2.715] | 26/32 | failed |

## 7. Warn / Challenge / Block FPR พร้อม cluster CI

| ระดับ | size | mean | cluster CI | งบ | verdict |
|---|---|---|---|---|---|
| warn | 50 | 1.787% | [1.270, 2.375] | 5.00% | **passed** |
| warn | 100 | 1.599% | [1.156, 2.147] | 5.00% | passed |
| warn | 500 | 1.862% | [1.372, 2.420] | 5.00% | passed |
| warn | 1000 | 1.899% | [1.399, 2.478] | 5.00% | passed |
| warn | 5000 | 1.837% | [1.335, 2.429] | 5.00% | passed |
| challenge | ทุกขนาด | 0.856 – 0.906% | ขอบบน 1.131 – 1.315% | 1.00% | **inconclusive** |
| block | 50 | 0.013% | [0.003, 0.028] | 0.20% | **passed** |
| block | 100 | 0.009% | [0.001, 0.020] | 0.20% | passed |
| block | 500 | 0.013% | [0.001, 0.030] | 0.20% | passed |
| block | 1000 | 0.009% | [0.000, 0.022] | 0.20% | passed |
| block | 5000 | 0.010% | [0.000, 0.025] | 0.20% | passed |

## 8. Recall รวมและแยก attack family

**recall@challenge (macro ถ่วงตามจำนวนเหตุการณ์) = 0.6673**

| family | n | recall@challenge (size 50) |
|---|---|---|
| combined_ato | 320 | 1.0000 |
| concurrent_sessions | 320 | 1.0000 |
| failed_spike | 320 | 1.0000 |
| new_device | 320 | 1.0000 |
| new_os | 320 | 1.0000 |
| new_ua_family | 320 | 1.0000 |
| permission_change | 160 | 1.0000 |
| subtle_lowandslow | 320 | 0.9125 |
| off_hours | 320 | 0.8969 |
| subsystem_lateral | 160 | 0.8375 |
| subtle_mild_offhour | 320 | 0.7531 |
| subtle_quiet_lateral | 320 | 0.6813 |
| campaign | 1600 | 0.4219 |
| login_velocity | 320 | 0.3844 |
| subtle_slow_burst | 320 | 0.2469 |
| new_passkey | 320 | 0.1844 |
| subtle_rare_device | 250 | 0.1440 |

7 ตระกูลที่จับได้ครบเป็นตระกูลที่มี policy floor รองรับ · ตระกูลที่พึ่งคะแนนล้วนต่ำกว่ามาก

## 9. คำตัดสิน Gate

| # | Gate | ผล |
|---|---|---|
| 1 | Population integrity | **ผ่าน** |
| 2 | Distribution fidelity | **ผ่าน** — 32/32 อยู่ใน tolerance |
| 3 | Leakage | **ผ่าน** — 0 จาก 843,620 แถว |
| 4 | Shortcut | **ผ่าน** — 0 ฟีเจอร์เข้าเกณฑ์ |
| 5 | Scoring integrity | **ผ่าน** — freeze 10/10 ตรวจก่อนเริ่มรอบ |
| 6 | Challenge FPR | **inconclusive ทุกขนาด** |
| 7 | Warn / Block FPR | **ผ่านทั้งคู่ทุกขนาด** |
| 8 | Recall | รายงานแล้ว — `recall@challenge = 0.6673` |
| 9 | Holdout | **ยังปิด** เพราะ validation ไม่ผ่าน |

### ผลการทดสอบก่อน freeze

```
เทสที่ต้องใช้ ml-service/scripts (รันบน host)      64 passed
  test_population_p48_t2.py     11
  test_population_p48.py        22
  test_generator_weekend_rate.py 13
  test_cluster_aware_gate.py    18
test_scoring_freeze.py                              4 passed
ชุดเต็มใน hub-backend                             965 passed · 42 skipped · 2 failed
```

เทสที่ไม่ผ่าน 2 รายการเป็น **ความไม่เสถียรตามลำดับการรันที่มีอยู่ก่อนรอบนี้**
ไม่เกี่ยวกับงาน P48-T2

```
tests/test_e2e_subsystem.py::test_e2e_register_bad_redirect_rejected      401 แทน 422
tests/test_scope_conformance.py::test_scope3_monitoring_requires_admin    401 แทน 403
```

ทั้งสองรายการ **ผ่านเมื่อรันแยกไฟล์** (17/17 และ 5/5) อาการคือโทเคนถูกปฏิเสธเป็น 401
ซึ่งเข้ากับสถานะที่ค้างใน Redis จากเทสอื่นในรันเดียวกัน · ไม่แตะโค้ดในรอบนี้เพราะอยู่นอก
ขอบเขตและกติกาห้ามแก้อะไรหลังเห็นผล — บันทึกไว้เป็นงานแยก

`tests/test_e2e_full_stack.py` และ `tests/test_l1_oidc.py` เป็นสคริปต์สแตนด์อโลนที่
เรียก `sys.exit()` ตอน import จึงต้อง `--ignore` เมื่อรันทั้งชุด (มีอยู่ก่อนรอบนี้)

## 10. สถานะ holdout

```
holdout_opened: false
holdout_profiles_untouched: 16
```

ไม่มีสคริปต์ใดในรอบนี้อ่านค่าจากโปรไฟล์ holdout · ทั้ง audit และ validation มี
assert กันไว้ · holdout ledger ยังไม่มี entry ของ seed ชุด `[401–405]`

**สงวนไว้สำหรับการตรวจสอบภายนอกหรืองานต่อยอด** ห้ามเปิดจนกว่า validation จะได้ `passed`

## 11. ข้อจำกัด

1. **ตัวเลขทั้งหมดมาจาก split `tune`** — split `test` ภายในผู้ใช้และโปรไฟล์ holdout
   ยังไม่ถูกเปิด · จากรอบก่อนมีจุดสอบเทียบเดียวว่า tune ให้ค่าต่ำกว่า holdout ราว
   1.70 เท่า ซึ่งเป็นการเทียบข้าม seed และข้าม split จึงเป็นการประมาณคร่าว ๆ เท่านั้น
2. **ข้อมูลเป็นข้อมูลสังเคราะห์** — การแจกแจงของประชากรเป็นการประกาศ ไม่ใช่การวัด
   จากประชากรจริง
3. **การเทียบ recall กับ baseline ไม่เป็นธรรม** — Config A ขอ challenge บ่อยกว่า
   ประมาณ 2.3–2.9 เท่าในรอบนี้ ค่า recall ที่สูงกว่าจึงส่วนหนึ่งมาจากการยิงถี่กว่า
4. **การนับ `inconclusive` เป็นไม่ผ่านเป็นการตัดสินเชิงนโยบาย** ไม่ใช่เชิงสถิติ
5. **แกนเวลาอื่นของ generator ยังไม่ถูกแก้** — `EPISODE_STRIDE_DAYS = 400` ยังทำให้
   ฟิลด์ที่อิงปฏิทิน (เช่น จำนวนวันที่ใช้งาน) เทียบกับข้อมูลจริงไม่ได้
6. **`session duration` ยังใช้ไม่ได้** — `logout_at` ไม่สะท้อนเวลาจบ session จริง

## 12. การเปรียบเทียบ P48 กับ P48-T2 เชิงพรรณนา

> **คำเตือน** — การเปรียบเทียบ P48 และ P48-T2 เป็นการเปรียบเทียบเชิงพรรณนาเท่านั้น
> เนื่องจากทั้งสองรอบใช้ประชากรจำลอง seed และ split คนละชุด ความแตกต่างที่พบจึง
> **ไม่สามารถระบุเชิงสาเหตุ**ว่าเกิดจากการแก้ `weekend_rate` เพียงอย่างเดียว และ
> **ไม่มีการทดสอบนัยสำคัญแบบ paired** ระหว่างสองรอบ

### 12.1 Challenge FPR (Config B)

| size | P48 | P48-T2 | verdict ทั้งสองรอบ |
|---|---|---|---|
| 50 | 0.871% [0.620, 1.176] | 0.856% [0.626, 1.131] | inconclusive |
| 100 | 0.809% [0.574, 1.105] | 0.893% [0.607, 1.240] | inconclusive |
| 500 | 0.841% [0.593, 1.142] | 0.905% [0.579, 1.312] | inconclusive |
| 1000 | 0.792% [0.557, 1.085] | 0.898% [0.579, 1.295] | inconclusive |
| 5000 | 0.802% [0.565, 1.101] | 0.906% [0.581, 1.315] | inconclusive |

### 12.2 Warn / Block และ baseline

| รายการ | P48 | P48-T2 | verdict |
|---|---|---|---|
| block @50 | 0.005% | 0.013% | passed ทั้งสองรอบ |
| warn @50 | 2.295% | 1.787% | passed ทั้งสองรอบ |
| baseline @50 | 3.561% | 2.461% | failed ทั้งสองรอบ |

### 12.3 Recall แยก family

| family | P48 | P48-T2 | ต่าง |
|---|---|---|---|
| campaign | 0.3725 | 0.4219 | +0.0494 |
| subsystem_lateral | 0.7875 | 0.8375 | +0.0500 |
| subtle_quiet_lateral | 0.6406 | 0.6813 | +0.0406 |
| off_hours | 0.8844 | 0.8969 | +0.0125 |
| subtle_lowandslow | 0.9344 | 0.9125 | −0.0219 |
| subtle_slow_burst | 0.2719 | 0.2469 | −0.0250 |
| login_velocity | 0.4188 | 0.3844 | −0.0344 |
| subtle_mild_offhour | 0.8094 | 0.7531 | −0.0562 |
| new_passkey | 0.2437 | 0.1844 | −0.0594 |
| subtle_rare_device | 0.2565 | 0.1440 | −0.1125 |
| 7 ตระกูลที่มี policy floor | 1.0000 | 1.0000 | 0 |

**แต่ละตระกูลเปลี่ยนไปไม่เหมือนกัน** บางตระกูลสูงขึ้น บางตระกูลต่ำลง
รายงานนี้**ไม่อธิบายเชิงสาเหตุ**ว่าเป็นผลของ `weekend_rate` เพราะเป็นคนละประชากร

### 12.4 สิ่งที่กล่าวได้จากการเปรียบเทียบนี้

**ข้อสรุปเชิงการนำไปใช้ไม่เปลี่ยนจาก P48 รุ่นเดิม** — warn และ block ผ่านทั้งสองรอบ
challenge ได้ `inconclusive` ทั้งสองรอบทุกขนาด และ baseline ไม่ผ่านทั้งสองรอบ

ความชันตามขนาดประวัติยังคงเล็กในทั้งสองรอบ (P48 1.10 เท่า · P48-T2 1.06 เท่า เมื่อเทียบค่าสูงสุดกับค่าต่ำสุดข้ามขนาด)

## 13. ข้อสรุปสำหรับงานวิจัย

> หลังแก้ generator ให้ `weekend_rate` มีความหมายเป็นสัดส่วนจริง และยืนยันว่าประชากร
> P48-T2 สร้างพฤติกรรมวันหยุดได้ตามค่าที่ประกาศ Config B ยังคงผ่านงบ Warn FPR และ
> Block FPR แต่ Challenge FPR มีช่วงความเชื่อมั่นระดับคลัสเตอร์คร่อมงบ 1% ทุกขนาด
> ประวัติ จึงให้ผล `inconclusive` และไม่เปิด final holdout ตามกติกาที่กำหนดไว้ล่วงหน้า

### สิ่งที่รอบนี้เพิ่มให้กับงานวิจัย

1. **ปิดช่องว่างเชิงวิธีวิทยาหนึ่งจุด** — ประชากรจำลองสร้างพฤติกรรมวันหยุดได้ตามที่
   ประกาศแล้ว ครอบคลุมถึงค่าที่วัดได้จากผู้ใช้จริงภายใน tolerance
2. **ข้อสรุปเชิงการนำไปใช้ไม่เปลี่ยน** ซึ่งเป็นหลักฐานว่าข้อสรุปมีความคงทนต่อการแก้
   ข้อบกพร่องด้านนี้ของ generator
3. **แสดงว่ากระบวนการตรวจจับข้อบกพร่องของตัวเองทำงาน** — บั๊กถูกพบจากการเทียบกับ
   ข้อมูลจริง ไม่ใช่จากการอ่านโค้ด

### สิ่งที่ยังตอบไม่ได้

- Challenge FPR อยู่ในงบ 1% หรือไม่ — ผู้ใช้ 32 คน × 5 seeds ยังแยกไม่ออก
- ตัวเลขจากข้อมูลสังเคราะห์ตรงกับ traffic จริงแค่ไหน — ยังไม่เคยวัด
- ช่องว่างระหว่าง split `tune` กับ holdout ซึ่งเป็นปัญหา bias ที่การเพิ่มหน่วยทดลอง
  แก้ไม่ได้

## 14. Artifact ของรอบนี้

ไฟล์ผลลัพธ์อยู่ใต้ `ml-service/data/` ซึ่ง **gitignore ทั้งโฟลเดอร์** ตามนโยบาย
"ข้อมูลจริงห้ามขึ้น git" จึงบันทึก sha256 ไว้ที่นี่แทน เพื่อให้ตรวจสอบย้อนได้ว่า
ตัวเลขในรายงานนี้มาจากไฟล์ชุดใด

| ไฟล์ (ใต้ `ml-service/data/hybrid_experiment/`) | ขนาด | sha256 |
|---|---|---|
| `population_p48_t2_summary.json` | 2,671 | `8b1ab544182f5ba4462745277b63f361fc4658f74d2a028d2a01ea835da6b774` |
| `audit_p48t2.json` | 3,824 | `d8851dadaa85e8ed5eb2aab9d6f33af74d531c5323f7f29d0876011a58fe840b` |
| `p48t2_provenance.json` | 4,889 | `9362bc0a87f67b24c5382687442240eb1480ad2938861abfb218be339e179c99` |
| `p48t2_validation.json` | 118,365 | `6714e7d3138a8c697d6354091d00f757853a7e3ac08451b97251c405ab3b1a10` |

`p48t2_provenance.json` บันทึก `git_commit = c4ac910f800ad42e52f5b61a308405dbac1894c8`
พร้อม sha256 ของไฟล์ต้นทาง 20 ไฟล์ และ fingerprint ของ scoring freeze
โดยมี `recorded_before_reading_results: true`

### ความสัมพันธ์กับ evidence manifest ของ P48

`docs/RBA_EVIDENCE_MANIFEST_2026-09-08.md` เป็นภาพนิ่งของรอบ P48 · เมื่อรัน
`python scripts/build_evidence_manifest.py --verify` ตอนนี้จะรายงานว่า 4 ไฟล์
เปลี่ยนไปแล้ว

```
ml-service/scripts/build_profiles_v2.py      (แก้ B71)
ml-service/scripts/population_p48.py         (เพิ่ม alias_prefix — ค่าเริ่มต้นคงเดิม)
ml-service/scripts/exp_p48_validation.py     (เพิ่มตัวเลือก --population p48t2)
ml-service/scripts/audit_p48_generator.py    (เพิ่มตัวเลือก --population p48t2)
```

**นี่คือพฤติกรรมที่ถูกต้อง ไม่ใช่ข้อผิดพลาด** — manifest ฉบับนั้น freeze คู่กับ tag
`p48-validation-inconclusive` และต้องรายงานว่าโค้ดขยับหลังจากนั้น · หลักฐานที่ผูกกับ
รอบ P48-T2 คือ `p48t2_provenance.json` ข้างต้น ไม่ใช่ manifest ฉบับ 2026-09-08

## 15. วิธีทำซ้ำ

```bash
python ml-service/scripts/population_p48_t2.py
python ml-service/scripts/audit_p48_generator.py --population p48t2 --seeds 401 402 403 404 405
python ml-service/scripts/exp_p48_validation.py --population p48t2 --seeds 401 402 403 404 405 \
    --out ../data/hybrid_experiment/p48t2_validation.json
```

ข้อมูลจริงไม่อยู่ในคลังโค้ด — ผู้ตรวจต้องใช้ anchor ของตนเองแล้วส่งผ่าน `--users`
