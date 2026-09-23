# สาธิต Shadow ในเครื่องด้วยชุดสถานการณ์ที่มี label — 2026-09-23

ชุดสถานการณ์ `tests/scenarios/hybrid_vm_scenarios.yaml` (20 สถานการณ์ · 22 เหตุการณ์) รันผ่าน
`scripts/run_vm_scenarios.py` ซึ่งเรียก `passkey._build_login_session` **ตัวที่ production เรียก** ·
L1–L4, ml-service (L3) และแถว `login_sessions` เป็นของจริง · ต่างเพียงเวกเตอร์ feature ที่ทับด้วยค่าของสถานการณ์
และการปิด `maybe_alert_ml_risk` (ห้ามส่ง Telegram/อีเมลออกนอก)

**label มาจากการสร้าง (labeled by construction) ไม่ใช่การโจมตีจริง**

## 1. สภาพแวดล้อม

| รายการ | ค่า |
|---|---|
| stack | ในเครื่อง · คอนเทนเนอร์ `hub-backend-vm` (โค้ดจาก worktree) · `APP_ENV=development` |
| โหมด | `L3_MODE=shadow_hybrid` — ผลจริงมาจาก policy/L1/L2 · baseline / hybrid / conditional เป็น**ผลจำลอง** |
| conditional params | `ambiguous_low=0.30, w_point=0.5, w_sequence=0.5, low_zone_agree=0.90` (candidate G ที่เลือกจาก calibration `fb4cca0`) |
| บัญชี | `vm-*@example.test` (11 บัญชี สร้างโดยสคริปต์) · IP `10.99.0.x` (private → ไม่มี geo lookup ออกนอก) |
| ทำซ้ำ | `--reset` ล้าง session/บัญชีทดสอบก่อนเริ่ม |

> **candidate G ไม่ผ่าน Accuracy Gate** (รายงาน `accuracy_gate_2026-09-23.md` §6) · ที่แสดงที่นี่คือผลจำลอง
> เพื่อดูพฤติกรรม ไม่ใช่ข้อเสนอให้ใช้งาน

## 2. ผล (22 เหตุการณ์ · ตรงตามคาด 19 · ข้อค้นพบ 3)

| สถานการณ์ | ตระกูล | ผลจริง | hybrid (จำลอง) | conditional (จำลอง) | คาดหวัง | ผล |
|---|---|---|---|---|---|---|
| VM-N01 | ปกติ | allow | would_allow | would_allow | allow | ตรง |
| VM-N02 | ปกติ (เวลาเลื่อน) | allow | would_allow | would_allow | allow–warn | ตรง |
| VM-N03 | ปกติ (ระบบเดิม) | allow | would_allow | would_allow | allow | ตรง |
| VM-N04 | ปกติ (หายไป 20 วัน) | allow | would_allow | would_allow | allow–warn | ตรง |
| VM-N05 | ปกติ (เปลี่ยนเบราว์เซอร์) | **would_challenge** | would_challenge | would_challenge | allow–warn | **ข้อค้นพบ 1** |
| VM-A06 | credential stuffing | would_block | would_block | would_block | ≥ challenge | ตรง |
| VM-A07 | failed spike | would_block | would_block | would_block | ≥ challenge | ตรง |
| VM-A08 | ATO หลายสัญญาณ | would_block | would_block | would_block | ≥ challenge | ตรง |
| VM-A09 | impossible travel | would_block | would_block | would_block | ≥ challenge | ตรง |
| VM-A10 | concurrent sessions | would_challenge | would_challenge | would_challenge | ≥ challenge | ตรง |
| VM-A11 | permission change | would_challenge | would_challenge | would_challenge | ≥ challenge | ตรง |
| VM-A12 | อุปกรณ์+ประเทศใหม่ | would_block | would_block | would_block | ≥ challenge | ตรง |
| VM-S13 | login velocity | **allow** | would_allow | would_allow | ≥ warn | **ข้อค้นพบ 2** |
| VM-S14 | quiet lateral | would_challenge | would_challenge | would_challenge | ≥ warn | ตรง |
| VM-S15 | subsystem lateral | would_challenge | would_challenge | would_challenge | ≥ warn | ตรง |
| VM-S16 | slow burst | would_challenge | would_challenge | would_challenge | ≥ warn | ตรง |
| VM-S17 | rare device | would_challenge | would_challenge | would_challenge | ≥ warn | ตรง |
| VM-S18 | new passkey | would_challenge | would_challenge | **would_block** | ≥ challenge | ตรง |
| VM-S19 | off-hours เล็กน้อย | **allow** | would_allow | would_allow | ≥ warn | **ข้อค้นพบ 3** |
| VM-S20 (3 ครั้ง) | campaign | would_challenge ทุกครั้ง | would_challenge | would_challenge | ≥ challenge | ตรง |

### ข้อค้นพบ

1. **VM-N05 — เปลี่ยนเบราว์เซอร์ตามปกติถูกยกเป็น challenge** · `is_new_user_agent_family=1` มี policy floor
   ระดับ challenge จึงยกโดยไม่สนคะแนน · เป็น false positive ที่อธิบายได้และสอดคล้องกับ challenge FPR
   ที่วัดได้ในงาน validation (ตระกูล `new_ua_family` จับได้ 100% ด้วย floor เดียวกัน)
2. **VM-S13 — login velocity ไม่ถูกหยิบขึ้นมาเลย** · ตรงกับ validation (recall ของตระกูลนี้ 0.28 ที่ baseline
   และ 0.08 ที่ hybrid) — เป็นจุดอ่อนที่ทราบอยู่แล้ว ไม่ใช่เรื่องใหม่
3. **VM-S19 — off-hours เล็กน้อยไม่ถูกหยิบขึ้นมา** · สัญญาณเดียวที่อ่อน ไม่ถึงเกณฑ์ใด ๆ

`conditional` ต่างจาก `hybrid` เพียงกรณีเดียว (VM-S18 ยกจาก challenge เป็น block ในช่วง high)

## 3. บั๊กที่พบเพราะสาธิตบนเส้นทางจริง (แก้แล้ว)

| อาการ | สาเหตุ | แก้ |
|---|---|---|
| แอป start ไม่ขึ้นเมื่อตั้ง `L3_CONDITIONAL_PARAMS` | validator ใน `config.py` import `risk_fusion` → `policy_gate` → `models` → `database` → `config` (วน) · เทสเดิมไม่เจอเพราะเรียก `Settings()` หลังโมดูลโหลดเสร็จ | ย้าย `ConditionalParams` ไป `app/security/conditional_params.py` (โมดูลใบ) · เทสใหม่รัน process จริง |
| `conditional_shadow` หายทั้งแถวเมื่อ policy ปฏิเสธ (VM-A06) | engine คืนค่าก่อนถึงจุดคำนวณ | คำนวณในเส้นทาง denied ด้วย (`zone = policy_denied`) · มีเทส |
| สาธิตสองรอบได้คนละผล | feature อิงประวัติ (login_count_24h, is_new_device ฯลฯ) — รอบแรกสร้างประวัติให้รอบสอง | เพิ่ม `--reset` ล้างเฉพาะบัญชี `vm-*@example.test` · มีเทสว่าไม่แตะผู้ใช้อื่น |
| L3 sequence บันทึกประวัติไม่ได้ (`localhost:6379`) | `.env` ของ host ชี้ Redis ที่ localhost · คอนเทนเนอร์สาธิตต้องใช้ `redis://redis:6379` | ส่ง `REDIS_URL` ของ compose เข้าไปตอน `docker run` |

## 3.1 วิเคราะห์ 3 เหตุการณ์ที่ไม่ตรงคาด

| รหัส | ที่คาด | ที่ได้ | อธิบาย |
|---|---|---|---|
| VM-N05 | allow–warn | **would_challenge** | `is_new_user_agent_family=1` เข้าเงื่อนไข policy floor ระดับ challenge ซึ่ง**ยกโดยไม่สนคะแนน** · เป็น false positive ที่ออกแบบไว้เช่นนั้น: ระบบเลือกฝั่งปลอดภัยเมื่อเบราว์เซอร์เปลี่ยน · ผู้ใช้แก้เองได้ด้วยการยืนยันตัวตน · สอดคล้องกับที่ตระกูล `new_ua_family` ถูกจับ 100% ในการทดลอง |
| VM-S13 | ≥ warn | **allow** | `login_velocity` เป็นตระกูลที่อ่อนที่สุดตระกูลหนึ่ง (recall 0.28 ที่ baseline · 0.08 ที่ hybrid ในการทดลอง) · สัญญาณคือ gap สั้นกับ count สูง ซึ่งผู้ใช้ปกติจำนวนมากก็มี → ตั้งเกณฑ์ให้จับได้จะดัน FPR เกินงบ · เป็นข้อจำกัดที่วัดได้ ไม่ใช่บั๊ก |
| VM-S19 | ≥ warn | **allow** | off-hours เล็กน้อย (ตี 3 เวลาไทย) มีสัญญาณเดียวและอ่อน · คะแนนรวมไม่ถึงเกณฑ์ใด · ตระกูล `subtle_mild_offhour` ได้ recall 0.65 ในการทดลอง จึงพลาดบางเคสเป็นเรื่องที่คาดได้ |

**ข้อจำกัดของหลักฐานชุดนี้**

- 22 เหตุการณ์ไม่ใช่กลุ่มตัวอย่างสำหรับวัดความแม่น — ใช้แสดงว่า**เส้นทางจริงทำงานครบ**และดูพฤติกรรมราย
  สถานการณ์ · ตัวเลขความแม่นอยู่ในรายงาน Accuracy Gate ซึ่งวัดบนหลายแสนเหตุการณ์
- label มาจากการสร้าง · ค่า feature ถูกกำหนดให้ตรงกับสถานการณ์ ไม่ได้เกิดจากพฤติกรรมจริง
- ภาพหน้าจอ Dashboard ต้องเข้าสู่ระบบด้วยบัญชีผู้ดูแลจริง (Google OAuth) ผมจึงถ่ายให้ไม่ได้ ·
  แถวทั้งหมดอยู่ใน `login_sessions` (`login_method = vm_scenario`) เปิดดูได้ที่หน้า ML/Incident
  และมีผลดิบครบใน `vm_evidence_2026-09-23.json`

## 3.2 การแสดงผล Shadow บน Dashboard (เพิ่ม 2026-09-23)

เดิมหน้า Session detail แสดงเฉพาะการตัดสินจริง คะแนน L1/L2/L3 และ SHAP · เพิ่มแผง **"ผลจำลอง (Shadow)"**
ที่แสดง baseline / hybrid / conditional พร้อมป้าย **"ไม่มีผลต่อสิทธิ์จริง"** และบรรทัดการตัดสินจริงกำกับ
(`hub/frontend/app/(console)/ml/_components/SessionDetailPanel.tsx`) · ค่าที่แสดงอ่านจาก
`risk_breakdown` ซึ่ง `risk_engine` เขียนเป็นข้อมูลอย่างเดียว ไม่มีเส้นทางใดนำไปตัดสินสิทธิ์

## 4. หลักฐาน

`tests/reports/vm_evidence_2026-09-23.json` — ต่อเหตุการณ์: `session_id`, คะแนน L1/L2/L3, `risk_score`,
ผลจริง, baseline/hybrid/conditional, เหตุผล, SHAP 5 อันดับแรก, feature ที่เปลี่ยน, เวลาในสถานการณ์
· แถวจริงอยู่ใน `login_sessions` (`login_method = vm_scenario`) จึงเปิดดูบน Security Dashboard ได้

## 5. ทำซ้ำ

```bash
docker run -d --name hub-backend-vm --network cah-net --env-file .env \
  -e APP_ENV=development -e L3_MODE=shadow_hybrid -e REDIS_URL=redis://redis:6379/0 \
  -e L3_CONDITIONAL_PARAMS='{"ambiguous_low": 0.3, "low_zone_agree": 0.9, "w_point": 0.5, "w_sequence": 0.5}' \
  -v <worktree>/hub/backend:/app -w /app cah-hub-hub-backend sleep infinity
docker exec hub-backend-vm python -m scripts.run_vm_scenarios --reset \
  --out /app/tests/reports/vm_evidence_2026-09-23.json
```
