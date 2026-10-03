# ฟีเจอร์ชั้น 3: การกู้บัญชีและการเปลี่ยนวิธียืนยันตัวตน

สถานะ: เก็บข้อมูลจริงและเตรียมการทดลองเท่านั้น ไม่ได้เพิ่มคะแนน ไม่ได้เปลี่ยน
โมเดล Point 23 ตัวหรือ Sequence 18 มิติที่ใช้งานอยู่ ไม่ส่งเวกเตอร์ 32 ตัวไป API เดิม

## เก็บอะไร

เก็บ snapshot `risk_breakdown.l3_auth_candidate` ตอนประเมิน primary login ที่ตรวจสอบแล้ว
ใน Google, LINE, Passkey และ discoverable login ทั้ง Hub และระบบย่อย
ใช้ UTC สำหรับระยะเวลา วัน/ชั่วโมงในเวกเตอร์ฐานยังใช้ Asia/Bangkok ตามสัญญาเดิม
snapshot มีฟีเจอร์ฐาน 23 ตัวเดิมและบริบทเพิ่ม 9 ตัวดังตาราง

| ฟีเจอร์ | ความหมายและการคำนวณ |
|---|---|
| recovery_observed | 1 เมื่อพบบันทึกกู้บัญชีสำเร็จก่อนเวลาประเมิน; 0 เมื่อไม่พบ |
| recovery_log1p_hours | ln(1 + ชั่วโมงตั้งแต่สำเร็จล่าสุด), จำกัดอายุที่ 365 วัน |
| factor_reset_observed | 1 เมื่อพบการรีเซ็ต/เพิกถอนปัจจัยสำเร็จก่อนเวลาประเมิน |
| factor_reset_log1p_hours | ln(1 + ชั่วโมงตั้งแต่รีเซ็ตล่าสุด), จำกัดที่ 365 วัน |
| auth_method_known | 1 เมื่อทราบวิธี primary login ที่ระบบนี้ตรวจสอบ |
| auth_phishing_resistant | 1 สำหรับ passkey/discoverable ที่ Hub ตรวจสอบโดยตรง |
| prior_auth_observed | 1 เมื่อมีวิธีล็อกอินที่ทราบอย่างน้อย 5 ครั้งในระบบเดียวกันใน 30 วัน |
| prior_passkey_rate | สัดส่วน passkey/discoverable ในประวัติวิธีที่ทราบ; 0 หากข้อมูลไม่พอ |
| auth_method_departure | prior_passkey_rate เมื่อวิธีปัจจุบันทราบและไม่ใช่ local passkey; มิฉะนั้น 0 |

อายุ 0 ต้องอ่านคู่กับ observed mask: ไม่มีหลักฐานไม่ใช่เพิ่งกู้บัญชี
ไม่ใช้คำขอ การอนุมัติ ticket หรือความล้มเหลวแทนการกู้สำเร็จ
ใช้ `target_id` ของผู้ได้รับผล ไม่ใช้ `actor_id` ของผู้ดูแล
การเปลี่ยน Google account นับเฉพาะ `changed_by=RECOVERY`; SELF ไม่นับเป็นกู้คืน
การรีเซ็ต passkey สร้าง audit `auth_factor_reset_completed` ใน transaction เดียวกัน
รวมเหตุการณ์เดิม `passkey_admin_reset` ที่ revoked_count > 0 และ `totp_revoked` สำหรับประวัติเดิม

วิธี Google/LINE/TOTP ไม่ได้แปลว่า provider ไม่ใช้ MFA หรือผู้ใช้เป็นผู้โจมตี:
Hub เพียงไม่มีหลักฐาน local WebAuthn ใน primary login นั้น
ภาพนี้อยู่ก่อน risk step-up; ไม่ใช่การประเมินความแข็งแรงของการยืนยันตัวตนขั้นสุดท้าย
ข้อมูลประวัติต้องเป็นเซสชันที่มี JTI และไม่ใช่ block/pending challenge
ไม่ลงโทษผู้ที่ไม่เคยใช้ passkey และไม่เทียบ Hub กับระบบย่อยคนละระบบ
ประวัติที่ไม่มี login_method จะถูกละเว้น ไม่แทนเป็นวิธีอ่อน

เมื่อ refresh token ประเมินคะแนนใหม่ จะรักษา snapshot candidate เดิมไว้
เพื่อไม่ให้ข้อมูลหลังล็อกอินถูกนำย้อนกลับไปใช้เป็นข้อมูลตอนล็อกอิน
การเก็บบริบทใช้ savepoint; หากเก็บไม่ได้จะบันทึก unavailable และไม่นำไปฝึก

## ส่งออกและเปรียบเทียบ

Hub:
```bash
python -m scripts.export_l3_auth_candidates --output /tmp/l3-auth.jsonl
```
ใช้เฉพาะ feedback ที่มี label: true_positive, false_positive, normal_confirmed
ใช้ snapshot ที่เก็บจริงเท่านั้น ไม่สร้างค่าทดแทนให้ session เก่าที่ไม่มี snapshot
ไฟล์มี checksum sidecar และใช้ hash แทน user/session ID; ไม่มี email/IP/ข้อมูลกู้คืนลับ
hash เป็นนามแฝง ไม่ใช่การรับประกันว่าข้อมูลไม่ระบุตัวตน

นำ JSONL และ `.jsonl.meta.json` ไป ML service:
```bash
python -m scripts.compare_auth_context --data /tmp/l3-auth.jsonl --output /tmp/l3-auth-candidates
```
ฝึก baseline 23 ตัวใหม่และ candidate 32 ตัวบน split เดียวกัน
แบ่งกลุ่มผู้ใช้ 60/20/20 ด้วย seed 42 ไม่ให้บัญชีเดียวกันอยู่ข้ามชุด
ต้องมีอย่างน้อย 15 บัญชี, normal ฝึก/ปรับเกณฑ์อย่างละ 20 แถว และ test มีทั้งสอง label
ฝึกด้วย normal เท่านั้น; เลือกเกณฑ์ p99 จาก normal calibration เท่านั้น
รายงาน FPR, recall, ROC-AUC และผลต่าง candidate–baseline; ไม่สุ่มแบ่งใหม่เพื่อให้ผลดีขึ้น
รายงาน p99 แยกประเภทผู้ใช้จาก normal calibration อย่างน้อย 20 แถวต่อประเภท
หากไม่พอรายงาน abstain ไม่ใช้เกณฑ์ของประเภทอื่นแทน; ทั้งหมดยังเป็น offline
นี่เป็น user holdout ไม่ใช่ time holdout และไม่ใช่เทียบกับไฟล์โมเดล production เดิมโดยตรง
ต้องตรวจเวลา/แคมเปญที่แยกอิสระเพิ่มเติม และการโจมตีที่ชั้น 1+2 ปล่อยผ่าน

ไฟล์โมเดลเป็น `.candidate.pkl` และไม่ถูกโหลดอัตโนมัติ ต้องตรวจผลข้อมูลจริง
ปรับ percentile แยกประเภทผู้ใช้ให้ตรง model hash และเพิ่ม versioned API ก่อนเปิดใช้
ผล unit test ที่สร้างข้อมูลจำลองพิสูจน์การทำงานของ pipeline เท่านั้น ไม่พิสูจน์ความแม่นยำ
ยังไม่มีผลเปรียบเทียบข้อมูลจริงของฟีเจอร์ใหม่จนกว่าจะสะสม snapshot และ feedback เพียงพอ

ยังไม่เพิ่ม AAGUID, Accept-Language หรือพฤติกรรมหลังล็อกอินในงานรอบนี้
ยังไม่ยืนยันเลขอ้างอิงในตารางบทที่ 4 เพราะไม่ได้รับบรรณานุกรมที่ตรงกัน
