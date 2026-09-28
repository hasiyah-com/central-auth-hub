# Pre-registration V5 — แก้สัญญาลายเซ็นอุปกรณ์ของชุดสังเคราะห์

วันที่ตรึง: 28 กันยายน 2569 · หลัง V4 pilot ล้มเหลว; ก่อนสร้างผล V5

## เหตุผลและข้อจำกัดการตีความ

V4 ตรวจพบว่าสัญญาณ L2 `signature_rarity` ไม่ทำงานกับ
`subtle_rare_device`: synthetic signature ใช้ `device|OS|browser` แต่ production
อ่าน User-Agent เป็น `OS|device|browser` (ชุดอุปกรณ์ต้นแบบ 14 แบบตรงกัน 0 แบบ)
และ Block FP ที่ history 2,000 ส่วนใหญ่เป็น normal campaign-like (112/124
สำหรับชุด 23 ฟีเจอร์) โดย L2 เป็นชั้นคะแนนหลัก 118/124 ครั้ง

V5 เปลี่ยน **เฉพาะ** ตัวสร้างข้อมูลสังเคราะห์ให้สร้าง/เปรียบเทียบ signature
ด้วยตัวแปลง production ตัวเดียวกันก่อนคำนวณ 23 ฟีเจอร์ ทั้ง Train, Calibration,
Tuning และ attack เก็บ V4/V3 และผลที่ตีพิมพ์ไว้ตามเดิม ห้ามใช้ Holdout V4/V3

## Protocol ที่ตรึง

- ประชากรสังเคราะห์ใหม่ 48 ราย seed `810928`, alias `Y01`–`Y48`,
  validation 32 / holdout 16, data seeds `741,742,743`
- Train/Calibration normal-only, Tuning ปกติ 500 + campaign-like normal 5
  + attack ไม่เกิน 35 ต่อคน; anomaly ≤7%; 23 feature contract เดิม
- ใช้ history 100 และ 2,000 เพื่อวินิจฉัยก่อน เมื่อ pilot ไม่ผ่านให้หยุด;
  Validation เต็มต้องวัด 5, 10, 20, 50, 100, 200, 500, 1,000, 2,000
- Candidates แบบ point รายคน 23 ฟีเจอร์ (control), behavioral 10,
  behavioral+trust 17, behavioral+geo 14; sequence ที่เห็น phase ของ campaign
  ตามเวลา; fusion gamma 0.35 และ resolver เดิม
- สอบเทียบ threshold แยก candidate จาก Calibration normal-only ครบ seeds
  และ sizes ที่วัด แล้ว freeze ก่อน Tuning; เป้าหมาย warn ≤2.5%,
  challenge-or-block ≤0.5%, block ≤0.1%
- ตรวจ generator: synthetic signature เท่ากับ `_device_signature(user_agent)`
  ของ production ทุกแถว, no-passkey age=0, แยก holdout ก่อนสร้าง,
  normal campaign-like อยู่ใน Tuning เท่านั้น
- รายงาน recall/precision/FPR, family recall, `signature_rarity` firing,
  block attribution และ normal campaign-like block แยกชั้น
- Gate สำหรับการประเมินเต็มยังเป็น recall ≥70%, precision ≥70%, family recall
  ≥50%, cluster upper CI warn ≤5%, challenge ≤1%, block ≤0.2%, ทุก seed ผ่าน
- **ห้าม** เลือก threshold/น้ำหนัก L2/attack generator จาก Tuning รอบนี้แล้ว
  อ้างว่าผ่านบนข้อมูลเดียวกัน
- โมเดล point รายคนยังไม่มี service parity หรือ Capacity Gate จริง:
  pilot นี้ไม่อนุญาตเปิด Holdout, Shadow หรือบังคับสิทธิ์ แม้ metric ดีขึ้น
