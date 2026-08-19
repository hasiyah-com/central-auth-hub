import { isPublicPath, pathMatches, BACKEND_PASSTHROUGH } from "../publicPaths";

describe("isPublicPath — flow ที่ยังไม่มี token ต้องไม่โดน middleware redirect", () => {
  // บั๊กจริง: POST /api/proxy/auth/frontend/exchange โดน redirect 307 ไป
  // /auth/login → browser follow ด้วย POST → หน้าเพจตอบ 405
  it("ปล่อยผ่าน login-code exchange (สาเหตุ 405 เดิม)", () => {
    expect(isPublicPath("/api/proxy/auth/frontend/exchange")).toBe(true);
  });

  it("ปล่อยผ่าน passkey login + recovery", () => {
    expect(isPublicPath("/api/proxy/auth/passkey/login/start")).toBe(true);
    expect(isPublicPath("/api/proxy/auth/passkey/recover/otp")).toBe(true);
  });

  it("ปล่อยผ่านหน้า /auth/* และ set-token", () => {
    expect(isPublicPath("/auth/login")).toBe(true);
    expect(isPublicPath("/auth/callback")).toBe(true);
    expect(isPublicPath("/api/set-token")).toBe(true);
  });

  it("ปล่อยผ่าน backend passthrough (single-domain mode)", () => {
    expect(isPublicPath("/oauth/token")).toBe(true); // เคยเป็นบั๊ก 307 เหมือนกัน
    expect(isPublicPath("/.well-known/jwks.json")).toBe(true);
    expect(isPublicPath("/api/v1/roster")).toBe(true);
    expect(isPublicPath("/health")).toBe(true);
  });

  it("ยังกัน path ที่ต้อง auth", () => {
    expect(isPublicPath("/dashboard")).toBe(false);
    expect(isPublicPath("/users")).toBe(false);
    expect(isPublicPath("/developer/subsystems")).toBe(false);
    // proxy ที่ไม่ใช่ public flow ต้องยังผ่าน middleware
    expect(isPublicPath("/api/proxy/admin/users")).toBe(false);
    expect(isPublicPath("/api/proxy/account/passkeys/list")).toBe(false);
  });

  it("ไม่ match prefix แบบหลอก (path traversal ทางชื่อ)", () => {
    // ต้องไม่ปล่อย /authorize เพราะขึ้นต้นด้วย /auth
    expect(isPublicPath("/authorize-evil")).toBe(false);
    expect(isPublicPath("/healthz-admin")).toBe(false);
  });
});

describe("pathMatches", () => {
  it("match exact และลูกเท่านั้น", () => {
    expect(pathMatches(["/oauth"], "/oauth")).toBe(true);
    expect(pathMatches(["/oauth"], "/oauth/token")).toBe(true);
    expect(pathMatches(["/oauth"], "/oauthx")).toBe(false);
  });

  it("BACKEND_PASSTHROUGH ต้อง sync กับ next.config.js", () => {
    // เตือนเมื่อมีคนแก้ข้างเดียว — รายการนี้ต้องตรงกับ `passthrough` ใน next.config.js
    expect(BACKEND_PASSTHROUGH).toEqual(
      expect.arrayContaining(["/oauth", "/.well-known", "/api/v1", "/health"])
    );
  });
});
