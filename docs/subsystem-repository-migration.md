# แยกระบบย่อยออกจาก Central Auth Hub

ฐานการแยก: main 2ea904bb6ac940c1aa261c16050c1040db1bdc54

แยกเป็น repository ท้องถิ่น subsystem-library, subsystem-dorm, subsystem-grade พร้อม Git bundle ที่ clone ได้โดยไม่ต้องมี repository กลาง ชื่อเหล่านี้เป็นชื่อที่เตรียมไว้ ยังไม่ได้สร้าง repository บน GitHub หรือ push

แต่ละชุดมีโค้ดเดิมที่ตรวจไบต์ตรงกับฐานก่อนปรับ deployment, ประวัติ commit ที่เกี่ยวข้อง, Compose local/production/Dokploy และ nginx template ของตนเอง เส้นทาง build ย้ายมา root แล้ว ประวัติผ่าน path filtering จึงมี commit SHA ใหม่ แต่ยังคง author/message ของ commit ที่เกี่ยวข้อง ไม่ได้ล้างประวัติ main เดิม

## นำเข้า repository แยก

แตกชุดส่งมอบ แล้วรันในโฟลเดอร์ที่จะเก็บงาน:

```bash
git clone -b main subsystem-library.bundle subsystem-library
git clone -b main subsystem-dorm.bundle subsystem-dorm
git clone -b main subsystem-grade.bundle subsystem-grade
```

ตั้ง Git remote หลังสร้าง repository ปลายทางแล้วเท่านั้น ไม่มีการกำหนด URL ปลอมใน bundle
อ่าน SOURCE_HISTORY.md ของแต่ละชุดก่อน deploy

## ย้าย deployment

1. สำรองฐานข้อมูลและบันทึกชื่อ volume ของแต่ละระบบก่อนเปลี่ยน source repository
2. ตั้ง repository และ Compose path ใน Dokploy ให้ชี้ repo ระบบย่อยใหม่ build context เป็น root
3. เก็บค่าจริงของ env ใน secret store ของ deployment ไม่ย้ายเข้า Git bundle
4. ใช้ Client ID/Secret และ Redirect URI เดิมถ้า domain/callback ไม่เปลี่ยน ถ้าเปลี่ยนให้แก้ทะเบียนและรออนุมัติตามนโยบาย
5. รักษา network และ volume ที่ต้องใช้ ไม่รัน down -v การแยก source ไม่ย้ายข้อมูลฐานข้อมูลให้อัตโนมัติ
6. nginx template ต้องใช้กับ TLS/ACME configuration ของ deployment นั้น; แต่ละ host ต้องจัด reverse proxy ของตัวเอง
7. ทดสอบ OAuth login/callback, token verification, whitelist, webhook และข้อมูลธุรกิจก่อนสลับบริการ

## สิ่งที่เปลี่ยนใน Hub

นำ application folders และ client Compose/nginx routes ออก สคริปต์ lifecycle และ TLS ของ Hub จัดการเฉพาะ Hub; worktree slots เหลือ hub/ml
ยังเก็บทะเบียน subsystems, generic OAuth/webhook APIs, SDK และ integration fixtures ใน CI เพราะเป็นหน้าที่ของระบบกลาง ไม่ใช่โค้ดธุรกิจของระบบย่อย
เอกสารและรายงานผลเก่าอาจกล่าวถึง path เดิม ถือเป็นประวัติ ไม่ใช่คำสั่ง deploy ปัจจุบัน

## ขอบเขต

นี่คือข้อ 1 ของแผนเท่านั้น ยังไม่ได้เปลี่ยน hardcoded development URL mapping ใน webhook_dispatcher หรือปรับชุดอีเมลเป็นชื่อกลาง (ข้อ 2/3 ต้องเป็นงานต่อเนื่อง) จึงยังไม่อ้างว่าไม่มี coupling เหลือทั้งหมด
ไม่มีการ merge/push/deploy หรือเปลี่ยนฐานข้อมูลจริง branch แยกนี้ยังไม่รวมงาน integration-email ที่ค้างอยู่
