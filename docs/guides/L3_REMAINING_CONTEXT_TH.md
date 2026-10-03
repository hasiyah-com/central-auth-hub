# ฟีเจอร์เพิ่มเติมครบ 5 กลุ่ม: สถานะและข้อจำกัด

สถานะ: เก็บข้อมูลและมี pipeline ฝึกตัวทดลอง ไม่เปิดคะแนนจริง
Point เดิมยังใช้ 23 ฟีเจอร์และ Sequence เดิมยังใช้ residual 18 มิติ
Point candidate v2 มี 38 ฟีเจอร์ (23 เดิม + 9 จากรอบแรก + 6 จากรอบนี้)
Post-auth candidate มี 6 ฟีเจอร์แยกต่างหาก ไม่ใส่ข้อมูลหลังล็อกอินในเวกเตอร์ตอนล็อกอิน

## AAGUID

อ่านจาก credential ที่ WebAuthn ตรวจสอบ assertion สำเร็จ ทั้ง Hub passkey/discoverable
และ subsystem passkey ไม่อ่าน AAGUID จากฟิลด์ที่ client อ้างเอง
AAGUID เป็นรุ่น authenticator ไม่ใช่รหัสเครื่องรายตัว
ค่า null, all-zero หรือ UUID ผิดรูปแบบเป็น unknown ไม่ถือว่าเป็นรุ่นใหม่
เทียบกับ AAGUID ที่พบใน snapshot ของบัญชีและระบบเดียวกัน 30 วันก่อนเวลาประเมิน
ต้องมีอย่างน้อย 5 ครั้งที่ทราบค่า จึงเปิด prior_aaguid_observed

| ฟีเจอร์ใหม่ | วิธีคำนวณ |
|---|---|
| aaguid_known | รู้รุ่นของ local passkey ที่ตรวจสอบแล้วหรือไม่ |
| prior_aaguid_observed | มีประวัติ AAGUID ที่ทราบอย่างน้อย 5 ครั้งหรือไม่ |
| aaguid_novel | รุ่นปัจจุบันไม่เคยพบในประวัติที่เพียงพอ |
| language_known | มี language tag ที่อ่านได้หรือไม่ |
| prior_language_observed | มีประวัติภาษาที่ทราบอย่างน้อย 5 ครั้งหรือไม่ |
| language_novel | ภาษาปัจจุบันไม่เคยพบในประวัติที่เพียงพอ |

## Accept-Language

อ่าน header ตอน primary login ที่ตรวจสอบแล้ว เลือก tag ที่มี q สูงสุด
ปรับเป็นตัวพิมพ์เล็ก (เช่น th-TH → th-th), q เท่ากันใช้ลำดับเดิม
ไม่ใช้ wildcard, q=0, malformed, NaN หรือ header เกิน 256 ตัวอักษร
ภาษาปลอม/เปลี่ยนได้ จึงไม่ใช่หลักฐานยึดบัญชี และไม่ได้เพิ่มคะแนนแบบกฎ
เก็บเฉพาะ tag ที่เลือก ไม่เก็บ header ทั้งชุด
snapshot เก่าที่ไม่มีภาษา/AAGUID ไม่ถูกเดาเติมย้อนหลัง

## พฤติกรรมหลังล็อกอิน

ใช้ request_logs ที่ middleware ตรวจ JWT สำเร็จและทราบ user_id
สรุปช่วง UTC 5 นาทีที่จบแล้ว (from รวม, to ไม่รวม) แสดงเวลาไทยบน UI
API /admin/ml/users/{id}/sessions คืน post_auth_context แยกจาก risk_breakdown ตอนล็อกอิน
ตัด heartbeat, refresh, health, docs และ polling หน้า ML ออก
ไม่มีการระบุว่าเมาส์/การดูหน้าเป็นกิจกรรมผู้ใช้ เพราะ request log ไม่พิสูจน์สิ่งนั้น
Hub มองไม่เห็น request ภายในระบบย่อย จึงไม่อ้างว่าครอบคลุมพฤติกรรมทุกระบบ
เป็นระดับบัญชี ไม่ใช่เซสชันรายเครื่อง เพราะ RequestLog ไม่มี JTI

| ฟีเจอร์ | วิธีคำนวณ |
|---|---|
| post_requests_observed | 1 เมื่อมีคำขอในช่วงนี้; 0 เมื่อไม่มีข้อมูล |
| post_request_count_log1p | ln(1 + จำนวนคำขอ) |
| post_route_diversity_log1p | ln(1 + จำนวนกลุ่ม route); สองส่วนแรกของ path และแทนเลข/UUID ด้วย :id |
| post_write_fraction | สัดส่วน POST/PUT/PATCH/DELETE |
| post_error_fraction | สัดส่วน status >= 400 รวมถูกปฏิเสธและ server error |
| post_interval_log1p_mean | ค่าเฉลี่ย ln(1 + วินาทีระหว่างคำขอต่อเนื่อง) |

หากเกิน 10,000 รายการต่อช่วงจะระบุ truncated และไม่ส่งออกช่วงนั้นไปฝึก
สรุปหน้า UI ไม่มีคะแนน anomaly ของโมเดลใหม่และไม่เปลี่ยนสิทธิ์

## ขั้นตอนทดลอง

Point v2 ใช้คำสั่งเดิม:
```bash
python -m scripts.export_l3_auth_candidates --output /tmp/auth-v2.jsonl
python -m scripts.compare_auth_context --data /tmp/auth-v2.jsonl --output /tmp/auth-v2-candidates
```
ตัวส่งออกใช้เฉพาะ snapshot v2 ที่มี feedback; dataset v1 ที่ส่งออกไว้เดิมยังใช้เปรียบเทียบ 32 ตัวได้

Post-auth แยกคำสั่ง:
```bash
python -m scripts.export_l3_post_auth --output /tmp/post-auth.jsonl --days 7
```
ไฟล์เริ่มด้วย label=null ต้องตรวจและให้ label 0/1 แยกแต่ละช่วงเวลาอย่างอิสระ
ห้ามคัดลอก feedback ของการล็อกอินไปใส่ทุกช่วงหลังล็อกอิน
เมื่อแก้ label ต้องคำนวณ SHA-256 ไฟล์ใหม่และอัปเดต dataset_sha256 ใน sidecar
จากนั้นใน ML service:
```bash
python -m scripts.train_post_auth_candidate --data /tmp/post-auth.jsonl --output /tmp/post-candidate
```
ต้องมีอย่างน้อย 15 บัญชี แยกผู้ใช้ train/cal/test และ normal ฝึก/ปรับเกณฑ์อย่างละ 20 แถว
ฝึก normal เท่านั้น เลือก p99 จาก normal calibration; test ต้องมีทั้ง normal/attack
ไฟล์ `.candidate.pkl` ไม่ถูก production loader โหลด
ต้องประเมินข้อมูลจริง เวลา/แคมเปญอิสระ และปรับเกณฑ์ก่อนเปิดใช้
ไม่มีผลความแม่นยำข้อมูลจริงของฟีเจอร์ใหม่ในงานนี้; unit test จำลองเป็นการตรวจ pipeline เท่านั้น

ไม่ต้อง migration ฐานข้อมูล: snapshot ใช้ JSON เดิม; post-auth ใช้ RequestLog เดิม
ต้อง deploy Hub เพื่อเริ่มเก็บ v2 และ deploy Frontend เพื่อเห็นการ์ด post-auth
