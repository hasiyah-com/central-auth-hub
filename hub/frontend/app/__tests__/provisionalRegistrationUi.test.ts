import fs from "node:fs";
import path from "node:path";

const root = path.join(__dirname, "..");

test("admin approval UI assigns a verified global user type", () => {
  const source = fs.readFileSync(
    path.join(root, "(console)", "pending-requests", "page.tsx"),
    "utf8"
  );
  expect(source).toContain('user_registration: "ตรวจสอบผู้ใช้ใหม่"');
  expect(source).toContain("JSON.stringify({ user_type: userType })");
  expect(source).toContain('["student", "teacher", "staff"]');
});

test("developer UI exposes only scoped domain registration policy", () => {
  const createPage = fs.readFileSync(
    path.join(root, "(developer)", "developer", "subsystems", "new", "page.tsx"),
    "utf8"
  );
  expect(createPage).toContain(
    'self_registration_mode: selfRegistration ? "domain_auto" : "closed"'
  );
  expect(createPage).toContain("allowed_email_domains:");
  expect(createPage).not.toContain("approved_user_type");
});
