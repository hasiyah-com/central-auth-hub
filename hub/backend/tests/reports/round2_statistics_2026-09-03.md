# Round 2 — เครื่องมือสถิติ (2026-09-03)

รายงานของงานที่ 1–5 ใน `docs/RBA_ROUND2_PROTOCOL.md` · เป็น **โครงสร้างพื้นฐาน**
ของ Round 2 (ยังไม่ได้รันการทดลองบน holdout ใหม่ — งานที่ 6–9)

| | |
|---|---|
| branch | `feature/hybrid-risk-round2` (ฐาน = tag `rba-hybrid-round1-failed-gate-2026-09-03`) |
| เทส | `hub/backend/tests/test_round2_statistics.py` — **17 passed** (host) · 1 skipped (container) |
| วิธี | TDD RED → GREEN · RED ยืนยันก่อน (ImportError: `tailcal` ยังไม่มี + field ยังไม่ถูก rename) |
| parity หลังแก้ | ผ่าน 6/6 กลุ่ม (การ rename ไม่กระทบ logic) |

## คำสั่งรัน (reproducible)

```bash
# host — โมดูลเป็น stdlib ล้วน ไม่ต้องมี numpy/app
cd hub/backend
python -m pytest tests/test_round2_statistics.py -v --noconftest -p no:cacheprovider

# container — skip สะอาด (harness ของ ml-service ไม่อยู่ใน /app)
docker compose exec hub-backend pytest tests/test_round2_statistics.py -q
```

> เทสชุดนี้ import จาก `ml-service/scripts/hybrid_experiment/` ซึ่งคอนเทนเนอร์
> `hub-backend` มองไม่เห็น (และไม่มี numpy ตาม B61) จึงใช้ `pytest.importorskip`
> ให้ skip ในคอนเทนเนอร์และรันจริงบน host · โมดูลที่ทดสอบเขียนด้วย **stdlib ล้วน**
> โดยตั้งใจ เพื่อให้ผลทำซ้ำได้โดยไม่ผูกกับเวอร์ชัน numpy/scipy

---

## งานที่ 5 — rename metric field

`l3_effective_unique` -> `within_config_l3_counterfactual_unique` ทุกจุดในโค้ด active
(metrics.py 5 · tune.py 8 · sweep.py 2 · exp_hybrid_gate.py 6 = 21 จุด) ·
ไม่แตะ `run_bytes_round1/` ซึ่งเป็นหลักฐาน byte-exact ของ Round 1

**เหตุผล:** ชื่อเดิมอ่านได้ว่า "L3 เพิ่มการตรวจจับ 12.7%" ซึ่งผิด — ค่านั้นเป็น
counterfactual **ภายใน config เดียวกัน** ("ถ้าตัด L3 ออกจาก Config E เอง จะมีกี่
เหตุการณ์ที่ผลเปลี่ยน") ขณะที่ recall **สุทธิ** ของ E ต่ำกว่า B ถึง 8.35 pp
ชื่อใหม่บังคับให้ผู้อ่านเห็นว่าเป็น within-config ไม่ใช่กำไรสุทธิ

เทสที่คุ้มครอง: `test_metric_field_renamed_everywhere`, `test_macro_reports_renamed_key`
— ยืนยันว่าชื่อเก่าหายจาก `EventOutcome` / `Summary` / `CellStat` / ผลของ `macro()`

---

## งานที่ 1 — paired hierarchical bootstrap

`bootstrap.paired_hierarchical(tree, two_arm_stat, ...)` — วัดผลต่างระหว่างสอง
config บนเหตุการณ์ **ชุดเดียวกัน** ต่อรอบ bootstrap แล้วสุ่มโครงสร้างสามชั้น
`user -> seed -> event` แบบมีคืน

**ทำไมต้อง paired:** Round 1 รายงาน CI แบบ unpaired แล้วอ้างว่า "CI ไม่ทับกัน =
ต่างกัน" · แต่ทุก config วัดบนเหตุการณ์ชุดเดียวกัน ความแปรปรวนส่วนใหญ่มาจาก
"ผู้ใช้คนไหนถูกสุ่มเข้ามา" ซึ่ง **ร่วมกันทั้งสองแขน** · การวัดผลต่างแบบ paired
หักล้างความแปรปรวนร่วมนั้น

เทสที่คุ้มครอง (6 ตัว):

| เทส | คุณสมบัติที่ตรึงไว้ |
|---|---|
| `test_paired_delta_is_exactly_zero_for_identical_arms` | สองแขนเหมือนเป๊ะ -> delta และ CI = [0,0] (พิสูจน์ว่า paired จริง ไม่ได้สุ่มแยก) |
| `test_paired_ci_is_narrower_than_unpaired_when_arms_correlated` | แขนสัมพันธ์กันสูง -> CI ของ paired **แคบกว่า** unpaired |
| `test_paired_respects_three_level_structure` | สัญญาณกระจุกในผู้ใช้เดียว -> CI กว้างกว่าเมื่อสัญญาณกระจายทั่ว (cluster ไม่ถูกละเลย) |
| `test_paired_is_deterministic_given_seed` | seed เดียวกัน -> ผลเท่ากันทุกหลัก |
| `test_paired_reports_sign_agreement` | รายงานสัดส่วนรอบที่ผลต่างมีทิศเดียวกับค่าจริง (แทน p-value อย่างหลวม) |

`unpaired_delta_width()` เพิ่มมาเพื่อใช้ **เทียบในเทสเท่านั้น** — ห้ามใช้รายงานจริง

---

## งานที่ 2 — hierarchical proportion CI (ระดับแคมเปญ)

`bootstrap.hierarchical_proportion(tree, ...)` — CI ของสัดส่วน "แคมเปญที่เฉพาะ L3
จับได้" โดย bootstrap ระดับผู้ใช้

**ทำไมไม่ใช้ Wilson:** Wilson สมมติทุกหน่วยเป็นอิสระ · แคมเปญของผู้ใช้คนเดียวกัน
สัมพันธ์กัน (โมเดลพลาดผู้ใช้คนหนึ่งมักพลาดทั้งชุด) · การ `0/245 · Wilson upper
1.54%` ของ Round 1 จึงยังไม่พอ

**กรณี all-zero (สำคัญ):** bootstrap ของ 0 ทั้งหมดได้ 0 เสมอ -> ขอบบนจะกลายเป็น 0
ซึ่ง **หลอก** ("เป็นไปไม่ได้เลย") · โค้ดตรวจจับกรณีนี้แล้วใช้ **Wilson เป็นขอบบน
สำรอง** พร้อมประกาศใน `upper_bound_method: "wilson_fallback_all_zero"`

เทสที่คุ้มครอง (3 ตัว): `test_zero_events_does_not_claim_impossibility`,
`test_clustered_zeros_give_wider_bound_than_wilson`, `test_all_hits_gives_upper_bound_one`

---

## งานที่ 3 — tail calibration (แทน ECE)

โมดูลใหม่ `hybrid_experiment/tailcal.py` — stdlib ล้วน

**ทำไมถอด ECE:** ECE เป็นเครื่องมือของ **probability prediction** แต่
`final_risk_score` เป็น **percentile evidence ไม่ใช่ probability** · ค่า ECE 0.607
ของ Config E ใน Round 1 จึงลงโทษโมเดลด้วยเกณฑ์ที่โมเดลไม่เคยอ้าง

เครื่องมือที่ใช้แทน:

| ฟังก์ชัน | ถามอะไร |
|---|---|
| `benign_exceedance(calib, eval)` | ตั้งเกณฑ์ที่ p95/p99/p99.9 ของ login ปกติชุดหนึ่ง -> login ปกติอีกชุดเกินกี่ % ควรใกล้ 5%/1%/0.1% · **ตรงกับงบ FPR โดยตรง** |
| `pit_uniformity(calib, sample)` | PIT ของ sample ภายใต้ CDF ของ calib ควรเป็น uniform[0,1] · วัดด้วย KS |
| `pit_values(calib, scores)` | ค่า PIT รายจุด — monotone, อยู่ใน [0,1] |
| `full_report(calib, holdout, validation)` | รวม exceedance + PIT · เทียบ validation vs holdout (ตอบว่าทำไม FPR บน holdout สูงกว่าที่จูน) |

เทสที่คุ้มครอง (5 ตัว): exceedance ตรง nominal บนข้อมูล uniform · exceedance ตรวจจับ
tail shift · KS เล็กสำหรับ uniform ใหญ่สำหรับ skewed · PIT monotone ·
**เอกสารต้องมีคำว่า "ไม่ใช่ probability" และ "ECE"** (กันการกลับไปใช้ ECE เงียบๆ)

---

## งานที่ 4 — common-FPR operating point

`sweep.operating_point_at_fpr(evaluate_fn, target_fpr, gamma, ...)` — ดันทุก config
ให้ทำงานที่ FPR ร่วมกัน (เช่น 1.5% ซึ่งสูงกว่า legacy floor 1.2467%) แล้วเทียบ recall

**ทำไม:** Round 1 บอกถูกแล้วว่า "เทียบที่ challenge FPR 1% ไม่ได้ เพราะ legacy
floor 1.2467%" · ทางแก้คือเทียบที่ common FPR **ที่สูงกว่า floor** — ยังเทียบข้าม
สถาปัตยกรรมได้จริง

**ห้ามขยับเป้า:** ถ้าไม่มีจุดถึงเป้า คืน `attained: False` + `minimum_attainable_fpr`
ไม่ใช่เขียนเป้าใหม่ให้ผลดูผ่าน · เดินผ่าน resolver ของ production เหมือน `sweep.search`

เทสที่คุ้มครอง (2 ตัว): `test_common_fpr_finds_point_at_or_below_target`,
`test_common_fpr_reports_unattainable_without_moving_target`

---

## ยังไม่ได้ทำ (งานที่ 6–9 — เป็นการรันการทดลอง)

| # | งาน | สถานะ |
|---|---|---|
| 6 | ปรับ block threshold ของ Config B **บน validation** | ยังไม่เริ่ม — ต้องกวาดบน validation-tuning |
| 7 | ประกาศ candidate/fallback | เสร็จ ใน `docs/RBA_ROUND2_PROTOCOL.md` |
| 8 | เปิด holdout seeds `[101-105]` | ยังไม่เปิด — หลัง freeze เท่านั้น |
| 9 | full pytest + operational latency (end-to-end รวม I/O) | ยังไม่ทำ |

**ขั้นถัดไปที่ต้องทำก่อนรันจริง:** wire เครื่องมือทั้ง 4 เข้า `cmd_final` ของ harness
แทน CI แบบ unpaired + ECE เดิม (ปัจจุบันโค้ดมีแล้วแต่ `final` ยังเรียกของเก่า)
แล้วจึง prepare -> tune (ปรับ block threshold ของ B) -> freeze -> final บน `[101-105]`
