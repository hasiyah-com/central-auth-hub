# Round 2 — สถานะก่อน Freeze (2026-09-03)

> **หยุดให้ตรวจก่อน freeze** ตามที่สั่ง · ยังไม่เปิด holdout `[101-105]` · ยังไม่ freeze
> · ยังไม่ commit โค้ด wiring (รอการตัดสิน candidate)

## 1. Wiring เข้า `cmd_final` — เสร็จ (โค้ด, ยังไม่รัน)

| เครื่องมือ | เดิม (Round 1) | ใหม่ (wired) |
|---|---|---|
| เทียบ config | unpaired CI อ้างว่า "CI ไม่ทับ = ต่าง" | **paired hierarchical bootstrap** `results[k]['paired_vs_deployed']` (ΔRecall/ΔRecall@ch/ΔChallengeFPR/ΔCampaignRecall + sign_agreement) · unpaired เก็บในชื่อ `descriptive_unpaired_ci` (บรรยายเท่านั้น) |
| campaign L3-only | Wilson (สมมติอิสระ) | **hierarchical_proportion** `campaign_l3_only_hierarchical_ci` (มี Wilson fallback กันขอบบน 0 หลอก) |
| calibration | **ECE** (ใช้ผิดบริบท) เป็น metric | **tail calibration** `tail_calibration_deployed` (benign_exceedance + PIT/KS, validation->holdout) · ECE เหลือเป็น `ece_raw_not_a_verdict` พร้อม caveat |
| gate | annotate มือหลังรัน | `_final_gate()` สร้างอัตโนมัติ + `verdict` ห้ามเลือก post-hoc |
| holdout seeds | ใช้ seed เดียวกับ tune | freeze รับ `--holdout-seeds` (ค่าเริ่มต้น `[101-105]`) · **freeze ปฏิเสธถ้า holdout seeds ทับ tune seeds** |

- parity gate หลัง wiring: **ผ่าน 6/6** (ไม่กระทบ scoring path)
- เทส host: **22 passed** · container skip สะอาด
- freeze เก็บ `deployed_validation_normal_score_quantiles` (คะแนน normal ของ deployed
  config บน validation-tuning) ไว้เป็น reference ของ tail calibration — ไม่ต้องเปิด
  validation ซ้ำตอน final

## 2. งานที่ 6 — block threshold ของ Config B บน validation

วัดบน validation-tuning (cells 42-46) เท่านั้น · ตรึง warn/challenge ของ B จาก
Round 1 (`warn=0.941667`, `challenge=0.989833`, gamma=1.0) · กวาดเฉพาะ block

| block threshold | block FPR | challenge FPR | recall | recall@challenge |
|---|---|---|---|---|
| **0.998112** (Round 1) | **0.00179** | 0.00780 | 0.89611 | 0.72515 |
| 0.99900 | 0.00113 | 0.00780 | 0.89611 | 0.72515 |
| 0.99950 | 0.00088 | 0.00780 | 0.89611 | 0.72515 |
| 0.99970 | 0.00050 | 0.00780 | 0.89611 | 0.72515 |
| 0.99990 | 0.00009 | 0.00780 | 0.89611 | 0.72515 |
| 0.99995 | 0.00005 | 0.00780 | 0.89611 | 0.72515 |
| 1.00000 | 0.00000 | 0.00780 | 0.89611 | 0.72515 |

**ข้อค้นพบสำคัญ:** recall / recall@challenge / challenge FPR **นิ่งสนิททุกค่า** ขณะที่
block FPR ลดลงจนถึง 0

**กลไก:** การยก block threshold ย้ายเหตุการณ์จาก block -> challenge เท่านั้น ·
attack ที่เคยถูก block ยังถูก surface (นับใน recall) และยังอยู่ระดับ challenge
(นับใน recall@challenge และ challenge FPR ซึ่งรวม block อยู่แล้ว) · normal ที่เคยถูก
block กลายเป็น challenge -> block FPR ลด แต่ challenge FPR ไม่ขยับ

-> **gate failure ข้อเดียวของ B ใน Round 1 (block FPR 0.25% > 0.2% บน holdout)
แก้ได้ที่ต้นทุน recall = 0** โดยยก block threshold

per-size ที่ block=1.0: block FPR = 0 ทุกขนาด (50/100/500/1000/5000)

## 3. ข้อเสนอ candidate ของ Round 2 (รออนุมัติก่อน freeze)

```
candidate: Config B · gamma=1.0 · warn=0.941667 · challenge=0.989833 · block=0.9999
fallback:  shadow / current deployment (ไม่ deploy อะไรใหม่ถ้า candidate ไม่ผ่าน)
```

**ทำไมเสนอ block=0.9999 ไม่ใช่ 1.0:**
- block=0.9999 -> validation block FPR 0.009% (margin ~22 เท่าใต้งบ 0.2%) · แม้ holdout
  จะ inflate แบบ Round 1 (~1.8 เท่า) ก็ยังราว 0.016% ใต้งบมาก
- ยัง**คงการ hard-block ไว้** สำหรับกรณีที่คะแนน >= 0.9999 = ทั้ง rule และ behavior
  สูงเกือบเต็มพร้อมกัน (สอง layer อิสระยืนยันตรงกัน) ซึ่งเป็นเคสที่ควร block จริง
- block=1.0 จะ**ปิดการ block ทั้งหมด** ของ deployed config ซึ่งเปลี่ยน security posture
  โดยไม่จำเป็น

**คาดการณ์บน holdout `[101-105]`** (ยังไม่เปิด — คาดจากโครงสร้าง ไม่ใช่ผลจริง):
- warn / challenge / recall ของ B **ไม่เปลี่ยน**จาก Round 1 เพราะ block threshold
  ไม่กระทบชั้นเหล่านั้น -> คาดว่า warn ~4%, challenge ~0.9%, recall ~0.90 (ผ่านงบ)
- block FPR คาดว่า < 0.02% (ผ่านงบ 0.2% ด้วย margin กว้าง)

## 4. สิ่งที่ยังไม่ได้ทำ (รออนุมัติ)

1. **commit โค้ด wiring + งานที่ 1-6** (ผมยังไม่ commit — รอตัดสิน candidate)
2. `freeze --deploy-config B --fallback "shadow" --holdout-seeds 101 102 103 104 105`
   ด้วย B block threshold ที่อนุมัติ
3. `final` เปิด `[101-105]` ครั้งเดียว + operational latency (end-to-end)
4. full pytest ในคอนเทนเนอร์ + บันทึก image/commit

## 5. จุดที่ต้องการการตัดสินก่อนไปต่อ

- **ยืนยัน block threshold ของ B**: `0.9999` (แนะนำ · คง block ไว้) หรือ `1.0` (ปิด block)
  หรือค่าอื่น
- ก่อน freeze ต้องกำหนด B's block threshold เป็นค่าเดียว (ประกาศล่วงหน้า) — การเลือก
  จากผล holdout ทีหลังคือ post-hoc ซึ่งห้าม
