# Pre-registration — Real-seeded Synthetic Population V1

วันที่ตรึงแผน: 27 กันยายน 2569 (ก่อนสร้างและอ่านผลการทดลองรอบนี้)

## 1. วัตถุประสงค์

ใช้ข้อมูลระบบจริงที่ผู้ดูแลส่งให้เป็นแม่แบบของพฤติกรรมปกติ แล้วสร้างประชากร
สังเคราะห์ที่ไม่มีตัวระบุบุคคล เพื่อทดสอบ L1, L2, L3 และ L4 ตามเส้นทาง production
โดยยังไม่เปิดให้ L3 มีผลต่อสิทธิ์ของผู้ใช้จริง

ข้อมูลต้นทางมี login 206 เหตุการณ์จาก 10 บัญชี และไม่มีเหตุการณ์ที่ถูกยืนยันด้วย
`is_attack_ip` หรือ `is_account_takeover` จึงใช้ประมาณการกระจายของ normal behavior
เท่านั้น ห้ามใช้กล่าวอ้าง recall ต่อการโจมตีจริง

## 2. การคุ้มครองข้อมูล

1. อ่าน CSV จาก path ที่ผู้รันระบุเท่านั้น
2. ไม่เขียน user id, email, ชื่อ, IP, user-agent, credential หรือ secret ลง artifact
3. แปลงอุปกรณ์เป็นหมวดทั่วไป และแปลง subsystem เป็น `HUB/SUB_A/SUB_B`
4. output ใช้ alias `R01`–`R48` และบัญชีสังเคราะห์ `@uni.ac.th`
5. เก็บเฉพาะสถิติรวมและ SHA-256 ของ ZIP ต้นทางเพื่อ reproducibility
6. raw data และ generated rows อยู่ใน directory ที่ gitignore ครอบคลุม

แนวทางนี้สอดคล้องกับข้อเสนอให้ลดการเก็บ IP และ browser identifier ในระบบ RBA:
Wiefling, Tolsdorf, Lo Iacono, *Privacy Considerations for Risk-Based
Authentication Systems* (2023), arXiv:2301.01505.

## 3. รูปแบบประชากร

| รายการ | ค่าที่ตรึง |
|---|---:|
| จำนวนโปรไฟล์ | 48 |
| validation profiles | 32 |
| holdout profiles | 16 |
| population seed | 770927 |
| data seeds | 701, 702, 703 |
| ประวัติที่ทดสอบ | 5, 10, 20, 50, 100, 200, 500, 1,000, 2,000 |
| ฟีเจอร์ | 23 ตัวเดิม ตาม `app.features.FEATURE_NAMES` |
| sequence window | 5 เหตุการณ์ ตาม production |

สร้างแต่ละโปรไฟล์โดย bootstrap โปรไฟล์จริงหนึ่งรายการ แล้ว perturb เฉพาะค่ารวม:
ช่วงเวลา login, สัดส่วนวันหยุด, จำนวน/สัดส่วนอุปกรณ์, ระบบย่อย, cadence,
วิธี login, passkey, scope และ permission age ค่าทุกตัวถูกตัดให้อยู่ในขอบเขตของ
generator และ feature contract เดิม

การใช้ login history รายคนและความเปลี่ยนแปลงของ IP/User-Agent/เวลาอ้างอิงจาก:

- Freeman et al., *Who Are You? A Statistical Approach to Measuring User
  Authenticity*, NDSS 2016, DOI 10.14722/ndss.2016.23240.
- Wiefling, Dürmuth, Lo Iacono, *What's in Score for Website Users: A
  Data-Driven Long-Term Study on Risk-Based Authentication Characteristics*,
  FC 2021, DOI 10.1007/978-3-662-64331-0_19.
- Wiefling et al., *Pump Up Password Security! Evaluating and Enhancing
  Risk-Based Authentication on a Real-World Large-Scale Online Service*,
  ACM TOPS 2022.

Isolation Forest อ้างอิง Liu, Ting, Zhou, *Isolation Forest*, ICDM 2008,
DOI 10.1109/ICDM.2008.17 และฝึกด้วย normal-only ตามลักษณะ one-class anomaly
detection ของงานนี้

## 4. การแบ่งข้อมูล

ต่อหนึ่งโปรไฟล์และหนึ่ง seed:

| Split | ข้อมูล | การใช้งาน |
|---|---|---|
| Train | normal 5,000 | เลือก nested history ตามขนาดที่ทดสอบ |
| Calibration | normal 500 | fit empirical CDF เท่านั้น |
| Tuning test | normal 500 + anomaly ไม่เกิน 35 | เลือกค่าบน validation |
| Final test | normal 1,000 + anomaly 40 | วัดหลัง freeze เท่านั้น |

อัตรา anomaly สูงสุดของ tuning test คือ `35/535 = 6.542%` และ final test คือ
`40/1040 = 3.846%` ซึ่งไม่เกิน 7% ชุด Train และ Calibration เป็น normal ทั้งหมด
และแบ่งตามลำดับเวลา ห้ามสุ่มแถวข้าม split

## 5. Gate ที่ตรึงก่อนเห็นผล

1. Privacy: artifact ไม่มีค่าจากคอลัมน์ตัวระบุหรือ secret
2. Feature contract: 23 ชื่อ ลำดับ และ range ตรง production
3. Leakage: final test ไม่ซ้ำ Train/Calibration/Tuning
4. Shortcut: ไม่มีฟีเจอร์เดียว AUC > 0.99 หรือ attack coverage < 0.05
5. Challenge FPR: cluster-aware upper CI ≤ 1%
6. Block FPR: cluster-aware upper CI ≤ 0.2%
7. Warn FPR: cluster-aware upper CI ≤ 5%
8. Detection quality: recall รวม ≥ 70%, precision ≥ 70%, และ recall ของแต่ละ
   attack family ≥ 50% บน validation
9. History sufficiency: ขนาดต่ำสุดที่ผ่านข้อ 5–8 ครบทั้งสาม seed; ถ้าไม่มีให้
   รายงานว่าไม่พบจุดที่เพียงพอ ห้ามลดเกณฑ์ย้อนหลัง
10. Model parity: candidate artifact ต้องถูกโหลดและให้คะแนนผ่าน `app.model`
    ได้ตรงกับการทดลองภายใน tolerance `1e-12`
11. Shadow: ต้องมี expert label และ production FPR เพียงพอก่อนเปิด `hybrid_stepup`
12. Capacity: ใช้ gate เดิมของระบบ; ถ้า P1 หรือ gate ใดไม่ผ่าน ห้าม merge เข้า main
    และห้ามเปิด Shadow Pilot

## 6. กติกาหลังเห็นผล

- validation ไม่ผ่านข้อใดข้อหนึ่ง ให้หยุดและคง holdout ไว้ปิด
- ห้ามเปลี่ยน threshold หรือรูปแบบ anomaly แล้วรันซ้ำด้วยชื่อ population เดิม
- การแก้ต้องสร้าง population/version/seed ชุดใหม่
- ผลจากข้อมูลสังเคราะห์ใช้ตัดสินความพร้อมสำหรับ shadow เท่านั้น จนกว่าจะมี expert
  labels จาก traffic จริงเพียงพอ
