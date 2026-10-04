import { auditPresentation, auditTone, loginMethodLabel } from "../auditPresentation";

describe("auditPresentation", () => {
  it("explains a blocked student login without calling it a credential failure", () => {
    const event = auditPresentation("hub_login_blocked_student");

    expect(event.title).toBe("นักศึกษาถูกปฏิเสธการเข้าสู่ระบบกลางโดยตรง");
    expect(event.result).toBe("ถูกปฏิเสธ");
    expect(event.resultDetail).toContain("ไม่ได้หมายความว่า Passkey");
    expect(event.actorLabel).toBe("บัญชีที่พยายามเข้าสู่ระบบ");
  });

  it("uses a safe generic explanation for unknown blocked actions", () => {
    expect(auditPresentation("future_action_blocked").result).toBe("ถูกปฏิเสธ");
    expect(auditTone("future_action_blocked")).toBe("danger");
  });

  it("translates discoverable passkey into a user-facing label", () => {
    expect(loginMethodLabel("discoverable")).toBe("Passkey แบบเลือกบัญชีจากอุปกรณ์");
  });
});
