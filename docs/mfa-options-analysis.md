# Step-Up Authentication — วิเคราะห์ตัวเลือก Second Factor

**บริบท:** ระบบใช้ Google OAuth เป็น primary authenticator อยู่แล้ว  
**โจทย์:** เมื่อ ML ตรวจพบ anomaly score สูง ควรใช้กลไกใดยืนยันตัวตนเพิ่มเติม  
**หลักที่ใช้วิเคราะห์:** CIA Triad (Confidentiality · Integrity · Availability)

---

## ตัวเลือกที่พิจารณา

### ตัวเลือก A — Student / Employee ID Challenge

ระบบขอให้ผู้ใช้กรอกรหัสนักศึกษาหรือรหัสพนักงานเมื่อตรวจพบความผิดปกติ  
ตรวจสอบกับ `users.identifier` ในฐานข้อมูล ไม่ต้องพึ่งระบบภายนอก

```
[Login ผิดปกติ] → "กรุณากรอกรหัสนักศึกษาของคุณ: [______]"
                → ตรวจกับ DB → ผ่าน / ไม่ผ่าน
```

**จุดเด่น:** ข้อมูลอยู่ใน DB แล้ว ไม่ต้องสร้างระบบใหม่  
**จุดด้อย:** รหัสนักศึกษาไม่ใช่ความลับจริง — เพื่อนในห้องรู้ได้ พิมพ์อยู่บนบัตร

---

### ตัวเลือก B — University Email OTP

ส่งรหัส OTP ไปยัง `@uni.ac.th` ซึ่งเป็นคนละ channel กับ Gmail ที่ใช้ login

```
[Login ผิดปกติ] → ส่ง OTP ไปที่ 650001@uni.ac.th
                → ผู้ใช้กรอก OTP → ผ่าน / หมดอายุ
```

**จุดเด่น:** พิสูจน์ว่าเข้าถึง email ของมหาวิทยาลัยได้จริง  
**จุดด้อย:** ถ้า SMTP ล่ม / อีเมลตกใน spam → ผู้ใช้เข้าระบบไม่ได้เลย (Availability พัง)  
ถ้ามหาวิทยาลัยใช้ Google Workspace = channel เดียวกับ Google อยู่ดี

---

### ตัวเลือก C — Session Downgrade (Read-Only Mode)

ไม่ block ไม่ขอรหัสใดเพิ่ม — แต่ **จำกัดสิทธิ์ session ชั่วคราว**  
ผู้ใช้ยังเข้าใช้งานได้ แต่ทำ write operations ไม่ได้จนกว่าจะ login ใหม่จาก device ที่คุ้นเคย

```
[score ≥ 0.70] → เข้าระบบได้ แต่:
    - ดูข้อมูลได้ (read-only)
    - จองหอพัก / ยืมหนังสือ ไม่ได้
    - แก้ไขข้อมูลส่วนตัว ไม่ได้
    - แสดง banner แจ้งเตือน + วิธีปลดล็อก
```

**จุดเด่น:** ไม่พึ่ง external service ไม่มี false positive ที่ lock ผู้ใช้ออก  
**จุดด้อย:** ผู้บุกรุกที่เป็น attacker จริงยังอ่านข้อมูลได้

---

### ตัวเลือก D — Trusted Device Registration

ผูก session กับ device fingerprint (User-Agent + browser family)  
ครั้งแรกจาก device ใหม่ → ถามยืนยัน ครั้งต่อไปจาก device เดิม → ผ่านเลย

```
[Device ใหม่] → "อุปกรณ์นี้ยังไม่คุ้นเคย บันทึกไว้สำหรับครั้งต่อไปไหม?"
    ยืนยัน → เก็บ fingerprint ใน DB → ครั้งต่อไปผ่านอัตโนมัติ
    ปฏิเสธ → session นี้ read-only
```

**จุดเด่น:** friction เกิดขึ้นแค่ครั้งแรก ไม่รบกวนการใช้งานปกติ  
**จุดด้อย:** User-Agent ถูก spoof ได้ ไม่ใช่ hardware fingerprint จริง

---

## ตารางเปรียบเทียบ CIA Triad

| | **A: Student ID** | **B: Email OTP** | **C: Session Downgrade** | **D: Trusted Device** |
|---|:---:|:---:|:---:|:---:|
| **C — Confidentiality** | 🟡 รหัสนักศึกษาไม่ใช่ความลับจริง | 🟢 เฉพาะเจ้าของ email เข้าถึงได้ | 🟡 attacker อ่านข้อมูลได้ แต่ไม่แก้ไข | 🟢 ผูกกับ device จริง |
| **I — Integrity** | 🟡 ไม่แน่ใจว่าคนกรอก = เจ้าของบัญชี | 🟢 พิสูจน์ได้แน่น | 🟢 ป้องกัน write operations ทันที | 🟢 device ใหม่ = flag ทันที |
| **A — Availability** | 🟢 ไม่ขึ้นกับระบบนอก | 🔴 SMTP ล่ม = เข้าไม่ได้ | 🟢 ยังใช้งานได้ แค่จำกัดสิทธิ์ | 🟢 friction เฉพาะครั้งแรก |
| **ความซับซ้อน UX** | ต่ำ | กลาง | **ต่ำที่สุด** | ต่ำ |
| **ป้องกัน attacker จริง** | 🟡 อ่อนถ้า ID หลุด | 🟢 ดี | 🟢 จำกัด damage | 🟢 ดี |
| **ต้องพึ่งระบบนอก** | ไม่ | ใช่ (SMTP) | ไม่ | ไม่ |
| **False Positive เจ็บแค่ไหน** | กลาง (ต้องหา ID) | สูง (อาจเข้าไม่ได้เลย) | **ต่ำที่สุด** (ใช้งานได้ต่อ) | ต่ำ (ยืนยันครั้งเดียว) |

---

## ทำไม Availability ถึงสำคัญเป็นพิเศษในระบบมหาวิทยาลัย

```
สถานการณ์จริง:
  นักศึกษาต้องจองหอพักก่อน deadline 23:59
  → ระบบ flag ว่าผิดปกติ (login จาก IP ใหม่ / device ใหม่)
  → ถ้าใช้ Email OTP แต่อีเมลถูก spam filter กัน
  → นักศึกษาจองไม่ทัน

ผลลัพธ์: ระบบ "ปลอดภัย" แต่ทำลาย Availability ตัวเอง
         = ระบบล้มเหลวในเป้าหมายหลัก
```

> **หลักการ:** Security ที่ดีต้องไม่ทำลาย Availability ของผู้ใช้ที่ถูกต้อง  
> การ block ผิดพลาด (false positive) ก็คือ Security failure รูปแบบหนึ่ง

---

## ข้อเสนอแนะ — Tiered Risk Response

ผสมแนวทาง C + D เข้าด้วยกัน เพื่อ balance CIA ได้ดีที่สุด:

```
anomaly_score < 0.40
    → PASS ปกติ

0.40 ≤ score < 0.70
    → Trusted Device check
      "อุปกรณ์นี้ยังไม่คุ้นเคย บันทึกไว้ไหม?"
      ถ้าปฏิเสธ / ไม่ยืนยัน → session read-only

score ≥ 0.70
    → Session Downgrade ทันที (ไม่ต้องถาม)
      แสดง banner: "สิทธิ์ถูกจำกัดชั่วคราว
                    กรุณา login ใหม่จาก device ที่คุ้นเคย"
      + บันทึก audit log + แจ้ง admin (async)
```

### สรุปเหตุผลที่เลือก C + D

| หลัก CIA | ตัวเลือกที่ดีที่สุด | เหตุผล |
|----------|-------------------|--------|
| **Confidentiality** | D — Trusted Device | ผูก session กับ device จริง ไม่ใช่แค่รหัสที่จำได้ |
| **Integrity** | C — Session Downgrade | ป้องกัน write operations ทันทีโดยไม่ต้องรอ admin |
| **Availability** | C — Session Downgrade | ไม่พึ่ง external service, ไม่ hard block ผู้ใช้ที่ถูกต้อง |

---

## สิ่งที่ไม่แนะนำในบริบทนี้

| แนวทาง | เหตุผลที่ไม่เหมาะ |
|--------|-----------------|
| TOTP / Authenticator App | ซ้ำซ้อนกับ Google 2FA ที่มีอยู่แล้ว |
| SMS OTP | ต้องเก็บเบอร์โทรศัพท์, SIM swap attack, ค่าใช้จ่าย |
| Email alert "ใช่คุณไหม?" | เหมือนที่ Google ทำอยู่แล้ว ไม่ได้เพิ่มคุณค่า |
| Hard block ทันที | False positive rate ~43% ที่ threshold 0.70 สูงเกินไป |

---

## สถานะปัจจุบันและ Roadmap

| Phase | แนวทาง | สถานะ |
|-------|--------|-------|
| ปัจจุบัน | Shadow Mode — log แต่ไม่ block | ✅ ทำงานอยู่ |
| Week 9-10 | Trusted Device Registration | ⏳ วางแผนแล้ว |
| Week 9-10 | Session Downgrade สำหรับ score ≥ 0.70 | ⏳ วางแผนแล้ว |
| อนาคต | Student ID Challenge สำหรับ high-stakes actions เท่านั้น | 💡 พิจารณา |

> **หมายเหตุ:** ขณะที่ precision ของโมเดลยังอยู่ที่ ~57% (threshold 0.70)  
> การใช้ Shadow Mode + Admin Review + Feedback Loop (P1-5)  
> เพื่อสะสม ground truth ก่อน enable enforcement เป็นแนวทางที่เหมาะสมที่สุด

---

*อ้างอิง: Wiefling et al. (2022) "More Than Just Good Passwords?" ACM TOPS —  
Risk-Based Authentication ควร balance security กับ usability โดยใช้ step-up challenge  
เฉพาะเมื่อ risk score สูงจริงๆ ไม่ใช่ทุก session*
