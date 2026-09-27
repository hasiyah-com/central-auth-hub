# Pre-registration — Real-seeded Synthetic Population V2

วันที่ตรึงแผน: 27 กันยายน 2569 (ก่อนสร้างประชากร V2 และก่อนอ่านผล V2)

## 1. เหตุผลที่ต้องมี V2

V1 ไม่ผ่าน gate ทุกขนาดประวัติ จึงไม่เปิด holdout และไม่นำผลไปเปลี่ยน policy
ของระบบจริง การวินิจฉัย V1 พบความคลาดเคลื่อนเชิงโครงสร้างสองข้อ:

1. generator บังคับทุก episode ให้มี 50 login ภายใน 25 วัน แม้อัตราการใช้งานที่
   สังเกตจากผู้ใช้ต้นแบบจะต่างกัน
2. `permission_change_age` และอายุ passkey เริ่มซ้ำจากค่าเดิมในทุก episode
   ทำให้เหตุการณ์ปกติบางส่วนดูเหมือนเพิ่งเปลี่ยนสิทธิ์ซ้ำๆ

V2 แก้เพียงสองข้อนี้แบบ opt-in และสอบเทียบ threshold จาก Calibration normal-only
ก่อนแตะ Tuning test ห้ามเปลี่ยน 23 ฟีเจอร์, family ของ attack, fusion, gamma,
Isolation Forest หรือ gate หลังเห็นผล

## 2. สมมติฐานที่ทดสอบ

- H1: cadence ที่สัมพันธ์กับประวัติจริงและ age carry จะลด false positive ของ
  L1+L2 บน normal behavior
- H2: หลังสอบเทียบ threshold โดยไม่ใช้ attack จะมีขนาดประวัติอย่างน้อยหนึ่งค่า
  ที่ผ่านงบ FPR และคุณภาพการตรวจจับพร้อมกันครบทั้งสาม seed
- H0: ไม่มีขนาดประวัติใดผ่านครบ ให้รายงานว่า “ยังไม่พบประวัติขั้นต่ำที่เพียงพอ”
  โดยไม่ลด gate และไม่เปิด holdout

## 3. งานวิจัยที่ใช้เป็น pattern

- Freeman et al., *Who Are You? A Statistical Approach to Measuring User
  Authenticity*, NDSS 2016, DOI `10.14722/ndss.2016.23240`: ใช้ประวัติ login
  รายบัญชีและวัดผลตามปริมาณประวัติ แทนการสมมติว่าทุกบัญชีมี baseline เท่ากัน
- Wiefling, Dürmuth, Lo Iacono, *What's in Score for Website Users: A
  Data-Driven Long-Term Study on Risk-Based Authentication Characteristics*,
  FC 2021, DOI `10.1007/978-3-662-64331-0_19`: ใช้รูปแบบเวลา อุปกรณ์ และบริบท
  จากพฤติกรรมระยะยาวในการสร้าง risk signal
- Wiefling, Tolsdorf, Lo Iacono, *Privacy Considerations for Risk-Based
  Authentication Systems*, 2023, arXiv `2301.01505`: ลดการส่งออกตัวระบุ เช่น IP
  และ browser fingerprint; artifact ใช้ alias และค่ารวมเท่านั้น
- Liu, Ting, Zhou, *Isolation Forest*, ICDM 2008, DOI
  `10.1109/ICDM.2008.17`: ฝึก anomaly detector ด้วยข้อมูลปกติเท่านั้น

งานวิจัยเป็น pattern ของการออกแบบการทดลอง ไม่ใช่หลักฐานว่าโมเดลของระบบนี้ผ่าน
การใช้งานจริง ผลต้องผ่าน gate ที่กำหนดด้านล่างเอง

## 4. ประชากรและ split ที่ตรึง

| รายการ | ค่าที่ตรึง |
|---|---:|
| จำนวนโปรไฟล์ | 48 |
| validation profiles | 32 |
| holdout profiles | 16 |
| population seed | 780927 |
| data seeds | 711, 712, 713 |
| ประวัติที่ทดสอบ | 5, 10, 20, 50, 100, 200, 500, 1,000, 2,000 |
| ฟีเจอร์ | 23 ตัวเดิม ตาม `app.features.FEATURE_NAMES` |
| sequence window | 5 เหตุการณ์ ตาม production |
| candidate | E: L1 + L2 + point-all + sequence |
| comparator | B: L1 + L2 ไม่มี L3 |
| fusion | max + corroboration, `gamma = 0.35` |

ต่อหนึ่งโปรไฟล์และ seed:

| Split | ข้อมูล | การใช้งาน |
|---|---:|---|
| Train | normal 5,000 | เลือก nested history ตามขนาดที่ทดสอบ |
| Calibration | normal 500 | fit ECDF และสอบเทียบ action threshold |
| Tuning test | normal 500 + anomaly ไม่เกิน 35 | วัด validation หลัง freeze threshold |
| Final test | normal 1,000 + anomaly 40 | holdout เท่านั้น; รอบนี้ยังไม่เปิด |

Tuning มี anomaly สูงสุด `35/535 = 6.542%` และ Train/Calibration เป็น normal
ทั้งหมด แบ่งตามเวลาและไม่สุ่มแถวข้าม split

## 5. การแก้ generator ที่ตรึง

คำนวณอัตรา login ต่อวันของ prototype จากจำนวนช่วงห่างและช่วงเวลาที่สังเกต แล้ว
shrink เข้าหา global rate ด้วย prior 10 วัน เพื่อลดความผันผวนจากบัญชีที่มีข้อมูลน้อย:

`rate = (interval_count + 10 * global_rate) / (span_days + 10)`

กำหนด `episode_days = clip(round(50 / rate), 25, 365)` และคง 50 events ต่อ
episode อายุ permission/passkey เพิ่มตามจำนวนวันของ episode ที่ผ่านไป ค่าเหล่านี้
เปิดใช้ด้วย field ของ profile V2 เท่านั้น เพื่อให้ V1 reproducible เหมือนเดิม

ห้ามส่งออกค่ารายบัญชีจริง `observed rate`, timestamp, user id, email, IP,
user-agent, credential หรือ secret ประชากร V2 ใช้ alias `V01`–`V48`, หมวดอุปกรณ์
ทั่วไป และ subsystem `HUB/SUB_A/SUB_B`

## 6. การสอบเทียบ threshold ก่อน Tuning

ใช้เฉพาะ Calibration normal ของ validation profiles ครบ 3 seeds × 9 history
sizes สร้าง `EventRecord` ผ่าน resolver production แล้วเลือก global threshold ชุดเดียว
โดยไม่อ่าน attack label:

1. เลือก block threshold ต่ำที่สุดที่ทำให้ point block rate ของทุก cell ≤ 0.1%
2. ตรึง block แล้วเลือก challenge threshold ต่ำที่สุดที่ทำให้ point
   challenge-or-block rate ของทุก cell ≤ 0.5%
3. ตรึงสองค่าก่อนหน้าแล้วเลือก warn threshold ต่ำที่สุดที่ทำให้ point
   warn rate ของทุก cell ≤ 2.5%
4. บังคับ `0 ≤ warn < challenge < block ≤ 1`; หากหาไม่ได้ให้ประกาศ calibration
   infeasible และหยุดโดยไม่แตะ Tuning
5. เขียน threshold พร้อม hash ของ input population/config เป็น frozen artifact ก่อน
   ประเมิน Tuning

เป้าหมาย calibration เป็นครึ่งหนึ่งของ deployment budget เพื่อเหลือ margin สำหรับ
cluster-aware confidence interval การเลือกค่าทุกครั้งต้องเรียก resolver production
ห้ามคัดลอกกฎ action ไปไว้ใน harness

## 7. Gate ที่ตรึงก่อนเห็นผล

1. Privacy scan ผ่านและ artifact ไม่มี PII/secret
2. ชื่อ ลำดับ จำนวน และ range ของ 23 ฟีเจอร์ตรง production
3. split ไม่รั่ว และ holdout aliases ไม่ถูกส่งเข้า generator/ตัวประเมิน
4. ไม่มี shortcut feature เดียว AUC > 0.99 หรือ attack coverage < 0.05
5. cluster-aware upper CI: warn ≤ 5%, challenge-or-block ≤ 1%, block ≤ 0.2%
6. recall รวม ≥ 70%, precision ≥ 70%, recall ทุก attack family ≥ 50%
7. ผ่านข้อ 5–6 ครบทุก seed; ขนาดต่ำสุดที่ผ่านคือประวัติขั้นต่ำที่รายงาน
8. model/service point-scoring parity ภายใน tolerance `1e-12`
9. anomaly ratio ของ Tuning ≤ 7%; Train และ Calibration ไม่มี anomaly
10. Shadow ต้องมี expert label และ production FPR เพียงพอก่อนเปิด enforcement
11. Capacity gate เดิมต้องผ่านทุกข้อ รวม P1
12. ถ้าข้อใดไม่ผ่าน ห้าม merge เข้า main, ห้ามเปลี่ยน production threshold/policy,
    ห้ามเปิด holdout และห้ามกล่าวว่า L3 พร้อมใช้งานทุกชั้น

## 8. กติกาหลังเห็นผล

- threshold เลือกจาก Calibration normal-only เพียงครั้งเดียว แล้ว freeze ก่อน Tuning
- ไม่ใช้ anomaly เพื่อเลือก threshold และไม่ grid-search ซ้ำบน Tuning
- ไม่เปลี่ยนสูตร cadence, seed, attack mix, feature หรือ gate ภายใต้ชื่อ V2
- ถ้า V2 ไม่ผ่าน ให้บันทึก failure mode และสร้าง pre-registration เวอร์ชันใหม่
- ผลสังเคราะห์อนุญาตให้ตัดสินได้เพียงว่าจะเข้าสู่ shadow หรือไม่ การเปิด
  Step-up/Block ต้องอาศัย expert-labeled production shadow และ capacity gate เพิ่มเติม
