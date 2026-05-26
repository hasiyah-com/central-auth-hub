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
  full_name?: string;
  user_type?: string;
  faculty?: string;
  is_hub_admin?: boolean;
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
