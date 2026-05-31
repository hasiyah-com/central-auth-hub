/**
 * Lightweight JWT helpers — ใช้ในฝั่ง server (middleware + route handlers) เป็นหลัก
 *
 * ไม่ verify signature (Hub เป็นคน issue + เก็บใน httpOnly cookie ของเราเอง)
 * แค่อ่าน payload + เช็ค exp พอ ถ้า cookie โดน tamper request จะถูก backend reject
 * ผ่าน JWKS verification เอง
 */

export type JwtPayload = {
  sub: string;
  email: string;
  // Hub JWT ใช้ "name" (= user.full_name) — เก็บไว้ทั้งสองชื่อเผื่อเปลี่ยน
  name?: string;
  full_name?: string;
  user_type?: string;     // student / teacher / staff / admin
  faculty?: string;
  is_hub_admin?: boolean; // อาจไม่มีใน claim — fallback ไปใช้ user_type === "admin"
  aud: string;
  exp: number;
  iat: number;
};

export function parseJwt(token: string): JwtPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    // base64url decode payload
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload + "=".repeat((4 - (payload.length % 4)) % 4);
    // ใช้ atob ทั้งใน edge runtime (middleware) และ browser
    const json =
      typeof atob !== "undefined"
        ? atob(padded)
        : Buffer.from(padded, "base64").toString("utf-8");
    return JSON.parse(decodeURIComponent(escape(json))) as JwtPayload;
  } catch {
    return null;
  }
}

export function isExpired(payload: JwtPayload | null): boolean {
  if (!payload) return true;
  const now = Math.floor(Date.now() / 1000);
  return payload.exp <= now;
}

export const TOKEN_COOKIE = "hub_token";

// ── Role helpers (used by middleware + Sidebar) ─────────────
// hub_admin (DB column) ตัดสินใจสิทธิ์ Admin Console
// user_type ∈ {student, teacher, staff, admin} ตัดสินใจสิทธิ์ Developer Portal
export function isAdmin(payload: JwtPayload | null | undefined): boolean {
  if (!payload) return false;
  return payload.is_hub_admin === true || payload.user_type === "admin";
}

export function isDeveloper(payload: JwtPayload | null | undefined): boolean {
  if (!payload) return false;
  return ["teacher", "staff", "admin"].includes(payload.user_type ?? "");
}
