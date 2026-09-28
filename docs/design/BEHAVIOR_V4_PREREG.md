# V4 — แผนทดลองการจดจำพฤติกรรมรายคน (ตรึงก่อนทดสอบ V4)

วันที่: 28 กันยายน 2569 · V3 ล้มเหลวและ Holdout V3 ยังปิด

## คำถามและขอบเขต

ทดสอบว่าการคัดฟีเจอร์ให้เน้นพฤติกรรมปกติรายคนช่วยเพิ่ม precision
โดยรักษา recall รวมและราย attack family ได้หรือไม่ คง Isolation Forest;
ไม่เพิ่ม loss, ไม่เปลี่ยน production contract หรือเกณฑ์ deploy

ผล V3 และข้อมูล Validation V3 ใช้วิเคราะห์เชิงสำรวจได้เท่านั้น
ห้ามใช้รับรอง V4 หรือเลือก threshold ของ V4

## การตรวจวิธีทดลองก่อนวัด V4

1. ทดสอบ sequence ของ campaign ที่เกิดตามลำดับเวลา: ระหว่างเหตุการณ์ที่ยืนยันว่า
   เกิดจริงและมาก่อน login ปัจจุบัน ต้องอัปเดต tail ของประวัติ; ห้ามใช้เหตุการณ์อนาคต
   ตรวจความตรงกับ production score หนึ่งเหตุการณ์โดยใช้ snapshot เดียวกัน
2. ตรวจว่า normal ที่คล้าย campaign ถูกป้อนเป็นข้อมูลปกติในชุดประเมินจริง
   และไม่นำเข้า Train/Calibration โดยไม่ได้ประกาศไว้ล่วงหน้า
3. ตรวจการข้ามขอบ episode, การรวม baseline รายคน, การรั่วของ labels และ
   การกระจายของฟีเจอร์ที่ถูกตัดออก รวมทั้งจำนวนเหตุการณ์ต่อ family
4. หากต้องเปลี่ยนการสร้างข้อมูล ให้ตรึง generator version ใหม่ก่อนรัน V4
   และใช้ Validation seed ใหม่; ห้ามอ้างผล V3 เทียบข้าม generator เป็นผล causal

## Candidate ฟีเจอร์ที่ต้องตรึงก่อนรัน V4

- All: 23 ฟีเจอร์เดิม (control)
- Behavioral: ชั่วโมงและวัน, เวลาเทียบปกติรายคน, อุปกรณ์และ family,
  ความถี่/ช่องว่าง, weekday usage, การใช้ subsystem/ความอ่อนไหวของ scope
- Behavioral + trust: เพิ่ม passkey/สิทธิ์และเหตุการณ์ยืนยันย้อนหลัง
- Behavioral + geo: เพิ่มบริบทประเทศและ impossible travel

ฟีเจอร์อุปกรณ์ปัจจุบันมีเพียง binary `is_new_device` และ
`is_new_user_agent_family`; ความหายากของอุปกรณ์ที่เคยใช้ส่วนใหญ่เป็นข้อมูล
profile ของ L2 จึงต้องวัดแยก ไม่กล่าวว่าตัวโมเดล 23 ฟีเจอร์เห็น device ID
หรือบทบาทจริง ระบบยังไม่มี role โดยตรงใน 23 ฟีเจอร์: scope เป็นเพียง proxy

การ mask ฟีเจอร์ในโมเดลทดลองต้องไม่เปลี่ยน schema ที่บริการรับหรือสลับลำดับ
และต้องแยก artifact ทดลองจาก production; parity ต้องตรวจด้วยชุดฟีเจอร์เดียวกัน

## การประเมิน

- สร้าง validation population/seed ใหม่; split 32/16, holdout ไม่เปิดก่อนผ่าน gate
- Train/Calibration normal-only; anomaly ใน Tuning ≤7%; history 5–2,000
- Calibration normal-only แยก candidate, freeze threshold ก่อน Tuning
- งบ cluster CI: warn ≤5%, challenge ≤1%, block ≤0.2%
- Recall ≥70%, precision ≥70%, recall ทุก family ≥50%, ผ่านทุก seed
- รายงานการเปลี่ยนจำนวน TP/FP เทียบ control, FPR และความสามารถตรวจจับ
  `campaign`, `new_passkey`, `subtle_rare_device` โดยแยก cold start
- ห้ามปรับ generator/threshold/ฟีเจอร์เพื่อให้ผ่านหลังเห็น Validation
- หากไม่มี candidate ผ่าน ให้คง holdout ปิดและรายงานข้อจำกัด;
  production/Shadow/Capacity ไม่เปลี่ยน

## การวิเคราะห์ V3 หลังทราบผล (ไม่ใช่ V4 Validation)

ตรวจ separability ของแต่ละฟีเจอร์ในสาม family ด้วย AUC ที่จัดการ tie และ
สัดส่วนที่ค่าของ attack อยู่ในช่วง normal; ระบุชัดว่าเป็นการสำรวจบนข้อมูลเดิม
ห้ามคัดฟีเจอร์โดยอ้าง AUC นี้แล้วกลับไปประเมินบน V3 เป็นผลรับรอง
