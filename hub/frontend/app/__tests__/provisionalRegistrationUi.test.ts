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

test("subsystem detail separates roles from allowed registration domains", () => {
  const detailPages = [
    path.join(root, "(developer)", "developer", "subsystems", "[id]", "page.tsx"),
    path.join(root, "(console)", "subsystems", "[id]", "page.tsx"),
  ].map((file) => fs.readFileSync(file, "utf8"));
  for (const detailPage of detailPages) {
    expect(detailPage).toContain("Allowed Registration Domains");
    expect(detailPage).toContain("sub.allowed_email_domains");
    expect(detailPage).toContain("เปิดรับผู้ใช้ใหม่");
    expect(detailPage).toContain('data-testid="role-domain-grid"');
    expect(detailPage).toContain("xl:grid-cols-2");
  }
});

test("central users page manages trusted registration domains", () => {
  const usersPage = fs.readFileSync(
    path.join(root, "(console)", "users", "page.tsx"),
    "utf8"
  );
  expect(usersPage).toContain("Trusted Registration Domains");
  expect(usersPage).toContain("/admin/users/registration-domains");
  expect(usersPage).toContain("เพิ่ม Domain");
});

test("developer subsystem exposes the same owner-manageable controls as admin", () => {
  const developerPage = fs.readFileSync(
    path.join(root, "(developer)", "developer", "subsystems", "[id]", "page.tsx"),
    "utf8"
  );
  const adminPage = fs.readFileSync(
    path.join(root, "(console)", "subsystems", "[id]", "page.tsx"),
    "utf8"
  );
  for (const source of [developerPage, adminPage]) {
    expect(source).toContain("<AccessPolicyCard");
    expect(source).toContain("apiKeyPrefix={sub.api_key_prefix}");
    expect(source).toContain("subsystem-detail-view");
  }
  expect(developerPage).toContain("editWebhookUrl");
  expect(developerPage).toContain("body.access_revoke_webhook_url");
});
