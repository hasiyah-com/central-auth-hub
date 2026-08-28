# L3 Sequence — Stability / Operational Readiness

**วันที่:** 29 ส.ค. 2026
**ขอบเขต:** restart · cold profile · model หาย/เสีย · concurrency · latency · fail-safe ·
**ยืนยันว่า L3 ไม่เปลี่ยน access decision**
**สถานะ:** ✅ ผ่านทั้งหมด — 23 tests + restart driver 6/6 · full suite 795 passed / 0 failed
**ทดสอบกับของจริงทั้งหมด** (Redis + ml-service ในคอนเทนเนอร์จริง ไม่ mock)

> การทดลอง offline (`exp_final_gate_2026-08-26.md`) ตอบว่า *"โมเดลนี้ตรวจจับได้ดีแค่ไหน"*
> เอกสารนี้ตอบคนละคำถาม: *"ระบบนี้อยู่รอดใน production ไหม"* — ซึ่งตัวเลข recall/FPR ตอบไม่ได้

---

## 0. สรุปผล

| หมวด | เกณฑ์ | ผล |
|---|---|---|
| 1. Restart | state อยู่รอด + คะแนนไม่เปลี่ยน | ✅ 6/6 (คะแนนเท่าเดิมทุกหลัก) |
| 2. Cold profile | ประวัติน้อย → เงียบ ไม่เดา | ✅ 3/3 |
| 3. Model หาย/เสีย | degrade ไม่ crash | ✅ 4/4 |
| 4. Concurrency | ไม่ race · ไม่ปนกัน | ✅ 5/5 |
| 5. Latency | p95 ต่ำกว่าครึ่งของ timeout | ✅ p95 **44ms** / budget 250ms |
| 6. Fail-safe (B21) | ml ล่ม/ช้า → login ไม่พัง | ✅ 4/4 |
| 7. **L3 ไม่เปลี่ยน access decision** | ยกได้แค่ allow→warn | ✅ **3/3 (สแกนครบทุกชุดค่า)** |

**พบปัญหาจริง 2 ข้อระหว่างทดสอบ — แก้แล้วทั้งคู่ (B62, B63)** ทั้งสองเป็นปัญหา
**เชิงปฏิบัติการ ไม่ใช่การปรับโมเดล** — ฟังก์ชันตัดสินใจ (residual 6 มิติ · W=5 · p99.9 ·
abstention tiers) ไม่ถูกแตะเลย ตัวเลขที่ freeze ไว้ยังใช้ได้

---

## 1. ปัญหาที่พบและแก้

### B62 — cache refit เฉพาะตอนข้อมูล "โต" → history หดแล้วโมเดลค้าง

```python
# ผิด: ถามทางเดียวว่า "โตพอจะ refit หรือยัง"
if cached and now - ts < TTL and len(history) < cached_n * 1.1:
    return cached_model
```

history ที่ **หด** (Redis eviction / key ถูกลบ / รีเซ็ตผู้ใช้) ผ่านเงื่อนไขนี้สบายๆ
ผลที่วัดได้: ลด history 2,000 → 400 แล้ว L3 ยังตอบ `n_history=2000`, `eligibility=challenge`

ไม่ใช่แค่คะแนนเก่า — `n_history` เป็นตัวกำหนด **eligibility** → ผู้ใช้ที่ประวัติหายไปแล้ว
ยังถูกตัดสินด้วย tier สูงเกินจริงนานถึง 1 ชั่วโมง

```python
# ถูก: เช็คสองทิศทาง
if cached and now - ts < TTL and cached_n <= n < cached_n * 1.1:
```

### B63 — fit อยู่บน login path → cache-miss storm

ยิง 20 request พร้อมกันของผู้ใช้ที่ cache ว่าง → **timeout ทุกอัน** สาเหตุสามชั้น:

| ชั้น | ปัญหา | แก้ |
|---|---|---|
| fit ซ้ำซ้อน | request N อันเห็น cache ว่างพร้อมกัน → fit ซ้ำ N ครั้ง (270ms × 20 = 5.4 วิ) | ล็อกต่อ user + double-check หลังได้ล็อก |
| อ่าน history เต็มทุกครั้ง | ทาง warm ก็ยัง `lrange -2000 -1` + parse 2,000 แถว ทั้งที่ต้องการ 4 แถว | `llen` (O(1)) + `_load_tail()` อ่านแค่ท้าย window |
| timeout ร่วมกับ ML หลัก | L3 ถ่วง login ได้ถึง 2 วิ ทั้งที่ยกได้สูงสุดแค่ warn | `l3_timeout_seconds = 0.5` แยกออกมา |

**หลักการที่ได้:** ส่วนประกอบที่เป็น *monitoring* ต้องมี timeout ของตัวเอง แยกจากส่วนที่เป็น
*ตัวตัดสิน* — ไม่มีสิทธิ์ถ่วง critical path เท่ากัน

**ข้อแลกเปลี่ยนที่ยอมรับ:** หลัง ml-service restart มีช่วง warm-up สั้นๆ ที่ L3 abstain
(เสียการเฝ้าระวัง 1–2 เหตุการณ์ ดีกว่าถ่วงทุก login)

---

## 2. Latency ที่วัดได้

**fit / score ตามขนาด history** (วัดในคอนเทนเนอร์ ml-service โดยตรง)

| history | fit | score |
|---|---|---|
| 100 | 111 ms | 1.36 ms |
| 500 | 303 ms | 1.57 ms |
| 1,000 | 154 ms | 1.44 ms |
| 2,000 | 272 ms | 1.46 ms |

**end-to-end จาก hub** (รวม HTTP + Redis + score · history 2,000 · n=30)

| ตัวชี้วัด | ค่า |
|---|---|
| p50 | **24.5 ms** |
| p95 | **44.2 ms** |
| max | 61.4 ms |
| งบ (ครึ่งหนึ่งของ `l3_timeout_seconds`) | 250 ms |

**Concurrency**

| สถานการณ์ | ผล |
|---|---|
| 20 request พร้อมกัน (user เดียว, cache ว่าง) | สำเร็จ **20/20** ใน 586 ms |
| 40 request พร้อมกัน (cache อุ่น) | ผลเหมือนกันทุกอัน (ไม่มี race) |
| 8 ผู้ใช้ต่างคน cold พร้อมกัน | รอบแรก timeout → หลัง warm-up สำเร็จ **8/8 ใน 141 ms** |
| เขียน history พร้อมกับให้คะแนน | ไม่มี exception · `n_history` ไม่เพี้ยน |

> ⚠️ ตัวเลข concurrency ขึ้นกับ CPU ของเครื่องที่รัน (เครื่องพัฒนา, ml-service 1 process)
> ใช้เป็น **ลำดับความสำคัญของขนาด** ไม่ใช่ SLA — ต้องวัดซ้ำบนเครื่อง production

---

## 3. Restart resilience (driver ฝั่ง host)

pytest รันในคอนเทนเนอร์จึง restart คอนเทนเนอร์อื่นไม่ได้ → แยกเป็น
`tests/manual_l3_restart_driver.py`

```
[1] seed history + วัดคะแนนก่อน restart
    llen=1500 n_history=1500 elig=warn fired=True raw=0.745461 tier=extreme
[2] หยุด ml-service -> L3 ต้องเงียบแบบ fail-safe
    error=l3_timeout fired=False
[3] start ml-service กลับมา (cache ในหน่วยความจำหายหมด)
[4] วัดคะแนนหลัง restart (ต้อง refit จาก Redis)
    llen=1500 n_history=1500 elig=warn fired=True raw=0.745461 tier=extreme

  [PASS] history อยู่รอดข้าม restart
  [PASS] ml-service ดับ -> L3 เงียบ ไม่ raise
  [PASS] กลับมาเองหลัง restart
  [PASS] n_history เท่าเดิม
  [PASS] คะแนนเท่าเดิมทุกหลัก
  [PASS] การตัดสินเท่าเดิม
  6/6 ผ่าน
```

`raw=0.745461` **เท่ากันทุกหลัก** ก่อน/หลัง restart — refit จาก history เดิมให้โมเดลเดิมเป๊ะ
(`random_state=42` คงที่) แปลว่า restart ไม่ทำให้พฤติกรรมการตัดสินเปลี่ยน

---

## 4. Cold profile & degradation

| สถานการณ์ | ผลที่ต้องได้ | ผล |
|---|---|---|
| ผู้ใช้ไม่มีประวัติเลย | abstain · ไม่แตะ decision ทั้ง 4 ค่า | ✅ |
| ประวัติ 99 แถว (< 100) | abstain แม้ residual สุดโต่ง | ✅ |
| ประวัติ 300 แถว (diagnostic) | ให้คะแนน+log ได้ แต่ **ห้ามเปลี่ยน decision** และ `shadow_decision=None` | ✅ |
| แถวขยะปนใน history | ข้ามเฉพาะแถวเสีย ที่เหลือใช้ได้ | ✅ |
| history เสียทั้งหมด (500 แถว) | abstain เงียบ ไม่ throw | ✅ |
| Redis ถูกล้างระหว่างใช้งาน | กลับไป abstain · `n_history=0` | ✅ |
| residual ผิดรูป (ว่าง/มิติไม่ครบ/NaN) | ปฏิเสธที่ client ไม่ยิง HTTP เลย | ✅ |

`MAX_HISTORY=2000` ทำให้ `ltrim` คุมเพดานเสมอ — **`n_history` ไม่มีทางเกิน 2,000**
แปลว่า tier `challenge` (≥2000) ไปถึงได้เฉพาะตอน buffer เต็มพอดี (ข้อสังเกตเชิงปฏิบัติการ
ที่ควรรู้ก่อนตีความ log)

---

## 5. Fail-safe (B21) — 3 ชั้น

| ชั้น | สถานการณ์ | ผล |
|---|---|---|
| client | ml-service ล่ม (พอร์ตตาย) | `l3_unreachable: *` · `fired=False` · decision ไม่ขยับทั้ง 4 ค่า |
| client | ml-service ช้า (timeout 1ms) | `l3_timeout` · ไม่ค้าง (< 1 วิ) |
| hub | Redis ไม่พร้อม (`redis=None`) | `record_residual()` ไม่ raise |
| risk_engine | L3 โยน exception ทั้งชั้น | decision ปกติ · `l3_sequence=None` |

---

## 6. 🔒 L3 ไม่เปลี่ยน access decision (เกณฑ์สำคัญที่สุด)

L3 อยู่ในสถานะ shadow — ถ้ามันเปลี่ยน `challenge`/`block` ได้ แปลว่าโมเดลที่ยังไม่ผ่าน
production replay กำลังตัดสินสิทธิ์ผู้ใช้จริง

**สแกนครบทุกชุดค่าที่เป็นไปได้** (4 eligibility × 3 tier × 2 fired × 3 score × 4 decision
= 288 กรณี):

| กฎ | ผล |
|---|---|
| ห้ามลด friction (`ACTIONS.index(out) >= ACTIONS.index(in)`) | ✅ ไม่มีกรณีใดลด |
| การเปลี่ยนที่เกิดขึ้นได้ มีเพียง | **`allow → warn`** เท่านั้น |
| `challenge` / `block` ถูกแตะ | ❌ ไม่มี |
| tier `diagnostic`/`abstain` เปลี่ยน decision | ❌ ไม่มี |
| decision นอก vocab (`would_*`, `mfa_passed`, `""`) | คืนค่าเดิม ไม่แปลงมั่ว |

**ยืนยันซ้ำด้วยของจริง:** ผู้ใช้ history 2,000 (tier สูงสุด) + residual สุดโต่ง →
`tier=extreme`, `shadow_decision=would_challenge` แต่ `apply_channel()` ยังยกได้แค่ `warn`
— `would_challenge` ถูกบันทึกไว้วิเคราะห์เท่านั้น **ไม่ enforce**

สอดคล้องกับ final gate ที่วัดได้ **L3 เปลี่ยน allow/challenge/block = 0 ครั้ง** จาก 63,230 เหตุการณ์

---

## 7. ผลการทดสอบ

```
tests/test_l3_stability.py

  cache-miss storm (20 พร้อมกัน): สำเร็จ 20/20 · timeout 0 · รวม 586ms
  cold 8 users พร้อมกัน: สำเร็จ 0/8 ใน 666ms  ->  รอบสอง (warm): สำเร็จ 8/8 ใน 141ms
  latency (n=30, history=2000): p50=24.5ms p95=44.2ms max=61.4ms mean=25.9ms
  live: tier=extreme shadow=would_challenge raw=0.743

============================= 23 passed in 18.66s ==============================
```

**Full system suite (Docker)**

```
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py --ignore=tests/test_l1_oidc.py
================= 795 passed, 53 skipped in 156.40s (0:02:36) ==================
```

(เพิ่มจาก 772 → 795 = stability suite 23 ตัว · ไม่มี regression)

---

## 8. Security check

| หัวข้อ | สถานะ |
|---|---|
| L3 ไม่ขยาย attack surface | endpoint รับแค่ `user_id` + residual 6 ตัวเลข · ยัง bind `127.0.0.1:9000` |
| L3 ไม่ลด friction | พิสูจน์ครบ 288 กรณี — ไม่มีเส้นทางใดทำให้ decision ต่ำลง |
| L3 ไม่ยกระดับเกินอำนาจ | เพดาน `warn` แข็ง · `would_challenge` เป็น log เท่านั้น |
| ล็อกไม่ทำ deadlock | ล็อกต่อ user ชั้นเดียว ไม่ซ้อน · guard lock แยกและปล่อยทันที |
| DoS ผ่าน L3 | fit ครั้งเดียวต่อคน + timeout 0.5 วิ + `MAX_HISTORY` คุมหน่วยความจำ |
| ข้อมูล | ทดสอบด้วย residual สังเคราะห์ล้วน · ไม่มี PII ในเอกสารนี้ |

---

## 9. สิ่งที่การทดสอบนี้ **ไม่ได้** ตอบ

1. **ไม่ได้วัดบน traffic จริง** — ผู้ใช้จริงมี pattern การ login ที่ต่างจาก residual สังเคราะห์
2. **ไม่ได้วัดบนเครื่อง production** — ตัวเลข concurrency/latency มาจากเครื่องพัฒนา
   (ml-service 1 process, ไม่มี worker เพิ่ม)
3. **ไม่ได้ทดสอบ Redis ล่มยาว / memory pressure จริง** — ทดสอบแค่ key หาย/ข้อมูลเสีย
4. **ไม่ได้ทดสอบ ml-service หลาย instance** — model cache เป็น in-memory ต่อ process
   ถ้าขยายเป็นหลาย replica แต่ละตัวจะ fit เอง (ผลเหมือนกันเพราะ deterministic แต่เปลือง CPU)

→ ทั้งหมดนี้เป็นเหตุผลที่ขั้นถัดไปคือ **production shadow replay** ไม่ใช่ enforcement

---

## 10. รันซ้ำได้

```bash
docker compose exec hub-backend pytest tests/test_l3_stability.py -v -s
```

```bash
py hub/backend/tests/manual_l3_restart_driver.py
```
