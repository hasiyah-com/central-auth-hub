# ชุดหลักฐานสำหรับผู้เชี่ยวชาญตรวจ — รอบ 8 ก.ย. 2569

**ส่วนเพิ่มเติมจาก** [`RBA_EXPERT_REVIEW_PACK_2026-08-29.md`](RBA_EXPERT_REVIEW_PACK_2026-08-29.md)
ซึ่งยังใช้ได้ทั้งฉบับ — เอกสารนี้รายงานเฉพาะสิ่งที่เปลี่ยนไปหลังจากนั้น
(ไม่เขียนทับของเดิม เพราะ tag `rba-expert-review-2026-08-29` อ้างไฟล์นั้นอยู่)

manifest ของรอบนี้: [`RBA_EVIDENCE_MANIFEST_2026-09-08.md`](RBA_EVIDENCE_MANIFEST_2026-09-08.md)
tag: `p48-validation-inconclusive`

---

## 1. สถานะระบบ ณ รอบนี้ (อ่านก่อนตัวเลขใด ๆ)

| องค์ประกอบ | สถานะ |
|---|---|
| Hybrid RBA (4 ชั้น) + Layer 3 | **Shadow** — ให้คะแนนและบันทึก **ไม่ตัดสินสิทธิ์** |
| การตัดสินการเข้าถึงจริง | policy / baseline ที่อนุมัติไว้เดิม ไม่เปลี่ยน |
| เกณฑ์ challenge FPR | **inconclusive** — ไม่ผ่านเงื่อนไขการนำขึ้นใช้งาน |
| holdout 16 โปรไฟล์ | **ไม่เคยเปิด** สงวนไว้สำหรับ external validation |

**ไม่มีการปรับ threshold, scoring logic หรือ generator เพิ่มในรอบนี้หลังการวัด**
scoring ถูก freeze ด้วย hash + เทสตรวจ (`hub/backend/tests/scoring_freeze.json`)

---

## 2. ข้อสรุปหลักของรอบนี้

### 2.1 ปัญหา "cold-start FPR" ที่ไล่ตามมาสามรอบ เป็นคุณสมบัติของ**ประชากรตัวอย่าง** ไม่ใช่ของระบบ

Round 2 / 2b / 2c พยายามปิดช่องว่าง challenge FPR ที่ cold start (1.18–1.23% เทียบงบ 1%)
ด้วยการปรับ threshold ทั้งสามรอบ และไม่สำเร็จทั้งสามรอบ

การวินิจฉัยพบว่า **ผู้ใช้คนเดียว (U01) ครองสัดส่วน FPR ได้ถึง 62%** ในบาง seed และ
โปรไฟล์ทั้ง 12 คนเป็นชุดเดิมทุก seed — การเปลี่ยน seed จึงไม่เพิ่มหน่วยทดลองเลย

เมื่อขยายเป็น 48 โปรไฟล์ ความชันตามขนาดประวัติแทบหายไป (1.09× เทียบ 2.0× เดิม)

หลักฐาน: `reports/cold_start_fpr_rootcause_2026-09-06.md`

### 2.2 ประชากรเล็กไม่ได้แค่แปรปรวนสูง แต่ **ลำเอียงไปทางดี**

วัดด้วยโค้ดชุดเดียวกันเป๊ะ ที่ขนาดประวัติเท่ากัน:

```
12 โปรไฟล์ -> 0.477%      48 โปรไฟล์ -> 0.802%      (ต่าง 1.68 เท่า)
```

ประชากร 12 คน "ผ่าน" เกณฑ์เกือบทุกขนาด ขณะที่ 48 คนไม่ผ่านเลย —
**ถ้าไม่ขยายประชากร เราจะสรุปว่าระบบผ่านงบทั้งที่ยังไม่ผ่าน**

### 2.3 เกณฑ์ตัดสินเดิมสรุปเกินหลักฐาน จึงเปลี่ยนเป็นสามทาง

gate เดิมเทียบ**ค่าประมาณจุด**กับงบแล้วประกาศ passed/failed ทั้งที่หน่วยอิสระมี
เพียง 12 ผู้ใช้ · ตอนนี้ตัดสินจาก **ช่วงความเชื่อมั่นระดับ cluster** เป็นสามทาง
(`passed` / `failed` / `inconclusive`) โดย inconclusive = ไม่ deploy (fail-closed)

หลักฐาน: `reports/cluster_aware_gate_2026-09-06.md` · `hybrid_experiment/gate.py`

### 2.4 ผลการวัดบนประชากร P48 (32 โปรไฟล์ validation × 5 seeds)

| ระดับ | ค่าเฉลี่ยระดับผู้ใช้ | CI (cluster) | งบ | ผล |
|---|---|---|---|---|
| challenge | 0.79 – 0.87% | [0.56, 1.18] | 1.00% | **inconclusive** |
| block | 0.005% | [0.000, 0.015] | 0.20% | passed |
| warn | 2.295% | [1.669, 3.114] | 5.00% | passed |

baseline เดิม: **3.561%** [2.565, 4.741] — เกินงบชัดเจนทุกขนาด
สถาปัตยกรรม Hybrid ลด false positive ลงราว **4 เท่า** แต่ยังพิสูจน์ไม่ได้ว่าอยู่ในงบ

หลักฐาน: `reports/p48_validation_2026-09-08.md` (freeze แล้ว)

### 2.5 การทดลองที่ให้ผล**ลบ** และถูกถอนออก

ทดลองรวม `new_subsystem` + `scope_escalation` เป็นตระกูลหลักฐานเดียว พร้อมถ่วง
น้ำหนักตามขนาดประวัติ · กวาดกริดสองรอบบน validation แล้ว **ปฏิเสธ**:

- ประโยชน์ด้าน FPR สูงสุด 0.08 pp ซึ่ง **แยกไม่ออกจากศูนย์** ใน paired test
- recall ของ `subtle_quiet_lateral` ตก **6.7 pp** อย่างมีนัย
- โค้ดถูกถอนออกจาก production แล้ว มี parity test พิสูจน์ว่าคะแนนเท่าเดิมทุกเคส

หลักฐาน: `reports/l2_subsystem_family_grid_2026-09-06.md`

---

## 3. จุดที่ขอให้ตรวจหนัก

1. **การนับ `inconclusive` เป็นไม่ผ่าน** — เป็นการตัดสินเชิงนโยบาย ไม่ใช่เชิงสถิติ
   ผู้ตรวจอาจเห็นต่างว่าค่าจุด 0.87% ที่ต่ำกว่างบควรถือว่าผ่าน
2. **ตัวเลขทั้งหมดมาจาก split `tune`** — split `test` ภายในผู้ใช้และโปรไฟล์ holdout
   ยังไม่ถูกเปิด · มีหลักฐานคร่าว ๆ (เทียบข้าม seed จึงไม่แน่นอน) ว่า tune ให้ค่า
   ต่ำกว่า holdout ราว 1.7 เท่า ซึ่งถ้าจริงจะทำให้ค่าจริงเกินงบ
3. **การแก้ pre-registration ระหว่างทาง (amendment #2)** — ตรึง `incidents = 0`
   หลังพบว่าเป็น policy floor ที่บังคับ challenge ทุก login · แก้ก่อนเปิด holdout
   และพิสูจน์ด้วย hash ว่าเปลี่ยนฟิลด์เดียว แต่ยังเป็นการแก้หลังเห็น validation
4. **การเทียบ recall กับ baseline ไม่เป็นธรรม** — baseline challenge ถี่กว่า 4 เท่า
   ตัวเลข recall ที่สูงกว่าจึงส่วนหนึ่งมาจากการยิงถี่ · เทียบที่ FPR เท่ากันทำไม่ได้
   เพราะพื้น FPR ของ baseline อยู่ที่ 1.2467% ซึ่งเกินงบอยู่แล้วเชิงโครงสร้าง
5. **การแจกแจงของประชากร P48 เป็นการประกาศ ไม่ใช่การวัด** — ช่วงค่าอ้างอิงจาก
   12 โปรไฟล์ที่วัดจากของจริงแล้วขยายให้กว้างขึ้น · ความสมจริงของการแจกแจงนี้
   เป็นข้อจำกัดที่ผู้จัดทำระบุเอง

---

## 4. สารบัญหลักฐานรอบนี้

### 4.1 รายงานการทดลอง (`hub/backend/tests/reports/`)

| ไฟล์ | เนื้อหา |
|---|---|
| `hybrid_risk_experiment_2026-09-03.md` | Round 1 — failed gate |
| `round2_statistics_2026-09-03.md` | paired bootstrap, hierarchical CI, tail calibration |
| `hybrid_risk_round2_2026-09-04.md` | Round 2 — failed gate |
| `hybrid_risk_round2b_2026-09-04.md` | Round 2b — holdout ชุดใหม่ |
| `hybrid_risk_round2c_2026-09-04.md` | Round 2c + บันทึกการแก้ข้อสรุปที่เกินหลักฐาน (B69) |
| `cold_start_fpr_rootcause_2026-09-06.md` | วินิจฉัยต้นเหตุ — ความแปรปรวนระดับผู้ใช้ |
| `cluster_aware_gate_2026-09-06.md` | cluster-aware FPR + verdict สามทาง |
| `l2_subsystem_family_grid_2026-09-06.md` | ผลลบของ L2 family — ถอนออก |
| `p48_population_and_audit_2026-09-08.md` | ประชากร P48 + ตรวจ shortcut/leakage |
| `p48_validation_2026-09-08.md` | **ผลหลักของรอบนี้ (freeze)** |

### 4.2 เอกสารกำกับวิธีวิทยา

- `docs/design/USER_POPULATION_P48_PREREG.md` — pre-registration + amendment ทั้งหมด
- `docs/design/L2_SUBSYSTEM_NOVELTY_FAMILY.md` — ออกแบบที่ถูกปฏิเสธ
- `docs/RBA_ROUND2_PROTOCOL.md` — โปรโตคอลของ Round 2

### 4.3 โค้ดที่ผลิตตัวเลข

```
ml-service/scripts/population_p48.py          ประชากร + split + roster
ml-service/scripts/audit_p48_generator.py     shortcut / leakage audit
ml-service/scripts/exp_p48_validation.py      การวัดหลัก
ml-service/scripts/exp_hybrid_gate.py         harness ของ hybrid gate
ml-service/scripts/exp_l2_family_grid.py      กริดที่ให้ผลลบ
hybrid_experiment/bootstrap.py                cluster_rate_ci + rate_verdict
hybrid_experiment/gate.py                     ตรรกะการตัดสินสามทาง
```

### 4.4 เทสที่บังคับความถูกต้องของวิธี

```
tests/test_population_p48.py         22 เทส — บังคับให้ตรงกับ pre-registration
tests/test_cluster_aware_gate.py     18 เทส — CI ระดับ cluster + verdict สามทาง
tests/test_scoring_freeze.py          4 เทส — scoring ต้องไม่ขยับระหว่างรอบ
tests/test_l2_evidence_only.py        3 เทส — L2 คืนหลักฐานเท่านั้น (B70)
tests/test_l2_legacy_mode_parity.py   1 เทส — 400 เคสสุ่ม ต่างสูงสุด < 1e-12
```

---

## 5. วิธีทำซ้ำ

```bash
python scripts/build_evidence_manifest.py --verify --manifest docs/RBA_EVIDENCE_MANIFEST_2026-09-08.md
python ml-service/scripts/population_p48.py
python ml-service/scripts/audit_p48_generator.py
python ml-service/scripts/exp_p48_validation.py
```

ข้อมูลจริง (anchor ผู้ใช้) ไม่อยู่ใน git ตามนโยบาย PII — ผู้ตรวจต้องใช้ anchor ของ
ตนเองแล้วส่งผ่าน `--users` · seed และ POP_SEED ประกาศไว้ในโค้ดและ pre-registration
