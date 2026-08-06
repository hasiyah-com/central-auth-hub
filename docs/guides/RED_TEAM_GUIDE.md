# Red-Team Guide — ทดสอบระบบด้วยการโจมตีจริง

> **เป้าหมาย:** สร้าง attack session **จริง** (ground truth 100%) เพื่อยืนยันว่า
> simulated attack ที่ใช้วัด recall นั้นสมจริงหรือไม่
>
> **ใช้เวลา:** ~1–2 ชั่วโมง · **ได้:** 10–20 เคส · **ปิดช่องโหว่:** methodology validity

---

## 1. ทำไมต้องทำ

ตอนนี้ recall ทั้งหมดมาจาก **simulated attack** (`build_attack_set.py`)
→ กรรมการถามได้ว่า *"แล้วรู้ได้ยังไงว่า attack ที่จำลองสมจริง?"*

**Red-team ตอบคำถามนี้** — โจมตีจริง แล้วเทียบว่าคะแนนที่ระบบให้ **ใกล้เคียงกับ
simulated ระดับเดียวกันหรือไม่**

| | Simulated | Red-team |
|---|---|---|
| จำนวน | 600 เคส | 10–20 เคส |
| Label ถูกต้อง | 100% (by construction) | **100% (ทำเอง)** |
| สมจริง | ต้องพิสูจน์ | **จริง 100%** |
| ใช้ทำอะไร | วัด recall หลัก | **ยืนยันว่า simulated เชื่อถือได้** |

> 💡 n น้อยไม่เป็นไร — red-team ไม่ได้ใช้วัด recall แต่ใช้ **validate** simulated

---

## 2. เตรียมตัว (5 นาที)

### สิ่งที่ต้องมี
| อุปกรณ์/บริการ | ใช้ทำอะไร | ทางเลือกฟรี |
|---|---|---|
| **VPN** | เปลี่ยนประเทศ | Proton VPN (ฟรี), Windscribe (10GB/เดือน), Cloudflare WARP |
| **อุปกรณ์ที่ 2** | เปลี่ยน device fingerprint | มือถือ / แท็บเล็ต / เครื่องเพื่อน |
| **Browser อื่น** | เปลี่ยน UA family | Firefox / Edge / Safari (ถ้าปกติใช้ Chrome) |

### ⚠️ เงื่อนไขสำคัญ — ต้องได้ geo_country จริง
GeoIP resolve ได้เฉพาะ **public IP** เท่านั้น — ถ้าเข้าผ่าน `localhost:8000`
จะได้ `geo_country = NULL` → สัญญาณภูมิศาสตร์หายหมด

**ตรวจก่อนเริ่ม:**
```bash
# ต้องมีไฟล์ GeoIP
docker compose exec hub-backend ls -la data/GeoLite2-Country.mmdb
```
- ✅ **ถ้ามีไฟล์ + เข้าผ่าน public URL/ngrok** → ได้ประเทศจริง (ดีที่สุด)
- ⚠️ **ถ้าเทสบน localhost** → geo เป็น NULL แต่ยังทดสอบ **device / เวลา / velocity** ได้
  (ระบุใน note ว่า `geo=null` เพื่อความซื่อสัตย์)

### ⚠️ ตั้งค่าก่อนเทส (สำคัญ)
```bash
# ปิด shadow mode ชั่วคราวเพื่อดู decision จริง (block/challenge)
# หรือปล่อยไว้ก็ได้ — จะเห็นเป็น would_block / would_challenge แทน
docker compose exec hub-backend env | grep ML_SHADOW_MODE
```

> 🔒 **ทำกับบัญชีตัวเองเท่านั้น** — ห้ามทดสอบกับบัญชีคนอื่นโดยไม่ได้รับอนุญาต

---

## 3. สถานการณ์ที่ต้องทำ (ตาม attacker model 4 ระดับ)

> ทำอย่างน้อย **2–3 ครั้งต่อระดับ** → รวม 8–12 เคส

### 🔴 A. `very_naive` — ไม่รู้อะไรเลย
> ผู้โจมตีได้แค่รหัสผ่านจาก data leak · IP/อุปกรณ์สุ่ม

**ทำยังไง:**
1. เปิด **VPN ประเทศไกล ๆ** (สหรัฐฯ / รัสเซีย / บราซิล)
2. ใช้ **อุปกรณ์อื่น** (มือถือ) + **browser ที่ไม่เคยใช้**
3. login **ตอนตี 2–4** (นอกเวลาปกติ)

**คาดหวัง:** score ≈ 1.0 · decision = `block`

---

### 🟠 B. `naive` — ใช้ browser ยอดนิยม
> รู้แค่รหัสผ่าน แต่ใช้ Chrome/Windows ที่คนส่วนใหญ่ใช้

**ทำยังไง:**
1. เปิด **VPN ต่างประเทศ**
2. ใช้ **Chrome บน Windows** (เหมือนที่คนทั่วไปใช้ แต่คนละเครื่องกับปกติ)
3. login **เวลาปกติ** (บ่าย/เย็น)

**คาดหวัง:** score ≈ 1.0 · decision = `block`

---

### 🟡 C. `vpn` — รู้ว่าเหยื่ออยู่ไทย
> ใช้ VPN exit ในไทยเพื่อลบสัญญาณภูมิศาสตร์

**ทำยังไง:**
1. เปิด **VPN ที่ออกในไทย** (หรือใช้ **มือถือ 4G/5G** — คนละ IP แต่ยังอยู่ไทย)
2. ใช้ **อุปกรณ์อื่น** (มือถือ/แท็บเล็ต)
3. login **เวลาปกติ**

**คาดหวัง:** score ≈ 0.9 · decision = `block` / `challenge`
→ ทดสอบว่า **ระบบจับได้ด้วย device แม้ geo ปกติ** (defense in depth)

---

### 🟢 D. `targeted` — เลียนแบบเหยื่อเกือบสมบูรณ์
> รู้ทั้งประเทศ อุปกรณ์ และเวลาที่เหยื่อใช้

**ทำยังไง:**
1. **ไม่ใช้ VPN** (อยู่ไทย เหมือนปกติ)
2. ใช้ **เครื่องเดิม browser เดิม** ที่เคย login
3. login **เวลาปกติ** ที่เคยใช้ (เช่น 9 โมง)
4. ต่างแค่ **network อื่น** (สลับ WiFi ↔ มือถือ) หรือเวลาคลาดไป 1–2 ชม.

**คาดหวัง:** score ต่ำ (~0.3) · decision = `allow` ⚠️

> 💡 **นี่คือเคสที่สำคัญที่สุด** — ถ้าระบบปล่อยผ่าน = ยืนยันข้อจำกัดเชิงทฤษฎีของ RBA
> (ตรงกับ simulated ที่ได้ recall 8.7–30%) → **เป็นผลลัพธ์ที่ถูกต้อง ไม่ใช่ความล้มเหลว**
> และเป็นเหตุผลว่าทำไมต้องมี Passkey

---

## 4. ขั้นตอนบันทึกผล

### 4.1 หา session ที่เพิ่งทำ
```bash
docker compose exec hub-backend python -m scripts.redteam_report list --email your@email.com
```
```
session_id                            เวลา (UTC)        ประเทศ    score  decision
7ac91be8-4433-44c0-8a38-cd45a848a060  2026-07-25 14:33   US       0.950  would_block
```

### 4.2 mark เป็น red-team
```bash
docker compose exec hub-backend python -m scripts.redteam_report mark \
    7ac91be8-4433-44c0-8a38-cd45a848a060 \
    --model very_naive \
    --note "ProtonVPN US, iPhone Safari, ตี 3"
```

**`--model` ต้องตรงกับสถานการณ์ที่ทำ:** `very_naive` / `naive` / `vpn` / `targeted`

> **note ควรใส่:** VPN อะไร/ประเทศไหน · อุปกรณ์ · browser · เวลา · `geo=null` ถ้าเทส localhost

### 4.3 ดูรายงานเทียบ simulated
```bash
docker compose exec hub-backend python -m scripts.redteam_report report
```

### 4.4 แก้ผิด
```bash
docker compose exec hub-backend python -m scripts.redteam_report unmark <session_id>
```

---

## 5. อ่านผลรายงาน

```
--- เทียบกับ simulated (attacker modeling) ---
model         n  real score  sim score    diff  real recall  sim recall
------------------------------------------------------------------------------
very_naive    3       0.980      1.000  -0.020       100.0%      100.0%
vpn           3       0.910      0.932  -0.022       100.0%      100.0%
targeted      3       0.310      0.298  +0.012         0.0%        8.7%

--- สรุป: simulated attack สมจริงแค่ไหน ---
  ค่าต่างเฉลี่ย |real − sim| = 0.018  (มากสุด 0.022)
  ✅ คะแนนจริงใกล้เคียง simulated มาก → attacker modeling น่าเชื่อถือ
```

### เกณฑ์ตัดสิน
| ค่าต่างสูงสุด | ความหมาย | ต้องทำอะไร |
|---|---|---|
| **≤ 0.15** | ✅ simulated น่าเชื่อถือ | เขียนในเล่มได้เต็มปาก |
| 0.15–0.30 | 🟡 ใกล้เคียงพอใช้ | ระบุ gap เป็นข้อจำกัด |
| > 0.30 | ⚠️ ต่างมาก | ทบทวน `_apply_attacker()` ใน `build_attack_set.py` |

---

## 6. เขียนลงเล่มยังไง

> "เพื่อตรวจสอบความสมจริงของชุดข้อมูลการโจมตีที่สังเคราะห์ขึ้น ผู้วิจัยได้ดำเนินการ
> ทดสอบเจาะระบบด้วยตนเอง (red-team) จำนวน N เคส ครอบคลุมผู้โจมตีทั้ง 4 ระดับ โดยใช้
> VPN เพื่อจำลองการเข้าถึงจากต่างประเทศ ใช้อุปกรณ์และเบราว์เซอร์ที่แตกต่างจากปกติ และ
> เข้าสู่ระบบในช่วงเวลาที่ผิดปกติ ทั้งนี้ดำเนินการกับบัญชีของผู้วิจัยเองเท่านั้น
>
> ผลการเปรียบเทียบพบว่าคะแนนความเสี่ยงจากการโจมตีจริงมีค่าใกล้เคียงกับการโจมตีที่
> สังเคราะห์ขึ้นในระดับเดียวกัน (ค่าต่างเฉลี่ย X) ซึ่งสนับสนุนว่าวิธีการจำลองผู้โจมตี
> (attacker modeling) ที่ใช้ในการประเมิน recall มีความสมเหตุสมผล"

---

## 7. ⚠️ ข้อควรระวัง

| ประเด็น | คำอธิบาย |
|---|---|
| **ทำกับบัญชีตัวเองเท่านั้น** | ห้ามทดสอบบัญชีผู้อื่นโดยไม่ได้รับอนุญาต (ผิดกฎหมาย + จริยธรรม) |
| **session ถูกบันทึกแม้โดน block** | ระบบสร้าง `LoginSession` ก่อนตัดสิน block → เก็บคะแนนได้ครบทุกเคส |
| **อย่าลืม unmark ของทดสอบ** | session ที่ mark จะกลายเป็น `is_account_takeover=True` และเข้า training data |
| **VPN บางตัวถูก blacklist** | ถ้า IP อยู่ใน ipsum feed จะได้ `is_attack_ip=1` → score สูงกว่าปกติ (ระบุใน note) |
| **n น้อยเป็นเรื่องปกติ** | red-team ใช้ validate ไม่ใช่วัด recall — 10–20 เคสเพียงพอ |

---

## 8. Checklist

```
[ ] ตรวจ GeoLite2-Country.mmdb มีอยู่
[ ] เตรียม VPN + อุปกรณ์ที่ 2 + browser อื่น
[ ] very_naive  × 3  (VPN ไกล + เครื่องใหม่ + ตี 3)
[ ] naive       × 3  (VPN ไกล + Chrome/Windows + เวลาปกติ)
[ ] vpn         × 3  (IP ไทย/4G + เครื่องอื่น + เวลาปกติ)
[ ] targeted    × 3  (เครื่องเดิม + เวลาเดิม + network อื่น)
[ ] mark ทุกเคสด้วย --model + --note
[ ] รัน report → บันทึกผลลง tests/reports/redteam_<date>.md
[ ] เทียบกับ attack_set_eval — ระบุ gap ในเล่ม
```

---

## อ้างอิง
- Attacker model 4 ระดับ: Wiefling et al. (2023) ACM TOPS 26(1) — ดู `docs/references.md` [1]
- Simulated baseline: `tests/reports/attack_set_eval_2026-07-22.md`
- Script: `hub/backend/scripts/redteam_report.py`
