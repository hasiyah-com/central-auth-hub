# Attack-Set Evaluation — วัด Recall ด้วย Attacker Modeling

**วันที่:** 2026-07-22
**สคริปต์:** `scripts/build_attack_set.py` → `scripts/evaluate_attack_set.py`
**อ้างอิงวิธีการ:** Wiefling et al. (2023) ACM TOPS 26(1) — ดู `docs/references.md` [1]
**เงื่อนไข:** รันหลังแก้ data leakage + retrain (ดู `feature_leakage_fix_2026-07-22.md`)

---

## 1. ปัญหาที่แก้

ระบบไม่มี **attack label จริง** (`is_account_takeover = 0` ทุกแถว) → วัด recall ไม่ได้
เป็นข้อจำกัดร่วมของงานวิจัย RBA (มีแต่บริษัทใหญ่ที่มีทีม security ยืนยันเคส ATO)

**วิธีแก้:** Attacker Modeling — จำลองการโจมตีตามระดับความรู้ของผู้โจมตี
แล้วกำหนด `label = 1` (**labeled by construction** — รู้แน่นอนเพราะเราสร้างมันขึ้นมา)

### หลักการสำคัญ: สร้างจาก session จริง ไม่ใช่สุ่มทั้งแถว
```
session จริงของ user A (TH, Chrome, 9 โมง, เครื่องเดิม)
        ↓ แปลงเฉพาะ feature ที่สะท้อน "ผู้โจมตีไม่ใช่เจ้าของบัญชี"
attack version (ประเทศใหม่, เครื่องใหม่, เวลาผิด, ...)
```
feature อื่น (สิทธิ์ · passkey เดิม · scope) **คงค่าจริงของเหยื่อไว้** เพราะผู้โจมตี
เข้าบัญชีของเหยื่อจริง (MITRE T1078 Valid Accounts) จึงสืบทอด context ของเหยื่อ

> 🔑 **จุดสำคัญ:** ตอนวัดผลส่ง `user_id` ของเหยื่อจริงเข้า risk engine ด้วย
> เพื่อให้ชั้น Behavior Profiling เทียบกับโปรไฟล์จริงของผู้ใช้คนนั้น
> (ถ้าใช้ user สมมติจะได้ cold-start score = ไม่สมจริง)

---

## 2. Attacker Model 4 ระดับ

| ระดับ | ผู้โจมตีรู้อะไร | MITRE | feature ที่แปลง |
|---|---|---|---|
| **very_naive** | รหัสผ่านอย่างเดียว · IP/UA สุ่ม | T1110.004 | ประเทศใหม่ · เครื่องใหม่ · UA family ใหม่ · เวลาสุ่ม · impossible travel 0.90–1.0 |
| **naive** | + ใช้ UA ยอดนิยม (Chrome/Windows) | T1110.004 | เหมือนบน แต่ `is_new_ua_family = 0` (UA ยอดนิยมมักตรงตระกูล) |
| **vpn** | + รู้ประเทศเหยื่อ → ใช้ VPN ในประเทศ | T1078 | `is_thailand = 1` · `is_new_country = 0` · impossible travel = 0 · ยังใช้เครื่องตัวเอง |
| **targeted** | + รู้อุปกรณ์/เวลาที่เหยื่อใช้ | T1078 | เลียนแบบเกือบสมบูรณ์ — เหลือแค่ session ซ้อน · failed logins เล็กน้อย · เวลาคลาด 0.5–3 ชม. |

**สัญญาณร่วมทุกระดับ:**
- `failed_logins_24h` เพิ่มตามระดับ (very_naive 2–6 → targeted 0–1) — credential stuffing นำหน้า
- `concurrent_session_count` +0–2 — เหยื่ออาจยัง login ค้าง
- `new_passkey_recently_added` ตามความน่าจะเป็น (15–40%) — ผู้โจมตีลงทะเบียน passkey ตัวเองเพื่อ persistence

> ⚠️ **ระดับที่ 5 (very_targeted) ทำไม่ได้** — Wiefling นิยามว่าใช้ค่าจริงจาก account
> takeover ที่เกิดขึ้นจริง ซึ่งงานนี้ไม่มี → ต้องระบุเป็นข้อจำกัดในเล่ม

---

## 3. ชุดข้อมูลที่สร้าง

| ไฟล์ | เนื้อหา |
|---|---|
| `attack_set.csv` | 600 แถว (150 × 4 models) · `label = 1` |
| `eval_set.csv` | **1,300 แถว** = normal จริง 700 + attack 600 (shuffle แล้ว) |

**Reproducible:** `--seed 42` (default) → รันซ้ำได้ผลเดิมทุกครั้ง

```bash
docker compose exec hub-backend python -m scripts.build_attack_set
docker compose exec hub-backend python -m scripts.evaluate_attack_set
```

---

## 4. ผลการประเมิน ⭐

**Threshold:** block = 0.85 · challenge = 0.70 · warn = 0.50
**เกณฑ์ "ตรวจจับได้":** decision ∈ {block, challenge} (สร้าง friction ให้ผู้โจมตี)

### Normal (real traffic)
| Metric | ค่า |
|---|---|
| n | 700 |
| mean risk score | 0.387 |
| **FPR (flagged)** | **98/700 = 14.0%** |

### Recall แยกตาม attacker model
| Attacker model | n | detected | **Recall** | mean score |
|---|---|---|---|---|
| **very_naive** | 150 | 150 | **100.0%** | 1.000 |
| **naive** | 150 | 150 | **100.0%** | 1.000 |
| **vpn** | 150 | 150 | **100.0%** | 0.932 |
| **targeted** | 150 | 13 | **8.7%** | 0.298 |

```
very_naive  ████████████████████████████ 100.0%
naive       ████████████████████████████ 100.0%
vpn         ████████████████████████████ 100.0%
targeted    ██·························· 8.7%
```

✅ **Sanity check ผ่าน:** recall ลดลงตามระดับความรู้ของผู้โจมตี — ตรงกับที่งานวิจัยคาดการณ์

---

## 5. การวิเคราะห์ผล (สำคัญสำหรับเล่ม)

### 5.1 ระบบจับ naive/VPN attacker ได้ 100%
ผู้โจมตีที่ไม่สืบข้อมูลเหยื่อ (หรือรู้แค่ประเทศ) ทิ้งสัญญาณชัดเจน:
ประเทศใหม่ · อุปกรณ์ใหม่ · impossible travel → rule layer จับได้ทันที

**น่าสนใจ:** แม้ VPN attacker จะลบสัญญาณภูมิศาสตร์ทิ้งหมด (ใช้ VPN ในไทย ไม่มี
impossible travel) ระบบยังจับได้ 100% เพราะ **`is_new_device` + behavior profiling**
→ แสดงว่าการมีหลายชั้น (defense in depth) ทำงานจริง ไม่ได้พึ่ง geo อย่างเดียว

### 5.2 targeted attacker จับได้เพียง 8.7% — เป็นเรื่องปกติและต้องรายงานตามจริง
ผู้โจมตีที่รู้ทั้งประเทศ + อุปกรณ์ + เวลาของเหยื่อ **แทบไม่ต่างจากผู้ใช้จริง**
(mean score 0.298 vs normal 0.387 — ต่ำกว่า normal เสียด้วยซ้ำ)

**นี่คือข้อจำกัดเชิงทฤษฎีของ RBA ทุกระบบ** รวมถึงของ Google/LinkedIn —
ถ้าผู้โจมตีเลียนแบบ context ได้สมบูรณ์ ก็ไม่มี "ความผิดปกติ" ให้ตรวจจับ

> 📌 **นี่คือเหตุผลที่ระบบต้องมี Passkey (phishing-resistant)** — RBA จับ targeted
> attacker ไม่ได้ แต่ Passkey ทำให้ผู้โจมตี**เข้าไม่ได้ตั้งแต่แรก**แม้รู้รหัสผ่าน
> → RBA กับ Passkey เสริมกัน ไม่ใช่แทนกัน

### 5.3 ตีความเชิงความปลอดภัย
| Attacker | โอกาสสำเร็จ | มาตรการที่รับมือได้ |
|---|---|---|
| very_naive / naive | ต่ำมาก (ถูกจับ 100%) | RBA |
| vpn | ต่ำมาก (ถูกจับ 100%) | RBA (device + behavior) |
| **targeted** | **สูง (รอด 91%)** | **Passkey / TOTP** (ไม่ใช่ RBA) |

---

## 6. ข้อจำกัด (ต้องเขียนในเล่ม)

| ข้อจำกัด | รายละเอียด |
|---|---|
| ⚠️ **Simulated ไม่ใช่ attack จริง** | recall มาจาก attacker model ที่จำลองขึ้น ต้องระบุเสมอ |
| ⚠️ **ไม่มี very_targeted** | ระดับที่ 5 ของ Wiefling ต้องใช้ข้อมูล ATO จริง |
| ⚠️ **rule ที่พึ่ง DB ถูกข้าม** | ตอน score ส่ง `ip=None`, `geo_country=None` → `_check_impossible_travel` / `_check_multi_account_ip` ไม่ทำงาน (แต่ค่าอยู่ใน feature vector แล้ว) → recall จริงอาจสูงกว่าเล็กน้อย |
| ⚠️ **FPR 14% ยังสูง** | เป้าหมายที่ดีคือ < 10% — สาเหตุหลักคือ test traffic ปนใน dataset |

---

## 7. สรุปสำหรับ thesis

> "เนื่องจากระบบไม่มีชุดข้อมูลการโจมตีที่มีป้ายกำกับจริง งานวิจัยนี้จึงประเมินความสามารถ
> ในการตรวจจับด้วยวิธี **attacker modeling** ตามแนวทางของ Wiefling et al. [1] โดยจำลอง
> ผู้โจมตี 4 ระดับตามระดับความรู้เกี่ยวกับเหยื่อ และสร้างเซสชันการโจมตีจากเซสชันจริงของ
> ผู้ใช้ (labeled by construction)
>
> ผลการประเมินบนชุดข้อมูล 1,300 รายการ (ปกติจริง 700 + โจมตีจำลอง 600) พบว่าระบบตรวจจับ
> ผู้โจมตีระดับ naive และ VPN ได้ **100%** ในขณะที่ผู้โจมตีแบบ targeted ที่ทราบทั้งประเทศ
> อุปกรณ์ และช่วงเวลาที่เหยื่อใช้งาน ถูกตรวจจับได้เพียง **8.7%** โดยมีอัตรา false positive
> บนทราฟฟิกจริงที่ **14.0%**
>
> ผลดังกล่าวสอดคล้องกับข้อจำกัดเชิงทฤษฎีของ RBA ที่อาศัยความผิดปกติของบริบทเป็นสัญญาณ
> — เมื่อผู้โจมตีเลียนแบบบริบทของเหยื่อได้สมบูรณ์ ระบบย่อมไม่พบความผิดปกติ ข้อค้นพบนี้
> ยืนยันความจำเป็นของการใช้ปัจจัยยืนยันตัวตนที่ต้านฟิชชิงได้ (Passkey/WebAuthn) ควบคู่กับ
> RBA เนื่องจากทั้งสองกลไกรับมือภัยคุกคามคนละลักษณะ"

---

## 8. สิ่งที่ทำต่อได้ (ถ้าเวลาเหลือ)

1. **Red-team จริง** — ให้ตัวเอง/เพื่อนโจมตีจริง (VPN, เครื่องอื่น) 10–30 เคส
   → ใช้ตรวจสอบว่า simulated attack สมจริงแค่ไหน (ถ้าคะแนนใกล้กัน = simulation เชื่อถือได้)
2. **ล้าง test traffic** — ลด FPR จาก 14% ให้ต่ำกว่า 10%
3. **ทดสอบ threshold sweep** — ดู trade-off ระหว่าง recall (targeted) กับ FPR
