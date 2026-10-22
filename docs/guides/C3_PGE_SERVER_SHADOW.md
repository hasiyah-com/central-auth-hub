# ทดสอบ C3 + PG-E บน server (shadow เท่านั้น)

## เปิดใช้งาน

โค้ดนี้เพิ่มการเปรียบเทียบนโยบาย ไม่เปลี่ยนโมเดล IF, threshold, การออก token, MFA gate หรือผล access เดิม ค่าเริ่มต้นปิด ไม่มีโหมด enforce ในการแก้นี้

ใน Dokploy Environment ของ Hub backend ตั้ง:

```env
C3_PGE_SHADOW_ENABLED=true
RISK_CONTEXTUAL_TRIAL_ENABLED=false
```

Deploy/recreate backend จาก main ที่มีการแก้นี้ทุก replica (restart อย่างเดียวไม่โหลด environment ใหม่ใน Compose) ไม่ต้อง migrate/seed ฐานข้อมูล ไม่ต้องเปลี่ยน client ID/secret, URL หรือ keys ไม่ต้อง retrain ML

Compose ของ Hub ใช้ env_file อยู่แล้ว ถ้า deploy ด้วยรูปแบบอื่น ต้องส่งตัวแปรให้ container backend ด้วย

## ผลที่อ่านได้

ผลอยู่ใน `LoginSession.risk_breakdown.c3_pge_shadow` และ log `[c3_pge_shadow]`:

- `mode=shadow`, `applied_to_access=false`, `version=c3-pge-shadow-v1`
- `baseline_l1_l2_decision`: ผลฐานก่อน fallback L3; ไม่ใช่ผล access หลังทุกนโยบาย
- `candidate_decision` และ `would_decision`: ผล C3 + PG-E ที่ยังไม่บังคับ
- `evidence`: จำนวน trusted history แบบ cap5, สถานะลิงก์ลงทะเบียน/การให้สิทธิ์
- `pge_reasons`, `candidate_rule_reasons`, `latency_ms`, `observed_at` (UTC)
- `l3_included=false`: ชุดเปรียบเทียบนี้ไม่เพิ่มโมเดล IF จากชุดทดลองเข้า server ผล L3 เดิมยังอยู่ช่องเดิม

`unavailable` = เก็บข้อมูล/คำนวณไม่ได้; `incompatible_contextual_trial` = เปิด contextual trial อีกชุดอยู่; `hard_block_preserved` = ข้ามการคำนวณและคง block อย่านับสถานะเหล่านี้เป็น allow หรือเป็นการทำนายที่ถูกต้อง

ตัวอย่าง SQL อ่านผลของบัญชีทดสอบ (ใส่ UUID ของตนเองเป็น bind parameter):

```sql
SELECT created_at, decision,
       risk_breakdown->'c3_pge_shadow' AS comparison
FROM login_sessions
WHERE user_id = :test_user_id
ORDER BY created_at DESC
LIMIT 20;
```

## ข้อจำกัดของหลักฐานจริง

main เดิมยังไม่มี `registration_session_id` ใน audit `passkey_registered` การติดตั้ง shadow นี้ **ไม่ได้ซ่อม enrollment gate หรือสร้างหลักฐานย้อนหลัง** รายการเก่าจึงเป็น unknown ไม่ถูกอนุมานว่า verified จากชื่อเครื่องหรือ label

Collector รองรับลิงก์ explicit ที่ server บันทึกใน audit ไปยัง LoginSession ของบัญชีเดียวกัน และมี strong authentication จริงพร้อมเวลายืนยันก่อนลงทะเบียนภายใน5นาที ปฏิเสธอนาคต, block, counter regression, คนละบัญชี/credential ส่วน first-factor email OTP ยังไม่มีลิงก์มาตรฐานใน runtime จึงยัง unknown

สิทธิ์ต้องมี latest grant ที่ตรง subsystem, ผู้ให้ และ server audit ก่อนเหตุการณ์ การมี provenance ไม่พิสูจน์ว่าไม่มีผู้โจมตี ข้อกำหนดนี้เข้มกว่าการจำลองที่มี actor อย่างเดียว จึงไม่ถือว่าผลวิจัย F1 0.766 ใช้กับ server อัตโนมัติ

C3 ใช้ floor/น้ำหนักเฉพาะกลุ่ม trusted history<5 ไม่เปิด contextual-trial อื่น เก็บ warn ขั้นต่ำตาม C2 กฎ block และ floor อื่นยังอยู่ PG-E ยก unknown recent change เป็น would_challenge ตามสูตรทดลอง แต่ไม่กระทบผู้ใช้จริง

เวลาในฟีเจอร์ 23 ตัวใช้ระบบเดิม ไม่เปลี่ยนเขตเวลา การเก็บ provenance ใช้ UTC ค่า failure/IP/travel/cross-system ของ L1 ใช้ observation cache ของเหตุการณ์ฐานเดียวกัน ไม่อ่านใหม่เพื่อหาอีกผลหนึ่ง ส่วน trusted history และ provenance เป็น read-only snapshot ตอนเก็บ shadow อาจเห็นรายการที่ commit พร้อมกันภายหลังการสกัดฟีเจอร์เล็กน้อย จึงเก็บเวลาและต้องตรวจสอบ concurrency ก่อนใช้ enforce

## ทดสอบด้วยบัญชีของตนเอง

1. ล็อกอินเครื่องเดิม ตรวจว่ามี comparison และผล access เดิมยังใช้ได้
2. ลองเบราว์เซอร์/เครื่องใหม่ ตรวจ device/browser flags กับ trusted count และผล would_decision
3. เพิ่ม passkey ผ่านหน้าเดิม แล้วล็อกอินใหม่ ตรวจสถานะ registration unknown ตามข้อมูลจริง อย่าสร้าง audit ปลอมเพื่อให้เป็น verified
4. ให้/ถอนสิทธิ์ผ่าน admin ตามปกติ ตรวจว่า provenance ตรง subsystem; ทดสอบเฉพาะบัญชีและระบบย่อยที่ควบคุม
5. เปรียบเทียบ latency และตรวจว่าไม่มี token/secret/credential key ในรายละเอียด
6. ทดสอบ failure path บน staging ด้วยเทสที่ให้มา การคำนวณ shadow พังต้องไม่เปลี่ยนผล access และไม่ rollback transaction หลัก

ห้ามสร้างพฤติกรรมโจมตีหรือ login ปลอมปนในบัญชีจริงโดยไม่มีขอบเขตทดสอบ ตัวเลข precision/recall/F1 จริงต้องมี ground truth จากสถานการณ์ที่รู้ผล ไม่อนุมานจากการยืนยัน MFA ผ่านหรือจากผลของระบบเอง

## ย้อนกลับ

ตั้ง `C3_PGE_SHADOW_ENABLED=false` แล้ว deploy/recreate backend ระบบจะหยุดเก็บ comparison ใหม่ทันทีหลังทุก replica รับค่าใหม่ ผล shadow เดิมอยู่ใน JSON เพื่อวิเคราะห์ โดยไม่มีการแก้ข้อมูลหรือ decisions ย้อนหลัง

## การทดสอบก่อน merge

เทสใหม่ตรวจ default-off, shadow isolation ทั้งกรณีสำเร็จ/พัง, DB savepoint, block/floor อื่น, reuse failure counts, unknown/future/cross-account provenance และ collector SQL บน PostgreSQL ของ CI

CI ของฐาน 011cb1b มี5failureเดิมจาก fixture IP และลำดับ header ที่ไม่ตรง policy ปัจจุบัน งานนี้ปรับเฉพาะเทส IP ให้ใช้ public fixture และทดสอบลำดับปัจจุบันรวม signed-proxy/forged-header ไม่เปลี่ยน get_client_ip ของ production
