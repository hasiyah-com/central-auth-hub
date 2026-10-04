export type AuditTone = "signal" | "warn" | "danger" | "default";

export type AuditPresentation = {
  title: string;
  description: string;
  result: string;
  resultDetail: string;
  actorLabel: string;
};

const EXACT: Record<string, Omit<AuditPresentation, "actorLabel">> = {
  hub_login_blocked_student: {
    title: "นักศึกษาถูกปฏิเสธการเข้าสู่ระบบกลางโดยตรง",
    description:
      "บัญชีนักศึกษาไม่มีสิทธิ์เข้า Hub Console โดยตรง ต้องเข้าสู่ระบบผ่านระบบย่อยที่ได้รับอนุญาต",
    result: "ถูกปฏิเสธ",
    resultDetail: "ปฏิเสธตามนโยบายสิทธิ์ ไม่ได้หมายความว่า Passkey หรือรหัสผ่านผิด",
  },
  hub_login_blocked_student_line: {
    title: "นักศึกษาถูกปฏิเสธการเข้าสู่ระบบกลางโดยตรง",
    description:
      "บัญชีนักศึกษาไม่มีสิทธิ์เข้า Hub Console โดยตรง ต้องเข้าสู่ระบบผ่านระบบย่อยที่ได้รับอนุญาต",
    result: "ถูกปฏิเสธ",
    resultDetail: "ปฏิเสธตามนโยบายสิทธิ์ ไม่ได้หมายความว่าบัญชี LINE ผิดพลาด",
  },
  hub_login_success: {
    title: "เข้าสู่ระบบกลางสำเร็จ",
    description: "ระบบตรวจสอบตัวตนและอนุญาตให้บัญชีนี้เข้า Hub Console แล้ว",
    result: "สำเร็จ",
    resultDetail: "สร้างเซสชันเข้าสู่ระบบสำเร็จ",
  },
  hub_logout: {
    title: "ออกจากระบบกลาง",
    description: "ผู้ใช้ออกจาก Hub Console และระบบยุติเซสชันที่เกี่ยวข้อง",
    result: "สำเร็จ",
    resultDetail: "คำสั่งออกจากระบบเสร็จสมบูรณ์",
  },
  subsystem_approved: {
    title: "อนุมัติระบบย่อย",
    description: "ผู้ดูแลอนุมัติให้ระบบย่อยเชื่อมต่อกับระบบกลาง",
    result: "อนุมัติแล้ว",
    resultDetail: "ระบบย่อยได้รับสิทธิ์เชื่อมต่อ",
  },
  subsystem_rejected: {
    title: "ปฏิเสธคำขอของระบบย่อย",
    description: "ผู้ดูแลไม่อนุมัติคำขอเชื่อมต่อของระบบย่อย",
    result: "ถูกปฏิเสธ",
    resultDetail: "คำขอไม่ได้รับอนุมัติ",
  },
  create_user: {
    title: "เพิ่มผู้ใช้ใหม่",
    description: "ผู้ดูแลสร้างบัญชีผู้ใช้ใหม่ในระบบกลาง",
    result: "สำเร็จ",
    resultDetail: "สร้างข้อมูลผู้ใช้แล้ว",
  },
  update_user: {
    title: "แก้ไขข้อมูลผู้ใช้",
    description: "ผู้ดูแลเปลี่ยนแปลงข้อมูลหรือสิทธิ์ของบัญชีผู้ใช้",
    result: "สำเร็จ",
    resultDetail: "บันทึกข้อมูลผู้ใช้แล้ว",
  },
  delete_user: {
    title: "ลบผู้ใช้",
    description: "ผู้ดูแลลบบัญชีผู้ใช้ออกจากระบบกลาง",
    result: "สำเร็จ",
    resultDetail: "ลบบัญชีผู้ใช้แล้ว",
  },
};

function humanizeAction(action: string): string {
  return action
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function auditTone(action: string): AuditTone {
  if (action.includes("approved") || action.includes("success") || action.includes("authorized")) return "signal";
  if (action.includes("rejected") || action.includes("failed") || action.includes("blocked") || action.includes("denied")) return "danger";
  if (action.includes("revoked") || action.includes("suspended") || action.includes("logout")) return "warn";
  return "default";
}

export function auditPresentation(action: string): AuditPresentation {
  const exact = EXACT[action];
  if (exact) return { ...exact, actorLabel: action.includes("login") ? "บัญชีที่พยายามเข้าสู่ระบบ" : "ผู้ดำเนินการ" };

  const tone = auditTone(action);
  if (action.includes("login") && action.includes("failed")) {
    return {
      title: "เข้าสู่ระบบไม่สำเร็จ",
      description: "ระบบไม่สามารถยืนยันตัวตนหรืออนุญาตการเข้าสู่ระบบครั้งนี้ได้",
      result: "ไม่สำเร็จ",
      resultDetail: "ดูข้อมูลประกอบด้านล่างเพื่อหาสาเหตุที่บันทึกไว้",
      actorLabel: "บัญชีที่พยายามเข้าสู่ระบบ",
    };
  }
  if (action.includes("blocked") || action.includes("denied")) {
    return {
      title: "ระบบปฏิเสธการดำเนินการ",
      description: "คำขอนี้ถูกหยุดตามนโยบายสิทธิ์หรือนโยบายความปลอดภัยของระบบ",
      result: "ถูกปฏิเสธ",
      resultDetail: "เหตุการณ์ถูกบล็อกก่อนดำเนินการสำเร็จ",
      actorLabel: "ผู้ร้องขอ",
    };
  }
  if (action.includes("revoked") || action.includes("suspended")) {
    return {
      title: "สิทธิ์หรือเซสชันถูกระงับ",
      description: "ระบบหรือผู้ดูแลได้ระงับสิทธิ์ที่เกี่ยวข้องกับเหตุการณ์นี้",
      result: "ระงับแล้ว",
      resultDetail: "สิทธิ์เดิมไม่สามารถใช้งานต่อได้",
      actorLabel: "ผู้ดำเนินการ",
    };
  }

  return {
    title: humanizeAction(action) || "เหตุการณ์ของระบบ",
    description: "ระบบบันทึกเหตุการณ์นี้ไว้เพื่อให้ผู้ดูแลตรวจสอบย้อนหลัง",
    result: tone === "signal" ? "สำเร็จ" : tone === "danger" ? "ไม่สำเร็จ" : "บันทึกแล้ว",
    resultDetail: "ยังไม่มีคำอธิบายเฉพาะสำหรับรหัสเหตุการณ์นี้",
    actorLabel: "ผู้ดำเนินการ",
  };
}

export function loginMethodLabel(method: unknown): string | null {
  if (method === "discoverable") return "Passkey แบบเลือกบัญชีจากอุปกรณ์";
  if (method === "passkey") return "Passkey";
  if (method === "google") return "Google";
  if (method === "line") return "LINE";
  if (method === "password") return "รหัสผ่าน";
  return typeof method === "string" && method ? method : null;
}
