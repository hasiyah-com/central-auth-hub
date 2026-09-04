# RBA Hybrid Risk — Round 2 Protocol (ประกาศล่วงหน้าก่อนแตะโค้ด)

> เอกสารนี้ต้องถูก **commit ก่อน** เริ่มแก้โค้ดใดๆ ของ Round 2
> เพื่อให้พิสูจน์ได้ว่า candidate / fallback / เกณฑ์ ถูกประกาศ **ก่อน** เห็นผล
> ไม่ใช่เลือกย้อนหลัง (post-hoc selection) ซึ่งเป็นเหตุผลที่ Config F
> ถูกห้ามใช้ใน Round 1 แม้จะผ่านงบ FPR ทุกระดับ

| | |
|---|---|
| ฐานของรอบนี้ | tag `rba-hybrid-round1-failed-gate-2026-09-03` (commit `db04d29`) |
| branch | `feature/hybrid-risk-round2` |
| สถานะ Round 1 | `final_round_1_failed_gate` — ไม่มี config ใดผ่าน Final Gate |
| ระบบ production | **ไม่เปลี่ยน** · L3 ยังคง shadow mode |

---

## 1. Candidate และ Fallback — ประกาศไว้ก่อน

```
candidate: Config B · gamma=1.0 · warn=0.941667 · challenge=0.989833 · block=0.9999
fallback:  current deployed configuration / shadow mode
```

**block=0.9999 ตัดสินบน validation แล้ว (2026-09-03)** — การยก block threshold จาก
Round 1 (0.998112) เป็น 0.9999 ลด validation block FPR จาก 0.179% เหลือ 0.009%
โดย recall / recall@challenge / challenge FPR **ไม่เปลี่ยนเลย** (block->challenge
ยังนับใน recall และ CHALLENGED) · เลือก 0.9999 ไม่ใช่ 1.0 เพื่อคง hard-block ไว้
สำหรับเคสที่ rule+behavior สูงเกือบเต็มพร้อมกัน · หลักฐาน:
`hub/backend/tests/reports/round2_prefreeze_2026-09-03.md`

**Config F ไม่ใช่ fallback** แม้จะผ่านงบ FPR ทุกระดับใน Round 1 เพราะ recall
ต่ำกว่ามาก (recall@challenge 0.4678 เทียบกับ B ที่ 0.7080) · ให้เก็บ F ไว้เป็น
**comparator** ในรายงานเท่านั้น ไม่ใช่ทางเลือกสำหรับ deploy

**ความหมายของ fallback ในที่นี้:** ถ้า candidate ไม่ผ่าน Final Gate อีกครั้ง
→ ไม่ deploy อะไรใหม่ · ระบบเดิมทำงานต่อ · L3 ยังคง shadow
ไม่ใช่ "ถอยไปใช้ config อื่นที่ผ่านงบ"

---

## 2. ขอบเขตของ Round 2 — ทำเฉพาะ 9 ข้อนี้

| # | งาน | หมายเหตุ |
|---|---|---|
| 1 | paired hierarchical bootstrap | ΔRecall(B−C), ΔRecall(B−D), ΔRecall(B−E), ΔChallengeFPR(B−E), ΔCampaignRecall(B−E) — สุ่มโครงสร้าง `user → seed → instance/event` เดียวกัน |
| 2 | hierarchical campaign CI | แทน Wilson ซึ่งสมมติแคมเปญเป็นอิสระ |
| 3 | tail calibration | benign percentile exceedance · FPR ที่ p95/p99/p99.9 · KS/PIT uniformity บน normal · เทียบ validation vs holdout |
| 4 | common FPR 1.5% | จุดเทียบที่สูงกว่า legacy floor (1.2467%) เพื่อให้เทียบกับระบบเดิมได้จริง — กวาดบน validation |
| 5 | rename metric field | `l3_effective_unique` → `within_config_l3_counterfactual_unique` |
| 6 | ปรับ block threshold ของ Config B | **บน validation เท่านั้น** ห้ามดูตัวเลข holdout ประกอบ |
| 7 | ประกาศ candidate / fallback ล่วงหน้า | เอกสารนี้ |
| 8 | holdout seeds ชุดใหม่ | `[101, 102, 103, 104, 105]` — ไม่เคยเปิด |
| 9 | full pytest + operational latency | latency ต้องวัดแบบ end-to-end รวม I/O ไม่ใช่เฉพาะเส้นทางคำนวณ |

**ห้ามทำใน Round 2:** เปลี่ยน fusion logic, เพิ่ม/ลด layer, เปลี่ยนสมมติฐานของ L3
งานเหล่านั้นเป็นของ Round 3

งานเสริมที่อนุญาต (ไม่กระทบผล): เปลี่ยนชื่อสคริปต์ live-stack 9 ไฟล์ในโฟลเดอร์
`tests/` จาก `test_*` เป็น `manual_*_driver.py` ตามแบบแผนที่มีอยู่ เพื่อให้
`pytest .` แบบไม่กรองทำงานได้

---

## 3. งบ FPR — ไม่เปลี่ยนจาก Round 1

| ระดับ | งบ |
|---|---|
| warn FPR | ≤ 5.0% |
| challenge FPR | ≤ 1.0% |
| block FPR | ≤ 0.2% |

**ห้ามขยับงบหลังเห็นผล** ถ้า candidate ทำไม่ได้ ต้องรายงานว่าทำไม่ได้
พร้อม `attainable_floor` ไม่ใช่เขียนงบใหม่ให้ผลดูผ่าน

---

## 4. ลำดับที่บังคับ

```
1. commit เอกสารนี้ (ก่อนแตะโค้ด)
2. แก้โค้ดตามขอบเขต §2 ข้อ 1-5
3. parity gate ต้องผ่านครบทุกกลุ่ม
4. audit shortcut บนชุดพัฒนา (ห้ามแตะ holdout ใหม่)
5. prepare + tune บน validation -> ปรับ block threshold ของ B
6. freeze (บันทึก candidate=B, fallback=shadow, hash โค้ด+split)
7. full pytest + บันทึก image/commit
8. final -- เปิด HOLDOUT_SEEDS [101-105] ครั้งเดียว
9. รายงาน + commit + tag
```

**holdout ของ Round 1** (seeds 42-46 ส่วน `test` / `final_attacks`) **ถูกเปิดแล้ว**
ห้ามใช้เป็น final holdout อีก · ใช้ได้เฉพาะเป็นข้อมูลอ้างอิงย้อนหลัง

---

## 5. Round 3 — แยกออกไปต่างหาก

**สมมติฐาน:** conditional L3 fusion — ให้ L3 มีผลเฉพาะเมื่อ L1/L2 อยู่ใน
uncertainty band แทนการดันคะแนนทุกเหตุการณ์

เป็นการ **เปลี่ยนสมมติฐานและ fusion logic** จึงห้ามปนกับ Round 2 ที่แก้เพียง
block threshold · ต้องใช้ validation ใหม่ และ **holdout seeds ชุดที่สาม
`[201, 202, 203, 204, 205]`**

```
Round 1  Hybrid ทุกแบบ            -> failed gate
Round 2  ทำ Config B ให้ผ่าน gate -> baseline ใหม่ที่เสถียร
Round 3  Conditional L3 fusion     -> IF ช่วยเฉพาะ uncertainty band ได้ไหม
```

ห้ามใช้ `[101-105]` ซ้ำหลัง Round 2 เปิดแล้ว

---

## 6. เงื่อนไขการผ่านของ Round 2

Round 2 ถือว่า **สำเร็จ** เมื่อ:

1. candidate (Config B ที่ปรับ block threshold แล้ว) ผ่านงบ FPR **ครบทั้งสามระดับ**
   บน holdout ชุดใหม่
2. parity gate ผ่านครบ
3. shortcut audit ไม่พบฟีเจอร์เข้าเกณฑ์ ทั้งชุดพัฒนาและ holdout
4. leakage เป็นศูนย์
5. full pytest ผ่าน พร้อมบันทึก command / image / commit

ถ้าข้อใดไม่ผ่าน → รายงานเป็น `final_round_2_failed_gate` และ **ไม่ deploy**
ตาม fallback ที่ประกาศไว้

---

## 7. ผลลัพธ์ (ปิดรอบ 2026-09-04)

**สถานะ: `final_round_2_failed_gate`** — Config B แก้ block สำเร็จ (0.25% → 0.04%)
แต่ไม่ผ่านที่ **warn FPR 5.26% > 5.0%** บน holdout `[101-105]` (distribution shift ที่
ขนาด 500/1000) → ไม่มี config ใหม่พร้อม deploy · fallback = shadow / current

- รายงานเต็ม: `hub/backend/tests/reports/hybrid_risk_round2_2026-09-04.md`
- ⚠️ provenance: holdout `[101-105]` ถูกเปิดหลายครั้งระหว่าง optimize (B68) → ขึ้นบัญชี
  spent ใน `holdout_ledger.json` · Round 2b (ถ้ามี) ต้องใช้ holdout ชุดใหม่ (ไม่ใช่
  101-105 หรือ 201-205 ที่สงวนให้ Round 3)
- paired bootstrap ยืนยัน B > C/D/E ด้าน recall เสถียร (sign 1.0, CI ไม่คร่อม 0) →
  L3 คงไว้ที่ shadow · ข้อสรุปหลักของ Round 1 ยังยืน
