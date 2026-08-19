/**
 * Public paths — path ที่ middleware ต้อง "ปล่อยผ่าน" โดยไม่เช็ค token cookie.
 *
 * แยกออกมาเป็นฟังก์ชันบริสุทธิ์เพื่อ unit-test ได้ (middleware เองรันบน edge
 * runtime เทสยาก) — กันบั๊กคลาสสิก: flow ที่ "ยังไม่มี token" ถูก middleware
 * redirect 307 ไป /auth/login แล้ว browser follow ด้วย POST → หน้าเพจตอบ 405
 * (เคยเกิดกับ /oauth/token และ /api/proxy/auth/frontend/exchange)
 */

/** prefix ที่ next.config.js rewrites ส่งตรงเข้า hub-backend (single-domain mode) */
export const BACKEND_PASSTHROUGH = [
  "/oauth",
  "/.well-known",
  "/account/passkeys",
  "/secret",
  "/api/v1",
  "/health",
];

export function pathMatches(prefixes: string[], pathname: string): boolean {
  return prefixes.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

/**
 * true = ปล่อยผ่าน middleware (ไม่ต้องมี token)
 *
 * ครอบคลุม:
 *  - `/auth/*` (หน้า login/callback/stepup — user ยังไม่ login จริง)
 *  - `/api/set-token`
 *  - `/api/proxy/auth/passkey/*`  — passkey login + recovery (public flow)
 *  - `/api/proxy/auth/frontend/*` — one-time login-code exchange
 *    ("ยังไม่มี token" คือเหตุผลที่เรียก; code เองคือ credential single-use)
 *  - BACKEND_PASSTHROUGH (server-to-server / cross-origin ที่ backend auth เอง)
 *  - static (`/_next`, favicon)
 */
export function isPublicPath(pathname: string): boolean {
  return (
    pathname.startsWith("/auth/") ||
    pathname.startsWith("/api/set-token") ||
    pathname.startsWith("/api/proxy/auth/passkey/") ||
    pathname.startsWith("/api/proxy/auth/frontend/") ||
    pathMatches(BACKEND_PASSTHROUGH, pathname) ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico"
  );
}
