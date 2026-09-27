# Pre-registration — Real-seeded Synthetic Population V3

วันที่ตรึงแผน: 27 กันยายน 2569 (ก่อนสร้างประชากรและอ่านผล V3)

## 1. เหตุผลและคำถามวิจัย

V2 ผ่าน Feature/Privacy/Parity/FPR gate ทุกขนาดประวัติ แต่ไม่ผ่าน Accuracy Gate:
ที่ history 2,000 recall 73.9% และ precision 62.1% โดย L3 เพิ่ม recall 7.4 จุด
เปอร์เซ็นต์เหนือ L1+L2 แต่ลด precision 23.8 จุด เป้าหมาย V3 คือแยกผลของ point
และ sequence แล้วทดสอบว่าการให้สองมุมมองยืนยันกันลด false positive ได้หรือไม่
โดยยังใช้ 23 ฟีเจอร์เดิม

สมมติฐาน:

- H1: point-only หรือ sequence-only อย่างน้อยหนึ่งตัวมี precision สูงกว่า E แบบ
  `max(point, sequence)` โดยยังรักษา recall รวมและราย family ตาม gate
- H2: consensus evidence = `min(point, sequence)` เมื่อทั้งสองมุมมอง eligible
  ลด false positive ของ L3 มากพอให้ precision ≥70% โดย recall รวม ≥70%
- H0: ไม่มี candidate ใดผ่านครบ ให้สรุปว่า constraint/model family ปัจจุบันยัง
  ไม่เพียงพอ ห้ามลด gate และห้ามเปิด Holdout

## 2. งานวิจัยต้นแบบ

- Freeman et al., *Who Are You? A Statistical Approach to Measuring User
  Authenticity*, NDSS 2016, DOI `10.14722/ndss.2016.23240`: baseline รายบัญชี
  และการวัดตามจำนวนประวัติ
- Wiefling, Dürmuth, Lo Iacono, *What's in Score for Website Users*, FC 2021,
  DOI `10.1007/978-3-662-64331-0_19`: บริบทเวลา/อุปกรณ์และการประเมิน RBA
  ระยะยาว
- Wiefling et al., *Privacy Considerations for Risk-Based Authentication
  Systems*, arXiv `2301.01505`: ลดการส่งออก IP/browser identifier และใช้ค่ารวม
- Liu, Ting, Zhou, *Isolation Forest*, ICDM 2008, DOI
  `10.1109/ICDM.2008.17`: ฝึก anomaly detector ด้วย normal-only

Consensus เป็น candidate ที่ต้องพิสูจน์ในระบบนี้ ไม่กล่าวอ้างว่างานข้างต้นรับรอง
สูตร `min` หรือรับรองผล deploy

## 3. ประชากรและ split ที่ตรึง

| รายการ | ค่า V3 |
|---|---:|
| synthetic profiles | 48 |
| validation / holdout | 32 / 16 |
| population seed | 790927 |
| validation data seeds | 721, 722, 723 |
| history sizes | 5, 10, 20, 50, 100, 200, 500, 1,000, 2,000 |
| features | 23 ตัวเดิม ตาม production contract |
| Train | normal 5,000 ต่อโปรไฟล์ |
| Calibration | normal 500 ต่อโปรไฟล์ |
| Tuning | normal 500 + anomaly ไม่เกิน 35 ต่อโปรไฟล์ |
| anomaly สูงสุด | 35/535 = 6.542% |
| final test | normal 1,000 + anomaly 40 เฉพาะเมื่อ Validation ผ่าน |

V3 ใช้ cadence/age carry แบบ V2 แต่ bootstrap/perturb ใหม่ด้วย population seed
ใหม่ alias `W01`–`W48` ห้ามใช้ผลหรือ Holdout V2 เลือก candidate V3

## 4. Candidate ที่ตรึง

| Key | หลักฐานที่ใช้ |
|---|---|
| B | L1 + L2 ไม่มี L3 (baseline) |
| C | L1 + L2 + point Isolation Forest |
| D | L1 + L2 + sequence Isolation Forest |
| E | L1 + L2 + `max(point, sequence)` แบบ V2 |
| G | L1 + L2 + consensus `min(point, sequence)` และ abstain หากขาดมุมมองใด |

ทุก candidate ใช้ production `fuse()` และ `resolve_action()` เดิม, gamma 0.35,
L3-solo block cap เดิม ห้ามเขียน decision mapping ซ้ำใน harness

## 5. Calibration และการเลือก candidate

1. สอบเทียบ global thresholds แยก B/C/D/E/G จาก Calibration normal-only ครบ
   3 seeds × 9 sizes
2. เป้าหมาย point rate: warn ≤2.5%, challenge-or-block ≤0.5%, block ≤0.1%
3. freeze threshold ของทุก candidate พร้อม population/config hash ก่อน Tuning
4. Candidate ผ่านเมื่อทุก history cell ที่อ้างเป็นจุดใช้งานผ่าน:
   - cluster-aware upper CI: warn ≤5%, challenge ≤1%, block ≤0.2%
   - recall รวม ≥70%, precision ≥70%, recall ทุก attack family ≥50%
   - ผ่าน point gate ทุก seed และ model/service parity ≤`1e-12`
5. เลือกจาก candidate ที่ผ่านด้วยลำดับ: history ต่ำสุด → precision สูงสุด →
   challenge FPR ต่ำสุด → key ตามตัวอักษร
6. B เป็น comparator ไม่เลือกเป็น “L3 candidate” แม้ผ่าน
7. หากไม่มี C/D/E/G ผ่าน หยุดและคง Holdout ปิด

## 6. กฎเปิด Holdout

หากมี L3 candidate ผ่าน Validation เท่านั้น ให้เขียน selection freeze artifact
ก่อนเปิด Holdout แล้วประเมิน candidate เดียวที่ history ที่เลือกกับ 16 holdout
profiles หนึ่งครั้ง ห้ามสลับ candidate/threshold หลังเห็น Holdout ผล Holdout ต้อง
ผ่าน FPR, recall, precision และ family gate เดิม จึงถือว่า synthetic validation ผ่าน

แม้ Holdout ผ่านก็อนุญาตเพียงเตรียม expert-labeled Shadow; ยังห้าม Step-up/Block
จนกว่า production shadow และ live Capacity Gate ผ่าน

## 7. Gate และกติกาหลังเห็นผล

- Privacy, feature contract, leakage, shortcut และ anomaly cap ต้องผ่าน
- Train/Calibration เป็น normal-only และแบ่งตามเวลา
- ห้ามแก้ 23 ฟีเจอร์, generator, attack mix, seed, gamma, consensus formula,
  threshold target หรือ gate ภายใต้ชื่อ V3
- ผลต่ำกว่า gate ต้องรายงานตรงไปตรงมา ห้ามทำ attack ให้ง่ายขึ้น
- ถ้า family ที่ล้มมี distribution ซ้อน normal ภายใต้ 23 ฟีเจอร์เดิม ให้ทำ
  separability diagnostic และรายงานข้อจำกัดก่อนเสนอ V4
- production policy/threshold/model file ไม่เปลี่ยนจากการทดลองนี้โดยอัตโนมัติ
- Capacity Gate ล่าสุดยังไม่ผ่าน จึงห้าม merge เข้า `main` และห้ามเปิด Shadow Pilot
