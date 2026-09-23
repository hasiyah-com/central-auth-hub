"""Expert Label Workflow — ผู้เชี่ยวชาญตรวจ alert จาก shadow decision.

แบบที่ล็อกไว้: docs/design/EXPERT_LABEL_WORKFLOW.md

  vocab       คำศัพท์ปิด (verdict / confidence / reason codes)
  provenance  ที่มาของเหตุการณ์ + เงื่อนไข eligible
  grouping    จัดกลุ่ม (user_id, primary_signal, หน้าต่าง 30 นาที)
  sync        สร้าง alert group + system disposition จาก login_sessions
  views       payload รอบแรก (blind) และรอบสอง
  reviews     label ของผู้ตรวจ — append-only
  queue       จ่ายงานให้ผู้ตรวจ (primary / second review / adjudication)
  metrics     สถิติเชิงพรรณนา + readiness gate · ยังไม่คำนวณ production FPR

label ของผู้ตรวจไม่ย้อนกลับไปเปลี่ยนการตัดสินการเข้าถึง และไม่ถูกนำไป train อัตโนมัติ
"""
